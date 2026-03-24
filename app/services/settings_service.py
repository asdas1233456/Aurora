"""应用配置读写服务。"""

from __future__ import annotations

import logging
from pathlib import Path

from dotenv import dotenv_values, set_key

from app.config import AppConfig
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
    "CHROMA_COLLECTION_NAME",
    "LOG_LEVEL",
    "API_HOST",
    "API_PORT",
    "CORS_ORIGINS",
}


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


def save_app_settings(config: AppConfig, values: dict[str, object]) -> None:
    """把页面提交的配置写回 .env 文件。"""
    env_path = ensure_env_file(config)

    for key, value in values.items():
        if key not in EDITABLE_ENV_KEYS:
            continue
        set_key(
            str(env_path),
            key,
            str(value).strip(),
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
