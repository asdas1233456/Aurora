"""本地启动 FastAPI 服务。"""

from __future__ import annotations

import uvicorn

from app.config import get_config


def main() -> None:
    """启动 uvicorn。"""
    config = get_config()
    uvicorn.run(
        "app.server:app",
        host=config.api_host,
        port=config.api_port,
        reload=False,
    )


if __name__ == "__main__":
    main()

