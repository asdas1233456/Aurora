"""Application settings read/write service for shared deployment."""

from __future__ import annotations

from dataclasses import replace
import logging

from app.config import (
    AppConfig,
    SUPPORTED_MODEL_PROVIDERS,
    _normalize_provider,
    is_openai_compatible_provider,
    is_openai_provider,
)
from app.schemas import AppSettings
from app.services.persistence_utils import utc_now_iso
from app.services.storage_service import connect_state_db


logger = logging.getLogger(__name__)

EDITABLE_SETTINGS_KEYS = {
    "LLM_PROVIDER",
    "EMBEDDING_PROVIDER",
    "LLM_API_BASE",
    "LLM_MODEL",
    "LLM_TEMPERATURE",
    "LLM_TIMEOUT",
    "LLM_MAX_TOKENS",
    "EMBEDDING_API_BASE",
    "EMBEDDING_MODEL",
    "CHUNK_SIZE",
    "CHUNK_OVERLAP",
    "TOP_K",
    "MAX_HISTORY_TURNS",
    "NO_ANSWER_MIN_SCORE",
    "CHROMA_COLLECTION_NAME",
    "LOG_LEVEL",
}
OPERATIONS_MANAGED_KEYS = {
    "LLM_API_KEY",
    "EMBEDDING_API_KEY",
    "API_HOST",
    "API_PORT",
    "CORS_ORIGINS",
    "AUTH_MODE",
    "TENANT_ID",
}

VALID_LOG_LEVELS = {"DEBUG", "INFO", "WARNING", "ERROR"}
VALID_PROVIDERS = SUPPORTED_MODEL_PROVIDERS


class SettingsValidationError(ValueError):
    """Raised when persisted settings fail validation."""

    def __init__(self, errors: dict[str, str]) -> None:
        self.errors = errors
        super().__init__("Settings validation failed")


class ManagedSettingUpdateError(ValueError):
    """Raised when UI callers attempt to modify operations-managed settings."""

    def __init__(self, keys: list[str]) -> None:
        self.keys = sorted(set(str(key).strip() for key in keys if str(key).strip()))
        super().__init__("Operations-managed settings cannot be modified here")


def load_app_settings(config: AppConfig) -> AppSettings:
    """Return the editable settings view, excluding operations-managed secrets."""
    return AppSettings(
        llm_provider=config.llm_provider,
        embedding_provider=config.embedding_provider,
        llm_api_key="",
        llm_api_base=config.llm_api_base,
        llm_model=config.llm_model,
        llm_temperature=config.llm_temperature,
        llm_timeout=config.llm_timeout,
        llm_max_tokens=config.llm_max_tokens,
        embedding_api_key="",
        embedding_api_base=config.embedding_api_base,
        embedding_model=config.embedding_model,
        chunk_size=config.chunk_size,
        chunk_overlap=config.chunk_overlap,
        top_k=config.default_top_k,
        max_history_turns=config.max_history_turns,
        no_answer_min_score=config.no_answer_min_score,
        collection_name=config.collection_name,
        log_level=config.log_level,
        api_host=config.api_host,
        api_port=config.api_port,
        cors_origins=config.cors_origins,
    )


def load_runtime_setting_values(config: AppConfig) -> dict[str, str]:
    """Load persisted non-sensitive settings from the application state database."""
    with connect_state_db(config) as connection:
        rows = connection.execute(
            """
            SELECT key, value
            FROM app_runtime_settings
            WHERE key IN ({placeholders})
            ORDER BY key ASC
            """.format(placeholders=", ".join("?" for _ in EDITABLE_SETTINGS_KEYS)),
            tuple(sorted(EDITABLE_SETTINGS_KEYS)),
        ).fetchall()
    return {str(row["key"]): str(row["value"] or "") for row in rows}


def apply_runtime_settings_overrides(config: AppConfig) -> AppConfig:
    """Overlay persisted runtime settings on top of env-derived config."""
    persisted = load_runtime_setting_values(config)
    if not persisted:
        return config
    return build_config_from_settings_values(config, persisted)


