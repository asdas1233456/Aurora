"""知识库管理相关的内部 API。"""

from __future__ import annotations

from pathlib import Path
from typing import Iterable

from app.config import AppConfig
from app.schemas import DocumentDeleteResult, DocumentRenameResult, DocumentSummary, KnowledgeBaseJob
from app.services.catalog_service import list_document_catalog, reset_document_tracking, update_document_annotations
from app.services.document_service import (
    delete_documents as delete_source_documents,
    read_document_preview,
    rename_document as rename_source_document,
    save_raw_files,
    save_uploaded_files,
)
from app.services.knowledge_base_job_service import cancel_job, get_current_job, get_job, start_rebuild_job
from app.services.knowledge_base_service import get_collection_count, index_exists


def upload_documents(uploaded_files: Iterable[object], config: AppConfig) -> list[str]:
    """保存上传文档。"""
    return save_uploaded_files(uploaded_files, config.data_dir)


def upload_raw_documents(files: Iterable[tuple[str, bytes]], config: AppConfig) -> list[str]:
    """保存 REST API 上传的原始文件。"""
    return save_raw_files(files, config.data_dir)


def get_document_list(config: AppConfig) -> list[DocumentSummary]:
    """返回文档摘要列表。"""
    return list_document_catalog(config)


def get_document_preview(file_path: str | Path, max_chars: int = 3000) -> str:
    """读取指定文档的预览内容。"""
    return read_document_preview(Path(file_path), max_chars=max_chars)


def delete_documents(paths: Iterable[str | Path], config: AppConfig) -> DocumentDeleteResult:
    """删除指定文档。"""
    result = delete_source_documents(paths, config.data_dir)
    reset_document_tracking(config, result.deleted_paths)
    return result


def rename_document(path: str | Path, new_name: str, config: AppConfig) -> DocumentRenameResult:
    """重命名指定文档。"""
    return rename_source_document(path, new_name, config.data_dir)


def update_document_metadata(
    paths: list[str],
    config: AppConfig,
    *,
    theme: str | None = None,
    tags: list[str] | None = None,
) -> list[DocumentSummary]:
    """更新文档主题和标签。"""
    return update_document_annotations(config, paths, theme=theme, tags=tags)


def knowledge_base_ready(config: AppConfig) -> bool:
    """判断知识库是否已构建。"""
    return index_exists(config)


def get_chunk_count(config: AppConfig) -> int:
    """返回向量库中的片段数量。"""
    return get_collection_count(config)


def rebuild_knowledge_base(config: AppConfig) -> KnowledgeBaseJob:
    """启动异步重建知识库任务。"""
    return start_rebuild_job(config)


def get_current_rebuild_job() -> KnowledgeBaseJob | None:
    """返回当前知识库任务。"""
    return get_current_job()


def get_rebuild_job(job_id: str) -> KnowledgeBaseJob | None:
    """根据任务 ID 返回知识库任务。"""
    return get_job(job_id)


def cancel_rebuild_job(job_id: str) -> KnowledgeBaseJob | None:
    """取消正在执行的知识库任务。"""
    return cancel_job(job_id)
