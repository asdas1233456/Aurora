"""日志读取与维护服务。"""

from __future__ import annotations

from collections import deque
from pathlib import Path

from app.config import AppConfig


def get_log_file_path(config: AppConfig) -> Path:
    """返回主日志文件路径。"""
    config.ensure_directories()
    return config.app_log_path


def tail_logs(config: AppConfig, limit: int = 200) -> list[str]:
    """读取最近的日志行。"""
    log_path = get_log_file_path(config)
    if not log_path.exists():
        return []

    with log_path.open("r", encoding="utf-8", errors="ignore") as file_obj:
        return list(deque(file_obj, maxlen=max(1, limit)))


def clear_logs(config: AppConfig) -> None:
    """清空主日志文件。"""
    log_path = get_log_file_path(config)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.write_text("", encoding="utf-8")


def get_log_summary(config: AppConfig) -> dict[str, int | str]:
    """返回日志文件基础统计。"""
    log_path = get_log_file_path(config)
    if not log_path.exists():
        return {
            "path": str(log_path),
            "exists": 0,
            "size_bytes": 0,
            "line_count": 0,
        }

    lines = tail_logs(config, limit=10_000)
    return {
        "path": str(log_path),
        "exists": 1,
        "size_bytes": log_path.stat().st_size,
        "line_count": len(lines),
    }