def merge_settings_with_current(config: AppConfig, values: dict[str, object]) -> dict[str, str]:
    """Merge a partial update with the current effective settings view."""
    merged_values = {
        "LLM_PROVIDER": config.llm_provider,
        "EMBEDDING_PROVIDER": config.embedding_provider,
        "LLM_API_KEY": config.llm_api_key,
        "LLM_API_BASE": config.llm_api_base,
        "LLM_MODEL": config.llm_model,
        "LLM_TEMPERATURE": str(config.llm_temperature),
        "LLM_TIMEOUT": str(config.llm_timeout),
        "LLM_MAX_TOKENS": str(config.llm_max_tokens),
        "EMBEDDING_API_KEY": config.embedding_api_key,
        "EMBEDDING_API_BASE": config.embedding_api_base,
        "EMBEDDING_MODEL": config.embedding_model,
        "CHUNK_SIZE": str(config.chunk_size),
        "CHUNK_OVERLAP": str(config.chunk_overlap),
        "TOP_K": str(config.default_top_k),
        "MAX_HISTORY_TURNS": str(config.max_history_turns),
        "NO_ANSWER_MIN_SCORE": str(config.no_answer_min_score),
        "CHROMA_COLLECTION_NAME": config.collection_name,
        "LOG_LEVEL": config.log_level,
        "API_HOST": config.api_host,
        "API_PORT": str(config.api_port),
        "CORS_ORIGINS": config.cors_origins,
    }

    for key, value in values.items():
        if key not in EDITABLE_SETTINGS_KEYS:
            continue
        text_value = str(value).strip()
        if key in {"LLM_PROVIDER", "EMBEDDING_PROVIDER"}:
            merged_values[key] = _normalize_provider(text_value)
        else:
            merged_values[key] = text_value

    return merged_values


def build_config_from_settings_values(config: AppConfig, values: dict[str, object]) -> AppConfig:
    """Build a temporary effective config using current secrets plus pending changes."""
    merged = merge_settings_with_current(config, values)
    return replace(
        config,
        llm_provider=merged["LLM_PROVIDER"],
        embedding_provider=merged["EMBEDDING_PROVIDER"],
        llm_api_key=merged["LLM_API_KEY"],
        llm_api_base=merged["LLM_API_BASE"],
        llm_model=merged["LLM_MODEL"],
        llm_temperature=float(merged["LLM_TEMPERATURE"] or config.llm_temperature),
        llm_timeout=float(merged["LLM_TIMEOUT"] or config.llm_timeout),
        llm_max_tokens=int(merged["LLM_MAX_TOKENS"] or config.llm_max_tokens),
        embedding_api_key=merged["EMBEDDING_API_KEY"],
        embedding_api_base=merged["EMBEDDING_API_BASE"],
        embedding_model=merged["EMBEDDING_MODEL"],
        chunk_size=int(merged["CHUNK_SIZE"] or config.chunk_size),
        chunk_overlap=int(merged["CHUNK_OVERLAP"] or config.chunk_overlap),
        default_top_k=int(merged["TOP_K"] or config.default_top_k),
        max_history_turns=int(merged["MAX_HISTORY_TURNS"] or config.max_history_turns),
        no_answer_min_score=float(merged["NO_ANSWER_MIN_SCORE"] or config.no_answer_min_score),
        collection_name=merged["CHROMA_COLLECTION_NAME"],
        log_level=merged["LOG_LEVEL"],
    )


def save_app_settings(
    config: AppConfig,
    values: dict[str, object],
    *,
    actor_user_id: str = "system",
) -> None:
    """Persist non-sensitive runtime settings into the state database."""
    ensure_editable_settings_only(values)
    merged_values = merge_settings_with_current(config, values)
    errors = validate_app_settings(merged_values)
    if errors:
        raise SettingsValidationError(errors)

    persisted_values = {
        key: merged_values[key]
        for key in EDITABLE_SETTINGS_KEYS
        if key in merged_values
    }
    updated_at = utc_now_iso()

    with connect_state_db(config) as connection:
        connection.executemany(
            """
            INSERT INTO app_runtime_settings (key, value, updated_at, updated_by)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(key) DO UPDATE SET
                value = excluded.value,
                updated_at = excluded.updated_at,
                updated_by = excluded.updated_by
            """,
            [
                (
                    key,
                    persisted_values[key],
                    updated_at,
                    actor_user_id,
                )
                for key in sorted(persisted_values)
            ],
        )

    logger.info("Persisted %s non-sensitive runtime settings.", len(persisted_values))


def ensure_editable_settings_only(values: dict[str, object]) -> None:
    managed_keys = [
        str(key).strip()
        for key in values
        if str(key).strip() in OPERATIONS_MANAGED_KEYS
    ]
    if managed_keys:
        raise ManagedSettingUpdateError(managed_keys)


def mask_secret(value: str) -> str:
    """Mask a sensitive value for UI display."""
    if not value:
        return ""
    if len(value) <= 8:
        return "*" * len(value)
    return f"{value[:4]}{'*' * (len(value) - 8)}{value[-4:]}"


