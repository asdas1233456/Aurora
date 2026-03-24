"""知识库管理相关的内部 API。"""

from __future__ import annotations

from pathlib import Path
from typing import Iterable

from app.config import AppConfig
from app.schemas import DocumentSummary, KnowledgeBaseStats
from app.services.document_service import (
    get_document_summaries,
    list_source_files,
    read_document_preview,
    save_raw_files,
    save_uploaded_files,
)
from app.services.knowledge_base_service import get_collection_count, index_exists, rebuild_index


def get_source_files(config: AppConfig):
    """返回当前数据目录中的文档列表。"""
    return list_source_files(config.data_dir)


def upload_documents(uploaded_files: Iterable[object], config: AppConfig) -> list[str]:
    """保存上传文档。"""
    return save_uploaded_files(uploaded_files, config.data_dir)


def upload_raw_documents(files: Iterable[tuple[str, bytes]], config: AppConfig) -> list[str]:
    """保存 REST API 上传的原始文件。"""
    return save_raw_files(files, config.data_dir)


def get_document_list(config: AppConfig) -> list[DocumentSummary]:
    """返回文档摘要列表。"""
    return get_document_summaries(config.data_dir)


def get_document_preview(file_path: str | Path, max_chars: int = 3000) -> str:
    """读取指定文档的预览内容。"""
    return read_document_preview(Path(file_path), max_chars=max_chars)


def knowledge_base_ready(config: AppConfig) -> bool:
    """判断知识库是否已构建。"""
    return index_exists(config)


def get_chunk_count(config: AppConfig) -> int:
    """返回向量库中的片段数量。"""
    return get_collection_count(config)


def rebuild_knowledge_base(config: AppConfig) -> KnowledgeBaseStats:
    """重建知识库并返回统计结果。"""
    stats = rebuild_index(config)
    return KnowledgeBaseStats(**stats)
