"""知识库重建任务服务。"""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime
import logging
import threading
import uuid

from app.config import AppConfig
from app.schemas import KnowledgeBaseJob, KnowledgeBaseStats
from app.services.catalog_service import get_document_status_counts, mark_document_failed, mark_documents_indexed, sync_document_catalog
from app.services.document_service import load_documents_from_paths
from app.services.knowledge_base_service import (
    add_nodes_with_embeddings,
    create_nodes_from_documents,
    delete_document_chunks,
    get_collection_count,
)


logger = logging.getLogger(__name__)

_JOB_LOCK = threading.Lock()
_JOBS: dict[str, KnowledgeBaseJob] = {}
_CURRENT_JOB_ID = ""


def start_rebuild_job(config: AppConfig) -> KnowledgeBaseJob:
    """启动新的知识库重建任务。"""
    global _CURRENT_JOB_ID
    with _JOB_LOCK:
        current_job = _JOBS.get(_CURRENT_JOB_ID)
        if current_job and current_job.status in {"queued", "running", "cancelling"}:
            return replace(current_job)

        job_id = uuid.uuid4().hex
        job = KnowledgeBaseJob(
            job_id=job_id,
            status="queued",
            stage="等待执行",
            progress=0.0,
            message="知识库重建任务已创建。",
            started_at=_now_text(),
        )
        _JOBS[job_id] = job
        _CURRENT_JOB_ID = job_id

    worker = threading.Thread(
        target=_run_job,
        args=(job_id, config),
        name=f"aurora-kb-job-{job_id[:8]}",
        daemon=True,
    )
    worker.start()
    return replace(job)


def get_job(job_id: str) -> KnowledgeBaseJob | None:
    with _JOB_LOCK:
        job = _JOBS.get(job_id)
        return replace(job) if job else None


def get_current_job() -> KnowledgeBaseJob | None:
    with _JOB_LOCK:
        job = _JOBS.get(_CURRENT_JOB_ID)
        return replace(job) if job else None


def cancel_job(job_id: str) -> KnowledgeBaseJob | None:
    with _JOB_LOCK:
        job = _JOBS.get(job_id)
        if not job:
            return None
        if job.status in {"completed", "completed_with_errors", "failed", "cancelled"}:
            return replace(job)

        job.cancel_requested = True
        if job.status == "running":
            job.status = "cancelling"
            job.message = "正在取消知识库重建任务。"
        return replace(job)


