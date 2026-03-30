"""Rule-driven consistency checks before a memory fact is written."""

from __future__ import annotations

import sqlite3

from app.schemas import ConsistencyCheckResult, MemoryFact, MemoryFactCreate, ResolvedMemoryFactIdentity
from app.services.memory_repository import MemoryRepository


class ConsistencyChecker:
    """Classify incoming writes as insert/update/correction/conflict/coexist."""

    def __init__(self, repository: MemoryRepository) -> None:
        self._repository = repository

    def check(
        self,
        payload: MemoryFactCreate,
        identity: ResolvedMemoryFactIdentity,
        *,
        connection: sqlite3.Connection | None = None,
    ) -> ConsistencyCheckResult:
        current_fact = self._repository.get_current_effective_fact(
            tenant_id=payload.tenant_id,
            scope_type=payload.scope_type,
            scope_id=payload.scope_id,
            subject_key=identity.subject_key,
            fact_key=identity.fact_key,
            connection=connection,
        )
        related_active_facts = [
            item
            for item in self._repository.list_current_effective_by_group(
                tenant_id=payload.tenant_id,
                scope_type=payload.scope_type,
                scope_id=payload.scope_id,
                consistency_group_id=identity.consistency_group_id,
                connection=connection,
            )
            if current_fact is None or item.id != current_fact.id
        ]

        correction_target = None
        correction_of = (payload.correction_of or "").strip()
        if correction_of:
            correction_target = self._repository.get_memory_fact_by_id(correction_of, connection=connection)
            if correction_target is None or correction_target.tenant_id != payload.tenant_id:
                raise ValueError("correction_of points to a memory fact that does not exist in this tenant.")

        if correction_target is not None:
            return ConsistencyCheckResult(
                operation="correction",
                subject_key=identity.subject_key,
                fact_key=identity.fact_key,
                consistency_group_id=identity.consistency_group_id,
                status="active",
                reason="explicit correction replaces the incorrect historical value",
                current_fact=current_fact,
                correction_target=correction_target,
                related_active_facts=related_active_facts,
            )

        if current_fact is None:
            if related_active_facts and identity.allows_coexistence:
                return ConsistencyCheckResult(
                    operation="coexist",
                    subject_key=identity.subject_key,
                    fact_key=identity.fact_key,
                    consistency_group_id=identity.consistency_group_id,
                    status="active",
                    reason="fact family allows multiple active values, so the new fact can coexist",
                    related_active_facts=related_active_facts,
                )
            if related_active_facts:
                return ConsistencyCheckResult(
                    operation="conflict",
                    subject_key=identity.subject_key,
                    fact_key=identity.fact_key,
                    consistency_group_id=identity.consistency_group_id,
                    status="conflict_pending_review",
                    reason="related active facts already exist and the write cannot be auto-classified safely",
                    related_active_facts=related_active_facts,
                )
            return ConsistencyCheckResult(
                operation="insert",
                subject_key=identity.subject_key,
                fact_key=identity.fact_key,
                consistency_group_id=identity.consistency_group_id,
                status="active",
                reason="no current effective version exists for this fact identity",
            )

        if payload.supersedes and payload.supersedes != current_fact.id:
            return ConsistencyCheckResult(
                operation="conflict",
                subject_key=identity.subject_key,
                fact_key=identity.fact_key,
                consistency_group_id=identity.consistency_group_id,
                status="conflict_pending_review",
                reason="supersedes points to a non-current version, so the write needs manual review",
                current_fact=current_fact,
                related_active_facts=related_active_facts,
            )

        if self._same_content(current_fact.content, payload.content):
            if self._incoming_priority(identity) > self._existing_priority(current_fact):
                return ConsistencyCheckResult(
                    operation="update",
                    subject_key=identity.subject_key,
                    fact_key=identity.fact_key,
                    consistency_group_id=identity.consistency_group_id,
                    status="active",
                    reason="incoming fact refreshes the current value with a more trusted source",
                    current_fact=current_fact,
                    related_active_facts=related_active_facts,
                )
            return ConsistencyCheckResult(
                operation="noop",
                subject_key=identity.subject_key,
                fact_key=identity.fact_key,
                consistency_group_id=identity.consistency_group_id,
                status="active",
                reason="incoming fact matches the current effective value and does not improve trust",
                current_fact=current_fact,
                related_active_facts=related_active_facts,
            )

        if self._should_replace(current_fact, identity):
            return ConsistencyCheckResult(
                operation="update",
                subject_key=identity.subject_key,
                fact_key=identity.fact_key,
                consistency_group_id=identity.consistency_group_id,
                status="active",
                reason="incoming fact is trusted enough to replace the current effective version",
                current_fact=current_fact,
                related_active_facts=related_active_facts,
            )

        return ConsistencyCheckResult(
            operation="conflict",
            subject_key=identity.subject_key,
            fact_key=identity.fact_key,
            consistency_group_id=identity.consistency_group_id,
            status="conflict_pending_review",
            reason="current and incoming values disagree, but replacement confidence is not decisive",
            current_fact=current_fact,
            related_active_facts=related_active_facts,
        )

    @staticmethod
    def _same_content(left: str, right: str) -> bool:
        return " ".join(str(left or "").split()).strip().lower() == " ".join(str(right or "").split()).strip().lower()

    def _should_replace(self, current_fact: MemoryFact, identity: ResolvedMemoryFactIdentity) -> bool:
        return self._incoming_priority(identity) > self._existing_priority(current_fact)

    @staticmethod
    def _incoming_priority(identity: ResolvedMemoryFactIdentity) -> float:
        return _source_priority(
            identity.source_type,
            identity.source_confidence,
            identity.reviewed_by_human,
        )

    @staticmethod
    def _existing_priority(memory_fact: MemoryFact) -> float:
        return _source_priority(
            memory_fact.source_type,
            memory_fact.source_confidence,
            memory_fact.reviewed_by_human,
        )


def _source_priority(source_type: str, source_confidence: float, reviewed_by_human: bool | None) -> float:
    base_priority = {
        "user_confirmed": 4.0,
        "imported": 3.0,
        "system_generated": 2.0,
        "model_inferred": 1.0,
    }.get(str(source_type or "").strip(), 1.0)
    review_boost = 0.5 if reviewed_by_human else 0.0
    return base_priority + review_boost + max(0.0, min(1.0, float(source_confidence or 0.0))) / 10.0
