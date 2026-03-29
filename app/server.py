"""FastAPI REST 服务入口。"""

from __future__ import annotations

import json
import logging
import mimetypes
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any

from fastapi import Body, FastAPI, File, HTTPException, Query, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from app.api.chat import ask_question
from app.api.knowledge_base import (
    cancel_rebuild_job,
    delete_documents,
    get_chunk_count,
    get_current_rebuild_job,
    get_document_list,
    get_document_preview,
    get_rebuild_job,
    knowledge_base_ready,
    rebuild_knowledge_base,
    rename_document,
    update_document_metadata,
    upload_raw_documents,
)
from app.api.knowledge_graph import get_knowledge_graph
from app.api.logs import clear_application_logs, get_logs_summary, get_recent_logs
from app.api.settings import get_masked_settings, test_settings, update_settings
from app.api.system import get_overview
from app.config import get_config
from app.logging_config import configure_logging
from app.services.catalog_service import get_document_status_counts
from app.services.rag_service import stream_answer_with_rag
from app.services.settings_service import SettingsValidationError


config = get_config()
configure_logging(config)
logger = logging.getLogger(__name__)

# Windows 某些环境下会把 .js 识别成 text/plain，导致浏览器拒绝加载模块脚本。
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


class DocumentsDeleteModel(BaseModel):
    """文档删除请求模型。"""

    paths: list[str] = Field(default_factory=list, min_length=1)


class DocumentRenameModel(BaseModel):
    """文档重命名请求模型。"""

    path: str
    new_name: str = Field(..., min_length=1)


class DocumentMetadataUpdateModel(BaseModel):
    """文档元数据更新请求模型。"""

    paths: list[str] = Field(default_factory=list, min_length=1)
    theme: str | None = None
    tags: list[str] | None = None


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


@app.patch("/api/v1/documents/metadata")
def patch_document_metadata(payload: DocumentMetadataUpdateModel):
    """更新文档主题与标签。"""
    result = update_document_metadata(
        payload.paths,
        get_config(),
        theme=payload.theme,
        tags=payload.tags,
    )
    return [asdict(item) for item in result]


@app.delete("/api/v1/documents")
def delete_document_files(payload: DocumentsDeleteModel = Body(...)):
    """删除一个或多个文档。"""
    result = delete_documents(payload.paths, get_config())
    return {
        "deleted_count": len(result.deleted_paths),
        "deleted_paths": result.deleted_paths,
        "missing_paths": result.missing_paths,
    }


@app.put("/api/v1/documents/rename")
def rename_document_file(payload: DocumentRenameModel):
    """重命名文档。"""
    try:
        result = rename_document(payload.path, payload.new_name, get_config())
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (FileExistsError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return asdict(result)


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
    status_counts = get_document_status_counts(runtime_config)
    current_job = get_current_rebuild_job()
    return {
        "ready": knowledge_base_ready(runtime_config),
        "chunk_count": get_chunk_count(runtime_config),
        "document_count": len(get_document_list(runtime_config)),
        "indexed_count": status_counts.get("indexed", 0),
        "changed_count": status_counts.get("changed", 0),
        "pending_count": status_counts.get("pending", 0),
        "failed_count": status_counts.get("failed", 0),
        "current_job": asdict(current_job) if current_job else None,
    }


@app.get("/api/v1/knowledge-base/jobs/current")
def get_current_kb_job():
    """返回当前知识库任务。"""
    current_job = get_current_rebuild_job()
    return asdict(current_job) if current_job else None


@app.get("/api/v1/knowledge-base/jobs/{job_id}")
def get_kb_job(job_id: str):
    """按任务 ID 查询知识库任务。"""
    job = get_rebuild_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="知识库任务不存在。")
    return asdict(job)


@app.post("/api/v1/knowledge-base/jobs/{job_id}/cancel")
def cancel_kb_job(job_id: str):
    """取消知识库任务。"""
    job = cancel_rebuild_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="知识库任务不存在。")
    return asdict(job)


@app.get("/api/v1/knowledge-graph")
def get_knowledge_graph_view():
    """返回知识图谱视图。"""
    graph = get_knowledge_graph(get_config())
    return {
        "nodes": [asdict(node) for node in graph.nodes],
        "edges": [asdict(edge) for edge in graph.edges],
        "summary": graph.summary,
    }


