"""Settings helpers for API routes."""

from __future__ import annotations

from dataclasses import asdict

from app.config import AppConfig
from app.services.connectivity_service import test_settings_connections
from app.services.settings_service import load_app_settings, save_app_settings


def get_settings(config: AppConfig) -> dict[str, object]:
    return asdict(load_app_settings(config))


def get_masked_settings(config: AppConfig) -> dict[str, object]:
    data = asdict(load_app_settings(config))
    data["llm_api_key"] = ""
    data["embedding_api_key"] = ""
    data["operations_managed_fields"] = [
        "LLM_API_KEY",
        "EMBEDDING_API_KEY",
        "API_HOST",
        "API_PORT",
        "CORS_ORIGINS",
    ]
    return data


def update_settings(
    config: AppConfig,
    values: dict[str, object],
    *,
    actor_user_id: str,
) -> None:
    save_app_settings(config, values, actor_user_id=actor_user_id)


def test_settings(config: AppConfig, values: dict[str, object]) -> dict[str, object]:
    return asdict(test_settings_connections(config, values))