def _run_job(job_id: str, config: AppConfig) -> None:
    _set_job(
        job_id,
        status="running",
        stage="同步文档目录",
        progress=0.04,
        message="正在同步文档状态。",
    )

    try:
        documents, removed_paths = sync_document_catalog(config)
        changed_documents = [item for item in documents if item.status in {"pending", "changed", "failed"}]
        _set_job(
            job_id,
            total_documents=len(documents),
            processed_documents=0,
            total_chunks=0,
            processed_chunks=0,
            message=f"共发现 {len(documents)} 份文档，待处理 {len(changed_documents)} 份。",
        )

        if _is_cancel_requested(job_id):
            _finish_job(job_id, status="cancelled", message="知识库重建已取消。")
            return

        removed_count = 0
        if removed_paths:
            _set_job(
                job_id,
                stage="清理过期索引",
                progress=0.08,
                message=f"正在清理 {len(removed_paths)} 份已删除文档的索引。",
            )
            for path in removed_paths:
                if _is_cancel_requested(job_id):
                    _finish_job(job_id, status="cancelled", message="知识库重建已取消。")
                    return
                delete_document_chunks(config, path)
                removed_count += 1

        if not changed_documents:
            counts = get_document_status_counts(config)
            stats = KnowledgeBaseStats(
                document_count=len(documents),
                chunk_count=get_collection_count(config),
                indexed_count=counts.get("indexed", 0),
                changed_count=counts.get("changed", 0),
                pending_count=counts.get("pending", 0),
                failed_count=counts.get("failed", 0),
                removed_count=removed_count,
                skipped_count=len(documents),
                job_id=job_id,
            )
            _finish_job(
                job_id,
                status="completed",
                message="没有检测到需要更新的文档，已跳过重建。",
                stats=stats,
            )
            return

        _set_job(
            job_id,
            stage="解析文档",
            progress=0.14,
            message="正在解析变更文档并生成切片。",
        )
        document_nodes: list[tuple[object, list[object]]] = []
        total_chunks = 0
        for index, document in enumerate(changed_documents, start=1):
            if _is_cancel_requested(job_id):
                _finish_job(job_id, status="cancelled", message="知识库重建已取消。")
                return

            source_documents = load_documents_from_paths(
                [document.path],
                config.data_dir,
                metadata_by_path={
                    document.path: {
                        "theme": document.theme,
                        "tags": document.tags,
                    }
                },
            )
            nodes = create_nodes_from_documents(config, source_documents)
            total_chunks += len(nodes)
            document_nodes.append((document, nodes))
            _set_job(
                job_id,
                progress=0.14 + (0.18 * index / max(1, len(changed_documents))),
                total_chunks=total_chunks,
                message=f"已完成 {index}/{len(changed_documents)} 份文档解析。",
            )

        indexed_count = 0
        failed_count = 0
        processed_chunks = 0
        processed_documents = 0

        for index, (document, nodes) in enumerate(document_nodes, start=1):
            if _is_cancel_requested(job_id):
                _finish_job(job_id, status="cancelled", message="知识库重建已取消。")
                return

            _set_job(
                job_id,
                stage="写入向量库",
                progress=0.34 + (0.52 * (index - 1) / max(1, len(document_nodes))),
                processed_documents=processed_documents,
                processed_chunks=processed_chunks,
                message=f"正在写入文档：{document.name}",
            )

            delete_document_chunks(config, document.path)

            try:
                inserted_chunks = add_nodes_with_embeddings(
                    config,
                    nodes,
                    progress_callback=lambda inserted, total, document=document, index=index: _set_job(
                        job_id,
                        stage="写入向量库",
                        progress=0.34
                        + 0.52
                        * (
                            ((index - 1) + (inserted / max(1, total)))
                            / max(1, len(document_nodes))
                        ),
                        processed_documents=processed_documents,
                        processed_chunks=processed_chunks + inserted,
                        message=f"正在写入文档：{document.name} ({inserted}/{total} 切片)",
                    ),
                    cancel_checker=lambda: _is_cancel_requested(job_id),
                )
                processed_chunks += inserted_chunks
                processed_documents += 1
                indexed_count += 1
                mark_documents_indexed(
                    config,
                    {
                        document.path: {
                            "content_hash": document.content_hash,
                            "chunk_count": len(nodes),
                        }
                    },
                )
            except Exception as exc:
                delete_document_chunks(config, document.path)
                failed_count += 1
                mark_document_failed(
                    config,
                    document.path,
                    error=str(exc),
                    content_hash=document.content_hash,
                )
                logger.exception("文档索引失败: %s", document.path)

        refreshed_documents, _ = sync_document_catalog(config)
        counts = get_document_status_counts(config)
        stats = KnowledgeBaseStats(
            document_count=len(refreshed_documents),
            chunk_count=get_collection_count(config),
            indexed_count=counts.get("indexed", 0),
            changed_count=counts.get("changed", 0),
            pending_count=counts.get("pending", 0),
            failed_count=counts.get("failed", 0),
            removed_count=removed_count,
            skipped_count=max(0, len(refreshed_documents) - indexed_count - failed_count),
            job_id=job_id,
        )

        if failed_count:
            _finish_job(
                job_id,
                status="completed_with_errors",
                message=f"知识库重建完成，其中 {failed_count} 份文档处理失败。",
                stats=stats,
            )
            return

        _finish_job(
            job_id,
            status="completed",
            message=f"知识库重建完成，共更新 {indexed_count} 份文档。",
            stats=stats,
        )
    except Exception as exc:
        logger.exception("知识库重建任务失败。")
        _finish_job(
            job_id,
            status="failed",
            message="知识库重建失败，请查看日志。",
            error=str(exc),
        )


def _is_cancel_requested(job_id: str) -> bool:
    with _JOB_LOCK:
        job = _JOBS.get(job_id)
        return bool(job and job.cancel_requested)


def _set_job(job_id: str, **updates: object) -> None:
    with _JOB_LOCK:
        job = _JOBS.get(job_id)
        if not job:
            return
        for key, value in updates.items():
            setattr(job, key, value)


def _finish_job(
    job_id: str,
    *,
    status: str,
    message: str,
    error: str = "",
    stats: KnowledgeBaseStats | None = None,
) -> None:
    with _JOB_LOCK:
        job = _JOBS.get(job_id)
        if not job:
            return
        job.status = status
        job.stage = "已结束"
        job.progress = 1.0 if status in {"completed", "completed_with_errors"} else job.progress
        job.message = message
        job.error = error
        job.finished_at = _now_text()
        job.stats = stats


def _now_text() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")
