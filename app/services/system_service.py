"""系统总览与统计服务。"""

from __future__ import annotations

from app.config import AppConfig
from app.schemas import SystemOverview
from app.services.document_service import get_document_summaries, list_source_files
from app.services.knowledge_base_service import get_collection_count, index_exists


def get_system_overview(config: AppConfig) -> SystemOverview:
    """返回系统概览数据。"""
    source_files = list_source_files(config.data_dir)
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
        source_file_count=len(source_files),
        chunk_count=get_collection_count(config),
    )


def get_recent_documents(config: AppConfig, limit: int = 5):
    """返回最近更新的文档摘要。"""
    documents = get_document_summaries(config.data_dir)
    return sorted(documents, key=lambda item: item.updated_at, reverse=True)[:limit]
