"""Scene-aware policy definitions for Aurora memory retrieval."""

from __future__ import annotations

from dataclasses import dataclass

from app.schemas import BusinessScene, MemoryFactType, ScopeType
from app.services.memory_retrieval_models import RetrievalMode


DEFAULT_SCOPE_WEIGHTS: dict[ScopeType, float] = {
    "session": 1.0,
    "user": 0.82,
    "project": 0.72,
    "team": 0.56,
    "global": 0.42,
}

DEFAULT_TYPE_WEIGHTS: dict[MemoryFactType, float] = {
    "fact": 1.0,
    "decision": 0.9,
    "pending_issue": 0.8,
    "preference": 0.55,
}

DEFAULT_PER_SCOPE_TOP_K: dict[ScopeType, int] = {
    "session": 2,
    "user": 1,
    "project": 2,
    "team": 1,
    "global": 1,
}


@dataclass(frozen=True, slots=True)
class ScenePolicy:
    """Ranking priors for a single business scene."""

    scene: BusinessScene
    scope_weights: dict[ScopeType, float]
    type_weights: dict[MemoryFactType, float]
    per_scope_top_k: dict[ScopeType, int]
    default_top_k: int
    candidate_limit: int
    min_relevance_score: float
    min_injection_score: float
    fallback_min_relevance_score: float
    recent_window_days: int
    max_injection_chars_per_memory: int
    default_retrieval_mode: RetrievalMode

    def scope_weight(self, scope_type: ScopeType) -> float:
        return float(self.scope_weights.get(scope_type, 0.0))

    def type_weight(self, memory_type: MemoryFactType) -> float:
        return float(self.type_weights.get(memory_type, 0.0))

    def allows_type(self, memory_type: MemoryFactType) -> bool:
        return self.type_weight(memory_type) > 0.0


class ScopeWeightPolicy:
    """Resolve default scope priors first, then apply scene-specific overrides."""

    def __init__(
        self,
        default_weights: dict[ScopeType, float] | None = None,
        scene_overrides: dict[BusinessScene, dict[ScopeType, float]] | None = None,
    ) -> None:
        self._default_weights = dict(default_weights or DEFAULT_SCOPE_WEIGHTS)
        self._scene_overrides = scene_overrides or {
            "qa_query": {},
            "troubleshooting": {
                "session": 0.86,
                "user": 0.58,
                "project": 0.98,
                "team": 0.62,
                "global": 0.40,
            },
            "onboarding": {
                "session": 0.66,
                "user": 0.60,
                "project": 1.0,
                "team": 0.90,
                "global": 0.52,
            },
            "command_lookup": {
                "session": 0.74,
                "user": 0.54,
                "project": 0.94,
                "team": 0.58,
                "global": 0.46,
            },
        }

    def resolve(self, scene: BusinessScene) -> dict[ScopeType, float]:
        weights = dict(self._default_weights)
        weights.update(self._scene_overrides.get(scene, {}))
        return weights


def build_scene_policy(
    scene: BusinessScene,
    *,
    scope_weight_policy: ScopeWeightPolicy | None = None,
) -> ScenePolicy:
    scope_policy = scope_weight_policy or ScopeWeightPolicy()
    scene_configs: dict[BusinessScene, dict[str, object]] = {
        "qa_query": {
            "type_weights": {
                "fact": 1.0,
                "decision": 0.88,
                "pending_issue": 0.40,
                "preference": 0.30,
            },
            "default_top_k": 2,
            "candidate_limit": 12,
            "min_relevance_score": 0.16,
            "min_injection_score": 0.46,
            "fallback_min_relevance_score": 0.22,
            "recent_window_days": 21,
            "max_injection_chars_per_memory": 220,
            "default_retrieval_mode": "ranked",
        },
        "troubleshooting": {
            "type_weights": {
                "fact": 0.92,
                "decision": 0.86,
                "pending_issue": 1.0,
                "preference": 0.18,
            },
            "default_top_k": 4,
            "candidate_limit": 18,
            "min_relevance_score": 0.12,
            "min_injection_score": 0.36,
            "fallback_min_relevance_score": 0.20,
            "recent_window_days": 14,
            "max_injection_chars_per_memory": 260,
            "default_retrieval_mode": "ranked_with_fallback",
        },
        "onboarding": {
            "type_weights": {
                "fact": 0.92,
                "decision": 1.0,
                "pending_issue": 0.44,
                "preference": 0.56,
            },
            "default_top_k": 4,
            "candidate_limit": 16,
            "min_relevance_score": 0.10,
            "min_injection_score": 0.34,
            "fallback_min_relevance_score": 0.18,
            "recent_window_days": 45,
            "max_injection_chars_per_memory": 260,
            "default_retrieval_mode": "ranked_with_fallback",
        },
        "command_lookup": {
            "type_weights": {
                "fact": 1.0,
                "decision": 0.84,
                "pending_issue": 0.36,
                "preference": 0.12,
            },
            "default_top_k": 2,
            "candidate_limit": 12,
            "min_relevance_score": 0.18,
            "min_injection_score": 0.48,
            "fallback_min_relevance_score": 0.24,
            "recent_window_days": 14,
            "max_injection_chars_per_memory": 200,
            "default_retrieval_mode": "ranked",
        },
    }
    config = scene_configs[scene]
    return ScenePolicy(
        scene=scene,
        scope_weights=scope_policy.resolve(scene),
        type_weights=dict(config["type_weights"]),
        per_scope_top_k=dict(DEFAULT_PER_SCOPE_TOP_K),
        default_top_k=int(config["default_top_k"]),
        candidate_limit=int(config["candidate_limit"]),
        min_relevance_score=float(config["min_relevance_score"]),
        min_injection_score=float(config["min_injection_score"]),
        fallback_min_relevance_score=float(config["fallback_min_relevance_score"]),
        recent_window_days=int(config["recent_window_days"]),
        max_injection_chars_per_memory=int(config["max_injection_chars_per_memory"]),
        default_retrieval_mode=config["default_retrieval_mode"],
    )
