"""系统总览与统计服务。"""

from __future__ import annotations

from app.config import AppConfig
from app.schemas import SystemOverview
from app.services.catalog_service import get_document_status_counts, list_document_catalog
from app.services.knowledge_graph_service import build_knowledge_graph_from_documents
from app.services.knowledge_base_job_service import get_current_job
from app.services.knowledge_base_service import get_collection_count


def get_system_overview(config: AppConfig) -> SystemOverview:
    """返回系统概览数据。"""
    status_counts = get_document_status_counts(config)
    current_job = get_current_job(config)
    chunk_count = get_collection_count(config)
    return build_system_overview(
        config,
        status_counts=status_counts,
        current_job=current_job,
        chunk_count=chunk_count,
    )


def build_system_overview(
    config: AppConfig,
    *,
    status_counts: dict[str, int],
    current_job,
    chunk_count: int,
) -> SystemOverview:
    return SystemOverview(
        app_name=config.app_name,
        app_version=config.app_version,
        data_dir=str(config.data_dir),
        db_dir=str(config.db_dir),
        logs_dir=str(config.logs_dir),
        llm_provider=config.llm_provider,
        embedding_provider=config.embedding_provider,
        llm_api_ready=config.llm_api_ready,
        embedding_api_ready=config.embedding_api_ready,
        knowledge_base_ready=chunk_count > 0,
        source_file_count=status_counts.get("total", 0),
        chunk_count=chunk_count,
        indexed_file_count=status_counts.get("indexed", 0),
        changed_file_count=status_counts.get("changed", 0),
        pending_file_count=status_counts.get("pending", 0),
        failed_file_count=status_counts.get("failed", 0),
        active_job_status=current_job.status if current_job else "",
        active_job_progress=current_job.progress if current_job else 0.0,
    )


def summarize_document_status_counts(documents: list[object]) -> dict[str, int]:
    counts = {
        "indexed": 0,
        "changed": 0,
        "pending": 0,
        "failed": 0,
        "total": len(documents),
    }
    for document in documents:
        status = str(getattr(document, "status", "") or "")
        if status not in counts:
            counts[status] = 0
        counts[status] += 1
    return counts


def build_knowledge_status(
    *,
    status_counts: dict[str, int],
    current_job,
    chunk_count: int,
    document_count: int,
) -> dict[str, object]:
    return {
        "ready": chunk_count > 0,
        "chunk_count": chunk_count,
        "document_count": document_count,
        "indexed_count": status_counts.get("indexed", 0),
        "changed_count": status_counts.get("changed", 0),
        "pending_count": status_counts.get("pending", 0),
        "failed_count": status_counts.get("failed", 0),
        "current_job": current_job,
    }


def get_workspace_bootstrap(config: AppConfig) -> dict[str, object]:
    documents = list_document_catalog(config)
    status_counts = summarize_document_status_counts(documents)
    current_job = get_current_job(config)
    chunk_count = get_collection_count(config)
    return {
        "overview": build_system_overview(
            config,
            status_counts=status_counts,
            current_job=current_job,
            chunk_count=chunk_count,
        ),
        "knowledge_status": build_knowledge_status(
            status_counts=status_counts,
            current_job=current_job,
            chunk_count=chunk_count,
            document_count=len(documents),
        ),
        "documents": documents,
        "graph": build_knowledge_graph_from_documents(config, documents),
    }


def get_recent_documents(config: AppConfig, limit: int = 5):
    """返回最近更新的文档摘要。"""
    documents = list_document_catalog(config)
    return sorted(documents, key=lambda item: item.updated_at, reverse=True)[:limit]
