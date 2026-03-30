from __future__ import annotations

from fastapi import APIRouter, Body, Depends, File, HTTPException, Query, UploadFile

from app.api.dependencies import get_app_config
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
from app.api.serializers import serialize_document_summary
from app.config import AppConfig


router = APIRouter(prefix="/api/v1/documents", tags=["documents"])


@router.get("")
def list_documents(config: AppConfig = Depends(get_app_config)):
    return [serialize_document_summary(item) for item in get_document_list(config)]


@router.get("/preview")
def preview_document(
    document_id: str = Query(..., description="文档 ID"),
    config: AppConfig = Depends(get_app_config),
):
    try:
        preview_text = get_document_preview(document_id, config, max_chars=4000)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"document_id": document_id, "preview": preview_text}


@router.post("/upload")
async def upload_document_files(
    files: list[UploadFile] = File(...),
    config: AppConfig = Depends(get_app_config),
):
    if not files:
        raise HTTPException(status_code=400, detail="请至少上传一个文件。")

    raw_files: list[tuple[str, bytes]] = []
    for file_item in files:
        raw_files.append((file_item.filename, await file_item.read()))

    saved_names = upload_raw_documents(raw_files, config)
    return {"saved_count": len(saved_names), "saved_files": saved_names}


@router.patch("/metadata")
def patch_document_metadata(
    payload: DocumentMetadataUpdateModel,
    config: AppConfig = Depends(get_app_config),
):
    result = update_document_metadata(
        payload.document_ids,
        config,
        theme=payload.theme,
        tags=payload.tags,
    )
    return [serialize_document_summary(item) for item in result]


@router.delete("")
def delete_document_files(
    payload: DocumentsDeleteModel = Body(...),
    config: AppConfig = Depends(get_app_config),
):
    result = delete_documents(payload.document_ids, config)
    return {
        "deleted_count": len(result.deleted_ids),
        "deleted_ids": result.deleted_ids,
        "missing_ids": result.missing_ids,
    }


@router.put("/rename")
def rename_document_file(
    payload: DocumentRenameModel,
    config: AppConfig = Depends(get_app_config),
):
    try:
        result = rename_document(payload.document_id, payload.new_name, config)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (FileExistsError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return {
        "document_id": result.document_id,
        "new_name": result.new_name,
        "old_relative_path": result.old_relative_path,
        "new_relative_path": result.new_relative_path,
    }
