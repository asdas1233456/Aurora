"""日志相关的内部 API。"""

from __future__ import annotations

from app.config import AppConfig
from app.services.log_service import clear_logs, filter_logs, get_log_summary


def get_recent_logs(
    config: AppConfig,
    limit: int = 200,
    *,
    level: str = "",
    keyword: str = "",
    start_time: str = "",
    end_time: str = "",
) -> list[str]:
    """返回最近日志。"""
    return filter_logs(
        config,
        limit=limit,
        level=level,
        keyword=keyword,
        start_time=start_time,
        end_time=end_time,
    )


def get_logs_summary(config: AppConfig) -> dict[str, int | str]:
    """返回日志统计。"""
    return get_log_summary(config)


def clear_application_logs(config: AppConfig) -> None:
    """清空应用日志。"""
    clear_logs(config)
