"""Authentication, project scoping, and permission helpers for shared deployment."""

from __future__ import annotations

from dataclasses import asdict
import re

from fastapi import Request

from app.core.config import AppConfig
from app.presentation.http.request_context import build_request_context
from app.schemas import AuthenticatedUser, MemoryRequestContext


_SAFE_ID_PATTERN = re.compile(r"[^a-zA-Z0-9_.:-]+")
_ROLE_PERMISSIONS = {
    "viewer": {
        "system.read",
        "chat.use",
        "documents.read",
        "graph.read",
        "knowledge_base.read",
    },
    "member": {
        "system.read",
        "chat.use",
        "documents.read",
        "documents.write",
        "graph.read",
        "knowledge_base.read",
    },
    "operator": {
        "system.read",
        "chat.use",
        "documents.read",
        "documents.write",
        "graph.read",
        "knowledge_base.read",
        "knowledge_base.operate",
        "logs.read",
    },
    "admin": {
        "system.read",
        "chat.use",
        "documents.read",
        "documents.write",
        "graph.read",
        "knowledge_base.read",
        "knowledge_base.operate",
        "logs.read",
        "logs.clear",
        "settings.read",
        "settings.write",
        "providers.dry_run",
        "internal.access",
    },
}


class AuthenticationRequiredError(PermissionError):
    """Raised when a request has no trusted authenticated user."""


class AuthorizationError(PermissionError):
    """Raised when an authenticated user attempts an unauthorized action."""


def resolve_authenticated_user(request: Request, config: AppConfig) -> AuthenticatedUser:
    """Resolve the effective authenticated user from the configured auth mode."""
    auth_mode = str(config.auth_mode or "").strip().lower()
    if auth_mode in {"", "development"}:
        return _build_development_user(config, auth_source="development")
    if auth_mode == "disabled":
        return _build_development_user(config, auth_source="disabled")
    if auth_mode == "trusted_header":
        return _build_trusted_header_user(request, config)
    raise AuthenticationRequiredError(f"Unsupported auth mode: {auth_mode}")


def permission_set_for_user(user: AuthenticatedUser) -> set[str]:
    return set(_ROLE_PERMISSIONS.get(user.role, _ROLE_PERMISSIONS["viewer"]))


def ensure_permission(user: AuthenticatedUser, permission: str) -> None:
    if permission not in permission_set_for_user(user):
        raise AuthorizationError(f"Role '{user.role}' cannot perform '{permission}'.")


def resolve_active_project_id(
    request: Request,
    user: AuthenticatedUser,
    config: AppConfig,
    *,
    requested_project_id: str | None = None,
) -> str:
    requested = _normalize_identifier(
        requested_project_id or request.headers.get(config.auth_active_project_header)
    )
    allowed = [_normalize_identifier(item) for item in user.allowed_project_ids]
    allowed = [item for item in allowed if item]
    default_project_id = _normalize_identifier(user.default_project_id) or (
        allowed[0] if allowed else _normalize_identifier(config.base_dir.name) or "aurora"
    )
    if requested and requested not in set(allowed or [default_project_id]):
        raise AuthorizationError(f"Project access denied for '{requested}'.")
    return requested or default_project_id


def build_authenticated_request_context(
    request: Request,
    config: AppConfig,
    user: AuthenticatedUser,
    *,
    session_id: str | None = None,
    request_id: str | None = None,
    project_id: str | None = None,
    department_id: str | None = None,
    actor_role: str = "conversation",
    allow_shared_scope_write: bool = False,
    allow_global_write: bool = False,
) -> MemoryRequestContext:
    active_project_id = resolve_active_project_id(
        request,
        user,
        config,
        requested_project_id=project_id,
    )
    return build_request_context(
        config=config,
        tenant_id=user.tenant_id,
        user_id=user.user_id,
        project_id=active_project_id,
        session_id=session_id or request.headers.get("x-aurora-session-id"),
        department_id=department_id or request.headers.get("x-aurora-department-id"),
        request_id=request_id or request.headers.get("x-request-id"),
        team_id=user.team_id,
        actor_role=actor_role,
        allow_shared_scope_write=allow_shared_scope_write,
        allow_global_write=allow_global_write,
    )


def serialize_authenticated_user(user: AuthenticatedUser) -> dict[str, object]:
    return asdict(user)


def describe_authorization(
    request: Request,
    user: AuthenticatedUser,
    config: AppConfig,
) -> dict[str, object]:
    active_project_id = resolve_active_project_id(request, user, config)
    return {
        "user": serialize_authenticated_user(user),
        "permissions": sorted(permission_set_for_user(user)),
        "active_project_id": active_project_id,
    }


def _build_development_user(config: AppConfig, *, auth_source: str) -> AuthenticatedUser:
    allowed_project_ids = _normalize_project_ids(config.auth_dev_project_ids)
    default_project_id = allowed_project_ids[0] if allowed_project_ids else "aurora"
    role = _normalize_role(config.auth_dev_role)
    return AuthenticatedUser(
        tenant_id=config.tenant_id,
        user_id=_normalize_identifier(config.auth_dev_user_id) or "aurora-admin",
        role=role,
        team_id=_normalize_identifier(config.auth_dev_team_id) or "team-platform",
        display_name=str(config.auth_dev_display_name or "Aurora Admin").strip() or "Aurora Admin",
        email=str(config.auth_dev_email or "").strip(),
        allowed_project_ids=allowed_project_ids or [default_project_id],
        default_project_id=default_project_id,
        auth_source=auth_source,
    )


def _build_trusted_header_user(request: Request, config: AppConfig) -> AuthenticatedUser:
    user_id = _normalize_identifier(request.headers.get(config.auth_header_user_id))
    if not user_id:
        raise AuthenticationRequiredError("Trusted SSO user header is missing.")

    role = _normalize_role(request.headers.get(config.auth_header_role) or "viewer")
    team_id = _normalize_identifier(request.headers.get(config.auth_header_team_id)) or "team_default"
    project_ids = _normalize_project_ids(request.headers.get(config.auth_header_project_ids))
    default_project_id = project_ids[0] if project_ids else (
        _normalize_identifier(config.base_dir.name) or "aurora"
    )

    return AuthenticatedUser(
        tenant_id=config.tenant_id,
        user_id=user_id,
        role=role,
        team_id=team_id,
        display_name=str(request.headers.get(config.auth_header_display_name) or user_id).strip()
        or user_id,
        email=str(request.headers.get(config.auth_header_email) or "").strip(),
        allowed_project_ids=project_ids or [default_project_id],
        default_project_id=default_project_id,
        auth_source="trusted_header",
    )


def _normalize_project_ids(raw_value: str | None) -> list[str]:
    raw_text = str(raw_value or "").strip()
    if not raw_text:
        return []
    normalized_ids: list[str] = []
    for item in re.split(r"[,\s;]+", raw_text):
        normalized = _normalize_identifier(item)
        if normalized and normalized not in normalized_ids:
            normalized_ids.append(normalized)
    return normalized_ids


def _normalize_role(raw_value: str | None) -> str:
    normalized = str(raw_value or "").strip().lower()
    if normalized not in _ROLE_PERMISSIONS:
        raise AuthenticationRequiredError(f"Unsupported application role: {raw_value}")
    return normalized


def _normalize_identifier(value: str | None) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        return ""
    return _SAFE_ID_PATTERN.sub("_", normalized)
