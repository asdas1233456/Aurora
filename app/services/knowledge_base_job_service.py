"""Knowledge-base background job service."""

from __future__ import annotations

from dataclasses import asdict, replace
from datetime import datetime
import json
import logging
from pathlib import Path
import threading
import uuid

from app.config import AppConfig
from app.schemas import KnowledgeBaseJob, KnowledgeBaseStats
from app.services.catalog_service import (
    get_document_status_counts,
    list_document_catalog,
    list_documents_needing_index,
    mark_document_failed,
    mark_documents_indexed,
    reset_all_document_tracking,
    sync_document_catalog,
)
from app.services.document_service import load_documents_from_paths
from app.services.knowledge_base_service import (
    add_nodes_with_embeddings,
    clear_retrieval_backends,
    create_nodes_from_documents,
    delete_document_chunks,
    get_collection_count,
)


logger = logging.getLogger(__name__)

_VALID_JOB_MODES = {"sync", "scan", "reset"}
_TERMINAL_JOB_STATUSES = {"completed", "completed_with_errors", "failed", "cancelled"}
_JOB_LOCK = threading.Lock()
_JOBS: dict[str, KnowledgeBaseJob] = {}
_CURRENT_JOB_ID = ""
_LOADED_JOBS_PATH = ""
_JOBS_FILE_NAME = "knowledge_base_jobs.json"


def start_rebuild_job(config: AppConfig, *, mode: str = "sync") -> KnowledgeBaseJob:
    """Start a new knowledge-base background job."""
    normalized_mode = str(mode or "sync").strip().lower() or "sync"
    if normalized_mode not in _VALID_JOB_MODES:
        raise ValueError(f"Unsupported knowledge-base job mode: {normalized_mode}")

    global _CURRENT_JOB_ID
    _ensure_store_loaded(config)

    with _JOB_LOCK:
        current_job = _JOBS.get(_CURRENT_JOB_ID)
        if current_job and current_job.status in {"queued", "running", "cancelling"}:
            return replace(current_job)

        job_id = uuid.uuid4().hex
        job = KnowledgeBaseJob(
            job_id=job_id,
            status="queued",
            mode=normalized_mode,
            stage="queued",
            progress=0.0,
            message=_build_created_message(normalized_mode),
            started_at=_now_text(),
        )
        _JOBS[job_id] = job
        _CURRENT_JOB_ID = job_id
        _save_store(config)

    worker = threading.Thread(
        target=_run_job,
        args=(job_id, config, normalized_mode),
        name=f"aurora-kb-job-{job_id[:8]}",
        daemon=True,
    )
    worker.start()
    return replace(job)


def get_job(config: AppConfig, job_id: str) -> KnowledgeBaseJob | None:
    _ensure_store_loaded(config)
    with _JOB_LOCK:
        job = _JOBS.get(job_id)
        return replace(job) if job else None


def get_current_job(config: AppConfig) -> KnowledgeBaseJob | None:
    _ensure_store_loaded(config)
    with _JOB_LOCK:
        job = _JOBS.get(_CURRENT_JOB_ID)
        return replace(job) if job else None


def cancel_job(config: AppConfig, job_id: str) -> KnowledgeBaseJob | None:
    _ensure_store_loaded(config)
    with _JOB_LOCK:
        job = _JOBS.get(job_id)
        if not job:
            return None
        if job.status in _TERMINAL_JOB_STATUSES:
            return replace(job)

        job.cancel_requested = True
        if job.status == "running":
            job.status = "cancelling"
            job.message = "正在取消知识库任务。"
        _save_store(config)
        return replace(job)


