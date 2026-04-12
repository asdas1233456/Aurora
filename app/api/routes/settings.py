from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request

from app.api.dependencies import get_app_config, require_permission
from app.api.request_models import SettingsUpdateModel
from app.api.security import audit_app_event, make_request_context
from app.api.settings import get_masked_settings, test_settings, update_settings
from app.auth import AuthenticatedUser
from app.config import AppConfig
from app.services.settings_service import ManagedSettingUpdateError, SettingsValidationError


router = APIRouter(prefix="/api/v1/settings", tags=["settings"])
runtime_router = APIRouter(prefix="/api/v1/runtime", tags=["runtime"])


@router.get("")
def get_settings_view(
    config: AppConfig = Depends(get_app_config),
    _user: AuthenticatedUser = Depends(require_permission("settings.read")),
):
    return get_masked_settings(config)


@router.put("")
def update_settings_view(
    request: Request,
    payload: SettingsUpdateModel,
    config: AppConfig = Depends(get_app_config),
    user: AuthenticatedUser = Depends(require_permission("settings.write")),
):
    request_context = make_request_context(request, config, user, actor_role="system")
    try:
        update_settings(config, payload.values, actor_user_id=user.user_id)
    except ManagedSettingUpdateError as exc:
        audit_app_event(
            config,
            user=user,
            action="settings.update",
            outcome="failed",
            request_context=request_context,
            target_type="settings",
            details={"forbidden_keys": exc.keys},
        )
        raise HTTPException(
            status_code=400,
            detail={
                "message": "Operations-managed settings must be injected by ops, not changed from the UI.",
                "forbidden_keys": exc.keys,
            },
        ) from exc
    except SettingsValidationError as exc:
        audit_app_event(
            config,
            user=user,
            action="settings.update",
            outcome="failed",
            request_context=request_context,
            target_type="settings",
            details={"errors": exc.errors},
        )
        raise HTTPException(
            status_code=400,
            detail={
                "message": "配置校验失败，请修正后再保存。",
                "errors": exc.errors,
            },
        ) from exc

    audit_app_event(
        config,
        user=user,
        action="settings.update",
        outcome="succeeded",
        request_context=request_context,
        target_type="settings",
        details={"updated_keys": sorted(payload.values.keys())},
    )
    return {"message": "非敏感运行配置已持久化。"}


@router.post("/test")
def test_settings_view(
    request: Request,
    payload: SettingsUpdateModel,
    config: AppConfig = Depends(get_app_config),
    user: AuthenticatedUser = Depends(require_permission("settings.read")),
):
    request_context = make_request_context(request, config, user, actor_role="system")
    try:
        result = test_settings(config, payload.values)
    except ManagedSettingUpdateError as exc:
        audit_app_event(
            config,
            user=user,
            action="settings.test",
            outcome="failed",
            request_context=request_context,
            target_type="settings",
            details={"forbidden_keys": exc.keys},
        )
        raise HTTPException(
            status_code=400,
            detail={
                "message": "Operations-managed settings must be injected by ops, not tested from the UI.",
                "forbidden_keys": exc.keys,
            },
        ) from exc
    audit_app_event(
        config,
        user=user,
        action="settings.test",
        outcome="succeeded",
        request_context=request_context,
        target_type="settings",
        details={"updated_keys": sorted(payload.values.keys())},
    )
    return result


@runtime_router.get("/config")
def get_runtime_config_help(
    _user: AuthenticatedUser = Depends(require_permission("settings.read")),
):
    return {
        "description": "浏览器侧运行时密钥透传已在共享部署模式下禁用。",
        "managed_by_ops": ["LLM_API_KEY", "EMBEDDING_API_KEY", "API_HOST", "API_PORT", "CORS_ORIGINS"],
    }
