"""FastAPI REST 服务入口。"""

from __future__ import annotations

import logging
import mimetypes
import time

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

from app.api.routes.chat import router as chat_router
from app.api.routes.documents import router as documents_router
from app.api.routes.knowledge_base import router as knowledge_base_router
from app.api.routes.knowledge_graph import router as knowledge_graph_router
from app.api.routes.logs import router as logs_router
from app.api.routes.settings import router as settings_router
from app.api.routes.settings import runtime_router
from app.api.routes.system import router as system_router
from app.config import get_config
from app.logging_config import configure_logging


config = get_config()
configure_logging(config)
logger = logging.getLogger(__name__)

# Windows 某些环境下会把 .js 识别成 text/plain，导致浏览器拒绝加载模块脚本。
mimetypes.add_type("application/javascript", ".js")
mimetypes.add_type("application/javascript", ".mjs")
mimetypes.add_type("text/css", ".css")

FRONTEND_DIST_DIR = config.base_dir / "frontend" / "dist"

app = FastAPI(
    title="Aurora REST API",
    version=config.app_version,
    description="Aurora 的 REST API，支持问答、建库、上传、日志和配置管理。",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=config.cors_origin_list or ["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(system_router)
app.include_router(documents_router)
app.include_router(knowledge_base_router)
app.include_router(knowledge_graph_router)
app.include_router(chat_router)
app.include_router(logs_router)
app.include_router(settings_router)
app.include_router(runtime_router)


@app.middleware("http")
async def log_request_middleware(request: Request, call_next):
    started_at = time.perf_counter()
    response = await call_next(request)
    cost_ms = (time.perf_counter() - started_at) * 1000
    logger.info(
        "HTTP %s %s -> %s (%.2f ms)",
        request.method,
        request.url.path,
        response.status_code,
        cost_ms,
    )
    return response


@app.get("/health")
def health_check():
    return {"status": "ok", "app": config.app_name, "version": config.app_version}


if FRONTEND_DIST_DIR.exists():
    assets_dir = FRONTEND_DIST_DIR / "assets"
    if assets_dir.exists():
        app.mount("/assets", StaticFiles(directory=assets_dir), name="assets")

    def _frontend_dev_hint() -> HTMLResponse:
        return HTMLResponse(
            """
            <html>
              <head>
                <meta charset="utf-8" />
                <title>Aurora Backend Ready</title>
                <style>
                  body { font-family: "Segoe UI", Arial, sans-serif; margin: 40px; line-height: 1.6; color: #1f2937; }
                  code { background: #f3f4f6; padding: 2px 6px; border-radius: 6px; }
                  a { color: #0f766e; }
                </style>
              </head>
              <body>
                <h1>Aurora backend is running.</h1>
                <p>The frontend production build is not available right now.</p>
                <p>Open <a href="http://127.0.0.1:5173/">http://127.0.0.1:5173/</a> to preview the app.</p>
                <p>Use <code>/api/v1/*</code> for API requests.</p>
              </body>
            </html>
            """
        )

    @app.get("/")
    def serve_frontend_index():
        index_file = FRONTEND_DIST_DIR / "index.html"
        if not index_file.exists():
            return _frontend_dev_hint()
        return FileResponse(index_file)

    @app.get("/{full_path:path}")
    def serve_frontend_fallback(full_path: str):
        candidate = FRONTEND_DIST_DIR / full_path
        if candidate.exists() and candidate.is_file():
            return FileResponse(candidate)
        index_file = FRONTEND_DIST_DIR / "index.html"
        if not index_file.exists():
            return _frontend_dev_hint()
        return FileResponse(index_file)
