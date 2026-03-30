"""FastAPI dependencies shared across route modules."""

from __future__ import annotations

from fastapi import Request

from app.config import AppConfig, get_config


def get_app_config() -> AppConfig:
    return get_config()


def get_runtime_config(request: Request) -> AppConfig:
    """根据请求头生成当前请求使用的配置。"""
    base_config = get_config()
    llm_api_key = request.headers.get("x-llm-api-key", "")
    embedding_api_key = request.headers.get("x-embedding-api-key", "")
    llm_api_base = request.headers.get("x-llm-api-base", "")
    embedding_api_base = request.headers.get("x-embedding-api-base", "")

    use_same_embedding_key = (
        request.headers.get("x-use-same-embedding-key", "true").strip().lower() == "true"
    )
    use_same_embedding_base = (
        request.headers.get("x-use-same-embedding-base", "true").strip().lower() == "true"
    )

    if use_same_embedding_key and llm_api_key and not embedding_api_key:
        embedding_api_key = llm_api_key
    if use_same_embedding_base and llm_api_base and not embedding_api_base:
        embedding_api_base = llm_api_base

    return base_config.with_runtime_overrides(
        llm_api_key=llm_api_key,
        embedding_api_key=embedding_api_key,
        llm_api_base=llm_api_base,
        embedding_api_base=embedding_api_base,
    )
