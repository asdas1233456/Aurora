from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from app.api.dependencies import get_runtime_config, require_internal_admin
from app.api.internal_utils import (
    build_internal_request_context,
    ensure_internal_api,
    serialize_request_context,
)
from app.api.request_models import (
    MemoryLifecycleMaintenanceModel,
    MemoryManualWriteModel,
    MemoryRetrievalPreviewModel,
    MemoryStatusUpdateModel,
)
from app.api.serializers import (
    serialize_lifecycle_maintenance_report,
    serialize_metric_snapshot_record,
    serialize_memory_audit_record,
    serialize_memory_retrieval_bundle,
    serialize_memory_fact,
    serialize_memory_retention_audit_record,
    serialize_policy_decision_record,
    serialize_security_event_record,
    serialize_scope_ref,
)
from app.auth import AuthenticatedUser
from app.config import AppConfig
from app.services.abuse_guard import RateLimitExceededError
from app.services.audit_service import AuditService
from app.services.chat_session_service import ChatSessionService
from app.services.governance_inspector import GovernanceInspector
from app.services.lifecycle_maintenance_service import LifecycleMaintenanceService
from app.services.memory.governance.memory_audit_service import MemoryAuditService
from app.services.memory.governance.memory_scope import ScopeResolver
from app.services.memory.governance.retention_audit_service import RetentionAuditService
from app.services.memory.read.memory_retriever import MemoryRetriever
from app.services.memory.write.memory_write_service import MemoryWriteService
from app.services.observability_service import ObservabilityService


router = APIRouter(prefix="/api/v1/internal/memory", tags=["internal-memory"], include_in_schema=False)


