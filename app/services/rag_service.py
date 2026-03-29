"""问答生成与引用组织模块。"""

from __future__ import annotations

import logging
import time
from collections.abc import Iterable

from app.config import AppConfig
from app.llm import get_llm_provider
from app.schemas import ChatResult, Citation, RetrievedChunk
from app.services.catalog_service import bump_citation_counts
from app.services.retrieval_service import retrieve_chunks


logger = logging.getLogger(__name__)


def _make_snippet(text: str, max_length: int = 220) -> str:
    """生成适合界面展示的引用片段摘要。"""
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
    """把检索结果转换成引用来源。"""
    citations: list[Citation] = []

    for chunk in retrieved_chunks:
        citations.append(
            Citation(
                file_name=chunk.file_name,
                source_path=chunk.source_path,
                snippet=_make_snippet(chunk.text),
                full_text=_make_full_text(chunk.text),
                score=chunk.score,
                vector_score=chunk.vector_score,
                lexical_score=chunk.lexical_score,
                theme=chunk.theme,
                tags=chunk.tags,
            )
        )

    return citations


def answer_with_rag(
    question: str,
    chat_history: list[dict[str, object]],
    config: AppConfig,
    top_k: int | None = None,
) -> ChatResult:
    """执行一次完整的 RAG 问答流程。"""
    logger.info("收到问答请求，问题=%s", question[:120])
    started_at = time.perf_counter()
    retrieval_started_at = started_at
    retrieved_chunks, retrieval_query, rewritten_question = retrieve_chunks(
        question=question,
        config=config,
        top_k=top_k,
        chat_history=chat_history,
    )
    retrieval_ms = (time.perf_counter() - retrieval_started_at) * 1000

    if _should_return_no_answer(retrieved_chunks, config):
        logger.info("问答已触发低置信度兜底。")
        return ChatResult(
            answer="当前知识库中没有足够信息回答该问题，请尝试换个问法、补充文档，或缩小问题范围后再试。",
            citations=build_citations(retrieved_chunks[:1]),
            retrieved_count=len(retrieved_chunks),
            retrieval_ms=retrieval_ms,
            generation_ms=0.0,
            total_ms=(time.perf_counter() - started_at) * 1000,
            rewritten_question=rewritten_question,
            retrieval_query=retrieval_query,
            confidence=float(retrieved_chunks[0].score or 0.0) if retrieved_chunks else 0.0,
        )

    provider = get_llm_provider(config)
    generation_started_at = time.perf_counter()
    answer = provider.generate_answer(
        question=question,
        chat_history=chat_history,
        retrieved_chunks=retrieved_chunks,
        config=config,
    )
    generation_ms = (time.perf_counter() - generation_started_at) * 1000
    total_ms = (time.perf_counter() - started_at) * 1000
    citations = build_citations(retrieved_chunks)
    bump_citation_counts(config, [item.source_path for item in citations])

    logger.info("问答完成，命中片段数=%s", len(retrieved_chunks))
    return ChatResult(
        answer=answer,
        citations=citations,
        retrieved_count=len(retrieved_chunks),
        retrieval_ms=retrieval_ms,
        generation_ms=generation_ms,
        total_ms=total_ms,
        rewritten_question=rewritten_question,
        retrieval_query=retrieval_query,
        confidence=float(retrieved_chunks[0].score or 0.0) if retrieved_chunks else 0.0,
    )


def stream_answer_with_rag(
    question: str,
    chat_history: list[dict[str, object]],
    config: AppConfig,
    top_k: int | None = None,
) -> tuple[Iterable[str], list[Citation], int, float, str, str, float]:
    """执行一次流式 RAG 问答流程。"""
    logger.info("收到流式问答请求，问题=%s", question[:120])
    retrieval_started_at = time.perf_counter()
    retrieved_chunks, retrieval_query, rewritten_question = retrieve_chunks(
        question=question,
        config=config,
        top_k=top_k,
        chat_history=chat_history,
    )
    retrieval_ms = (time.perf_counter() - retrieval_started_at) * 1000

    if _should_return_no_answer(retrieved_chunks, config):
        def empty_stream():
            yield "当前知识库中没有足够信息回答该问题，请尝试换个问法、补充文档，或缩小问题范围后再试。"

        citations = build_citations(retrieved_chunks[:1])
        return (
            empty_stream(),
            citations,
            len(retrieved_chunks),
            retrieval_ms,
            rewritten_question,
            retrieval_query,
            float(retrieved_chunks[0].score or 0.0) if retrieved_chunks else 0.0,
        )

    provider = get_llm_provider(config)
    citations = build_citations(retrieved_chunks)
    bump_citation_counts(config, [item.source_path for item in citations])
    stream = provider.stream_answer(
        question=question,
        chat_history=chat_history,
        retrieved_chunks=retrieved_chunks,
        config=config,
    )
    return (
        stream,
        citations,
        len(retrieved_chunks),
        retrieval_ms,
        rewritten_question,
        retrieval_query,
        float(retrieved_chunks[0].score or 0.0) if retrieved_chunks else 0.0,
    )


def _should_return_no_answer(retrieved_chunks: list[RetrievedChunk], config: AppConfig) -> bool:
    if not retrieved_chunks:
        return True
    top_chunk = retrieved_chunks[0]
    top_score = float(top_chunk.score or 0.0)
    return top_score < config.no_answer_min_score
