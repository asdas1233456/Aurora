"""配置相关的内部 API。"""

from __future__ import annotations

from dataclasses import asdict

from app.config import AppConfig
from app.services.settings_service import load_app_settings, mask_secret, save_app_settings


def get_settings(config: AppConfig) -> dict[str, object]:
    """返回可编辑配置。"""
    return asdict(load_app_settings(config))


def get_masked_settings(config: AppConfig) -> dict[str, object]:
    """返回脱敏后的配置。"""
    data = asdict(load_app_settings(config))
    data["llm_api_key"] = mask_secret(str(data.get("llm_api_key", "")))
    data["embedding_api_key"] = mask_secret(str(data.get("embedding_api_key", "")))
    return data


def update_settings(config: AppConfig, values: dict[str, object]) -> None:
    """更新配置。"""
    save_app_settings(config, values)

