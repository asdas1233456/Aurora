from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Body, Depends, File, HTTPException, Query, Request, UploadFile

from app.api.dependencies import get_app_config, require_permission
from app.api.knowledge_base import (
    delete_documents,
    get_document_list,
    get_document_preview,
    rename_document,
    update_document_metadata,
    upload_raw_documents,
)
from app.api.request_models import (
    DocumentMetadataUpdateModel,
    DocumentRenameModel,
    DocumentsDeleteModel,
)
from app.api.security import audit_app_event, concurrency_slot, enforce_rate_limit, make_request_context
from app.api.serializers import serialize_document_preview, serialize_document_summary
from app.auth import AuthenticatedUser
from app.config import AppConfig
from app.services.document_service import quarantine_rejected_upload


router = APIRouter(prefix="/api/v1/documents", tags=["documents"])

_MIME_ALLOWLIST = {
    ".pdf": {"application/pdf"},
    ".docx": {
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "application/octet-stream",
    },
    ".xlsx": {
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "application/octet-stream",
    },
    ".html": {"text/html", "application/xhtml+xml", "text/plain"},
    ".htm": {"text/html", "application/xhtml+xml", "text/plain"},
    ".url": {"text/plain", "application/octet-stream"},
    ".txt": {"text/plain", "application/octet-stream"},
    ".md": {"text/markdown", "text/plain", "application/octet-stream"},
    ".csv": {"text/csv", "text/plain", "application/octet-stream"},
    ".json": {"application/json", "text/plain", "application/octet-stream"},
    ".yaml": {
        "application/yaml",
        "application/x-yaml",
        "text/yaml",
        "text/plain",
        "application/octet-stream",
    },
    ".yml": {
        "application/yaml",
        "application/x-yaml",
        "text/yaml",
        "text/plain",
        "application/octet-stream",
    },
    ".sql": {"application/sql", "text/plain", "application/octet-stream"},
}


@router.get("")
def list_documents(
    config: AppConfig = Depends(get_app_config),
    _user: AuthenticatedUser = Depends(require_permission("documents.read")),
):
    return [serialize_document_summary(item) for item in get_document_list(config)]


@router.get("/preview")
def preview_document(
    document_id: str = Query(..., description="Document ID"),
    config: AppConfig = Depends(get_app_config),
    _user: AuthenticatedUser = Depends(require_permission("documents.read")),
):
    try:
        preview_payload = get_document_preview(document_id, config, max_chars=4000)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return serialize_document_preview(preview_payload)


@router.post("/upload")
async def upload_document_files(
    request: Request,
    files: list[UploadFile] = File(...),
    config: AppConfig = Depends(get_app_config),
    user: AuthenticatedUser = Depends(require_permission("documents.write")),
):
    if not files:
        raise HTTPException(status_code=400, detail="At least one file is required.")
    if len(files) > config.upload_max_batch_files:
        raise HTTPException(
            status_code=400,
            detail=f"At most {config.upload_max_batch_files} files can be uploaded at once.",
        )

    request_context = make_request_context(request, config, user, actor_role="system")
    enforce_rate_limit(
        config,
        request_context=request_context,
        user=user,
        request=request,
        action_name="document_upload",
        target_type="documents",
    )

    with concurrency_slot(
        config,
        request_context=request_context,
        user=user,
        request=request,
        action_name="document_upload",
        target_type="documents",
    ):
        raw_files: list[tuple[str, bytes]] = []
        for file_item in files:
            file_name = Path(str(file_item.filename or "")).name
            if not file_name:
                raise HTTPException(status_code=400, detail="Uploaded files must include a filename.")
            content = await file_item.read(config.upload_max_file_bytes + 1)
            content_type = str(file_item.content_type or "").strip().lower()
            _validate_upload_candidate(
                config,
                file_name=file_name,
                content=content,
                content_type=content_type,
            )
            raw_files.append((file_name, content))

        saved_names = upload_raw_documents(raw_files, config)

    audit_app_event(
        config,
        user=user,
        action="documents.upload",
        outcome="succeeded",
        request_context=request_context,
        target_type="documents",
        details={"saved_files": saved_names},
    )
    return {"saved_count": len(saved_names), "saved_files": saved_names}


@router.patch("/metadata")
def patch_document_metadata(
    request: Request,
    payload: DocumentMetadataUpdateModel,
    config: AppConfig = Depends(get_app_config),
    user: AuthenticatedUser = Depends(require_permission("documents.write")),
):
    request_context = make_request_context(request, config, user, actor_role="system")
    result = update_document_metadata(
        payload.document_ids,
        config,
        theme=payload.theme,
        tags=payload.tags,
    )
    audit_app_event(
        config,
        user=user,
        action="documents.metadata.update",
        outcome="succeeded",
        request_context=request_context,
        target_type="documents",
        details={"document_ids": payload.document_ids},
    )
    return [serialize_document_summary(item) for item in result]


@router.delete("")
def delete_document_files(
    request: Request,
    payload: DocumentsDeleteModel = Body(...),
    config: AppConfig = Depends(get_app_config),
    user: AuthenticatedUser = Depends(require_permission("documents.write")),
):
    request_context = make_request_context(request, config, user, actor_role="system")
    result = delete_documents(payload.document_ids, config)
    audit_app_event(
        config,
        user=user,
        action="documents.delete",
        outcome="succeeded",
        request_context=request_context,
        target_type="documents",
        details={"document_ids": payload.document_ids, "deleted_ids": result.deleted_ids},
    )
    return {
        "deleted_count": len(result.deleted_ids),
        "deleted_ids": result.deleted_ids,
        "missing_ids": result.missing_ids,
    }


@router.put("/rename")
def rename_document_file(
    request: Request,
    payload: DocumentRenameModel,
    config: AppConfig = Depends(get_app_config),
    user: AuthenticatedUser = Depends(require_permission("documents.write")),
):
    request_context = make_request_context(request, config, user, actor_role="system")
    try:
        result = rename_document(payload.document_id, payload.new_name, config)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (FileExistsError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    audit_app_event(
        config,
        user=user,
        action="documents.rename",
        outcome="succeeded",
        request_context=request_context,
        target_type="document",
        target_id=payload.document_id,
        details={"new_name": payload.new_name},
    )
    return {
        "document_id": result.document_id,
        "new_name": result.new_name,
        "old_relative_path": result.old_relative_path,
        "new_relative_path": result.new_relative_path,
    }


def _validate_upload_candidate(
    config: AppConfig,
    *,
    file_name: str,
    content: bytes,
    content_type: str,
) -> None:
    suffix = Path(file_name).suffix.lower()
    if len(content) > config.upload_max_file_bytes:
        quarantine_rejected_upload(
            file_name=file_name,
            content=content[: config.upload_max_file_bytes],
            reason="file_too_large",
            config=config,
            content_type=content_type,
        )
        raise HTTPException(
            status_code=400,
            detail=f"{file_name} exceeds the upload limit of {config.upload_max_file_bytes} bytes.",
        )

    normalized_content_type = content_type.split(";")[0].strip().lower() if content_type else ""
    allowed_mime_types = _MIME_ALLOWLIST.get(suffix, {"application/octet-stream", "text/plain"})
    if normalized_content_type and normalized_content_type not in allowed_mime_types:
        quarantine_rejected_upload(
            file_name=file_name,
            content=content,
            reason="mime_type_mismatch",
            config=config,
            content_type=normalized_content_type,
        )
        raise HTTPException(
            status_code=400,
            detail=f"{file_name} has a disallowed MIME type: {normalized_content_type}.",
        )
