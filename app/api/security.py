"""Shared helpers for authenticated route context, auditing, and throttling."""

from __future__ import annotations

from contextlib import contextmanager

from fastapi import HTTPException, Request

from app.auth import AuthenticatedUser, AuthorizationError, build_authenticated_request_context
from app.config import AppConfig
from app.modules.system.request_concurrency import RequestConcurrencyGuard
from app.schemas import MemoryRequestContext
from app.services.abuse_guard import AbuseGuard
from app.services.application_audit_service import ApplicationAuditService


def make_request_context(
    request: Request,
    config: AppConfig,
    user: AuthenticatedUser,
    *,
    session_id: str | None = None,
    request_id: str | None = None,
    project_id: str | None = None,
    actor_role: str = "conversation",
) -> MemoryRequestContext:
    try:
        return build_authenticated_request_context(
            request,
            config,
            user,
            session_id=session_id,
            request_id=request_id,
            project_id=project_id,
            actor_role=actor_role,
        )
    except AuthorizationError as exc:
        audit_app_event(
            config,
            user=user,
            action="project.access",
            outcome="denied",
            target_type="project",
            target_id=str(project_id or request.headers.get(config.auth_active_project_header) or ""),
            details={
                "reason": str(exc),
                "path": request.url.path,
                "method": request.method,
            },
        )
        raise HTTPException(
            status_code=403,
            detail="You do not have access to the requested project.",
        ) from exc


def audit_app_event(
    config: AppConfig,
    *,
    user: AuthenticatedUser,
    action: str,
    outcome: str,
    request_context: MemoryRequestContext | None = None,
    target_type: str = "",
    target_id: str = "",
    details: dict[str, object] | None = None,
) -> None:
    ApplicationAuditService(config).record_event(
        user=user,
        action=action,
        outcome=outcome,
        request_context=request_context,
        target_type=target_type,
        target_id=target_id,
        details=details,
    )


def enforce_rate_limit(
    config: AppConfig,
    *,
    request_context: MemoryRequestContext,
    user: AuthenticatedUser,
    request: Request,
    action_name: str,
    target_type: str,
    target_id: str = "",
) -> None:
    decision = AbuseGuard().check_and_consume(request_context, action_name=action_name)
    if decision.allowed:
        return

    audit_app_event(
        config,
        user=user,
        action=action_name,
        outcome="denied",
        request_context=request_context,
        target_type=target_type,
        target_id=target_id,
        details={
            "reason": decision.reason,
            "limited_scope": decision.limited_scope,
            "retry_after_seconds": decision.retry_after_seconds,
            "path": request.url.path,
            "method": request.method,
        },
    )
    raise HTTPException(
        status_code=429,
        detail={
            "message": "Too many requests. Please retry later.",
            "retry_after_seconds": decision.retry_after_seconds,
        },
    )


def acquire_concurrency_slot(
    config: AppConfig,
    *,
    request_context: MemoryRequestContext,
    user: AuthenticatedUser,
    request: Request,
    action_name: str,
    target_type: str,
    target_id: str = "",
    status_code: int = 429,
) -> None:
    decision = RequestConcurrencyGuard().try_acquire(action_name)
    if decision.allowed:
        return

    audit_app_event(
        config,
        user=user,
        action=action_name,
        outcome="denied",
        request_context=request_context,
        target_type=target_type,
        target_id=target_id,
        details={
            "reason": "concurrency_limit_reached",
            "active_count": decision.active_count,
            "limit": decision.limit,
            "path": request.url.path,
            "method": request.method,
        },
    )
    raise HTTPException(
        status_code=status_code,
        detail={
            "message": "This action already has too many active requests.",
            "active_count": decision.active_count,
            "limit": decision.limit,
        },
    )


def release_concurrency_slot(action_name: str) -> None:
    RequestConcurrencyGuard().release(action_name)


@contextmanager
def concurrency_slot(
    config: AppConfig,
    *,
    request_context: MemoryRequestContext,
    user: AuthenticatedUser,
    request: Request,
    action_name: str,
    target_type: str,
    target_id: str = "",
    status_code: int = 429,
):
    acquire_concurrency_slot(
        config,
        request_context=request_context,
        user=user,
        request=request,
        action_name=action_name,
        target_type=target_type,
        target_id=target_id,
        status_code=status_code,
    )
    try:
        yield
    finally:
        release_concurrency_slot(action_name)
