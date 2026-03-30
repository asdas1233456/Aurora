"""Contracts for Aurora's scene-aware memory retrieval pipeline."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from app.schemas import (
    BusinessScene,
    ForgettingStatus,
    MemoryContextItem,
    MemoryFact,
    MemoryFactType,
    MemorySourceType,
    RetentionLevel,
    RetrievalVisibility,
    ScopeRef,
    ScopeType,
)


RetrievalMode = Literal["exact_scope_only", "ranked", "ranked_with_fallback"]


@dataclass(slots=True)
class MemoryQuery:
    """Normalized retrieval request used inside the memory pipeline only."""

    tenant_id: str
    user_id: str
    project_id: str
    session_id: str
    scene: BusinessScene
    user_query: str
    allowed_scopes: tuple[ScopeRef, ...]
    top_k: int
    retrieval_mode: RetrievalMode = "ranked"
    retrieval_metadata: dict[str, object] = field(default_factory=dict)


@dataclass(slots=True)
class MemoryRetrievalPlan:
    """Planner output that keeps the hot path rule-driven and explainable."""

    scene: BusinessScene
    enabled: bool
    enable_reason: str
    top_k: int
    candidate_limit: int
    per_scope_candidate_limit: int
    retrieval_mode: RetrievalMode
    scope_weights: dict[ScopeType, float]
    type_weights: dict[MemoryFactType, float]
    per_scope_top_k: dict[ScopeType, int]
    min_relevance_score: float
    min_injection_score: float
    fallback_min_relevance_score: float
    recent_window_days: int
    max_injection_chars_per_memory: int
    query_cues: tuple[str, ...] = ()


@dataclass(slots=True)
class MemoryCandidate:
    """A readable candidate that survived scope and current-version filtering."""

    memory_fact_id: str
    scope_type: ScopeType
    scope_id: str
    type: MemoryFactType
    content: str
    source_session_id: str
    updated_at: str
    source_confidence: float
    subject_key: str = ""
    fact_key: str = ""
    version: int = 1
    source_type: MemorySourceType = "system_generated"
    created_at: str = ""
    value_score: float = 0.0
    retention_level: RetentionLevel = "normal"
    retrieval_visibility: RetrievalVisibility = "normal"
    forgetting_status: ForgettingStatus = "none"
    access_count: int = 0
    successful_use_count: int = 0
    last_accessed_at: str | None = None
    memory_fact: MemoryFact | None = field(default=None, repr=False)

    @classmethod
    def from_fact(cls, memory_fact: MemoryFact) -> "MemoryCandidate":
        return cls(
            memory_fact_id=memory_fact.id,
            scope_type=memory_fact.scope_type,
            scope_id=memory_fact.scope_id,
            type=memory_fact.type,
            content=memory_fact.content,
            source_session_id=memory_fact.source_session_id,
            updated_at=memory_fact.updated_at,
            source_confidence=float(memory_fact.source_confidence or 0.0),
            subject_key=memory_fact.subject_key,
            fact_key=memory_fact.fact_key,
            version=int(memory_fact.version or 1),
            source_type=memory_fact.source_type,
            created_at=memory_fact.created_at,
            value_score=float(memory_fact.value_score or 0.0),
            retention_level=memory_fact.retention_level,
            retrieval_visibility=memory_fact.retrieval_visibility,
            forgetting_status=memory_fact.forgetting_status,
            access_count=int(memory_fact.access_count or 0),
            successful_use_count=int(memory_fact.successful_use_count or 0),
            last_accessed_at=memory_fact.last_accessed_at,
            memory_fact=memory_fact,
        )


@dataclass(slots=True)
class MemoryRelevanceSignal:
    """Lightweight lexical relevance result used by the ranker."""

    score: float
    matched_reason: str = ""
    matched_terms: tuple[str, ...] = ()


@dataclass(slots=True)
class DroppedMemoryCandidate:
    """Trace-friendly dropped candidate record."""

    memory_fact_id: str
    scope_type: ScopeType
    scope_id: str
    type: MemoryFactType
    content: str
    drop_reason: str
    retrieval_score: float = 0.0
    matched_reason: str = ""


@dataclass(slots=True)
class MemoryRetrievalResult:
    """Ranked candidate that can still be dropped before final injection."""

    memory_fact_id: str
    scope_type: ScopeType
    scope_id: str
    type: MemoryFactType
    content: str
    retrieval_score: float
    matched_reason: str = ""
    selected_for_injection: bool = False
    source_session_id: str = ""
    updated_at: str = ""
    source_confidence: float = 0.0
    subject_key: str = ""
    fact_key: str = ""
    version: int = 1
    source_type: MemorySourceType = "system_generated"
    value_score: float = 0.0
    retention_level: RetentionLevel = "normal"
    retrieval_visibility: RetrievalVisibility = "normal"
    forgetting_status: ForgettingStatus = "none"
    score_breakdown: dict[str, float] = field(default_factory=dict)
    rank: int = 0
    memory_fact: MemoryFact | None = field(default=None, repr=False)


@dataclass(slots=True)
class MemoryRetrievalBundle:
    """Result bundle consumed by upper layers instead of raw repository rows."""

    selected_memories: list[MemoryRetrievalResult]
    dropped_candidates: list[DroppedMemoryCandidate]
    total_candidates: int
    total_selected: int
    retrieval_trace: dict[str, object] | None = None
    retrieval_plan: MemoryRetrievalPlan | None = None
    memory_context: list[MemoryContextItem] = field(default_factory=list)

    def selected_facts(self) -> list[MemoryFact]:
        return [
            item.memory_fact
            for item in self.selected_memories
            if item.memory_fact is not None
        ]
