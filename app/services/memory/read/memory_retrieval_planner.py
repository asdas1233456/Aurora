"""Rule-driven planner for Aurora's scene-aware memory retrieval."""

from __future__ import annotations

from app.schemas import BusinessScene
from app.services.capability_guard import infer_scene
from app.services.memory_retrieval_models import MemoryQuery, MemoryRetrievalPlan
from app.services.memory_scene_policy import ScenePolicy, build_scene_policy


_CONTEXTUAL_MARKERS = (
    "current",
    "currently",
    "session",
    "project",
    "team",
    "our",
    "we",
    "this",
    "that",
    "之前",
    "当前",
    "本次",
    "这次",
    "我们",
    "团队",
    "项目",
    "偏好",
    "历史",
    "上下文",
)


class RetrievalPlanner:
    """Translate a user request into a bounded, explainable retrieval plan."""

    def resolve_scene(self, requested_scene: str | None, user_query: str) -> BusinessScene:
        normalized = str(requested_scene or "").strip()
        if normalized in {"qa_query", "troubleshooting", "onboarding", "command_lookup"}:
            return normalized  # type: ignore[return-value]
        return infer_scene(user_query)

    def build_scene_policy(self, scene: BusinessScene) -> ScenePolicy:
        return build_scene_policy(scene)

    def plan(self, query: MemoryQuery, policy: ScenePolicy) -> MemoryRetrievalPlan:
        top_k = max(1, min(int(query.top_k or policy.default_top_k), policy.default_top_k))
        scope_count = max(len(query.allowed_scopes), 1)
        per_scope_candidate_limit = max(
            2,
            min(policy.candidate_limit, (policy.candidate_limit // scope_count) + 1),
        )
        query_cues = self._collect_query_cues(query.user_query)

        enabled = bool(query.allowed_scopes)
        enable_reason = "allowed_scopes_available"
        if not query.allowed_scopes:
            enable_reason = "no_allowed_scopes"
        elif not str(query.user_query or "").strip() and query.retrieval_mode != "exact_scope_only":
            enabled = False
            enable_reason = "empty_user_query"
        elif query_cues:
            enable_reason = "scene_and_contextual_signal"
        elif query.scene in {"troubleshooting", "onboarding"}:
            enable_reason = "scene_requires_memory_support"
        else:
            enable_reason = "scene_allows_ranked_memory"

        candidate_limit = max(policy.candidate_limit, top_k * 4)
        if query.scene in {"qa_query", "command_lookup"} and not query_cues:
            # General QA and command lookup keep memory as a small augmentation unless the query
            # clearly asks about session/project-specific context.
            candidate_limit = min(candidate_limit, max(top_k * 3, 8))

        return MemoryRetrievalPlan(
            scene=query.scene,
            enabled=enabled,
            enable_reason=enable_reason,
            top_k=top_k,
            candidate_limit=candidate_limit,
            per_scope_candidate_limit=per_scope_candidate_limit,
            retrieval_mode=query.retrieval_mode,
            scope_weights=dict(policy.scope_weights),
            type_weights=dict(policy.type_weights),
            per_scope_top_k=dict(policy.per_scope_top_k),
            min_relevance_score=policy.min_relevance_score,
            min_injection_score=policy.min_injection_score,
            fallback_min_relevance_score=policy.fallback_min_relevance_score,
            recent_window_days=policy.recent_window_days,
            max_injection_chars_per_memory=policy.max_injection_chars_per_memory,
            query_cues=query_cues,
        )

    @staticmethod
    def _collect_query_cues(user_query: str) -> tuple[str, ...]:
        normalized = str(user_query or "").strip().lower()
        if not normalized:
            return ()
        cues = [marker for marker in _CONTEXTUAL_MARKERS if marker in normalized]
        return tuple(dict.fromkeys(cues))
