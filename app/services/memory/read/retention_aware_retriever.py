"""Retention-aware filtering layered on top of scope, consistency, and correction rules."""

from __future__ import annotations

from app.schemas import MemoryFact
from app.services.memory_retrieval_models import DroppedMemoryCandidate, MemoryCandidate


class RetentionAwareRetriever:
    """Remove memories that left the default chain while keeping audit-visible history intact."""

    def filter_candidates_for_default_retrieval(
        self,
        candidates: list[MemoryCandidate],
    ) -> tuple[list[MemoryCandidate], list[DroppedMemoryCandidate]]:
        visible: list[MemoryCandidate] = []
        dropped: list[DroppedMemoryCandidate] = []
        for candidate in candidates:
            drop_reason = self._drop_reason(
                retrieval_visibility=candidate.retrieval_visibility,
                forgetting_status=candidate.forgetting_status,
            )
            if drop_reason is None:
                visible.append(candidate)
                continue
            dropped.append(
                DroppedMemoryCandidate(
                    memory_fact_id=candidate.memory_fact_id,
                    scope_type=candidate.scope_type,
                    scope_id=candidate.scope_id,
                    type=candidate.type,
                    content=candidate.content,
                    drop_reason=drop_reason,
                    retrieval_score=float(candidate.value_score or 0.0),
                    matched_reason=f"retention:{candidate.retrieval_visibility}/{candidate.forgetting_status}",
                )
            )
        return visible, dropped

    def filter_facts_for_default_retrieval(
        self,
        facts: list[MemoryFact],
        *,
        top_k: int,
    ) -> list[MemoryFact]:
        visible = [
            item
            for item in facts
            if self._drop_reason(
                retrieval_visibility=item.retrieval_visibility,
                forgetting_status=item.forgetting_status,
            )
            is None
        ]
        visible.sort(
            key=lambda item: (
                self._visibility_rank(item.retrieval_visibility),
                float(item.value_score or 0.0),
                item.updated_at,
                item.id,
            ),
            reverse=True,
        )
        return visible[:top_k]

    @staticmethod
    def _drop_reason(
        *,
        retrieval_visibility: str,
        forgetting_status: str,
    ) -> str | None:
        if retrieval_visibility == "archive_only" or forgetting_status == "archived":
            return "retention_archive_only"
        if retrieval_visibility == "hidden_from_default":
            return "retention_hidden_from_default"
        if forgetting_status == "expired":
            return "retention_expired"
        return None

    @staticmethod
    def _visibility_rank(retrieval_visibility: str) -> int:
        return {
            "normal": 2,
            "deprioritized": 1,
            "hidden_from_default": 0,
            "archive_only": -1,
        }.get(str(retrieval_visibility or "normal"), 0)
