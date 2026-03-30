"""Business-contract-first RAG orchestration."""

from __future__ import annotations

import logging
import time
from collections.abc import Iterable

from app.config import AppConfig
from app.providers.factory import ProviderFactory
from app.schemas import (
    BusinessErrorInfo,
    BusinessRequest,
    BusinessResponse,
    ChatResult,
    Citation,
    ConversationTurn,
    GenerationConfig,
    KnowledgeContextItem,
    MemoryContextItem,
    MemoryFact,
    MemoryRequestContext,
    RetrievedChunk,
)
from app.services.degradation_controller import DegradationController
from app.services.observability_service import ObservabilityService
from app.services.capability_guard import (
    CapabilityGuard,
    ResponseNormalizer,
    build_output_contract,
    build_system_instruction,
    chunk_text,
    infer_scene,
)
from app.services.catalog_service import bump_citation_counts
from app.services.retrieval_service import retrieve_chunks


logger = logging.getLogger(__name__)


def _make_snippet(text: str, max_length: int = 220) -> str:
    cleaned_text = " ".join(text.split())
    if len(cleaned_text) <= max_length:
        return cleaned_text
    return f"{cleaned_text[:max_length]}..."


def _make_full_text(text: str, max_length: int = 1200) -> str:
    cleaned_text = " ".join(text.split())
    if len(cleaned_text) <= max_length:
        return cleaned_text
    return f"{cleaned_text[:max_length]}..."


def build_citations(retrieved_chunks: list[RetrievedChunk]) -> list[Citation]:
    return [
        Citation(
            knowledge_id=f"kb-{index}",
            document_id=chunk.document_id,
            file_name=chunk.file_name,
            source_path=chunk.source_path,
            relative_path=chunk.relative_path,
            snippet=_make_snippet(chunk.text),
            full_text=_make_full_text(chunk.text),
            score=chunk.score,
            vector_score=chunk.vector_score,
            lexical_score=chunk.lexical_score,
            theme=chunk.theme,
            tags=chunk.tags,
        )
        for index, chunk in enumerate(retrieved_chunks, start=1)
    ]


def answer_with_rag(
    question: str,
    chat_history: list[dict[str, object]],
    config: AppConfig,
    top_k: int | None = None,
    memory_facts: list[MemoryFact] | None = None,
    memory_context: list[MemoryContextItem] | None = None,
    scene: str | None = None,
    request_context: MemoryRequestContext | None = None,
) -> ChatResult:
    logger.info("Received chat request, question=%s", question[:120])
    started_at = time.perf_counter()
    resolved_memory_context = _resolve_memory_context(memory_context, memory_facts)
    resolved_scene = scene or infer_scene(question)
    observability = ObservabilityService(config)
    degradation_controller = DegradationController(config, observability=observability)
    observability.log_event(
        "chat.answer_requested",
        request_context=request_context,
        payload={"scene": resolved_scene, "top_k": top_k_or_default(config, top_k)},
    )

    retrieval_started_at = started_at
    retrieved_chunks, retrieval_query, rewritten_question = retrieve_chunks(
        question=question,
        config=config,
        top_k=top_k,
        chat_history=chat_history,
    )
    retrieval_ms = (time.perf_counter() - retrieval_started_at) * 1000

    # Retrieval, scope isolation, memory retrieval, and scene inference stay provider-agnostic above this boundary.
    business_request = build_business_request(
        question=question,
        chat_history=chat_history,
        retrieved_chunks=retrieved_chunks,
        memory_context=resolved_memory_context,
        memory_facts=memory_facts,
        config=config,
        retrieval_query=retrieval_query,
        rewritten_question=rewritten_question,
        scene=resolved_scene,
        requested_top_k=top_k,
        request_context=request_context,
    )
    observability.record_metric(
        "prompt_token_estimate",
        value=float(_estimate_prompt_tokens(question, chat_history, resolved_memory_context, retrieved_chunks)),
        dimensions={"scene": resolved_scene},
    )
    observability.record_metric(
        "memory_context_size",
        value=float(sum(len(item.content) for item in resolved_memory_context)),
        dimensions={"scene": resolved_scene},
    )

    if _should_return_no_answer(retrieved_chunks, config):
        logger.info("Knowledge retrieval confidence below threshold, returning controlled fallback.")
        fallback_response = ResponseNormalizer().normalize(
            business_request,
            BusinessResponse(
                answer="",
                citations=[],
                confidence=0.0,
                used_memory_ids=[],
                used_knowledge_ids=[],
                provider=config.llm_provider,
                model=config.llm_model,
                error_info=BusinessErrorInfo(
                    code="insufficient_knowledge",
                    message="Knowledge retrieval did not provide enough evidence for generation.",
                ),
            ),
        )
        return _to_chat_result(
            response=fallback_response,
            retrieved_chunks=retrieved_chunks,
            memory_context=resolved_memory_context,
            retrieval_ms=retrieval_ms,
            generation_ms=0.0,
            total_ms=(time.perf_counter() - started_at) * 1000,
            rewritten_question=rewritten_question,
            retrieval_query=retrieval_query,
        )

    # ProviderFactory + CapabilityGuard form the only model-facing boundary the chat flow depends on.
    adapter = ProviderFactory(config).create()
    guard = CapabilityGuard()
    if getattr(adapter, "provider_name", config.llm_provider) != config.llm_provider and request_context is not None:
        degradation_controller.record_provider_fallback(
            request_context=request_context,
            provider=getattr(adapter, "provider_name", "unknown"),
            model=getattr(adapter, "model_name", config.llm_model),
            reason="llm_api_not_ready",
            payload={"requested_provider": config.llm_provider},
        )

    generation_started_at = time.perf_counter()
    business_response = guard.generate(adapter, business_request)
    generation_ms = (time.perf_counter() - generation_started_at) * 1000
    observability.record_metric(
        "provider_call_latency_ms",
        value=generation_ms,
        dimensions={"provider": business_response.provider or getattr(adapter, "provider_name", "unknown")},
    )
    total_ms = (time.perf_counter() - started_at) * 1000
    if business_response.error_info is not None:
        observability.increment_metric(
            "provider_error_count",
            dimensions={
                "provider": business_response.provider or getattr(adapter, "provider_name", "unknown"),
                "code": business_response.error_info.code,
            },
        )
        if request_context is not None and business_response.error_info.code in {
            "provider_generation_failed",
            "low_quality_response",
        }:
            degradation_controller.record_provider_fallback(
                request_context=request_context,
                provider=business_response.provider or getattr(adapter, "provider_name", "unknown"),
                model=business_response.model or getattr(adapter, "model_name", ""),
                reason=business_response.error_info.code,
                payload=dict(business_response.error_info.details),
            )

    citations = business_response.citations
    bump_citation_counts(config, [item.source_path for item in citations])
    logger.info("Chat generation complete, retrieved_chunks=%s provider=%s", len(retrieved_chunks), business_response.provider)
    observability.log_event(
        "chat.answer_completed",
        request_context=request_context,
        payload={
            "scene": resolved_scene,
            "used_memory_ids": list(business_response.used_memory_ids),
            "used_knowledge_ids": list(business_response.used_knowledge_ids),
            "provider": business_response.provider,
            "model": business_response.model,
            "retrieved_count": len(retrieved_chunks),
        },
    )
    return _to_chat_result(
        response=business_response,
        retrieved_chunks=retrieved_chunks,
        memory_context=resolved_memory_context,
        retrieval_ms=retrieval_ms,
        generation_ms=generation_ms,
        total_ms=total_ms,
        rewritten_question=rewritten_question,
        retrieval_query=retrieval_query,
    )


