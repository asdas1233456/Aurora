"""Consistency-aware filtering and scope-priority collapsing for memory retrieval."""

from __future__ import annotations

from collections.abc import Mapping

from app.schemas import MemoryFact
from app.services.memory_retrieval_models import DroppedMemoryCandidate, MemoryCandidate


_SCOPE_PRIORITY = {
    "session": 0,
    "user": 1,
    "project": 2,
    "team": 3,
    "global": 4,
}


class ConsistentMemoryRetriever:
    """Return only current effective facts and hide lower-priority scope duplicates."""

    def collapse_candidates(
        self,
        candidates: list[MemoryCandidate],
        *,
        scope_weights: Mapping[str, float],
    ) -> tuple[list[MemoryCandidate], list[DroppedMemoryCandidate]]:
        grouped_candidates: dict[tuple[str, str], list[MemoryCandidate]] = {}
        for candidate in candidates:
            grouped_candidates.setdefault(self._candidate_identity_key(candidate), []).append(candidate)

        surviving_candidates: list[MemoryCandidate] = []
        dropped_candidates: list[DroppedMemoryCandidate] = []

        # Keep only the strongest representative per logical fact so narrower/newer variants
        # do not flood the ranker with the same information repeated across scopes.
        for group_items in grouped_candidates.values():
            ordered_group = sorted(
                group_items,
                key=lambda item: (
                    float(scope_weights.get(item.scope_type, 0.0)),
                    float(item.source_confidence or 0.0),
                    int(item.version or 1),
                    item.updated_at,
                    item.created_at,
                ),
                reverse=True,
            )
            surviving_candidates.append(ordered_group[0])
            for shadowed in ordered_group[1:]:
                dropped_candidates.append(
                    DroppedMemoryCandidate(
                        memory_fact_id=shadowed.memory_fact_id,
                        scope_type=shadowed.scope_type,
                        scope_id=shadowed.scope_id,
                        type=shadowed.type,
                        content=shadowed.content,
                        drop_reason=f"shadowed_by_same_identity:{ordered_group[0].memory_fact_id}",
                        matched_reason="consistency_scope_collapse",
                    )
                )

        surviving_candidates.sort(
            key=lambda item: (item.updated_at, float(scope_weights.get(item.scope_type, 0.0))),
            reverse=True,
        )
        return surviving_candidates, dropped_candidates

    def filter_for_default_retrieval(
        self,
        candidates: list[MemoryFact],
        *,
        top_k: int,
    ) -> list[MemoryFact]:
        ordered_candidates = sorted(
            candidates,
            key=lambda item: (item.version, item.updated_at, item.created_at),
            reverse=True,
        )
        ordered_candidates.sort(key=lambda item: _SCOPE_PRIORITY.get(item.scope_type, 99))

        selected: list[MemoryFact] = []
        seen_identity_keys: set[tuple[str, str]] = set()
        for item in ordered_candidates:
            if item.status != "active":
                continue
            if item.superseded_by:
                continue

            identity_key = self._identity_key(item)
            if identity_key in seen_identity_keys:
                continue

            seen_identity_keys.add(identity_key)
            selected.append(item)
            if len(selected) >= top_k:
                break

        return selected

    @staticmethod
    def _identity_key(item: MemoryFact) -> tuple[str, str]:
        subject_key = item.subject_key or f"legacy-subject:{item.id}"
        fact_key = item.fact_key or f"legacy-fact:{item.id}"
        return subject_key, fact_key

    @staticmethod
    def _candidate_identity_key(item: MemoryCandidate) -> tuple[str, str]:
        subject_key = item.subject_key or f"legacy-subject:{item.memory_fact_id}"
        fact_key = item.fact_key or f"legacy-fact:{item.memory_fact_id}"
        return subject_key, fact_key
