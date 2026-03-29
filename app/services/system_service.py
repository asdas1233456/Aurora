"""系统总览与统计服务。"""

from __future__ import annotations

from app.config import AppConfig
from app.schemas import SystemOverview
from app.services.catalog_service import get_document_status_counts, list_document_catalog
from app.services.knowledge_base_job_service import get_current_job
from app.services.knowledge_base_service import get_collection_count, index_exists


def get_system_overview(config: AppConfig) -> SystemOverview:
    """返回系统概览数据。"""
    documents = list_document_catalog(config)
    status_counts = get_document_status_counts(config)
    current_job = get_current_job()
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
        knowledge_base_ready=index_exists(config),
        source_file_count=len(documents),
        chunk_count=get_collection_count(config),
        indexed_file_count=status_counts.get("indexed", 0),
        changed_file_count=status_counts.get("changed", 0),
        pending_file_count=status_counts.get("pending", 0),
        failed_file_count=status_counts.get("failed", 0),
        active_job_status=current_job.status if current_job else "",
        active_job_progress=current_job.progress if current_job else 0.0,
    )


def get_recent_documents(config: AppConfig, limit: int = 5):
    """返回最近更新的文档摘要。"""
    documents = list_document_catalog(config)
    return sorted(documents, key=lambda item: item.updated_at, reverse=True)[:limit]
