"""Transform ranked retrieval results into provider-agnostic memory context."""

from __future__ import annotations

from app.schemas import MemoryContextItem
from app.services.memory_retrieval_models import MemoryRetrievalPlan, MemoryRetrievalResult


class MemoryInjectionBuilder:
    """Keep memory injection independent from repository rows and provider adapters."""

    def build_context(
        self,
        selected_memories: list[MemoryRetrievalResult],
        *,
        plan: MemoryRetrievalPlan | None = None,
    ) -> list[MemoryContextItem]:
        max_chars = int(plan.max_injection_chars_per_memory) if plan is not None else 0
        return [
            MemoryContextItem(
                memory_id=item.memory_fact_id,
                scope_type=item.scope_type,
                scope_id=item.scope_id,
                memory_type=item.type,
                content=_truncate_content(item.content, max_chars),
                subject_key=item.subject_key,
                fact_key=item.fact_key,
                version=item.version,
                source_type=item.source_type,
                retrieval_score=item.retrieval_score,
                matched_reason=item.matched_reason,
            )
            for item in selected_memories
        ]


def _truncate_content(content: str, max_chars: int) -> str:
    normalized = str(content or "").strip()
    if max_chars <= 0 or len(normalized) <= max_chars:
        return normalized
    if max_chars <= 3:
        return normalized[:max_chars]
    return f"{normalized[: max_chars - 3].rstrip()}..."
