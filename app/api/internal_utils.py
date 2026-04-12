"""Shared helpers for Aurora's opt-in internal validation APIs."""

from __future__ import annotations

import re

from fastapi import HTTPException, Request

from app.api.request_context import build_request_context
from app.auth import serialize_authenticated_user
from app.config import AppConfig
from app.schemas import AuthenticatedUser


_SAFE_ID_PATTERN = re.compile(r"[^a-zA-Z0-9_.:-]+")


def ensure_internal_api(request: Request) -> None:
    if not getattr(request.state, "internal_access_granted", False):
        raise HTTPException(status_code=403, detail="This endpoint is reserved for internal validation.")


def header_as_bool(request: Request, header_name: str) -> bool:
    return request.headers.get(header_name, "").strip().lower() in {"1", "true", "yes", "on"}


def build_internal_request_context(
    request: Request,
    runtime_config: AppConfig,
    authenticated_user: AuthenticatedUser,
    *,
    tenant_id: str | None = None,
    user_id: str | None = None,
    project_id: str | None = None,
    session_id: str | None = None,
    department_id: str | None = None,
    request_id: str | None = None,
    team_id: str | None = None,
    global_scope_id: str | None = None,
):
    return build_request_context(
        config=runtime_config,
        tenant_id=tenant_id or authenticated_user.tenant_id,
        user_id=user_id or request.headers.get("x-aurora-user-id") or authenticated_user.user_id,
        project_id=project_id or request.headers.get("x-aurora-project-id") or authenticated_user.default_project_id,
        session_id=session_id or request.headers.get("x-aurora-session-id"),
        department_id=department_id or request.headers.get("x-aurora-department-id"),
        request_id=request_id or request.headers.get("x-request-id"),
        team_id=team_id or request.headers.get("x-aurora-team-id") or authenticated_user.team_id,
        global_scope_id=global_scope_id or request.headers.get("x-aurora-global-scope-id"),
        actor_role=(request.headers.get("x-aurora-actor-role", "system").strip().lower() or "system"),
        allow_shared_scope_write=header_as_bool(request, "x-aurora-allow-shared-scope-write"),
        allow_global_write=header_as_bool(request, "x-aurora-allow-global-write"),
    )


def serialize_request_context(request_context) -> dict[str, object]:
    return {
        "request_id": request_context.request_id,
        "tenant_id": request_context.tenant_id,
        "user_id": request_context.user_id,
        "project_id": request_context.project_id,
        "session_id": request_context.session_id,
        "department_id": request_context.department_id,
        "team_id": request_context.team_id,
        "global_scope_id": request_context.global_scope_id,
        "actor_role": request_context.actor_role,
        "allow_shared_scope_write": request_context.allow_shared_scope_write,
        "allow_global_write": request_context.allow_global_write,
    }


def serialize_internal_actor(user: AuthenticatedUser) -> dict[str, object]:
    return serialize_authenticated_user(user)


def resolve_internal_identifier(
    request: Request,
    *,
    param_value: str | None = None,
    header_name: str | None = None,
    required: bool = False,
    field_label: str = "identifier",
) -> str | None:
    raw_value = (param_value or (request.headers.get(header_name, "") if header_name else "")).strip()
    normalized = _SAFE_ID_PATTERN.sub("_", raw_value) if raw_value else ""
    if normalized:
        return normalized
    if required:
        raise HTTPException(status_code=400, detail=f"{field_label} is required.")
    return None