@router.post("/facts")
def create_memory_fact(
    request: Request,
    payload: MemoryManualWriteModel,
    runtime_config: AppConfig = Depends(get_runtime_config),
    user: AuthenticatedUser = Depends(require_internal_admin),
):
    ensure_internal_api(request)
    request_context = build_internal_request_context(
        request,
        runtime_config,
        user,
        tenant_id=payload.tenant_id,
        user_id=payload.user_id,
        project_id=payload.project_id,
        session_id=payload.session_id,
        request_id=payload.request_id,
        team_id=payload.team_id,
        global_scope_id=payload.global_scope_id,
    )

    try:
        ChatSessionService(runtime_config).ensure_session(
            request_context,
            title=(payload.session_title or "Manual memory validation").strip(),
        )
        write_service = MemoryWriteService(runtime_config)
        create_payload = write_service.build_create_payload(
            request_context,
            content=payload.content,
            memory_type=payload.type,
            scope_type=payload.scope_type,
            scope_id=payload.scope_id,
            source_kind=payload.source_kind,
            confirmed=payload.confirmed,
            subject_key=payload.subject_key,
            fact_key=payload.fact_key,
            correction_of=payload.correction_of,
            source_type=payload.source_type,
            source_confidence=payload.source_confidence,
            reviewed_by_human=payload.reviewed_by_human,
            consistency_group_id=payload.consistency_group_id,
        )
        write_result = write_service.write_memory_fact(request_context, create_payload)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except RateLimitExceededError as exc:
        raise HTTPException(status_code=429, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    resolved = ScopeResolver().resolve(request_context)
    return {
        "item": serialize_memory_fact(write_result.memory_fact),
        "consistency": {
            "operation": write_result.operation,
            "reason": write_result.reason,
            "subject_key": write_result.subject_key,
            "fact_key": write_result.fact_key,
            "consistency_group_id": write_result.consistency_group_id,
            "superseded_fact_ids": write_result.superseded_fact_ids,
            "hidden_by_scope_fact_ids": write_result.hidden_by_scope_fact_ids,
        },
        "allowed_scopes": [serialize_scope_ref(item) for item in resolved.allowed_scopes],
        "request_context": serialize_request_context(request_context),
    }


@router.get("/facts")
def list_memory_facts(
    request: Request,
    tenant_id: str | None = None,
    user_id: str | None = None,
    project_id: str | None = None,
    session_id: str | None = None,
    request_id: str | None = None,
    team_id: str | None = None,
    global_scope_id: str | None = None,
    limit: int = Query(default=5, ge=1, le=20),
    runtime_config: AppConfig = Depends(get_runtime_config),
    user: AuthenticatedUser = Depends(require_internal_admin),
):
    ensure_internal_api(request)
    request_context = build_internal_request_context(
        request,
        runtime_config,
        user,
        tenant_id=tenant_id,
        user_id=user_id,
        project_id=project_id,
        session_id=session_id,
        request_id=request_id,
        team_id=team_id,
        global_scope_id=global_scope_id,
    )
    resolver = ScopeResolver()
    resolved = resolver.resolve(request_context)
    items = MemoryRetriever(runtime_config, scope_resolver=resolver).retrieve(resolved, top_k=limit)
    return {
        "items": [serialize_memory_fact(item) for item in items],
        "count": len(items),
        "allowed_scopes": [serialize_scope_ref(item) for item in resolved.allowed_scopes],
        "request_context": serialize_request_context(request_context),
    }


@router.post("/retrieve")
def preview_memory_retrieval(
    request: Request,
    payload: MemoryRetrievalPreviewModel,
    runtime_config: AppConfig = Depends(get_runtime_config),
    user: AuthenticatedUser = Depends(require_internal_admin),
):
    ensure_internal_api(request)
    request_context = build_internal_request_context(
        request,
        runtime_config,
        user,
        tenant_id=payload.tenant_id,
        user_id=payload.user_id,
        project_id=payload.project_id,
        session_id=payload.session_id,
        request_id=payload.request_id,
        team_id=payload.team_id,
        global_scope_id=payload.global_scope_id,
    )
    resolver = ScopeResolver()
    resolved = resolver.resolve(request_context)
    bundle = MemoryRetriever(
        runtime_config,
        scope_resolver=resolver,
    ).retrieve_bundle(
        resolved,
        scene=payload.scene,
        user_query=payload.question,
        top_k=payload.top_k or runtime_config.default_top_k,
        retrieval_mode=payload.retrieval_mode,
        retrieval_metadata={"request_id": request_context.request_id, "preview": True},
    )
    return {
        "bundle": serialize_memory_retrieval_bundle(bundle),
        "allowed_scopes": [serialize_scope_ref(item) for item in resolved.allowed_scopes],
        "request_context": serialize_request_context(request_context),
    }


@router.get("/facts/{memory_fact_id}")
def get_memory_fact(
    memory_fact_id: str,
    request: Request,
    tenant_id: str | None = None,
    user_id: str | None = None,
    project_id: str | None = None,
    session_id: str | None = None,
    request_id: str | None = None,
    team_id: str | None = None,
    global_scope_id: str | None = None,
    runtime_config: AppConfig = Depends(get_runtime_config),
    user: AuthenticatedUser = Depends(require_internal_admin),
):
    ensure_internal_api(request)
    request_context = build_internal_request_context(
        request,
        runtime_config,
        user,
        tenant_id=tenant_id,
        user_id=user_id,
        project_id=project_id,
        session_id=session_id,
        request_id=request_id,
        team_id=team_id,
        global_scope_id=global_scope_id,
    )
    item = MemoryWriteService(runtime_config).get_memory_fact_by_id(request_context, memory_fact_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Memory fact not found or not accessible.")
    return {"item": serialize_memory_fact(item), "request_context": serialize_request_context(request_context)}


@router.get("/facts/{memory_fact_id}/history")
def get_memory_fact_history(
    memory_fact_id: str,
    request: Request,
    tenant_id: str | None = None,
    user_id: str | None = None,
    project_id: str | None = None,
    session_id: str | None = None,
    request_id: str | None = None,
    team_id: str | None = None,
    global_scope_id: str | None = None,
    limit: int = Query(default=20, ge=1, le=100),
    runtime_config: AppConfig = Depends(get_runtime_config),
    user: AuthenticatedUser = Depends(require_internal_admin),
):
    ensure_internal_api(request)
    request_context = build_internal_request_context(
        request,
        runtime_config,
        user,
        tenant_id=tenant_id,
        user_id=user_id,
        project_id=project_id,
        session_id=session_id,
        request_id=request_id,
        team_id=team_id,
        global_scope_id=global_scope_id,
    )
    write_service = MemoryWriteService(runtime_config)
    base_item = write_service.get_memory_fact_by_id(request_context, memory_fact_id)
    if base_item is None:
        raise HTTPException(status_code=404, detail="Memory fact not found or not accessible.")

    items = write_service.list_memory_history(
        request_context,
        memory_fact_id,
        limit=limit,
    )
    return {
        "base_item": serialize_memory_fact(base_item),
        "items": [serialize_memory_fact(item) for item in items],
        "count": len(items),
        "request_context": serialize_request_context(request_context),
    }


@router.patch("/facts/{memory_fact_id}/status")
def update_memory_fact_status(
    memory_fact_id: str,
    payload: MemoryStatusUpdateModel,
    request: Request,
    runtime_config: AppConfig = Depends(get_runtime_config),
    user: AuthenticatedUser = Depends(require_internal_admin),
):
    ensure_internal_api(request)
    request_context = build_internal_request_context(
        request,
        runtime_config,
        user,
        tenant_id=payload.tenant_id,
        user_id=payload.user_id,
        project_id=payload.project_id,
        session_id=payload.session_id,
        request_id=payload.request_id,
        team_id=payload.team_id,
        global_scope_id=payload.global_scope_id,
    )

    try:
        item = MemoryWriteService(runtime_config).update_memory_fact_status(
            request_context,
            memory_fact_id=memory_fact_id,
            status=payload.status,
        )
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except RateLimitExceededError as exc:
        raise HTTPException(status_code=429, detail=str(exc)) from exc

    if item is None:
        raise HTTPException(status_code=404, detail="Memory fact not found or not accessible.")
    return {"item": serialize_memory_fact(item), "request_context": serialize_request_context(request_context)}


@router.get("/audit/request/{request_id}")
def list_memory_audit_by_request(
    request_id: str,
    request: Request,
    tenant_id: str | None = None,
    runtime_config: AppConfig = Depends(get_runtime_config),
    user: AuthenticatedUser = Depends(require_internal_admin),
):
    ensure_internal_api(request)
    request_context = build_internal_request_context(
        request,
        runtime_config,
        user,
        tenant_id=tenant_id,
        request_id=request_id,
    )
    items = MemoryAuditService(runtime_config).list_by_request_id(request_context.tenant_id, request_id)
    return {
        "items": [serialize_memory_audit_record(item) for item in items],
        "count": len(items),
        "tenant_id": request_context.tenant_id,
        "request_id": request_id,
    }


@router.get("/facts/{memory_fact_id}/retention-audit")
def list_memory_retention_audit(
    memory_fact_id: str,
    request: Request,
    tenant_id: str | None = None,
    request_id: str | None = None,
    runtime_config: AppConfig = Depends(get_runtime_config),
    user: AuthenticatedUser = Depends(require_internal_admin),
):
    ensure_internal_api(request)
    request_context = build_internal_request_context(
        request,
        runtime_config,
        user,
        tenant_id=tenant_id,
        request_id=request_id,
    )
    items = RetentionAuditService(runtime_config).list_by_memory_fact_id(
        request_context.tenant_id,
        memory_fact_id,
    )
    return {
        "items": [serialize_memory_retention_audit_record(item) for item in items],
        "count": len(items),
        "tenant_id": request_context.tenant_id,
        "memory_fact_id": memory_fact_id,
    }


@router.get("/governance/summary")
def get_governance_summary(
    request: Request,
    tenant_id: str | None = None,
    request_id: str | None = None,
    limit: int = Query(default=10, ge=1, le=50),
    capture_snapshot: bool = False,
    runtime_config: AppConfig = Depends(get_runtime_config),
    user: AuthenticatedUser = Depends(require_internal_admin),
):
    ensure_internal_api(request)
    request_context = build_internal_request_context(
        request,
        runtime_config,
        user,
        tenant_id=tenant_id,
        request_id=request_id,
    )
    summary = GovernanceInspector(runtime_config).build_summary(
        tenant_id=request_context.tenant_id,
        limit=limit,
        capture_snapshot=capture_snapshot,
    )
    return {
        "summary": summary,
        "request_context": serialize_request_context(request_context),
    }


@router.get("/security-events")
def list_security_events(
    request: Request,
    tenant_id: str | None = None,
    request_id: str | None = None,
    limit: int = Query(default=20, ge=1, le=100),
    status: str | None = None,
    runtime_config: AppConfig = Depends(get_runtime_config),
    user: AuthenticatedUser = Depends(require_internal_admin),
):
    ensure_internal_api(request)
    request_context = build_internal_request_context(
        request,
        runtime_config,
        user,
        tenant_id=tenant_id,
        request_id=request_id,
    )
    items = AuditService(runtime_config).list_security_events(
        tenant_id=request_context.tenant_id,
        limit=limit,
        status=status,
    )
    return {
        "items": [serialize_security_event_record(item) for item in items],
        "count": len(items),
        "tenant_id": request_context.tenant_id,
    }


@router.get("/policy-decisions")
def list_policy_decisions(
    request: Request,
    request_id: str | None = None,
    decision: str | None = None,
    limit: int = Query(default=20, ge=1, le=100),
    runtime_config: AppConfig = Depends(get_runtime_config),
    _user: AuthenticatedUser = Depends(require_internal_admin),
):
    ensure_internal_api(request)
    items = AuditService(runtime_config).list_policy_decisions(
        request_id=request_id,
        decision=decision,
        limit=limit,
    )
    return {
        "items": [serialize_policy_decision_record(item) for item in items],
        "count": len(items),
        "request_id": request_id or "",
    }


@router.get("/metrics/snapshots")
def list_metric_snapshots(
    request: Request,
    metric_name: str | None = None,
    limit: int = Query(default=20, ge=1, le=100),
    runtime_config: AppConfig = Depends(get_runtime_config),
    _user: AuthenticatedUser = Depends(require_internal_admin),
):
    ensure_internal_api(request)
    items = ObservabilityService(runtime_config).list_metric_snapshots(
        metric_name=metric_name,
        limit=limit,
    )
    return {
        "items": [serialize_metric_snapshot_record(item) for item in items],
        "count": len(items),
        "metric_name": metric_name or "",
    }


@router.post("/lifecycle/run")
def run_memory_lifecycle_maintenance(
    request: Request,
    payload: MemoryLifecycleMaintenanceModel,
    runtime_config: AppConfig = Depends(get_runtime_config),
    user: AuthenticatedUser = Depends(require_internal_admin),
):
    ensure_internal_api(request)
    request_context = build_internal_request_context(
        request,
        runtime_config,
        user,
        tenant_id=payload.tenant_id,
        request_id=payload.request_id,
    )
    try:
        report = LifecycleMaintenanceService(runtime_config).run_due(
            tenant_id=request_context.tenant_id,
            limit=payload.limit,
            dry_run=payload.dry_run,
            request_context=request_context,
        )
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    return {
        "report": serialize_lifecycle_maintenance_report(report),
        "tenant_id": request_context.tenant_id,
        "request_context": serialize_request_context(request_context),
    }
