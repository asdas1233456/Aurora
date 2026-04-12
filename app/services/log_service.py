"""日志读取与维护服务。"""

from __future__ import annotations

from collections import deque
from datetime import datetime
from pathlib import Path
import re

from app.config import AppConfig


_SENSITIVE_PATTERNS = [
    re.compile(r"(?i)(authorization\s*:\s*bearer\s+)[^\s]+"),
    re.compile(r"(?i)(bearer\s+)[a-z0-9._\-]{12,}"),
    re.compile(r"(?i)((?:api[_-]?key|secret|password|token)\s*[:=]\s*)[^\s,;]+"),
    re.compile(r"([A-Za-z]:\\Users\\[^\\\s]+)"),
]


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
        return [_sanitize_log_line(line) for line in deque(file_obj, maxlen=max(1, limit))]


def filter_logs(
    config: AppConfig,
    *,
    limit: int = 200,
    level: str = "",
    keyword: str = "",
    start_time: str = "",
    end_time: str = "",
) -> list[str]:
    """按条件筛选最近日志。"""
    lines = tail_logs(config, limit=10_000)
    normalized_level = level.strip().upper()
    normalized_keyword = keyword.strip().lower()
    start_dt = _parse_log_datetime(start_time)
    end_dt = _parse_log_datetime(end_time)

    filtered: list[str] = []
    for line in lines:
        parsed_line = _parse_log_line(line)

        if normalized_level and parsed_line["level"] != normalized_level:
            continue
        if normalized_keyword and normalized_keyword not in parsed_line["raw"].lower():
            continue
        if start_dt and parsed_line["timestamp"] and parsed_line["timestamp"] < start_dt:
            continue
        if end_dt and parsed_line["timestamp"] and parsed_line["timestamp"] > end_dt:
            continue

        filtered.append(line)

    return filtered[-max(1, limit) :]


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


def _parse_log_line(line: str) -> dict[str, object]:
    parts = [part.strip() for part in line.split("|", maxsplit=3)]
    timestamp = _parse_log_datetime(parts[0]) if parts else None
    level = parts[1].upper() if len(parts) > 1 else ""
    return {
        "timestamp": timestamp,
        "level": level,
        "raw": line,
    }


def _parse_log_datetime(value: str) -> datetime | None:
    normalized_value = value.strip()
    if not normalized_value:
        return None

    candidate_values = [
        normalized_value,
        normalized_value.replace("T", " "),
    ]
    for candidate in candidate_values:
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
            try:
                return datetime.strptime(candidate, fmt)
            except ValueError:
                continue

    return None


def _sanitize_log_line(line: str) -> str:
    sanitized = str(line or "")
    for pattern in _SENSITIVE_PATTERNS:
        sanitized = pattern.sub(lambda match: f"{match.group(1)}***", sanitized)
    return sanitized
