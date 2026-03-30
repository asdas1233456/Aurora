"""Shared models for backend-only chat memory assimilation."""

from __future__ import annotations

from dataclasses import dataclass, field

from app.schemas import MemoryFactType, MemorySourceType, ScopeType


@dataclass(slots=True)
class ChatMemoryCandidate:
    """A bounded memory write candidate ready for governance validation."""

    content: str
    memory_type: MemoryFactType
    scope_type: ScopeType
    confirmed: bool = True
    source_kind: str = "memory_extraction"
    source_type: MemorySourceType = "user_confirmed"
    source_confidence: float = 1.0
    reviewed_by_human: bool | None = True
    subject_key: str | None = None
    fact_key: str | None = None
    origin: str = "rule"


@dataclass(slots=True)
class ChatMemoryAssimilationReport:
    """Write report used for logs, tests, and operational visibility."""

    persisted_memory_ids: list[str] = field(default_factory=list)
    operations: list[str] = field(default_factory=list)
    candidate_count: int = 0
    rule_candidate_count: int = 0
    llm_candidate_count: int = 0
    failed_candidate_count: int = 0
