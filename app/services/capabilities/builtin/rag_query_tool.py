"""Built-in knowledge retrieval capability."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from app.schemas import RetrievedChunk
from app.services.capabilities.base import BaseTool
from app.services.capabilities.models import CapabilityContext, CapabilityDescriptor
from app.services.knowledge_access_policy import build_access_filter
from app.services.retrieval_service import retrieve_chunks


class KBRetrieveTool(BaseTool):
    """Wrap the existing retrieval service as a registry-visible tool."""

    descriptor = CapabilityDescriptor(
        name="kb.retrieve",
        capability_type="tool",
        display_name="Knowledge Retrieval",
        description="Retrieve knowledge chunks from Aurora retrieval storage.",
        read_only=True,
        concurrency_safe=True,
        allow_user_invoke=True,
        allow_model_invoke=True,
        routing_tags=("kb", "retrieval", "rag"),
    )

    def execute(
        self,
        payload: Mapping[str, Any],
        context: CapabilityContext,
    ) -> tuple[list[RetrievedChunk], str, str]:
        """Execute one retrieval request.

        The tool deliberately delegates to the existing retrieval pipeline so we
        keep one source of truth for query rewriting, recall, and reranking.
        """

        question = str(payload.get("question") or payload.get("query") or "").strip()
        if not question:
            raise ValueError("question is required for kb.retrieve")

        top_k_raw = payload.get("top_k")
        top_k = int(top_k_raw) if top_k_raw not in {None, ""} else None
        chat_history = _normalize_chat_history(payload.get("chat_history"))
        access_filter = payload.get("access_filter")
        return retrieve_chunks(
            question=question,
            config=self.config,
            top_k=top_k,
            chat_history=chat_history,
            access_filter=access_filter if access_filter is not None else build_access_filter(context),
        )


def _normalize_chat_history(raw_value: object) -> list[dict[str, object]]:
    """Normalize chat-history payloads into the existing retrieval format."""
    if not isinstance(raw_value, list):
        return []

    normalized_items: list[dict[str, object]] = []
    for item in raw_value:
        if not isinstance(item, Mapping):
            continue
        normalized_items.append({str(key): value for key, value in item.items()})
    return normalized_items
