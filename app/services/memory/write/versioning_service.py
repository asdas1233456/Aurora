"""Version and supersession handling for governed memory facts."""

from __future__ import annotations

import sqlite3

from app.schemas import ConsistencyCheckResult, MemoryFact, MemoryFactCreate, ResolvedMemoryFactIdentity
from app.services.memory_repository import MemoryRepository


class VersioningService:
    """Assign versions and maintain supersedes/superseded_by links."""

    def __init__(self, repository: MemoryRepository) -> None:
        self._repository = repository

    def build_versioned_payload(
        self,
        payload: MemoryFactCreate,
        identity: ResolvedMemoryFactIdentity,
        check_result: ConsistencyCheckResult,
    ) -> MemoryFactCreate:
        base_fact = self._base_fact_for_version(check_result)
        next_version = (base_fact.version + 1) if base_fact is not None else 1
        supersedes = None
        correction_of = payload.correction_of

        if check_result.operation == "update" and check_result.current_fact is not None:
            supersedes = check_result.current_fact.id
        elif check_result.operation == "correction":
            correction_target = check_result.correction_target
            correction_of = correction_target.id if correction_target is not None else payload.correction_of
            if check_result.current_fact is not None:
                supersedes = check_result.current_fact.id
            elif correction_target is not None:
                supersedes = correction_target.id

        return MemoryFactCreate(
            tenant_id=payload.tenant_id,
            owner_user_id=payload.owner_user_id,
            project_id=payload.project_id,
            scope_type=payload.scope_type,
            scope_id=payload.scope_id,
            type=payload.type,
            content=payload.content,
            source_session_id=payload.source_session_id,
            status=check_result.status,
            source_kind=payload.source_kind,
            confirmed=payload.confirmed,
            subject_key=identity.subject_key,
            fact_key=identity.fact_key,
            version=next_version,
            supersedes=supersedes,
            correction_of=correction_of,
            source_type=identity.source_type,
            source_confidence=identity.source_confidence,
            reviewed_by_human=identity.reviewed_by_human,
            consistency_group_id=identity.consistency_group_id,
        )

    def apply_supersession(
        self,
        replacement_fact_id: str,
        check_result: ConsistencyCheckResult,
        *,
        connection: sqlite3.Connection | None = None,
        now: str | None = None,
    ) -> list[str]:
        superseded_ids: list[str] = []
        target = self._current_target_for_supersession(check_result)
        if target is None:
            return superseded_ids

        updated_target = self._repository.update_memory_fact_status(
            target.id,
            "superseded",
            superseded_by=replacement_fact_id,
            connection=connection,
            now=now,
        )
        if updated_target is not None:
            superseded_ids.append(updated_target.id)
        return superseded_ids

    @staticmethod
    def _base_fact_for_version(check_result: ConsistencyCheckResult) -> MemoryFact | None:
        if check_result.current_fact is not None:
            return check_result.current_fact
        if check_result.correction_target is not None:
            return check_result.correction_target
        return None

    @staticmethod
    def _current_target_for_supersession(check_result: ConsistencyCheckResult) -> MemoryFact | None:
        if check_result.operation not in {"update", "correction"}:
            return None
        if check_result.current_fact is not None:
            return check_result.current_fact
        return check_result.correction_target
