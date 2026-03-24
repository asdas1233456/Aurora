"""FastAPI REST 服务入口。"""

from __future__ import annotations

import logging
import json
import mimetypes
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, HTTPException, Query, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.api.chat import ask_question
from app.api.knowledge_base import (
    get_chunk_count,
    get_document_list,
    get_document_preview,
    knowledge_base_ready,
    rebuild_knowledge_base,
    upload_raw_documents,
)
from app.api.logs import clear_application_logs, get_logs_summary, get_recent_logs
from app.api.settings import get_masked_settings, update_settings
from app.api.system import get_overview
from app.config import get_config
from app.logging_config import configure_logging
from app.services.rag_service import stream_answer_with_rag


config = get_config()
configure_logging(config)
logger = logging.getLogger(__name__)

# Windows 某些环境下会把 .js 识别成 text/plain，导致浏览器拒绝加载模块脚本。
# 这里在应用启动时显式注册常用前端静态资源类型，确保 Vue 构建产物能正确返回。
mimetypes.add_type("application/javascript", ".js")
mimetypes.add_type("application/javascript", ".mjs")
mimetypes.add_type("text/css", ".css")

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


class ChatMessageModel(BaseModel):
    """聊天消息模型。"""

    role: str = Field(..., description="消息角色，例如 user / assistant")
    content: str = Field(..., description="消息内容")


class ChatRequestModel(BaseModel):
    """问答请求模型。"""

    question: str = Field(..., description="用户问题")
    top_k: int | None = Field(default=None, ge=1, le=20)
    chat_history: list[ChatMessageModel] = Field(default_factory=list)


class SettingsUpdateModel(BaseModel):
    """配置更新模型。"""

    values: dict[str, Any]


FRONTEND_DIST_DIR = config.base_dir / "frontend" / "dist"


def _resolve_runtime_config(request: Request):
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


@app.middleware("http")
async def log_request_middleware(request, call_next):
    """记录请求耗时。"""
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
    """基础健康检查。"""
    return {"status": "ok", "app": config.app_name, "version": config.app_version}


@app.get("/api/v1/system/overview")
def get_system_overview(request: Request):
    """返回系统总览。"""
    return asdict(get_overview(_resolve_runtime_config(request)))


@app.get("/api/v1/documents")
def get_documents():
    """返回文档列表。"""
    return [asdict(item) for item in get_document_list(get_config())]


@app.get("/api/v1/documents/preview")
def preview_document(path: str = Query(..., description="文档绝对路径")):
    """返回文档预览内容。"""
    try:
        preview_text = get_document_preview(path, max_chars=4000)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"path": path, "preview": preview_text}


@app.post("/api/v1/documents/upload")
async def upload_document_files(files: list[UploadFile] = File(...)):
    """上传文档到 data 目录。"""
    if not files:
        raise HTTPException(status_code=400, detail="请至少上传一个文件。")

    raw_files: list[tuple[str, bytes]] = []
    for file_item in files:
        raw_files.append((file_item.filename, await file_item.read()))

    saved_names = upload_raw_documents(raw_files, get_config())
    return {"saved_count": len(saved_names), "saved_files": saved_names}


@app.get("/api/v1/knowledge-base/status")
def get_kb_status(request: Request):
    """返回知识库状态。"""
    runtime_config = _resolve_runtime_config(request)
    return {
        "ready": knowledge_base_ready(runtime_config),
        "chunk_count": get_chunk_count(runtime_config),
        "document_count": len(get_document_list(runtime_config)),
    }


@app.post("/api/v1/knowledge-base/rebuild")
def rebuild_kb(request: Request):
    """重建知识库。"""
    runtime_config = _resolve_runtime_config(request)
    try:
        stats = rebuild_knowledge_base(runtime_config)
    except Exception as exc:
        logger.exception("REST 重建知识库失败。")
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return asdict(stats)


