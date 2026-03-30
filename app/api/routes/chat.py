from __future__ import annotations

import json
import logging
import time

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse

from app.api.chat import ask_question, prepare_stream_answer
from app.api.dependencies import get_runtime_config
from app.api.request_context import build_request_context
from app.api.request_models import ChatRequestModel
from app.api.serializers import serialize_citation
from app.config import AppConfig


logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/chat", tags=["chat"])


@router.post("/ask")
def ask_kb_question(
    request: Request,
    payload: ChatRequestModel,
    runtime_config: AppConfig = Depends(get_runtime_config),
):
    try:
        request_context = _build_chat_request_context(request, payload, runtime_config)
        result = ask_question(
            question=payload.question,
            chat_history=[item.model_dump() for item in payload.chat_history],
            config=runtime_config,
            top_k=payload.top_k,
            request_context=request_context,
            session_title=payload.session_title,
            scene=payload.scene,
        )
    except Exception as exc:
        logger.exception("REST chat ask failed.")
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return {
        "session_id": request_context.session_id,
        "answer": result.answer,
        "summary": result.summary,
        "steps": result.steps,
        "retrieved_count": result.retrieved_count,
        "retrieval_ms": result.retrieval_ms,
        "generation_ms": result.generation_ms,
        "total_ms": result.total_ms,
        "rewritten_question": result.rewritten_question,
        "retrieval_query": result.retrieval_query,
        "confidence": result.confidence,
        "provider": result.provider,
        "model": result.model,
        "used_knowledge_ids": result.used_knowledge_ids,
        "error_info": _serialize_error_info(result.error_info),
        "citations": [serialize_citation(item) for item in result.citations],
    }


@router.post("/stream")
def stream_kb_question(
    request: Request,
    payload: ChatRequestModel,
    runtime_config: AppConfig = Depends(get_runtime_config),
):
    request_context = _build_chat_request_context(request, payload, runtime_config)

    def generate():
        started_at = time.perf_counter()
        try:
            (
                stream,
                citations,
                retrieved_count,
                _memory_count,
                retrieval_ms,
                rewritten_question,
                retrieval_query,
                confidence,
                summary,
                provider,
                model,
                steps,
                _used_memory_ids,
                used_knowledge_ids,
                error_info,
            ) = prepare_stream_answer(
                question=payload.question,
                chat_history=[item.model_dump() for item in payload.chat_history],
                config=runtime_config,
                top_k=payload.top_k,
                request_context=request_context,
                session_title=payload.session_title,
                scene=payload.scene,
            )

            yield json.dumps(
                {
                    "type": "meta",
                    "session_id": request_context.session_id,
                    "retrieved_count": retrieved_count,
                    "retrieval_ms": retrieval_ms,
                    "rewritten_question": rewritten_question,
                    "retrieval_query": retrieval_query,
                    "confidence": confidence,
                    "summary": summary,
                    "provider": provider,
                    "model": model,
                    "steps": steps,
                    "used_knowledge_ids": used_knowledge_ids,
                    "error_info": error_info,
                },
                ensure_ascii=False,
            ) + "\n"

            full_answer_parts: list[str] = []
            generation_started_at = time.perf_counter()
            for chunk in stream:
                if not chunk:
                    continue
                full_answer_parts.append(chunk)
                yield json.dumps({"type": "delta", "content": chunk}, ensure_ascii=False) + "\n"
            generation_ms = (time.perf_counter() - generation_started_at) * 1000

            yield json.dumps(
                {
                    "type": "done",
                    "session_id": request_context.session_id,
                    "answer": "".join(full_answer_parts),
                    "summary": summary,
                    "steps": steps,
                    "provider": provider,
                    "model": model,
                    "used_knowledge_ids": used_knowledge_ids,
                    "error_info": error_info,
                    "citations": [serialize_citation(item) for item in citations],
                    "retrieved_count": retrieved_count,
                    "retrieval_ms": retrieval_ms,
                    "generation_ms": generation_ms,
                    "total_ms": (time.perf_counter() - started_at) * 1000,
                    "rewritten_question": rewritten_question,
                    "retrieval_query": retrieval_query,
                    "confidence": confidence,
                },
                ensure_ascii=False,
            ) + "\n"
        except Exception as exc:
            logger.exception("REST chat stream failed.")
            yield json.dumps({"type": "error", "message": str(exc)}, ensure_ascii=False) + "\n"

    return StreamingResponse(generate(), media_type="application/x-ndjson")


def _build_chat_request_context(
    request: Request,
    payload: ChatRequestModel,
    runtime_config: AppConfig,
):
    return build_request_context(
        config=runtime_config,
        tenant_id=payload.tenant_id or request.headers.get("x-aurora-tenant-id"),
        user_id=payload.user_id or request.headers.get("x-aurora-user-id"),
        project_id=payload.project_id or request.headers.get("x-aurora-project-id"),
        session_id=payload.session_id or request.headers.get("x-aurora-session-id"),
        request_id=payload.request_id or request.headers.get("x-request-id"),
    )


def _serialize_error_info(error_info):
    if error_info is None:
        return None
    return {
        "code": error_info.code,
        "message": error_info.message,
        "retryable": error_info.retryable,
        "details": dict(error_info.details),
    }
