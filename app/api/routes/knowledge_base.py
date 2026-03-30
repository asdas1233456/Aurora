from __future__ import annotations

from fastapi import APIRouter, Body, Depends, HTTPException

from app.api.dependencies import get_runtime_config
from app.api.knowledge_base import (
    cancel_rebuild_job,
    get_chunk_count,
    get_current_rebuild_job,
    get_rebuild_job,
    rebuild_knowledge_base,
)
from app.api.request_models import KnowledgeBaseRunModel
from app.api.serializers import serialize_job
from app.config import AppConfig
from app.services.catalog_service import get_document_status_counts


router = APIRouter(prefix="/api/v1/knowledge-base", tags=["knowledge-base"])


@router.get("/status")
def get_kb_status(runtime_config: AppConfig = Depends(get_runtime_config)):
    status_counts = get_document_status_counts(runtime_config)
    current_job = get_current_rebuild_job(runtime_config)
    chunk_count = get_chunk_count(runtime_config)
    return {
        "ready": chunk_count > 0,
        "chunk_count": chunk_count,
        "document_count": status_counts.get("total", 0),
        "indexed_count": status_counts.get("indexed", 0),
        "changed_count": status_counts.get("changed", 0),
        "pending_count": status_counts.get("pending", 0),
        "failed_count": status_counts.get("failed", 0),
        "current_job": serialize_job(current_job),
    }


@router.get("/jobs/current")
def get_current_kb_job(runtime_config: AppConfig = Depends(get_runtime_config)):
    return serialize_job(get_current_rebuild_job(runtime_config))


@router.get("/jobs/{job_id}")
def get_kb_job(job_id: str, runtime_config: AppConfig = Depends(get_runtime_config)):
    job = get_rebuild_job(runtime_config, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Knowledge-base job does not exist.")
    return serialize_job(job)


@router.post("/jobs/{job_id}/cancel")
def cancel_kb_job(job_id: str, runtime_config: AppConfig = Depends(get_runtime_config)):
    job = cancel_rebuild_job(runtime_config, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Knowledge-base job does not exist.")
    return serialize_job(job)


@router.post("/rebuild")
def rebuild_kb(
    payload: KnowledgeBaseRunModel | None = Body(default=None),
    runtime_config: AppConfig = Depends(get_runtime_config),
):
    try:
        mode = payload.mode if payload else "sync"
        job = rebuild_knowledge_base(runtime_config, mode=mode)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return serialize_job(job)


@router.post("/sync")
def sync_kb(runtime_config: AppConfig = Depends(get_runtime_config)):
    return rebuild_kb(KnowledgeBaseRunModel(mode="sync"), runtime_config)


@router.post("/scan")
def scan_kb(runtime_config: AppConfig = Depends(get_runtime_config)):
    return rebuild_kb(KnowledgeBaseRunModel(mode="scan"), runtime_config)


@router.post("/reset")
def reset_kb(runtime_config: AppConfig = Depends(get_runtime_config)):
    return rebuild_kb(KnowledgeBaseRunModel(mode="reset"), runtime_config)
