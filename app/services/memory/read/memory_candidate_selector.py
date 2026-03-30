"""Candidate selection for Aurora memory retrieval."""

from __future__ import annotations

from app.config import AppConfig
from app.schemas import ResolvedScopeContext
from app.services.memory_access_policy import MemoryAccessPolicy
from app.services.memory_repository import MemoryRepository
from app.services.memory_retrieval_models import MemoryCandidate, MemoryQuery, MemoryRetrievalPlan


class MemoryCandidateSelector:
    """Read a bounded candidate set without mixing in ranking concerns."""

    def __init__(
        self,
        config: AppConfig,
        *,
        repository: MemoryRepository | None = None,
        access_policy: MemoryAccessPolicy | None = None,
    ) -> None:
        self._repository = repository or MemoryRepository(config)
        self._access_policy = access_policy or MemoryAccessPolicy()

    def select(
        self,
        resolved_context: ResolvedScopeContext,
        query: MemoryQuery,
        plan: MemoryRetrievalPlan,
    ) -> list[MemoryCandidate]:
        if not plan.enabled:
            return []

        candidates: list[MemoryCandidate] = []
        seen_ids: set[str] = set()

        # Query each allowed scope separately so recent session chatter cannot starve project/team facts
        # before the ranker gets a chance to compare them.
        for scope in query.allowed_scopes:
            facts = self._repository.list_by_filters(
                tenant_id=query.tenant_id,
                scope_type=scope.scope_type,
                scope_id=scope.scope_id,
                current_only=True,
                limit=plan.per_scope_candidate_limit,
            )
            for fact in facts:
                if fact.id in seen_ids:
                    continue
                if fact.status != "active" or fact.superseded_by:
                    continue
                if not self._access_policy.can_read(resolved_context, fact):
                    continue
                seen_ids.add(fact.id)
                candidates.append(MemoryCandidate.from_fact(fact))

        candidates.sort(
            key=lambda item: (item.updated_at, item.scope_type, item.memory_fact_id),
            reverse=True,
        )
        return candidates[: plan.candidate_limit]
