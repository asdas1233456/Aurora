"""FastAPI dependencies shared across route modules."""

from __future__ import annotations

from fastapi import Depends, HTTPException, Request

from app.auth import (
    AuthenticationRequiredError,
    AuthorizationError,
    ensure_permission,
    resolve_authenticated_user,
)
from app.config import AppConfig, get_config
from app.schemas import AuthenticatedUser
from app.services.application_audit_service import ApplicationAuditService


def get_app_config() -> AppConfig:
    return get_config()


def get_runtime_config() -> AppConfig:
    """Shared runtime config now always comes from server-side managed settings."""
    return get_config()


def get_authenticated_user(
    request: Request,
    config: AppConfig = Depends(get_app_config),
) -> AuthenticatedUser:
    cached_user = getattr(request.state, "authenticated_user", None)
    if cached_user is not None:
        return cached_user

    try:
        resolved_user = resolve_authenticated_user(request, config)
    except AuthenticationRequiredError as exc:
        _record_auth_audit(
            config,
            user=None,
            request=request,
            action="auth.required",
            outcome="denied",
            reason=str(exc),
        )
        raise HTTPException(status_code=401, detail="Authentication is required.") from exc

    request.state.authenticated_user = resolved_user
    return resolved_user


def require_permission(permission: str):
    def _dependency(
        request: Request,
        config: AppConfig = Depends(get_app_config),
        user: AuthenticatedUser = Depends(get_authenticated_user),
    ) -> AuthenticatedUser:
        try:
            ensure_permission(user, permission)
        except AuthorizationError as exc:
            _record_auth_audit(
                config,
                user=user,
                request=request,
                action=permission,
                outcome="denied",
                reason=str(exc),
            )
            raise HTTPException(status_code=403, detail="You do not have permission to perform this action.") from exc
        return user

    return _dependency


def require_internal_admin(
    request: Request,
    config: AppConfig = Depends(get_app_config),
    user: AuthenticatedUser = Depends(require_permission("internal.access")),
) -> AuthenticatedUser:
    request.state.internal_access_granted = True
    return user


def _record_auth_audit(
    config: AppConfig,
    *,
    user: AuthenticatedUser | None,
    request: Request,
    action: str,
    outcome: str,
    reason: str,
) -> None:
    try:
        ApplicationAuditService(config).record_event(
            user=user,
            action=action,
            outcome=outcome,
            target_type="route",
            target_id=request.url.path,
            details={
                "reason": reason,
                "method": request.method,
                "path": request.url.path,
            },
        )
    except Exception:
        # Authorization should never fail closed because audit persistence is unavailable.
        return
