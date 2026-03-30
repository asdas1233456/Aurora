"""Shared helpers for Aurora's opt-in internal validation APIs."""

from __future__ import annotations

import re

from fastapi import HTTPException, Request

from app.api.request_context import build_request_context
from app.config import AppConfig


_SAFE_ID_PATTERN = re.compile(r"[^a-zA-Z0-9_.:-]+")


def ensure_internal_api(request: Request) -> None:
    # Internal endpoints stay behind an explicit header so public clients do not discover them accidentally.
    if not header_as_bool(request, "x-aurora-internal-api"):
        raise HTTPException(status_code=403, detail="This endpoint is reserved for internal validation.")


def header_as_bool(request: Request, header_name: str) -> bool:
    return request.headers.get(header_name, "").strip().lower() in {"1", "true", "yes", "on"}


def build_internal_request_context(
    request: Request,
    runtime_config: AppConfig,
    *,
    tenant_id: str | None = None,
    user_id: str | None = None,
    project_id: str | None = None,
    session_id: str | None = None,
    request_id: str | None = None,
    team_id: str | None = None,
    global_scope_id: str | None = None,
):
    return build_request_context(
        config=runtime_config,
        tenant_id=tenant_id or request.headers.get("x-aurora-tenant-id"),
        user_id=user_id or request.headers.get("x-aurora-user-id"),
        project_id=project_id or request.headers.get("x-aurora-project-id"),
        session_id=session_id or request.headers.get("x-aurora-session-id"),
        request_id=request_id or request.headers.get("x-request-id"),
        team_id=team_id or request.headers.get("x-aurora-team-id"),
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
        "team_id": request_context.team_id,
        "global_scope_id": request_context.global_scope_id,
        "actor_role": request_context.actor_role,
        "allow_shared_scope_write": request_context.allow_shared_scope_write,
        "allow_global_write": request_context.allow_global_write,
    }


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