def _run_job(job_id: str, config: AppConfig, mode: str) -> None:
    try:
        documents, removed_paths = _prepare_catalog(config, job_id, mode)
        changed_documents = list_documents_needing_index(config)

        _set_job(
            config,
            job_id,
            total_documents=len(documents),
            processed_documents=0,
            total_chunks=0,
            processed_chunks=0,
            message=_build_discovery_message(len(documents), len(changed_documents), mode),
        )

        if _is_cancel_requested(job_id):
            _finish_job(config, job_id, status="cancelled", message="知识库任务已取消。")
            return

        removed_count = _remove_deleted_documents(config, job_id, removed_paths, mode)
        if _is_cancel_requested(job_id):
            _finish_job(config, job_id, status="cancelled", message="知识库任务已取消。")
            return

        if not changed_documents:
            stats = _build_stats(
                config,
                job_id,
                mode=mode,
                document_count=len(list_document_catalog(config)),
                removed_count=removed_count,
            )
            _finish_job(
                config,
                job_id,
                status="completed",
                message=_build_no_work_message(mode),
                stats=stats,
            )
            return

        document_nodes = _parse_changed_documents(config, job_id, changed_documents)
        if _is_cancel_requested(job_id):
            _finish_job(config, job_id, status="cancelled", message="知识库任务已取消。")
            return

        indexed_count, failed_count = _write_index_updates(config, job_id, document_nodes)

        refreshed_documents = list_document_catalog(config)
        stats = _build_stats(
            config,
            job_id,
            mode=mode,
            document_count=len(refreshed_documents),
            removed_count=removed_count,
        )
        if failed_count:
            _finish_job(
                config,
                job_id,
                status="completed_with_errors",
                message=f"知识库任务完成，其中 {failed_count} 份文档处理失败。",
                stats=stats,
            )
            return

        _finish_job(
            config,
            job_id,
            status="completed",
            message=f"知识库任务完成，共更新 {indexed_count} 份文档。",
            stats=stats,
        )
    except Exception as exc:
        logger.exception("Knowledge-base job failed.")
        _finish_job(
            config,
            job_id,
            status="failed",
            message="知识库任务失败，请查看日志。",
            error=str(exc),
        )


def _prepare_catalog(
    config: AppConfig,
    job_id: str,
    mode: str,
) -> tuple[list[object], list[str]]:
    if mode == "sync":
        _set_job(
            config,
            job_id,
            status="running",
            stage="loading",
            progress=0.03,
            message="正在加载待同步文档。",
        )
        return list_document_catalog(config), []

    _set_job(
        config,
        job_id,
        status="running",
        stage="scanning",
        progress=0.05,
        message="正在扫描文档目录并同步 catalog。",
    )
    documents, removed_paths = sync_document_catalog(config, full_scan=True)

    if mode == "reset":
        _set_job(
            config,
            job_id,
            stage="resetting",
            progress=0.12,
            message="正在清空索引并重置文档状态。",
        )
        clear_retrieval_backends(config)
        reset_all_document_tracking(config)
        documents = list_document_catalog(config)

    return documents, removed_paths


def _remove_deleted_documents(
    config: AppConfig,
    job_id: str,
    removed_paths: list[str],
    mode: str,
) -> int:
    if not removed_paths or mode == "reset":
        return len(removed_paths)

    _set_job(
        config,
        job_id,
        stage="cleanup",
        progress=0.12,
        message=f"正在清理 {len(removed_paths)} 份已删除文档的索引。",
    )
    removed_count = 0
    for path in removed_paths:
        if _is_cancel_requested(job_id):
            return removed_count
        delete_document_chunks(config, path)
        removed_count += 1
    return removed_count


