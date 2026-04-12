"""Application logging configuration."""

from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
import re

from app.core.config import AppConfig, get_config


_LOGGING_CONFIGURED = False
_REDACTION_PATTERNS = [
    re.compile(r"(?i)(authorization\s*:\s*bearer\s+)[^\s]+"),
    re.compile(r"(?i)(bearer\s+)[a-z0-9._\\-]{12,}"),
    re.compile(r"(?i)((?:api[_-]?key|secret|password|token)\s*[:=]\s*)[^\s,;]+"),
]


class SensitiveDataRedactionFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        sanitized = message
        for pattern in _REDACTION_PATTERNS:
            sanitized = pattern.sub(lambda match: f"{match.group(1)}***", sanitized)
        if sanitized != message:
            record.msg = sanitized
            record.args = ()
        return True


class WindowsSafeRotatingFileHandler(RotatingFileHandler):
    """Keep logging alive when another local process is rotating the same file."""

    def doRollover(self) -> None:
        try:
            super().doRollover()
        except PermissionError:
            if self.stream:
                self.stream.close()
                self.stream = None
            self.stream = self._open()


def configure_logging(config: AppConfig | None = None) -> None:
    """Configure file and console logging for the application."""
    global _LOGGING_CONFIGURED

    if _LOGGING_CONFIGURED:
        return

    resolved_config = config or get_config()
    resolved_config.ensure_directories()

    formatter = logging.Formatter(
        fmt="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    file_handler = WindowsSafeRotatingFileHandler(
        resolved_config.app_log_path,
        maxBytes=1_000_000,
        backupCount=5,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)
    file_handler.addFilter(SensitiveDataRedactionFilter())

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    console_handler.addFilter(SensitiveDataRedactionFilter())

    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, resolved_config.log_level, logging.INFO))
    root_logger.handlers.clear()
    root_logger.addHandler(file_handler)
    root_logger.addHandler(console_handler)

    logging.getLogger("chromadb").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("openai").setLevel(logging.INFO)
    logging.getLogger("uvicorn.access").setLevel(logging.INFO)

    _LOGGING_CONFIGURED = True