def validate_app_settings(values: dict[str, str]) -> dict[str, str]:
    """Validate the effective settings view using server-managed secrets where needed."""
    errors: dict[str, str] = {}

    llm_provider = _normalize_provider(values.get("LLM_PROVIDER", "").strip())
    embedding_provider = _normalize_provider(values.get("EMBEDDING_PROVIDER", "").strip())
    log_level = values.get("LOG_LEVEL", "").strip().upper()
    provider_text = "、".join(sorted(VALID_PROVIDERS))

    if llm_provider not in VALID_PROVIDERS:
        errors["LLM_PROVIDER"] = f"仅支持以下提供方：{provider_text}。"
    if embedding_provider not in VALID_PROVIDERS:
        errors["EMBEDDING_PROVIDER"] = f"仅支持以下提供方：{provider_text}。"
    if log_level and log_level not in VALID_LOG_LEVELS:
        errors["LOG_LEVEL"] = "仅支持 DEBUG、INFO、WARNING、ERROR。"

    _validate_required_text(values, "LLM_MODEL", "LLM 模型不能为空。", errors)
    _validate_required_text(values, "EMBEDDING_MODEL", "Embedding 模型不能为空。", errors)
    _validate_required_text(values, "CHROMA_COLLECTION_NAME", "Collection 名称不能为空。", errors)
    _validate_number(values, "CHUNK_SIZE", int, 100, 4000, errors, "Chunk Size 需要在 100 到 4000 之间。")
    _validate_number(values, "CHUNK_OVERLAP", int, 0, 1000, errors, "Chunk Overlap 需要在 0 到 1000 之间。")
    _validate_number(values, "TOP_K", int, 1, 20, errors, "Top K 需要在 1 到 20 之间。")
    _validate_number(values, "MAX_HISTORY_TURNS", int, 0, 20, errors, "Max History Turns 需要在 0 到 20 之间。")
    _validate_number(values, "NO_ANSWER_MIN_SCORE", float, 0, 1, errors, "No Answer Min Score 需要在 0 到 1 之间。")
    _validate_number(values, "LLM_TEMPERATURE", float, 0, 2, errors, "Temperature 需要在 0 到 2 之间。")
    _validate_number(values, "LLM_TIMEOUT", float, 1, 600, errors, "Timeout 需要在 1 到 600 秒之间。")
    _validate_number(values, "LLM_MAX_TOKENS", int, 128, 16384, errors, "Max Tokens 需要在 128 到 16384 之间。")

    chunk_size = _safe_cast(values.get("CHUNK_SIZE", ""), int)
    chunk_overlap = _safe_cast(values.get("CHUNK_OVERLAP", ""), int)
    if chunk_size is not None and chunk_overlap is not None and chunk_overlap >= chunk_size:
        errors["CHUNK_OVERLAP"] = "Chunk Overlap 需要小于 Chunk Size。"

    if is_openai_provider(llm_provider):
        _validate_required_text(values, "LLM_API_KEY", "OpenAI 模式下必须提供 LLM API Key。", errors)
    if is_openai_compatible_provider(llm_provider):
        _validate_http_url(values, "LLM_API_BASE", "兼容模式下必须提供有效的 LLM API Base。", errors)

    if is_openai_provider(embedding_provider):
        _validate_required_text(values, "EMBEDDING_API_KEY", "OpenAI 模式下必须提供 Embedding API Key。", errors)
    if is_openai_compatible_provider(embedding_provider):
        _validate_http_url(values, "EMBEDDING_API_BASE", "兼容模式下必须提供有效的 Embedding API Base。", errors)

    if values.get("LLM_API_BASE", "").strip():
        _validate_http_url(values, "LLM_API_BASE", "LLM API Base 必须以 http:// 或 https:// 开头。", errors)
    if values.get("EMBEDDING_API_BASE", "").strip():
        _validate_http_url(
            values,
            "EMBEDDING_API_BASE",
            "Embedding API Base 必须以 http:// 或 https:// 开头。",
            errors,
        )

    return errors


def _validate_required_text(
    values: dict[str, str],
    key: str,
    message: str,
    errors: dict[str, str],
) -> None:
    if not values.get(key, "").strip():
        errors[key] = message


def _validate_http_url(
    values: dict[str, str],
    key: str,
    message: str,
    errors: dict[str, str],
) -> None:
    value = values.get(key, "").strip()
    if not value or not value.startswith(("http://", "https://")):
        errors[key] = message


def _validate_number(
    values: dict[str, str],
    key: str,
    cast_type: type[int] | type[float],
    minimum: int | float,
    maximum: int | float,
    errors: dict[str, str],
    message: str,
) -> None:
    value = _safe_cast(values.get(key, ""), cast_type)
    if value is None or value < minimum or value > maximum:
        errors[key] = message


def _safe_cast(value: str, cast_type: type[int] | type[float]) -> int | float | None:
    try:
        return cast_type(value)
    except (TypeError, ValueError):
        return None