def _parse_changed_documents(config: AppConfig, job_id: str, changed_documents: list[object]):
    _set_job(
        config,
        job_id,
        stage="parsing",
        progress=0.18,
        message="正在解析待同步文档并生成切片。",
    )

    document_nodes: list[tuple[object, list[object]]] = []
    total_chunks = 0
    for index, document in enumerate(changed_documents, start=1):
        if _is_cancel_requested(job_id):
            return document_nodes

        source_documents = load_documents_from_paths(
            [document.path],
            config.data_dir,
            metadata_by_path={
                document.path: {
                    "document_id": document.document_id,
                    "theme": document.theme,
                    "tags": document.tags,
                }
            },
        )
        nodes = create_nodes_from_documents(config, source_documents)
        total_chunks += len(nodes)
        document_nodes.append((document, nodes))
        _set_job(
            config,
            job_id,
            progress=0.18 + (0.18 * index / max(1, len(changed_documents))),
            total_chunks=total_chunks,
            message=f"已完成 {index}/{len(changed_documents)} 份文档解析。",
        )
    return document_nodes


def _write_index_updates(
    config: AppConfig,
    job_id: str,
    document_nodes: list[tuple[object, list[object]]],
) -> tuple[int, int]:
    indexed_count = 0
    failed_count = 0
    processed_chunks = 0
    processed_documents = 0

    for index, (document, nodes) in enumerate(document_nodes, start=1):
        if _is_cancel_requested(job_id):
            break

        _set_job(
            config,
            job_id,
            stage="indexing",
            progress=0.38 + (0.5 * (index - 1) / max(1, len(document_nodes))),
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
                    config,
                    job_id,
                    stage="indexing",
                    progress=0.38
                    + 0.5
                    * (((index - 1) + (inserted / max(1, total))) / max(1, len(document_nodes))),
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
            logger.exception("Document indexing failed: %s", document.path)

    return indexed_count, failed_count


def _build_stats(
    config: AppConfig,
    job_id: str,
    *,
    mode: str,
    document_count: int,
    removed_count: int,
) -> KnowledgeBaseStats:
    counts = get_document_status_counts(config)
    indexed_count = counts.get("indexed", 0)
    failed_count = counts.get("failed", 0)
    return KnowledgeBaseStats(
        document_count=document_count,
        chunk_count=get_collection_count(config),
        mode=mode,
        indexed_count=indexed_count,
        changed_count=counts.get("changed", 0),
        pending_count=counts.get("pending", 0),
        failed_count=failed_count,
        removed_count=removed_count,
        skipped_count=max(0, document_count - indexed_count - failed_count),
        job_id=job_id,
    )


def _build_created_message(mode: str) -> str:
    if mode == "reset":
        return "已创建完全重置任务。"
    if mode == "scan":
        return "已创建目录扫描任务。"
    return "已创建快速同步任务。"


def _build_discovery_message(total_documents: int, changed_documents: int, mode: str) -> str:
    if mode == "reset":
        return f"共发现 {total_documents} 份文档，准备全量重建 {changed_documents} 份。"
    return f"共发现 {total_documents} 份文档，待处理 {changed_documents} 份。"


def _build_no_work_message(mode: str) -> str:
    if mode == "sync":
        return "没有待同步的文档，本次已跳过。"
    if mode == "scan":
        return "扫描完成，没有发现需要更新的文档。"
    return "完全重置完成，但当前没有可重建文档。"


def _get_jobs_path(config: AppConfig) -> Path:
    config.ensure_directories()
    return config.db_dir / _JOBS_FILE_NAME


def _ensure_store_loaded(config: AppConfig) -> None:
    global _CURRENT_JOB_ID, _JOBS, _LOADED_JOBS_PATH
    jobs_path = str(_get_jobs_path(config))
    with _JOB_LOCK:
        if _LOADED_JOBS_PATH == jobs_path:
            return

        _JOBS, _CURRENT_JOB_ID = _load_store(config)
        _LOADED_JOBS_PATH = jobs_path


def _load_store(config: AppConfig) -> tuple[dict[str, KnowledgeBaseJob], str]:
    jobs_path = _get_jobs_path(config)
    if not jobs_path.exists():
        return {}, ""

    try:
        payload = json.loads(jobs_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}, ""

    raw_jobs = payload.get("jobs", [])
    current_job_id = str(payload.get("current_job_id", "") or "")
    jobs: dict[str, KnowledgeBaseJob] = {}
    for item in raw_jobs if isinstance(raw_jobs, list) else []:
        job = _deserialize_job(item)
        if job:
            jobs[job.job_id] = job

    interrupted = False
    for job in jobs.values():
        if job.status not in {"queued", "running", "cancelling"}:
            continue
        interrupted = True
        job.status = "failed"
        job.stage = "finished"
        job.message = "服务重启导致任务中断，请重新发起。"
        job.error = job.error or "service restarted while task was in progress"
        job.finished_at = job.finished_at or _now_text()

    if interrupted:
        _write_store(config, jobs, current_job_id)

    return jobs, current_job_id


def _save_store(config: AppConfig) -> None:
    _write_store(config, _JOBS, _CURRENT_JOB_ID)


def _write_store(
    config: AppConfig,
    jobs: dict[str, KnowledgeBaseJob],
    current_job_id: str,
) -> None:
    recent_jobs = sorted(
        jobs.values(),
        key=lambda item: (item.started_at, item.job_id),
        reverse=True,
    )[:60]
    payload = {
        "updated_at": _now_text(),
        "current_job_id": current_job_id,
        "jobs": [asdict(job) for job in recent_jobs],
    }
    _get_jobs_path(config).write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _deserialize_job(payload: object) -> KnowledgeBaseJob | None:
    if not isinstance(payload, dict):
        return None

    stats_payload = payload.get("stats")
    stats = None
    if isinstance(stats_payload, dict):
        stats = KnowledgeBaseStats(
            document_count=int(stats_payload.get("document_count", 0) or 0),
            chunk_count=int(stats_payload.get("chunk_count", 0) or 0),
            mode=str(stats_payload.get("mode", "sync") or "sync"),
            indexed_count=int(stats_payload.get("indexed_count", 0) or 0),
            changed_count=int(stats_payload.get("changed_count", 0) or 0),
            pending_count=int(stats_payload.get("pending_count", 0) or 0),
            failed_count=int(stats_payload.get("failed_count", 0) or 0),
            removed_count=int(stats_payload.get("removed_count", 0) or 0),
            skipped_count=int(stats_payload.get("skipped_count", 0) or 0),
            job_id=str(stats_payload.get("job_id", "") or ""),
        )

    return KnowledgeBaseJob(
        job_id=str(payload.get("job_id", "") or ""),
        status=str(payload.get("status", "") or ""),
        mode=str(payload.get("mode", "sync") or "sync"),
        stage=str(payload.get("stage", "") or ""),
        progress=float(payload.get("progress", 0.0) or 0.0),
        message=str(payload.get("message", "") or ""),
        total_documents=int(payload.get("total_documents", 0) or 0),
        processed_documents=int(payload.get("processed_documents", 0) or 0),
        total_chunks=int(payload.get("total_chunks", 0) or 0),
        processed_chunks=int(payload.get("processed_chunks", 0) or 0),
        started_at=str(payload.get("started_at", "") or ""),
        finished_at=str(payload.get("finished_at", "") or ""),
        error=str(payload.get("error", "") or ""),
        cancel_requested=bool(payload.get("cancel_requested", False)),
        stats=stats,
    )


def _is_cancel_requested(job_id: str) -> bool:
    with _JOB_LOCK:
        job = _JOBS.get(job_id)
        return bool(job and job.cancel_requested)


def _set_job(config: AppConfig, job_id: str, **updates: object) -> None:
    with _JOB_LOCK:
        job = _JOBS.get(job_id)
        if not job:
            return
        for key, value in updates.items():
            setattr(job, key, value)
        _save_store(config)


def _finish_job(
    config: AppConfig,
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
        job.stage = "finished"
        if status in {"completed", "completed_with_errors"}:
            job.progress = 1.0
        job.message = message
        job.error = error
        job.finished_at = _now_text()
        job.stats = stats
        _save_store(config)


def _now_text() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")