def stream_answer_with_rag(
    question: str,
    chat_history: list[dict[str, object]],
    config: AppConfig,
    top_k: int | None = None,
    memory_facts: list[MemoryFact] | None = None,
    memory_context: list[MemoryContextItem] | None = None,
    scene: str | None = None,
    request_context: MemoryRequestContext | None = None,
) -> tuple[Iterable[str], list[Citation], int, int, float, str, str, float, str, str, str, list[str], list[str], list[str], dict[str, object] | None]:
    result = answer_with_rag(
        question=question,
        chat_history=chat_history,
        config=config,
        top_k=top_k,
        memory_facts=memory_facts,
        memory_context=memory_context,
        scene=scene,
        request_context=request_context,
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


def build_business_request(
    *,
    question: str,
    chat_history: list[dict[str, object]],
    retrieved_chunks: list[RetrievedChunk],
    memory_context: list[MemoryContextItem] | None = None,
    memory_facts: list[MemoryFact] | None = None,
    config: AppConfig,
    retrieval_query: str,
    rewritten_question: str,
    scene: str,
    requested_top_k: int | None,
    request_context: MemoryRequestContext | None = None,
) -> BusinessRequest:
    resolved_scene = scene if scene in {"qa_query", "troubleshooting", "onboarding", "command_lookup"} else infer_scene(question)
    resolved_memory_context = _resolve_memory_context(memory_context, memory_facts)
    return BusinessRequest(
        scene=resolved_scene,
        user_query=question,
        system_instruction=build_system_instruction(resolved_scene),
        conversation_context=_build_conversation_context(chat_history, config.max_history_turns),
        # Memory and knowledge stay separate so preference/background signals never masquerade as citations.
        memory_context=resolved_memory_context,
        knowledge_context=_build_knowledge_context(retrieved_chunks),
        output_contract=build_output_contract(resolved_scene),
        safety_rules=[
            "Use knowledge context as evidence and memory context as background only.",
            "Do not fabricate citations, commands, or unsupported conclusions.",
            "If the knowledge evidence is weak, respond conservatively and say what is missing.",
            "Reply in the user's language unless they explicitly ask for another language.",
        ],
        generation_config=GenerationConfig(
            temperature=config.llm_temperature,
            max_tokens=config.llm_max_tokens,
            timeout_seconds=config.llm_timeout,
        ),
        request_metadata={
            "retrieval_query": retrieval_query,
            "rewritten_question": rewritten_question,
            "requested_top_k": top_k_or_default(config, requested_top_k),
            "memory_count": len(resolved_memory_context),
            "request_id": request_context.request_id if request_context else "",
            "tenant_id": request_context.tenant_id if request_context else "",
            "user_id": request_context.user_id if request_context else "",
            "session_id": request_context.session_id if request_context else "",
        },
    )


def top_k_or_default(config: AppConfig, requested_top_k: int | None) -> int:
    return requested_top_k or config.default_top_k


def _build_conversation_context(
    chat_history: list[dict[str, object]],
    max_turns: int,
) -> list[ConversationTurn]:
    recent_messages = chat_history[-max_turns * 2 :] if max_turns > 0 else []
    turns: list[ConversationTurn] = []
    for message in recent_messages:
        role = str(message.get("role", "")).strip()
        content = str(message.get("content", "")).strip()
        if not role or not content:
            continue
        turns.append(ConversationTurn(role=role, content=content))
    return turns


def _build_memory_context(memory_facts: list[MemoryFact]) -> list[MemoryContextItem]:
    return [
        MemoryContextItem(
            memory_id=item.id,
            scope_type=item.scope_type,
            scope_id=item.scope_id,
            memory_type=item.type,
            content=item.content,
            subject_key=item.subject_key,
            fact_key=item.fact_key,
            version=item.version,
            source_type=item.source_type,
        )
        for item in memory_facts
    ]


def _resolve_memory_context(
    memory_context: list[MemoryContextItem] | None,
    memory_facts: list[MemoryFact] | None,
) -> list[MemoryContextItem]:
    if memory_context is not None:
        return list(memory_context)
    return _build_memory_context(memory_facts or [])


def _build_knowledge_context(retrieved_chunks: list[RetrievedChunk]) -> list[KnowledgeContextItem]:
    context_items: list[KnowledgeContextItem] = []
    for index, chunk in enumerate(retrieved_chunks, start=1):
        context_items.append(
            KnowledgeContextItem(
                knowledge_id=f"kb-{index}",
                document_id=chunk.document_id,
                file_name=chunk.file_name,
                source_path=chunk.source_path,
                relative_path=chunk.relative_path,
                content=chunk.text,
                score=chunk.score,
                theme=chunk.theme,
                tags=list(chunk.tags),
            )
        )
    return context_items


def _to_chat_result(
    *,
    response: BusinessResponse,
    retrieved_chunks: list[RetrievedChunk],
    memory_context: list[MemoryContextItem],
    retrieval_ms: float,
    generation_ms: float,
    total_ms: float,
    rewritten_question: str,
    retrieval_query: str,
) -> ChatResult:
    confidence = response.confidence
    if confidence <= 0 and not response.error_info and retrieved_chunks:
        confidence = max(0.0, min(1.0, float(retrieved_chunks[0].score or 0.0)))

    return ChatResult(
        answer=response.answer,
        citations=response.citations,
        retrieved_count=len(retrieved_chunks),
        memory_count=len(memory_context),
        retrieval_ms=retrieval_ms,
        generation_ms=generation_ms,
        total_ms=total_ms,
        rewritten_question=rewritten_question,
        retrieval_query=retrieval_query,
        confidence=confidence,
        summary=response.summary,
        steps=response.steps,
        used_memory_ids=response.used_memory_ids,
        used_knowledge_ids=response.used_knowledge_ids,
        provider=response.provider,
        model=response.model,
        raw_response=response.raw_response,
        error_info=response.error_info,
    )


def _serialize_error_info(error_info: BusinessErrorInfo | None) -> dict[str, object] | None:
    if error_info is None:
        return None
    return {
        "code": error_info.code,
        "message": error_info.message,
        "retryable": error_info.retryable,
        "details": dict(error_info.details),
    }


def _should_return_no_answer(retrieved_chunks: list[RetrievedChunk], config: AppConfig) -> bool:
    if not retrieved_chunks:
        return True
    top_chunk = retrieved_chunks[0]
    top_score = float(top_chunk.score or 0.0)
    return top_score < config.no_answer_min_score


def _estimate_prompt_tokens(
    question: str,
    chat_history: list[dict[str, object]],
    memory_context: list[MemoryContextItem],
    retrieved_chunks: list[RetrievedChunk],
) -> int:
    total_chars = len(str(question or ""))
    total_chars += sum(len(str(item.get("content", "") or "")) for item in chat_history)
    total_chars += sum(len(item.content) for item in memory_context)
    total_chars += sum(len(item.text) for item in retrieved_chunks)
    return max(int(total_chars / 4), 1) if total_chars else 0
