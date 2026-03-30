from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from app.api.dependencies import get_app_config
from app.api.request_models import SettingsUpdateModel
from app.api.settings import get_masked_settings, test_settings, update_settings
from app.config import AppConfig
from app.services.settings_service import SettingsValidationError


router = APIRouter(prefix="/api/v1/settings", tags=["settings"])
runtime_router = APIRouter(prefix="/api/v1/runtime", tags=["runtime"])


@router.get("")
def get_settings_view(config: AppConfig = Depends(get_app_config)):
    return get_masked_settings(config)


@router.put("")
def update_settings_view(
    payload: SettingsUpdateModel,
    config: AppConfig = Depends(get_app_config),
):
    try:
        update_settings(config, payload.values)
    except SettingsValidationError as exc:
        raise HTTPException(
            status_code=400,
            detail={
                "message": "配置校验失败，请修正后再保存。",
                "errors": exc.errors,
            },
        ) from exc
    return {"message": "配置已写入 .env。"}


@router.post("/test")
def test_settings_view(
    payload: SettingsUpdateModel,
    config: AppConfig = Depends(get_app_config),
):
    return test_settings(config, payload.values)


@runtime_router.get("/config")
def get_runtime_config_help():
    return {
        "description": "可通过请求头覆盖当前请求使用的模型 Key / Base，不写入 .env。",
        "headers": {
            "X-LLM-API-Key": "当前请求使用的 LLM API Key",
            "X-Embedding-API-Key": "当前请求使用的 Embedding API Key",
            "X-LLM-API-Base": "当前请求使用的 LLM API Base",
            "X-Embedding-API-Base": "当前请求使用的 Embedding API Base",
            "X-Use-Same-Embedding-Key": "true/false，默认 true",
            "X-Use-Same-Embedding-Base": "true/false，默认 true",
        },
    }
