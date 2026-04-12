"""FastAPI HTTP bootstrap for Aurora."""

from __future__ import annotations

import logging
import mimetypes
import time

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app.core.config import get_config
from app.core.logging import configure_logging
from app.presentation.http.routes.chat import router as chat_router
from app.presentation.http.routes.documents import router as documents_router
from app.presentation.http.routes.internal_chat import router as internal_chat_router
from app.presentation.http.routes.knowledge_base import router as knowledge_base_router
from app.presentation.http.routes.knowledge_graph import alias_router as graph_router
from app.presentation.http.routes.knowledge_graph import router as knowledge_graph_router
from app.presentation.http.routes.logs import router as logs_router
from app.presentation.http.routes.memory import router as memory_router
from app.presentation.http.routes.providers import router as providers_router
from app.presentation.http.routes.settings import router as settings_router
from app.presentation.http.routes.settings import runtime_router
from app.presentation.http.routes.system import router as system_router
from app.services.persistence_health_service import PersistenceHealthService


def create_app() -> FastAPI:
    config = get_config()
    configure_logging(config)
    logger = logging.getLogger(__name__)

    mimetypes.add_type("application/javascript", ".js")
    mimetypes.add_type("application/javascript", ".mjs")
    mimetypes.add_type("text/css", ".css")

    frontend_dist_dir = config.base_dir / "frontend" / "dist"

    app = FastAPI(
        title="Aurora REST API",
        version=config.app_version,
        description="Aurora 的 REST API，支持问答、建库、上传、日志和配置管理。",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=config.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(system_router)
    app.include_router(documents_router)
    app.include_router(knowledge_base_router)
    app.include_router(knowledge_graph_router)
    app.include_router(graph_router)
    app.include_router(chat_router)
    app.include_router(internal_chat_router)
    app.include_router(memory_router)
    app.include_router(providers_router)
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
        current_config = get_config()
        return {
            "status": "ok",
            "app": current_config.app_name,
            "version": current_config.app_version,
        }

    @app.get("/ready")
    def ready_check():
        current_config = get_config()
        report = PersistenceHealthService(current_config).inspect()
        required_tables_ready = all(report.table_status.values())
        status = "ready" if required_tables_ready else "degraded"
        payload = {
            "status": status,
            "tenant_id": current_config.tenant_id,
            "auth_mode": current_config.auth_mode,
            "deployment_mode": current_config.deployment_mode,
            "storage": {
                "session_count": report.session_count,
                "message_count": report.message_count,
                "memory_count": report.memory_count,
                "table_status": report.table_status,
            },
        }
        if required_tables_ready:
            return payload
        return JSONResponse(status_code=503, content=payload)

    if frontend_dist_dir.exists():
        assets_dir = frontend_dist_dir / "assets"
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
            index_file = frontend_dist_dir / "index.html"
            if not index_file.exists():
                return _frontend_dev_hint()
            return FileResponse(index_file)

        @app.get("/{full_path:path}")
        def serve_frontend_fallback(full_path: str):
            candidate = frontend_dist_dir / full_path
            if candidate.exists() and candidate.is_file():
                return FileResponse(candidate)
            index_file = frontend_dist_dir / "index.html"
            if not index_file.exists():
                return _frontend_dev_hint()
            return FileResponse(index_file)

    return app


app = create_app()

__all__ = ["app", "create_app"]