@app.post("/api/v1/knowledge-base/rebuild")
def rebuild_kb(request: Request):
    """启动异步重建知识库。"""
    runtime_config = _resolve_runtime_config(request)
    try:
        job = rebuild_knowledge_base(runtime_config)
    except Exception as exc:
        logger.exception("REST 重建知识库失败。")
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return asdict(job)


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
        "retrieval_ms": result.retrieval_ms,
        "generation_ms": result.generation_ms,
        "total_ms": result.total_ms,
        "rewritten_question": result.rewritten_question,
        "retrieval_query": result.retrieval_query,
        "confidence": result.confidence,
        "citations": [asdict(item) for item in result.citations],
    }


@app.post("/api/v1/chat/stream")
def stream_kb_question(payload: ChatRequestModel, request: Request):
    """执行流式知识库问答，返回 NDJSON 流。"""
    runtime_config = _resolve_runtime_config(request)

    def generate():
        started_at = time.perf_counter()
        try:
            (
                stream,
                citations,
                retrieved_count,
                retrieval_ms,
                rewritten_question,
                retrieval_query,
                confidence,
            ) = stream_answer_with_rag(
                question=payload.question,
                chat_history=[item.model_dump() for item in payload.chat_history],
                config=runtime_config,
                top_k=payload.top_k,
            )

            meta_event = {
                "type": "meta",
                "retrieved_count": retrieved_count,
                "retrieval_ms": retrieval_ms,
                "rewritten_question": rewritten_question,
                "retrieval_query": retrieval_query,
                "confidence": confidence,
            }
            yield json.dumps(meta_event, ensure_ascii=False) + "\n"

            full_answer_parts: list[str] = []
            generation_started_at = time.perf_counter()
            for chunk in stream:
                if not chunk:
                    continue
                full_answer_parts.append(chunk)
                yield json.dumps({"type": "delta", "content": chunk}, ensure_ascii=False) + "\n"
            generation_ms = (time.perf_counter() - generation_started_at) * 1000

            done_event = {
                "type": "done",
                "answer": "".join(full_answer_parts),
                "citations": [asdict(item) for item in citations],
                "retrieved_count": retrieved_count,
                "retrieval_ms": retrieval_ms,
                "generation_ms": generation_ms,
                "total_ms": (time.perf_counter() - started_at) * 1000,
                "rewritten_question": rewritten_question,
                "retrieval_query": retrieval_query,
                "confidence": confidence,
            }
            yield json.dumps(done_event, ensure_ascii=False) + "\n"
        except Exception as exc:
            logger.exception("REST 流式问答失败。")
            yield json.dumps({"type": "error", "message": str(exc)}, ensure_ascii=False) + "\n"

    return StreamingResponse(generate(), media_type="application/x-ndjson")


@app.get("/api/v1/logs")
def get_logs(
    limit: int = Query(default=200, ge=1, le=1000),
    level: str = Query(default=""),
    keyword: str = Query(default=""),
    start_time: str = Query(default=""),
    end_time: str = Query(default=""),
):
    """返回最近日志。"""
    runtime_config = get_config()
    return {
        "summary": get_logs_summary(runtime_config),
        "filters": {
            "level": level,
            "keyword": keyword,
            "start_time": start_time,
            "end_time": end_time,
        },
        "lines": get_recent_logs(
            runtime_config,
            limit=limit,
            level=level,
            keyword=keyword,
            start_time=start_time,
            end_time=end_time,
        ),
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
    try:
        update_settings(get_config(), payload.values)
    except SettingsValidationError as exc:
        raise HTTPException(
            status_code=400,
            detail={
                "message": "配置校验失败，请修正后再保存。",
                "errors": exc.errors,
            },
        ) from exc
    return {"message": "配置已写入 .env。"}


@app.post("/api/v1/settings/test")
def test_settings_view(payload: SettingsUpdateModel):
    """测试配置连通性。"""
    return test_settings(get_config(), payload.values)


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
        """返回构建后的 React 首页。"""
        index_file = FRONTEND_DIST_DIR / "index.html"
        if not index_file.exists():
            return _frontend_dev_hint()
        return FileResponse(index_file)

    @app.get("/{full_path:path}")
    def serve_frontend_fallback(full_path: str):
        """前端路由回退到 React 单页应用。"""
        candidate = FRONTEND_DIST_DIR / full_path
        if candidate.exists() and candidate.is_file():
            return FileResponse(candidate)
        index_file = FRONTEND_DIST_DIR / "index.html"
        if not index_file.exists():
            return _frontend_dev_hint()
        return FileResponse(index_file)
