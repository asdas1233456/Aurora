"""问答生成与引用组织模块。"""

from __future__ import annotations

import logging
from collections.abc import Iterable

from app.config import AppConfig
from app.llm import get_llm_provider
from app.schemas import ChatResult, Citation, RetrievedChunk
from app.services.retrieval_service import retrieve_chunks


logger = logging.getLogger(__name__)


def _make_snippet(text: str, max_length: int = 220) -> str:
    """生成适合界面展示的引用片段摘要。"""
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
                score=chunk.score,
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
    retrieved_chunks = retrieve_chunks(question=question, config=config, top_k=top_k)

    if not retrieved_chunks:
        logger.info("未检索到相关片段。")
        return ChatResult(
            answer="当前知识库中没有检索到相关内容，请尝试换个问法，或补充文档后重新构建知识库。",
            citations=[],
            retrieved_count=0,
        )

    provider = get_llm_provider(config)
    answer = provider.generate_answer(
        question=question,
        chat_history=chat_history,
        retrieved_chunks=retrieved_chunks,
        config=config,
    )

    logger.info("问答完成，命中片段数=%s", len(retrieved_chunks))
    return ChatResult(
        answer=answer,
        citations=build_citations(retrieved_chunks),
        retrieved_count=len(retrieved_chunks),
    )


def stream_answer_with_rag(
    question: str,
    chat_history: list[dict[str, object]],
    config: AppConfig,
    top_k: int | None = None,
) -> tuple[Iterable[str], list[Citation], int]:
    """执行一次流式 RAG 问答流程。"""
    logger.info("收到流式问答请求，问题=%s", question[:120])
    retrieved_chunks = retrieve_chunks(question=question, config=config, top_k=top_k)

    if not retrieved_chunks:
        def empty_stream():
            yield "当前知识库中没有检索到相关内容，请尝试换个问法，或补充文档后重新构建知识库。"

        return empty_stream(), [], 0

    provider = get_llm_provider(config)
    citations = build_citations(retrieved_chunks)
    stream = provider.stream_answer(
        question=question,
        chat_history=chat_history,
        retrieved_chunks=retrieved_chunks,
        config=config,
    )
    return stream, citations, len(retrieved_chunks)
