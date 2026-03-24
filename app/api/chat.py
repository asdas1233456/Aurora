"""聊天相关的内部 API。"""

from __future__ import annotations

from app.config import AppConfig
from app.schemas import ChatResult
from app.services.rag_service import answer_with_rag


def ask_question(
    question: str,
    chat_history: list[dict[str, object]],
    config: AppConfig,
    top_k: int | None = None,
) -> ChatResult:
    """执行一次知识库问答。"""
    return answer_with_rag(
        question=question,
        chat_history=chat_history,
        config=config,
        top_k=top_k,
    )