@app.post("/api/v1/chat/ask")
def ask_kb_question(payload: ChatRequestModel, request: Request):
    """执行一次知识库问答。"""
    runtime_config = _resolve_runtime_config(request)
    try:
        result = ask_question(
            question=payload.question,
            chat_history=[item.model_dump() for item in payload.chat_history],
            config=runtime_config,
            top_k=payload.top_k,
        )
    except Exception as exc:
        logger.exception("REST 问答失败。")
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return {
        "answer": result.answer,
        "retrieved_count": result.retrieved_count,
        "citations": [asdict(item) for item in result.citations],
    }


@app.post("/api/v1/chat/stream")
def stream_kb_question(payload: ChatRequestModel, request: Request):
    """执行流式知识库问答，返回 NDJSON 流。"""
    runtime_config = _resolve_runtime_config(request)

    def generate():
        try:
            stream, citations, retrieved_count = stream_answer_with_rag(
                question=payload.question,
                chat_history=[item.model_dump() for item in payload.chat_history],
                config=runtime_config,
                top_k=payload.top_k,
            )

            meta_event = {
                "type": "meta",
                "retrieved_count": retrieved_count,
            }
            yield json.dumps(meta_event, ensure_ascii=False) + "\n"

            full_answer_parts: list[str] = []
            for chunk in stream:
                if not chunk:
                    continue
                full_answer_parts.append(chunk)
                yield json.dumps({"type": "delta", "content": chunk}, ensure_ascii=False) + "\n"

            done_event = {
                "type": "done",
                "answer": "".join(full_answer_parts),
                "citations": [asdict(item) for item in citations],
                "retrieved_count": retrieved_count,
            }
            yield json.dumps(done_event, ensure_ascii=False) + "\n"
        except Exception as exc:
            logger.exception("REST 流式问答失败。")
            yield json.dumps({"type": "error", "message": str(exc)}, ensure_ascii=False) + "\n"

    return StreamingResponse(generate(), media_type="application/x-ndjson")


@app.get("/api/v1/logs")
def get_logs(limit: int = Query(default=200, ge=1, le=1000)):
    """返回最近日志。"""
    runtime_config = get_config()
    return {
        "summary": get_logs_summary(runtime_config),
        "lines": get_recent_logs(runtime_config, limit=limit),
    }


@app.delete("/api/v1/logs")
def delete_logs():
    """清空日志。"""
    clear_application_logs(get_config())
    return {"message": "日志已清空。"}


@app.get("/api/v1/settings")
def get_settings_view():
    """返回脱敏后的配置视图。"""
    return get_masked_settings(get_config())


@app.put("/api/v1/settings")
def update_settings_view(payload: SettingsUpdateModel):
    """更新配置。"""
    update_settings(get_config(), payload.values)
    return {"message": "配置已写入 .env。"}


@app.get("/api/v1/runtime/config")
def get_runtime_config_help():
    """返回请求级运行时配置说明。"""
    return {
        "description": "可通过请求头覆盖当前请求使用的模型 Key / Base，不写入 .env。",
        "headers": {
            "X-LLM-API-Key": "当前请求使用的 LLM API Key",
            "X-Embedding-API-Key": "当前请求使用的 Embedding API Key",
            "X-LLM-API-Base": "当前请求使用的 LLM API Base",
            "X-Embedding-API-Base": "当前请求使用的 Embedding API Base",
            "X-Use-Same-Embedding-Key": "true/false，默认 true",
            "X-Use-Same-Embedding-Base": "true/false，默认 true",
        },
    }


if FRONTEND_DIST_DIR.exists():
    assets_dir = FRONTEND_DIST_DIR / "assets"
    if assets_dir.exists():
        app.mount("/assets", StaticFiles(directory=assets_dir), name="assets")

    @app.get("/")
    def serve_frontend_index():
        """返回构建后的 Vue 首页。"""
        return FileResponse(FRONTEND_DIST_DIR / "index.html")

    @app.get("/{full_path:path}")
    def serve_frontend_fallback(full_path: str):
        """前端路由回退到 Vue 单页应用。"""
        candidate = FRONTEND_DIST_DIR / full_path
        if candidate.exists() and candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(FRONTEND_DIST_DIR / "index.html")
