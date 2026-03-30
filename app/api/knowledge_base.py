"""Internal knowledge-base management API helpers."""

from __future__ import annotations

import logging
from pathlib import Path

from app.config import AppConfig
from app.schemas import DocumentDeleteResult, DocumentRenameResult, DocumentSummary, KnowledgeBaseJob
from app.services.catalog_service import (
    get_document_by_id,
    get_documents_by_ids,
    list_document_catalog,
    register_documents_in_catalog,
    remove_documents_from_catalog,
    rename_document_in_catalog,
    reset_document_tracking,
    update_document_annotations,
)
from app.services.document_service import (
    delete_documents as delete_source_documents,
    read_document_preview,
    rename_document as rename_source_document,
    save_raw_files,
    save_uploaded_files,
)
from app.services.knowledge_base_job_service import cancel_job, get_current_job, get_job, start_rebuild_job
from app.services.knowledge_base_service import delete_document_chunks, get_collection_count, index_exists

logger = logging.getLogger(__name__)


def upload_documents(uploaded_files: list[object], config: AppConfig) -> list[str]:
    """Save uploaded documents into the source data directory."""
    saved_names = save_uploaded_files(uploaded_files, config.data_dir)
    register_documents_in_catalog(config, [config.data_dir / name for name in saved_names])
    return saved_names


def upload_raw_documents(files: list[tuple[str, bytes]], config: AppConfig) -> list[str]:
    """Save REST API uploads into the source data directory."""
    saved_names = save_raw_files(files, config.data_dir)
    register_documents_in_catalog(config, [config.data_dir / name for name in saved_names])
    return saved_names


def get_document_list(config: AppConfig) -> list[DocumentSummary]:
    """Return catalog summaries."""
    return list_document_catalog(config)


def get_document_preview(document_id: str, config: AppConfig, max_chars: int = 3000) -> str:
    """Read a document preview by document ID."""
    document = get_document_by_id(config, document_id)
    if not document:
        raise FileNotFoundError("Document does not exist or has been removed.")
    return read_document_preview(Path(document.path), max_chars=max_chars)


def delete_documents(document_ids: list[str], config: AppConfig) -> DocumentDeleteResult:
    """Delete selected source documents and their index entries."""
    documents, missing_ids = get_documents_by_ids(config, document_ids)
    source_result = delete_source_documents([item.path for item in documents], config.data_dir)
    deleted_ids = [item.document_id for item in documents if item.path in source_result.deleted_paths]
    for deleted_path in source_result.deleted_paths:
        delete_document_chunks(config, deleted_path)
    remove_documents_from_catalog(config, deleted_ids)
    if not deleted_ids:
        logger.warning(
            "Document delete completed without removing files. requested_ids=%s missing_ids=%s missing_paths=%s",
            document_ids,
            missing_ids,
            source_result.missing_paths,
        )
    elif missing_ids or source_result.missing_paths:
        logger.warning(
            "Document delete partially completed. deleted_ids=%s missing_ids=%s missing_paths=%s",
            deleted_ids,
            missing_ids,
            source_result.missing_paths,
        )
    return DocumentDeleteResult(
        deleted_ids=deleted_ids,
        deleted_paths=source_result.deleted_paths,
        missing_ids=missing_ids,
        missing_paths=source_result.missing_paths,
    )


def rename_document(document_id: str, new_name: str, config: AppConfig) -> DocumentRenameResult:
    """Rename one source document and mark it for re-indexing."""
    document = get_document_by_id(config, document_id)
    if not document:
        raise FileNotFoundError("Document does not exist or has been removed.")

    source_result = rename_source_document(document.path, new_name, config.data_dir)
    delete_document_chunks(config, source_result.old_path)
    rename_document_in_catalog(
        config,
        document_id=document.document_id,
        old_path=source_result.old_path,
        new_path=source_result.new_path,
    )
    return DocumentRenameResult(
        document_id=document.document_id,
        old_path=source_result.old_path,
        new_path=source_result.new_path,
        old_relative_path=source_result.old_relative_path,
        new_relative_path=source_result.new_relative_path,
        new_name=source_result.new_name,
    )


def update_document_metadata(
    document_ids: list[str],
    config: AppConfig,
    *,
    theme: str | None = None,
    tags: list[str] | None = None,
) -> list[DocumentSummary]:
    """Update catalog annotations and queue the documents for re-indexing."""
    documents, _ = get_documents_by_ids(config, document_ids)
    paths = [item.path for item in documents]
    updated_documents = update_document_annotations(config, paths, theme=theme, tags=tags)
    reset_document_tracking(config, paths)
    return updated_documents


def knowledge_base_ready(config: AppConfig) -> bool:
    """Return whether a retrieval index is available."""
    return index_exists(config)


def get_chunk_count(config: AppConfig) -> int:
    """Return indexed chunk count."""
    return get_collection_count(config)


def rebuild_knowledge_base(config: AppConfig, *, mode: str = "sync") -> KnowledgeBaseJob:
    """Start an asynchronous knowledge-base job."""
    return start_rebuild_job(config, mode=mode)


def get_current_rebuild_job(config: AppConfig) -> KnowledgeBaseJob | None:
    """Return the current knowledge-base job."""
    return get_current_job(config)


def get_rebuild_job(config: AppConfig, job_id: str) -> KnowledgeBaseJob | None:
    """Return a knowledge-base job by ID."""
    return get_job(config, job_id)


def cancel_rebuild_job(config: AppConfig, job_id: str) -> KnowledgeBaseJob | None:
    """Cancel a running knowledge-base job."""
    return cancel_job(config, job_id)
