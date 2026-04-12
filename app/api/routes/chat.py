from __future__ import annotations

import json
import logging
import time

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse

from app.api.chat import ask_question, prepare_stream_answer
from app.api.dependencies import get_runtime_config, require_permission
from app.api.request_models import ChatRequestModel, ChatSessionRenameModel
from app.api.security import (
    acquire_concurrency_slot,
    concurrency_slot,
    enforce_rate_limit,
    make_request_context,
    release_concurrency_slot,
)
from app.api.serializers import (
    serialize_chat_message_record,
    serialize_chat_session_record,
    serialize_citation,
)
from app.auth import AuthenticatedUser
from app.config import AppConfig
from app.services.message_repository import MessageRepository
from app.services.session_repository import SessionRepository


logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/chat", tags=["chat"])


@router.get("/sessions")
def list_chat_sessions(
    request: Request,
    limit: int = Query(default=30, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    status: str = Query(default=""),
    query: str = Query(default=""),
    runtime_config: AppConfig = Depends(get_runtime_config),
    user: AuthenticatedUser = Depends(require_permission("chat.use")),
):
    request_context = make_request_context(
        request,
        runtime_config,
        user,
        actor_role="conversation",
    )
    enforce_rate_limit(
        runtime_config,
        request_context=request_context,
        user=user,
        request=request,
        action_name="chat_history_read",
        target_type="chat_sessions",
    )

    session_repository = SessionRepository(runtime_config)
    message_repository = MessageRepository(runtime_config)
    items = session_repository.list_sessions(
        tenant_id=user.tenant_id,
        user_id=user.user_id,
        project_id=request_context.project_id,
        status=str(status or "").strip() or None,
        limit=limit,
        offset=offset,
    )
    normalized_query = str(query or "").strip().lower()
    if normalized_query:
        items = [item for item in items if normalized_query in item.title.lower()]

    message_count_map = message_repository.count_by_session_ids(
        tenant_id=user.tenant_id,
        session_ids=[item.id for item in items],
    )

    return {
        "items": [
            {
                "session": serialize_chat_session_record(item),
                "message_count": message_count_map.get(item.id, 0),
                "last_message": _serialize_optional_message(
                    message_repository.get_latest_by_session(
                        tenant_id=user.tenant_id,
                        session_id=item.id,
                    )
                ),
            }
            for item in items
        ],
        "count": len(items),
        "filters": {
            "project_id": request_context.project_id,
            "status": str(status or "").strip(),
            "query": query,
            "limit": limit,
            "offset": offset,
        },
    }


@router.get("/sessions/{session_id}")
def get_chat_session(
    session_id: str,
    request: Request,
    runtime_config: AppConfig = Depends(get_runtime_config),
    user: AuthenticatedUser = Depends(require_permission("chat.use")),
):
    request_context = make_request_context(
        request,
        runtime_config,
        user,
        actor_role="conversation",
    )
    session_repository = SessionRepository(runtime_config)
    message_repository = MessageRepository(runtime_config)
    session = _get_owned_session(
        session_repository,
        tenant_id=user.tenant_id,
        user_id=user.user_id,
        project_id=request_context.project_id,
        session_id=session_id,
    )
    return {
        "session": serialize_chat_session_record(session),
        "message_count": message_repository.count_by_session(
            tenant_id=user.tenant_id,
            session_id=session.id,
        ),
        "last_message": _serialize_optional_message(
            message_repository.get_latest_by_session(
                tenant_id=user.tenant_id,
                session_id=session.id,
            )
        ),
    }


@router.get("/sessions/{session_id}/messages")
def get_chat_session_messages(
    session_id: str,
    request: Request,
    limit: int = Query(default=80, ge=1, le=200),
    runtime_config: AppConfig = Depends(get_runtime_config),
    user: AuthenticatedUser = Depends(require_permission("chat.use")),
):
    request_context = make_request_context(
        request,
        runtime_config,
        user,
        actor_role="conversation",
    )
    session_repository = SessionRepository(runtime_config)
    message_repository = MessageRepository(runtime_config)
    session = _get_owned_session(
        session_repository,
        tenant_id=user.tenant_id,
        user_id=user.user_id,
        project_id=request_context.project_id,
        session_id=session_id,
    )
    messages = message_repository.list_by_session(
        tenant_id=user.tenant_id,
        session_id=session.id,
        limit=limit,
    )
    return {
        "session": serialize_chat_session_record(session),
        "messages": [serialize_chat_message_record(item) for item in messages],
        "count": len(messages),
    }


@router.patch("/sessions/{session_id}")
def rename_chat_session(
    session_id: str,
    payload: ChatSessionRenameModel,
    request: Request,
    runtime_config: AppConfig = Depends(get_runtime_config),
    user: AuthenticatedUser = Depends(require_permission("chat.use")),
):
    request_context = make_request_context(
        request,
        runtime_config,
        user,
        actor_role="conversation",
    )
    enforce_rate_limit(
        runtime_config,
        request_context=request_context,
        user=user,
        request=request,
        action_name="chat_history_update",
        target_type="chat_session",
        target_id=session_id,
    )

    session_repository = SessionRepository(runtime_config)
    session = _get_owned_session(
        session_repository,
        tenant_id=user.tenant_id,
        user_id=user.user_id,
        project_id=request_context.project_id,
        session_id=session_id,
    )
    try:
        updated_session = session_repository.update_title(
            tenant_id=user.tenant_id,
            session_id=session.id,
            title=payload.title,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if updated_session is None:
        raise HTTPException(status_code=404, detail="Chat session not found.")
    return {
        "session": serialize_chat_session_record(updated_session),
    }


@router.post("")
def stream_kb_question_sse(
    request: Request,
    payload: ChatRequestModel,
    runtime_config: AppConfig = Depends(get_runtime_config),
    user: AuthenticatedUser = Depends(require_permission("chat.use")),
):
    return _stream_kb_question(
        request=request,
        payload=payload,
        runtime_config=runtime_config,
        user=user,
        transport="sse",
    )


@router.post("/ask")
def ask_kb_question(
    request: Request,
    payload: ChatRequestModel,
    runtime_config: AppConfig = Depends(get_runtime_config),
    user: AuthenticatedUser = Depends(require_permission("chat.use")),
):
    request_context = _build_chat_request_context(request, payload, runtime_config, user)
    enforce_rate_limit(
        runtime_config,
        request_context=request_context,
        user=user,
        request=request,
        action_name="chat_request",
        target_type="chat",
        target_id=request_context.session_id,
    )
    try:
        with concurrency_slot(
            runtime_config,
            request_context=request_context,
            user=user,
            request=request,
            action_name="chat_request",
            target_type="chat",
            target_id=request_context.session_id,
        ):
            result = ask_question(
                question=payload.question,
                chat_history=[item.model_dump() for item in payload.chat_history],
                config=runtime_config,
                top_k=payload.top_k,
                request_context=request_context,
                session_title=payload.session_title,
                scene=payload.scene,
            )
    except HTTPException:
        raise
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
    user: AuthenticatedUser = Depends(require_permission("chat.use")),
):
    return _stream_kb_question(
        request=request,
        payload=payload,
        runtime_config=runtime_config,
        user=user,
        transport="ndjson",
    )


def _stream_kb_question(
    *,
    request: Request,
    payload: ChatRequestModel,
    runtime_config: AppConfig,
    user: AuthenticatedUser,
    transport: str,
):
    request_context = _build_chat_request_context(request, payload, runtime_config, user)
    enforce_rate_limit(
        runtime_config,
        request_context=request_context,
        user=user,
        request=request,
        action_name="chat_request",
        target_type="chat",
        target_id=request_context.session_id,
    )
    acquire_concurrency_slot(
        runtime_config,
        request_context=request_context,
        user=user,
        request=request,
        action_name="chat_request",
        target_type="chat",
        target_id=request_context.session_id,
    )

    def emit(event_name: str, payload_data: dict[str, object]) -> str:
        event_payload = {"type": event_name, **payload_data}
        if transport == "sse":
            return (
                f"event: {event_name}\n"
                f"data: {json.dumps(event_payload, ensure_ascii=False)}\n\n"
            )
        return json.dumps(event_payload, ensure_ascii=False) + "\n"

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

            yield emit(
                "meta",
                {
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
            )

            full_answer_parts: list[str] = []
            generation_started_at = time.perf_counter()
            for chunk in stream:
                if not chunk:
                    continue
                full_answer_parts.append(chunk)
                yield emit("delta", {"content": chunk})
            generation_ms = (time.perf_counter() - generation_started_at) * 1000

            yield emit(
                "done",
                {
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
            )
        except Exception as exc:
            logger.exception("REST chat stream failed.")
            yield emit("error", {"message": str(exc)})
        finally:
            release_concurrency_slot("chat_request")

    response_headers = {"Cache-Control": "no-cache"}
    if transport == "sse":
        response_headers["X-Accel-Buffering"] = "no"
    return StreamingResponse(
        generate(),
        media_type="text/event-stream" if transport == "sse" else "application/x-ndjson",
        headers=response_headers,
    )


def _build_chat_request_context(
    request: Request,
    payload: ChatRequestModel,
    runtime_config: AppConfig,
    user: AuthenticatedUser,
):
    return make_request_context(
        request,
        runtime_config,
        user,
        session_id=payload.session_id,
        request_id=payload.request_id,
        actor_role="conversation",
    )


def _get_owned_session(
    session_repository: SessionRepository,
    *,
    tenant_id: str,
    user_id: str,
    project_id: str,
    session_id: str,
):
    session = session_repository.get_session(
        tenant_id=tenant_id,
        session_id=session_id,
    )
    if session is None or session.user_id != user_id or session.project_id != project_id:
        raise HTTPException(status_code=404, detail="Chat session not found.")
    return session


def _serialize_error_info(error_info):
    if error_info is None:
        return None
    return {
        "code": error_info.code,
        "message": error_info.message,
        "retryable": error_info.retryable,
        "details": dict(error_info.details),
    }


def _serialize_optional_message(message):
    if message is None:
        return None
    return serialize_chat_message_record(message)
