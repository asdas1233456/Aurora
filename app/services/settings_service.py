"""应用配置读写服务。"""

from __future__ import annotations

from dataclasses import replace
import logging
from pathlib import Path

from dotenv import dotenv_values, set_key

from app.config import (
    AppConfig,
    SUPPORTED_MODEL_PROVIDERS,
    _normalize_provider,
    is_openai_compatible_provider,
    is_openai_provider,
)
from app.schemas import AppSettings


logger = logging.getLogger(__name__)

EDITABLE_ENV_KEYS = {
    "LLM_PROVIDER",
    "EMBEDDING_PROVIDER",
    "LLM_API_KEY",
    "LLM_API_BASE",
    "LLM_MODEL",
    "LLM_TEMPERATURE",
    "LLM_TIMEOUT",
    "LLM_MAX_TOKENS",
    "EMBEDDING_API_KEY",
    "EMBEDDING_API_BASE",
    "EMBEDDING_MODEL",
    "CHUNK_SIZE",
    "CHUNK_OVERLAP",
    "TOP_K",
    "MAX_HISTORY_TURNS",
    "NO_ANSWER_MIN_SCORE",
    "CHROMA_COLLECTION_NAME",
    "LOG_LEVEL",
    "API_HOST",
    "API_PORT",
    "CORS_ORIGINS",
}

VALID_LOG_LEVELS = {"DEBUG", "INFO", "WARNING", "ERROR"}
VALID_PROVIDERS = SUPPORTED_MODEL_PROVIDERS


class SettingsValidationError(ValueError):
    """配置校验失败。"""

    def __init__(self, errors: dict[str, str]) -> None:
        self.errors = errors
        super().__init__("配置校验失败")


def _get_env_path(config: AppConfig) -> Path:
    return config.base_dir / ".env"


def ensure_env_file(config: AppConfig) -> Path:
    """确保 .env 文件存在。"""
    env_path = _get_env_path(config)
    if env_path.exists():
        return env_path

    example_path = config.base_dir / ".env.example"
    if example_path.exists():
        env_path.write_text(example_path.read_text(encoding="utf-8"), encoding="utf-8")
    else:
        env_path.write_text("", encoding="utf-8")
    return env_path


def load_app_settings(config: AppConfig) -> AppSettings:
    """读取当前可编辑配置。"""
    ensure_env_file(config)
    return AppSettings(
        llm_provider=config.llm_provider,
        embedding_provider=config.embedding_provider,
        llm_api_key=config.llm_api_key,
        llm_api_base=config.llm_api_base,
        llm_model=config.llm_model,
        llm_temperature=config.llm_temperature,
        llm_timeout=config.llm_timeout,
        llm_max_tokens=config.llm_max_tokens,
        embedding_api_key=config.embedding_api_key,
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


def load_raw_env_values(config: AppConfig) -> dict[str, str]:
    """返回 .env 文件中的原始键值。"""
    env_path = ensure_env_file(config)
    raw_values = dotenv_values(env_path)
    return {
        key: str(value or "")
        for key, value in raw_values.items()
        if key in EDITABLE_ENV_KEYS
    }


def merge_settings_with_current(config: AppConfig, values: dict[str, object]) -> dict[str, str]:
    """把页面提交值与当前配置合并成完整配置视图。"""
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
        if key not in EDITABLE_ENV_KEYS:
            continue
        text_value = str(value).strip()
        if key in {"LLM_PROVIDER", "EMBEDDING_PROVIDER"}:
            merged_values[key] = _normalize_provider(text_value)
        else:
            merged_values[key] = text_value

    return merged_values


def build_config_from_settings_values(config: AppConfig, values: dict[str, object]) -> AppConfig:
    """基于页面值生成一份临时配置对象。"""
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
        api_host=merged["API_HOST"],
        api_port=int(merged["API_PORT"] or config.api_port),
        cors_origins=merged["CORS_ORIGINS"],
    )


def save_app_settings(config: AppConfig, values: dict[str, object]) -> None:
    """把页面提交的配置写回 .env 文件。"""
    env_path = ensure_env_file(config)
    merged_values = merge_settings_with_current(config, values)
    errors = validate_app_settings(merged_values)
    if errors:
        raise SettingsValidationError(errors)

    for key, value in values.items():
        if key not in EDITABLE_ENV_KEYS:
            continue
        normalized_value = str(value).strip()
        if key in {"LLM_PROVIDER", "EMBEDDING_PROVIDER"}:
            normalized_value = _normalize_provider(normalized_value)
        set_key(
            str(env_path),
            key,
            normalized_value,
            quote_mode="never",
        )

    logger.info("配置已写入 .env 文件: %s", env_path)


def mask_secret(value: str) -> str:
    """对敏感值做脱敏展示。"""
    if not value:
        return ""
    if len(value) <= 8:
        return "*" * len(value)
    return f"{value[:4]}{'*' * (len(value) - 8)}{value[-4:]}"


def validate_app_settings(values: dict[str, str]) -> dict[str, str]:
    """校验即将写入的配置。"""
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
    _validate_number(values, "API_PORT", int, 1, 65535, errors, "API Port 需要在 1 到 65535 之间。")

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
        _validate_http_url(
            values,
            "EMBEDDING_API_BASE",
            "兼容模式下必须提供有效的 Embedding API Base。",
            errors,
        )

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
