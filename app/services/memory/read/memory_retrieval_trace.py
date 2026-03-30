"""Cheap, in-memory retrieval tracing for Aurora memory retrieval."""

from __future__ import annotations

from app.services.memory_retrieval_models import MemoryQuery, MemoryRetrievalBundle, MemoryRetrievalPlan


class RetrievalTraceService:
    """Build explainable trace payloads without adding I/O to the hot path."""

    def build_trace(
        self,
        *,
        query: MemoryQuery,
        plan: MemoryRetrievalPlan,
        bundle: MemoryRetrievalBundle,
        readable_candidate_count: int = 0,
        consistent_candidate_count: int = 0,
        consistency_dropped_count: int = 0,
        error: str = "",
    ) -> dict[str, object]:
        return {
            "scene": query.scene,
            "user_query": query.user_query,
            "retrieval_metadata": dict(query.retrieval_metadata),
            "allowed_scopes": [
                {"scope_type": item.scope_type, "scope_id": item.scope_id}
                for item in query.allowed_scopes
            ],
            "plan": {
                "enabled": plan.enabled,
                "enable_reason": plan.enable_reason,
                "top_k": plan.top_k,
                "candidate_limit": plan.candidate_limit,
                "per_scope_candidate_limit": plan.per_scope_candidate_limit,
                "retrieval_mode": plan.retrieval_mode,
                "scope_weights": dict(plan.scope_weights),
                "type_weights": dict(plan.type_weights),
                "per_scope_top_k": dict(plan.per_scope_top_k),
                "min_relevance_score": plan.min_relevance_score,
                "min_injection_score": plan.min_injection_score,
                "fallback_min_relevance_score": plan.fallback_min_relevance_score,
                "recent_window_days": plan.recent_window_days,
                "max_injection_chars_per_memory": plan.max_injection_chars_per_memory,
                "query_cues": list(plan.query_cues),
            },
            "summary": {
                "readable_candidate_count": readable_candidate_count,
                "consistent_candidate_count": consistent_candidate_count,
                "total_candidates": bundle.total_candidates,
                "total_selected": bundle.total_selected,
                "consistency_dropped_count": consistency_dropped_count,
                "selected_memory_ids": [item.memory_fact_id for item in bundle.selected_memories],
                "selected_context_chars": sum(len(item.content) for item in bundle.memory_context),
                "dropped_count": len(bundle.dropped_candidates),
                "error": error,
            },
            "selected": [
                {
                    "memory_fact_id": item.memory_fact_id,
                    "scope_type": item.scope_type,
                    "type": item.type,
                    "retrieval_score": item.retrieval_score,
                    "value_score": item.value_score,
                    "retention_level": item.retention_level,
                    "retrieval_visibility": item.retrieval_visibility,
                    "forgetting_status": item.forgetting_status,
                    "matched_reason": item.matched_reason,
                    "score_breakdown": dict(item.score_breakdown),
                }
                for item in bundle.selected_memories
            ],
            "dropped": [
                {
                    "memory_fact_id": item.memory_fact_id,
                    "scope_type": item.scope_type,
                    "type": item.type,
                    "drop_reason": item.drop_reason,
                    "retrieval_score": item.retrieval_score,
                    "matched_reason": item.matched_reason,
                }
                for item in bundle.dropped_candidates[:20]
            ],
        }
