"""日志配置模块。"""

from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler

from app.config import AppConfig, get_config


_LOGGING_CONFIGURED = False


def configure_logging(config: AppConfig | None = None) -> None:
    """配置应用日志。

    这里使用文件 + 控制台双通道，既方便本地调试，也便于日志页展示。
    """
    global _LOGGING_CONFIGURED

    if _LOGGING_CONFIGURED:
        return

    resolved_config = config or get_config()
    resolved_config.ensure_directories()

    formatter = logging.Formatter(
        fmt="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    file_handler = RotatingFileHandler(
        resolved_config.app_log_path,
        maxBytes=1_000_000,
        backupCount=5,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)

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

