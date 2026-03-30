"""Ranking and bounded injection selection for Aurora memory retrieval."""

from __future__ import annotations

from datetime import datetime, timezone

from app.services.memory_retrieval_models import (
    DroppedMemoryCandidate,
    MemoryCandidate,
    MemoryQuery,
    MemoryRetrievalBundle,
    MemoryRetrievalPlan,
    MemoryRetrievalResult,
    MemoryRelevanceSignal,
)


class MemoryRanker:
    """Combine lightweight signals into a stable Top-K selection."""

    def __init__(self, *, score_weights: dict[str, float] | None = None) -> None:
        # Keep ranking weights configurable so future learned or feedback-based tuning
        # can reuse the same ranker boundary without touching retrieval orchestration.
        self._score_weights = {
            "relevance": 0.33,
            "scope_priority": 0.18,
            "recency": 0.12,
            "type_priority": 0.10,
            "source_confidence": 0.07,
            "retention_value": 0.20,
        }
        if score_weights:
            self._score_weights.update(
                {
                    key: float(value)
                    for key, value in score_weights.items()
                    if key in self._score_weights
                }
            )

    def rank(
        self,
        *,
        query: MemoryQuery,
        plan: MemoryRetrievalPlan,
        candidates: list[MemoryCandidate],
        relevance_signals: dict[str, MemoryRelevanceSignal],
        consistency_drops: list[DroppedMemoryCandidate] | None = None,
    ) -> MemoryRetrievalBundle:
        dropped_candidates = list(consistency_drops or [])
        ranked_results: list[MemoryRetrievalResult] = []
        drop_reasons: dict[str, str] = {}

        for candidate in candidates:
            signal = relevance_signals.get(candidate.memory_fact_id, MemoryRelevanceSignal(score=0.0))
            if not self._type_enabled(plan, candidate):
                dropped_candidates.append(
                    self._drop(candidate, reason="scene_filtered_type", signal=signal)
                )
                continue
            if self._drop_low_value_preference(query, plan, candidate, signal):
                dropped_candidates.append(
                    self._drop(candidate, reason="scene_filtered_low_value_preference", signal=signal)
                )
                continue

            score_breakdown = {
                "relevance": 1.0 if plan.retrieval_mode == "exact_scope_only" else signal.score,
                "scope_priority": float(plan.scope_weights.get(candidate.scope_type, 0.0)),
                "recency": self._recency_score(candidate.updated_at, recent_window_days=plan.recent_window_days),
                "type_priority": float(plan.type_weights.get(candidate.type, 0.0)),
                "source_confidence": max(0.0, min(1.0, candidate.source_confidence)),
                "retention_value": self._retention_value(candidate),
            }
            retrieval_score = sum(
                score_breakdown[name] * weight
                for name, weight in self._score_weights.items()
            )
            ranked_results.append(
                MemoryRetrievalResult(
                    memory_fact_id=candidate.memory_fact_id,
                    scope_type=candidate.scope_type,
                    scope_id=candidate.scope_id,
                    type=candidate.type,
                    content=candidate.content,
                    retrieval_score=retrieval_score,
                    matched_reason=signal.matched_reason,
                    selected_for_injection=False,
                    source_session_id=candidate.source_session_id,
                    updated_at=candidate.updated_at,
                    source_confidence=candidate.source_confidence,
                    subject_key=candidate.subject_key,
                    fact_key=candidate.fact_key,
                    version=candidate.version,
                    source_type=candidate.source_type,
                    value_score=candidate.value_score,
                    retention_level=candidate.retention_level,
                    retrieval_visibility=candidate.retrieval_visibility,
                    forgetting_status=candidate.forgetting_status,
                    score_breakdown=score_breakdown,
                    memory_fact=candidate.memory_fact,
                )
            )

        ranked_results.sort(
            key=lambda item: (item.retrieval_score, item.updated_at, item.memory_fact_id),
            reverse=True,
        )
        for index, item in enumerate(ranked_results, start=1):
            item.rank = index

        selected: list[MemoryRetrievalResult] = []
        scope_counts: dict[str, int] = {}
        for item in ranked_results:
            drop_reason = self._select_or_explain(item, plan, scope_counts, selected)
            if drop_reason:
                drop_reasons[item.memory_fact_id] = drop_reason

        if not selected and plan.retrieval_mode == "ranked_with_fallback":
            fallback_item = self._select_fallback(ranked_results, plan)
            if fallback_item is not None:
                fallback_item.selected_for_injection = True
                fallback_item.matched_reason = (
                    f"{fallback_item.matched_reason}; fallback" if fallback_item.matched_reason else "fallback"
                )
                selected.append(fallback_item)
                scope_counts[fallback_item.scope_type] = scope_counts.get(fallback_item.scope_type, 0) + 1
                drop_reasons.pop(fallback_item.memory_fact_id, None)

        for item in ranked_results:
            if item.selected_for_injection:
                continue
            dropped_candidates.append(
                DroppedMemoryCandidate(
                    memory_fact_id=item.memory_fact_id,
                    scope_type=item.scope_type,
                    scope_id=item.scope_id,
                    type=item.type,
                    content=item.content,
                    drop_reason=drop_reasons.get(item.memory_fact_id, "not_selected"),
                    retrieval_score=item.retrieval_score,
                    matched_reason=item.matched_reason,
                )
            )

        return MemoryRetrievalBundle(
            selected_memories=selected,
            dropped_candidates=dropped_candidates,
            total_candidates=len(candidates),
            total_selected=len(selected),
        )

    @staticmethod
    def _type_enabled(plan: MemoryRetrievalPlan, candidate: MemoryCandidate) -> bool:
        return float(plan.type_weights.get(candidate.type, 0.0)) > 0.0

    @staticmethod
    def _drop_low_value_preference(
        query: MemoryQuery,
        plan: MemoryRetrievalPlan,
        candidate: MemoryCandidate,
        signal: MemoryRelevanceSignal,
    ) -> bool:
        return (
            query.scene == "command_lookup"
            and candidate.type == "preference"
            and signal.score < max(plan.min_relevance_score, 0.24)
        )

    @staticmethod
    def _select_or_explain(
        item: MemoryRetrievalResult,
        plan: MemoryRetrievalPlan,
        scope_counts: dict[str, int],
        selected: list[MemoryRetrievalResult],
    ) -> str | None:
        relevance_score = float(item.score_breakdown.get("relevance", 0.0))
        if plan.retrieval_mode != "exact_scope_only" and relevance_score < plan.min_relevance_score:
            return "below_min_relevance"
        if plan.retrieval_mode != "exact_scope_only" and item.retrieval_score < plan.min_injection_score:
            return "below_injection_threshold"

        scope_cap = int(plan.per_scope_top_k.get(item.scope_type, 0))
        if scope_cap <= 0:
            return "scope_injection_disabled"
        if scope_counts.get(item.scope_type, 0) >= scope_cap:
            return "per_scope_cap_reached"
        if len(selected) >= plan.top_k:
            return "top_k_cap_reached"

        item.selected_for_injection = True
        selected.append(item)
        scope_counts[item.scope_type] = scope_counts.get(item.scope_type, 0) + 1
        return None

    @staticmethod
    def _select_fallback(
        ranked_results: list[MemoryRetrievalResult],
        plan: MemoryRetrievalPlan,
    ) -> MemoryRetrievalResult | None:
        for item in ranked_results:
            if float(item.score_breakdown.get("relevance", 0.0)) < plan.fallback_min_relevance_score:
                continue
            if int(plan.per_scope_top_k.get(item.scope_type, 0)) <= 0:
                continue
            return item
        return None

    @staticmethod
    def _drop(
        candidate: MemoryCandidate,
        *,
        reason: str,
        signal: MemoryRelevanceSignal,
    ) -> DroppedMemoryCandidate:
        return DroppedMemoryCandidate(
            memory_fact_id=candidate.memory_fact_id,
            scope_type=candidate.scope_type,
            scope_id=candidate.scope_id,
            type=candidate.type,
            content=candidate.content,
            drop_reason=reason,
            retrieval_score=signal.score,
            matched_reason=signal.matched_reason,
        )

    @staticmethod
    def _recency_score(updated_at: str, *, recent_window_days: int) -> float:
        try:
            parsed = datetime.fromisoformat(updated_at.replace("Z", "+00:00"))
        except ValueError:
            return 0.0

        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)

        age_days = max(
            (datetime.now(timezone.utc) - parsed.astimezone(timezone.utc)).total_seconds() / 86400.0,
            0.0,
        )
        if age_days <= 1:
            return 1.0
        if age_days <= recent_window_days / 4:
            return 0.82
        if age_days <= recent_window_days:
            return 0.62
        if age_days <= recent_window_days * 3:
            return 0.36
        return 0.16

    @staticmethod
    def _retention_value(candidate: MemoryCandidate) -> float:
        value_score = max(0.0, min(1.0, float(candidate.value_score or 0.0) / 100.0))
        visibility_modifier = 0.72 if candidate.retrieval_visibility == "deprioritized" else 1.0
        if candidate.forgetting_status == "cooling" and candidate.retrieval_visibility == "deprioritized":
            visibility_modifier *= 0.9
        return value_score * visibility_modifier
