from __future__ import annotations

from fastapi import APIRouter, Body, Depends, HTTPException, Request

from app.api.dependencies import get_runtime_config, require_permission
from app.api.knowledge_base import (
    cancel_rebuild_job,
    get_chunk_count,
    get_current_rebuild_job,
    get_rebuild_job,
    rebuild_knowledge_base,
)
from app.api.request_models import KnowledgeBaseRunModel
from app.api.security import audit_app_event, concurrency_slot, enforce_rate_limit, make_request_context
from app.api.serializers import serialize_job
from app.auth import AuthenticatedUser
from app.config import AppConfig
from app.services.catalog_service import get_document_status_counts


router = APIRouter(prefix="/api/v1/knowledge-base", tags=["knowledge-base"])


@router.get("/status")
def get_kb_status(
    runtime_config: AppConfig = Depends(get_runtime_config),
    _user: AuthenticatedUser = Depends(require_permission("knowledge_base.read")),
):
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
def get_current_kb_job(
    runtime_config: AppConfig = Depends(get_runtime_config),
    _user: AuthenticatedUser = Depends(require_permission("knowledge_base.read")),
):
    return serialize_job(get_current_rebuild_job(runtime_config))


@router.get("/jobs/{job_id}")
def get_kb_job(
    job_id: str,
    runtime_config: AppConfig = Depends(get_runtime_config),
    _user: AuthenticatedUser = Depends(require_permission("knowledge_base.read")),
):
    job = get_rebuild_job(runtime_config, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Knowledge-base job does not exist.")
    return serialize_job(job)


@router.post("/jobs/{job_id}/cancel")
def cancel_kb_job(
    job_id: str,
    request: Request,
    runtime_config: AppConfig = Depends(get_runtime_config),
    user: AuthenticatedUser = Depends(require_permission("knowledge_base.operate")),
):
    request_context = make_request_context(request, runtime_config, user, actor_role="system")
    job = cancel_rebuild_job(runtime_config, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Knowledge-base job does not exist.")
    audit_app_event(
        runtime_config,
        user=user,
        action="knowledge_base.cancel",
        outcome="succeeded",
        request_context=request_context,
        target_type="knowledge_base_job",
        target_id=job_id,
        details={"status": job.status},
    )
    return serialize_job(job)


@router.post("/rebuild")
def rebuild_kb(
    request: Request,
    payload: KnowledgeBaseRunModel | None = Body(default=None),
    runtime_config: AppConfig = Depends(get_runtime_config),
    user: AuthenticatedUser = Depends(require_permission("knowledge_base.operate")),
):
    request_context = make_request_context(request, runtime_config, user, actor_role="system")
    requested_mode = payload.mode if payload else "sync"
    current_job = get_current_rebuild_job(runtime_config)
    if current_job and current_job.status in {"queued", "running", "cancelling"}:
        audit_app_event(
            runtime_config,
            user=user,
            action="knowledge_base.rebuild",
            outcome="denied",
            request_context=request_context,
            target_type="knowledge_base_job",
            target_id=current_job.job_id,
            details={
                "reason": "job_in_progress",
                "active_job_id": current_job.job_id,
                "active_status": current_job.status,
                "requested_mode": requested_mode,
            },
        )
        raise HTTPException(
            status_code=409,
            detail={
                "message": "A knowledge-base job is already in progress.",
                "active_job_id": current_job.job_id,
                "active_status": current_job.status,
            },
        )
    enforce_rate_limit(
        runtime_config,
        request_context=request_context,
        user=user,
        request=request,
        action_name="knowledge_rebuild",
        target_type="knowledge_base",
    )
    try:
        with concurrency_slot(
            runtime_config,
            request_context=request_context,
            user=user,
            request=request,
            action_name="knowledge_rebuild",
            target_type="knowledge_base",
            status_code=409,
        ):
            job = rebuild_knowledge_base(runtime_config, mode=requested_mode)
    except HTTPException:
        raise
    except Exception as exc:
        audit_app_event(
            runtime_config,
            user=user,
            action="knowledge_base.rebuild",
            outcome="failed",
            request_context=request_context,
            target_type="knowledge_base",
            details={"mode": requested_mode, "error": str(exc)},
        )
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    audit_app_event(
        runtime_config,
        user=user,
        action="knowledge_base.rebuild",
        outcome="succeeded",
        request_context=request_context,
        target_type="knowledge_base_job",
        target_id=job.job_id,
        details={"mode": job.mode, "status": job.status},
    )
    return serialize_job(job)


@router.post("/sync")
def sync_kb(
    request: Request,
    runtime_config: AppConfig = Depends(get_runtime_config),
    user: AuthenticatedUser = Depends(require_permission("knowledge_base.operate")),
):
    return rebuild_kb(request, KnowledgeBaseRunModel(mode="sync"), runtime_config, user)


@router.post("/scan")
def scan_kb(
    request: Request,
    runtime_config: AppConfig = Depends(get_runtime_config),
    user: AuthenticatedUser = Depends(require_permission("knowledge_base.operate")),
):
    return rebuild_kb(request, KnowledgeBaseRunModel(mode="scan"), runtime_config, user)


@router.post("/reset")
def reset_kb(
    request: Request,
    runtime_config: AppConfig = Depends(get_runtime_config),
    user: AuthenticatedUser = Depends(require_permission("knowledge_base.operate")),
):
    return rebuild_kb(request, KnowledgeBaseRunModel(mode="reset"), runtime_config, user)
