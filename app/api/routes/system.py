from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request

from app.api.dependencies import get_runtime_config, require_permission
from app.api.security import audit_app_event
from app.api.serializers import serialize_overview, serialize_workspace_bootstrap
from app.api.system import get_bootstrap, get_overview
from app.auth import AuthenticatedUser, AuthorizationError, describe_authorization
from app.config import AppConfig


router = APIRouter(prefix="/api/v1/system", tags=["system"])


@router.get("/overview")
def get_system_overview(
    runtime_config: AppConfig = Depends(get_runtime_config),
    _user: AuthenticatedUser = Depends(require_permission("system.read")),
):
    return serialize_overview(get_overview(runtime_config))


@router.get("/bootstrap")
def get_system_bootstrap(
    request: Request,
    runtime_config: AppConfig = Depends(get_runtime_config),
    user: AuthenticatedUser = Depends(require_permission("system.read")),
):
    payload = get_bootstrap(runtime_config)
    try:
        payload["auth"] = describe_authorization(request, user, runtime_config)
    except AuthorizationError as exc:
        audit_app_event(
            runtime_config,
            user=user,
            action="project.access",
            outcome="denied",
            target_type="project",
            target_id=str(request.headers.get(runtime_config.auth_active_project_header) or ""),
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
    return serialize_workspace_bootstrap(payload)
