"""Chat orchestration with scope-aware memory retrieval and persistent recovery."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass

from app.api.request_context import build_request_context
from app.api.serializers import serialize_citation
from app.config import AppConfig
from app.schemas import ChatMessageCreate, ChatResult, MemoryRequestContext
from app.services.capability_guard import chunk_text
from app.services.message_repository import MessageRepository
from app.services.degradation_controller import DegradationController
from app.services.memory.governance.memory_repository import MemoryRepository
from app.services.memory.governance.memory_scope import ScopeResolver
from app.services.memory.read.memory_retrieval_models import MemoryRetrievalBundle
from app.services.memory.read.memory_retriever import MemoryRetriever
from app.services.memory.write.chat_memory_service import ChatMemoryService
from app.services.observability_service import ObservabilityService
from app.services.rag_service import answer_with_rag
from app.services.session_recovery_service import SessionRecoveryService
from app.services.session_repository import SessionRepository


logger = logging.getLogger(__name__)


@dataclass(slots=True)
class PreparedChatRequest:
    """State assembled before the RAG pipeline runs."""

    request_context: MemoryRequestContext
    user_question: str
    session_title: str
    conversation_history: list[dict[str, object]]
    memory_bundle: MemoryRetrievalBundle


def prepare_chat_request(
    *,
    question: str,
    chat_history: list[dict[str, object]],
    config: AppConfig,
    request_context: MemoryRequestContext,
    top_k: int | None = None,
    session_title: str | None = None,
    scene: str | None = None,
) -> PreparedChatRequest:
    observability = ObservabilityService(config)
    degradation_controller = DegradationController(config, observability=observability)
    scope_resolver = ScopeResolver()
    session_repository = SessionRepository(config)
    message_repository = MessageRepository(config)
    recovery_service = SessionRecoveryService(
        config,
        session_repository=session_repository,
        message_repository=message_repository,
    )
    memory_retriever = MemoryRetriever(config, scope_resolver=scope_resolver)

    resolved_title = (session_title or _derive_session_title(question)).strip() or "New chat"
    session_repository.ensure_session(request_context, title=resolved_title)
    persisted_user_message = message_repository.create_message(
        ChatMessageCreate(
            tenant_id=request_context.tenant_id,
            session_id=request_context.session_id,
            user_id=request_context.user_id,
            role="user",
            content=question,
            metadata_json=_build_user_message_metadata(
                request_context=request_context,
                scene=scene,
                top_k=top_k,
                session_title=resolved_title,
            ),
        )
    )

    history_message_limit = max(config.max_history_turns * 2, 0)
    recovery_snapshot = recovery_service.recover_session(
        request_context,
        message_limit=max(history_message_limit + 1, 1),
    )
    # Persist first, then recover. This guarantees crash-safe recovery while avoiding duplicate current-turn context.
    recovered_history = recovery_service.build_recent_chat_history(
        recovery_snapshot,
        fallback_history=chat_history,
        exclude_message_ids=(persisted_user_message.id,),
        message_limit=history_message_limit,
    )

    resolved_context = scope_resolver.resolve(request_context)
    memory_limit = max(top_k or config.default_top_k, 1)
    try:
        memory_bundle = memory_retriever.retrieve_bundle(
            resolved_context,
            scene=scene,
            user_query=question,
            top_k=memory_limit,
            retrieval_metadata={
                "request_id": request_context.request_id,
                "session_title": resolved_title,
            },
            fail_open=True,
        )
    except Exception as exc:  # pragma: no cover - defensive fallback on top of retriever fail_open
        degradation_controller.degrade_memory_retrieval(
            request_context=request_context,
            reason="chat_prepare_exception",
            payload={"exception_type": exc.__class__.__name__},
        )
        memory_bundle = MemoryRetrievalBundle(
            selected_memories=[],
            dropped_candidates=[],
            total_candidates=0,
            total_selected=0,
            retrieval_plan=None,
            memory_context=[],
            retrieval_trace={
                "summary": {"error": f"{exc.__class__.__name__}: {exc}"},
            },
        )
    if memory_bundle.retrieval_trace and memory_bundle.retrieval_trace.get("summary", {}).get("error"):
        logger.warning(
            "Memory retrieval failed open for request_id=%s: %s",
            request_context.request_id,
            memory_bundle.retrieval_trace["summary"].get("error"),
        )
        degradation_controller.degrade_memory_retrieval(
            request_context=request_context,
            reason="memory_fail_open",
            payload={"detail": memory_bundle.retrieval_trace["summary"].get("error")},
        )
    return PreparedChatRequest(
        request_context=request_context,
        user_question=question,
        session_title=resolved_title,
        conversation_history=recovered_history,
        memory_bundle=memory_bundle,
    )


def ask_question(
    question: str,
    chat_history: list[dict[str, object]],
    config: AppConfig,
    top_k: int | None = None,
    request_context: MemoryRequestContext | None = None,
    session_title: str | None = None,
    scene: str | None = None,
) -> ChatResult:
    normalized_context = request_context or build_request_context(config=config)
    prepared_request = prepare_chat_request(
        question=question,
        chat_history=chat_history,
        config=config,
        request_context=normalized_context,
        top_k=top_k,
        session_title=session_title,
        scene=scene,
    )
    resolved_scene = _resolve_bundle_scene(prepared_request.memory_bundle, scene)
    result = answer_with_rag(
        question=question,
        chat_history=prepared_request.conversation_history,
        config=config,
        top_k=top_k,
        memory_context=prepared_request.memory_bundle.memory_context,
        scene=resolved_scene,
        request_context=prepared_request.request_context,
    )
    _persist_assistant_message(
        config=config,
        prepared_request=prepared_request,
        result=result,
        scene=resolved_scene,
    )
    return result


def prepare_stream_answer(
    question: str,
    chat_history: list[dict[str, object]],
    config: AppConfig,
    top_k: int | None = None,
    request_context: MemoryRequestContext | None = None,
    session_title: str | None = None,
    scene: str | None = None,
):
    normalized_context = request_context or build_request_context(config=config)
    prepared_request = prepare_chat_request(
        question=question,
        chat_history=chat_history,
        config=config,
        request_context=normalized_context,
        top_k=top_k,
        session_title=session_title,
        scene=scene,
    )
    resolved_scene = _resolve_bundle_scene(prepared_request.memory_bundle, scene)
    result = answer_with_rag(
        question=question,
        chat_history=prepared_request.conversation_history,
        config=config,
        top_k=top_k,
        memory_context=prepared_request.memory_bundle.memory_context,
        scene=resolved_scene,
        request_context=prepared_request.request_context,
    )
    _persist_assistant_message(
        config=config,
        prepared_request=prepared_request,
        result=result,
        scene=resolved_scene,
    )
    return (
        chunk_text(result.answer),
        result.citations,
        result.retrieved_count,
        result.memory_count,
        result.retrieval_ms,
        result.rewritten_question,
        result.retrieval_query,
        result.confidence,
        result.summary,
        result.provider,
        result.model,
        result.steps,
        result.used_memory_ids,
        result.used_knowledge_ids,
        _serialize_error_info(result.error_info),
    )


def _persist_assistant_message(
    *,
    config: AppConfig,
    prepared_request: PreparedChatRequest,
    result: ChatResult,
    scene: str | None,
) -> None:
    message_repository = MessageRepository(config)
    session_repository = SessionRepository(config)
    message_repository.create_message(
        ChatMessageCreate(
            tenant_id=prepared_request.request_context.tenant_id,
            session_id=prepared_request.request_context.session_id,
            user_id=prepared_request.request_context.user_id,
            role="assistant",
            content=result.answer,
            provider=result.provider,
            model=result.model,
            citations_json=json.dumps(
                [serialize_citation(item) for item in result.citations],
                ensure_ascii=False,
            ),
            metadata_json=_build_assistant_message_metadata(
                request_context=prepared_request.request_context,
                result=result,
                scene=scene,
                session_title=prepared_request.session_title,
                memory_bundle=prepared_request.memory_bundle,
            ),
        )
    )
    session_repository.update_last_active(
        tenant_id=prepared_request.request_context.tenant_id,
        session_id=prepared_request.request_context.session_id,
    )
    if result.used_memory_ids:
        MemoryRepository(config).mark_successful_use(list(dict.fromkeys(result.used_memory_ids)))
    try:
        ChatMemoryService(config).assimilate_turn(
            request_context=prepared_request.request_context,
            user_message=prepared_request.user_question,
            assistant_result=result,
            scene=scene,
        )
    except Exception:
        logger.warning(
            "Automatic memory assimilation failed for request_id=%s.",
            prepared_request.request_context.request_id,
            exc_info=True,
        )


def _build_user_message_metadata(
    *,
    request_context: MemoryRequestContext,
    scene: str | None,
    top_k: int | None,
    session_title: str,
) -> str:
    return json.dumps(
        {
            "request_id": request_context.request_id,
            "scene": scene or "",
            "requested_top_k": top_k,
            "session_title": session_title,
        },
        ensure_ascii=False,
    )


def _build_assistant_message_metadata(
    *,
    request_context: MemoryRequestContext,
    result: ChatResult,
    scene: str | None,
    session_title: str,
    memory_bundle: MemoryRetrievalBundle,
) -> str:
    return json.dumps(
        {
            "request_id": request_context.request_id,
            "scene": scene or "",
            "session_title": session_title,
            "retrieved_count": result.retrieved_count,
            "memory_count": result.memory_count,
            "retrieval_ms": result.retrieval_ms,
            "generation_ms": result.generation_ms,
            "total_ms": result.total_ms,
            "confidence": result.confidence,
            "rewritten_question": result.rewritten_question,
            "retrieval_query": result.retrieval_query,
            "provider": result.provider,
            "model": result.model,
            "steps": result.steps,
            "used_memory_ids": result.used_memory_ids,
            "used_knowledge_ids": result.used_knowledge_ids,
            "summary": result.summary,
            "error_info": _serialize_error_info(result.error_info),
            "memory_retrieval": _summarize_memory_bundle(memory_bundle),
        },
        ensure_ascii=False,
    )


def _derive_session_title(question: str) -> str:
    normalized = " ".join(str(question or "").split()).strip()
    if not normalized:
        return "New chat"
    return normalized[:48]


def _serialize_error_info(error_info):
    if error_info is None:
        return None
    return {
        "code": error_info.code,
        "message": error_info.message,
        "retryable": error_info.retryable,
        "details": dict(error_info.details),
    }


def _resolve_bundle_scene(memory_bundle: MemoryRetrievalBundle, fallback_scene: str | None) -> str | None:
    if memory_bundle.retrieval_plan is not None:
        return memory_bundle.retrieval_plan.scene
    return fallback_scene


def _summarize_memory_bundle(memory_bundle: MemoryRetrievalBundle) -> dict[str, object]:
    return {
        "scene": memory_bundle.retrieval_plan.scene if memory_bundle.retrieval_plan else "",
        "retrieval_mode": memory_bundle.retrieval_plan.retrieval_mode if memory_bundle.retrieval_plan else "",
        "total_candidates": memory_bundle.total_candidates,
        "total_selected": memory_bundle.total_selected,
        "selected_memory_ids": [item.memory_fact_id for item in memory_bundle.selected_memories],
    }
