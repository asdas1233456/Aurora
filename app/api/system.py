"""系统状态相关的内部 API。"""

from __future__ import annotations

from app.config import AppConfig
from app.services.system_service import get_recent_documents, get_system_overview


def get_overview(config: AppConfig):
    """返回系统概览。"""
    return get_system_overview(config)


def get_latest_documents(config: AppConfig, limit: int = 5):
    """返回最近文档。"""
    return get_recent_documents(config, limit=limit)
