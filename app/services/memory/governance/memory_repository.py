"""Data access for Aurora memory facts."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from uuid import uuid4

from app.config import AppConfig
from app.schemas import MemoryFact, MemoryFactCreate, ScopeRef
from app.services.persistence_utils import utc_now_iso
from app.services.storage_service import connect_state_db


_UNSET = object()
_MEMORY_FACT_COLUMNS = """
id, tenant_id, owner_user_id, project_id, scope_type, scope_id,
type, content, status, source_session_id, created_at, updated_at,
subject_key, fact_key, version, superseded_by, supersedes, correction_of,
source_type, source_confidence, reviewed_by_human, consistency_group_id,
value_score, retention_level, ttl_seconds, expires_at, last_accessed_at,
access_count, successful_use_count, decay_factor, archived_at,
retrieval_visibility, forgetting_status, next_evaluation_at,
retention_policy_id, archive_bucket
"""


class MemoryRepository:
    """Repository focused on memory_facts table access only."""

    def __init__(self, config: AppConfig) -> None:
        self._config = config

    def create_memory_fact(
        self,
        payload: MemoryFactCreate,
        *,
        connection: sqlite3.Connection | None = None,
        memory_fact_id: str | None = None,
        now: str | None = None,
    ) -> MemoryFact:
        memory_fact_id = memory_fact_id or str(uuid4())
        now = now or utc_now_iso()
        normalized_payload = self._normalize_create_payload(payload, memory_fact_id)

        with self._connection_scope(connection) as active_connection:
            active_connection.execute(
                """
                INSERT INTO memory_facts (
                    id, tenant_id, owner_user_id, project_id, scope_type, scope_id,
                    type, content, status, source_session_id, created_at, updated_at,
                    subject_key, fact_key, version, superseded_by, supersedes, correction_of,
                    source_type, source_confidence, reviewed_by_human, consistency_group_id,
                    value_score, retention_level, ttl_seconds, expires_at, last_accessed_at,
                    access_count, successful_use_count, decay_factor, archived_at,
                    retrieval_visibility, forgetting_status, next_evaluation_at,
                    retention_policy_id, archive_bucket
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    memory_fact_id,
                    normalized_payload.tenant_id,
                    normalized_payload.owner_user_id,
                    normalized_payload.project_id,
                    normalized_payload.scope_type,
                    normalized_payload.scope_id,
                    normalized_payload.type,
                    normalized_payload.content,
                    normalized_payload.status,
                    normalized_payload.source_session_id,
                    now,
                    now,
                    normalized_payload.subject_key,
                    normalized_payload.fact_key,
                    normalized_payload.version,
                    normalized_payload.superseded_by,
                    normalized_payload.supersedes,
                    normalized_payload.correction_of,
                    normalized_payload.source_type,
                    normalized_payload.source_confidence,
                    _bool_to_db(normalized_payload.reviewed_by_human),
                    normalized_payload.consistency_group_id,
                    normalized_payload.value_score,
                    normalized_payload.retention_level,
                    normalized_payload.ttl_seconds,
                    normalized_payload.expires_at,
                    normalized_payload.last_accessed_at,
                    normalized_payload.access_count,
                    normalized_payload.successful_use_count,
                    normalized_payload.decay_factor,
                    normalized_payload.archived_at,
                    normalized_payload.retrieval_visibility,
                    normalized_payload.forgetting_status,
                    normalized_payload.next_evaluation_at,
                    normalized_payload.retention_policy_id,
                    normalized_payload.archive_bucket,
                ),
            )

        return MemoryFact(
            id=memory_fact_id,
            tenant_id=normalized_payload.tenant_id,
            owner_user_id=normalized_payload.owner_user_id,
            project_id=normalized_payload.project_id,
            scope_type=normalized_payload.scope_type,
            scope_id=normalized_payload.scope_id,
            type=normalized_payload.type,
            content=normalized_payload.content,
            status=normalized_payload.status,
            source_session_id=normalized_payload.source_session_id,
            created_at=now,
            updated_at=now,
            subject_key=normalized_payload.subject_key or "",
            fact_key=normalized_payload.fact_key or "",
            version=int(normalized_payload.version or 1),
            superseded_by=normalized_payload.superseded_by,
            supersedes=normalized_payload.supersedes,
            correction_of=normalized_payload.correction_of,
            source_type=normalized_payload.source_type or "system_generated",
            source_confidence=float(normalized_payload.source_confidence or 0.0),
            reviewed_by_human=normalized_payload.reviewed_by_human,
            consistency_group_id=normalized_payload.consistency_group_id,
            value_score=float(normalized_payload.value_score or 0.0),
            retention_level=normalized_payload.retention_level or "normal",
            ttl_seconds=normalized_payload.ttl_seconds,
            expires_at=normalized_payload.expires_at,
            last_accessed_at=normalized_payload.last_accessed_at,
            access_count=int(normalized_payload.access_count or 0),
            successful_use_count=int(normalized_payload.successful_use_count or 0),
            decay_factor=float(normalized_payload.decay_factor or 1.0),
            archived_at=normalized_payload.archived_at,
            retrieval_visibility=normalized_payload.retrieval_visibility or "normal",
            forgetting_status=normalized_payload.forgetting_status or "none",
            next_evaluation_at=normalized_payload.next_evaluation_at,
            retention_policy_id=normalized_payload.retention_policy_id,
            archive_bucket=normalized_payload.archive_bucket,
        )

    def get_memory_fact_by_id(
        self,
        memory_fact_id: str,
        *,
        connection: sqlite3.Connection | None = None,
    ) -> MemoryFact | None:
        with self._connection_scope(connection) as active_connection:
            row = active_connection.execute(
                """
                SELECT
                    """
                + _MEMORY_FACT_COLUMNS
                + """
                FROM memory_facts
                WHERE id = ?
                """,
                (memory_fact_id,),
            ).fetchone()

        return self._row_to_memory_fact(row) if row is not None else None

    def list_active_by_scopes(
        self,
        *,
        tenant_id: str,
        scopes: tuple[ScopeRef, ...],
        limit: int = 5,
        connection: sqlite3.Connection | None = None,
    ) -> list[MemoryFact]:
        if not scopes:
            return []

        scope_sql = " OR ".join("(scope_type = ? AND scope_id = ?)" for _ in scopes)
        parameters: list[object] = [tenant_id]
        for scope in scopes:
            parameters.extend((scope.scope_type, scope.scope_id))
        parameters.append(limit)

        with self._connection_scope(connection) as active_connection:
            rows = active_connection.execute(
                f"""
                SELECT
                    {_MEMORY_FACT_COLUMNS}
                FROM memory_facts
                WHERE tenant_id = ?
                  AND status = 'active'
                  AND COALESCE(superseded_by, '') = ''
                  AND ({scope_sql})
                ORDER BY updated_at DESC, created_at DESC
                LIMIT ?
                """,
                tuple(parameters),
            ).fetchall()

        return [self._row_to_memory_fact(row) for row in rows]

    def list_by_filters(
        self,
        *,
        tenant_id: str,
        scope_type: str | None = None,
        scope_id: str | None = None,
        owner_user_id: str | None = None,
        project_id: str | None = None,
        source_session_id: str | None = None,
        status: str | None = None,
        subject_key: str | None = None,
        fact_key: str | None = None,
        consistency_group_id: str | None = None,
        retrieval_visibility: str | None = None,
        forgetting_status: str | None = None,
        current_only: bool = False,
        limit: int = 20,
        connection: sqlite3.Connection | None = None,
    ) -> list[MemoryFact]:
        conditions = ["tenant_id = ?"]
        parameters: list[object] = [tenant_id]

        if scope_type:
            conditions.append("scope_type = ?")
            parameters.append(scope_type)
        if scope_id:
            conditions.append("scope_id = ?")
            parameters.append(scope_id)
        if owner_user_id:
            conditions.append("owner_user_id = ?")
            parameters.append(owner_user_id)
        if project_id:
            conditions.append("project_id = ?")
            parameters.append(project_id)
        if source_session_id:
            conditions.append("source_session_id = ?")
            parameters.append(source_session_id)
        if status:
            conditions.append("status = ?")
            parameters.append(status)
        if subject_key:
            conditions.append("subject_key = ?")
            parameters.append(subject_key)
        if fact_key:
            conditions.append("fact_key = ?")
            parameters.append(fact_key)
        if consistency_group_id:
            conditions.append("consistency_group_id = ?")
            parameters.append(consistency_group_id)
        if retrieval_visibility:
            conditions.append("retrieval_visibility = ?")
            parameters.append(retrieval_visibility)
        if forgetting_status:
            conditions.append("forgetting_status = ?")
            parameters.append(forgetting_status)
        if current_only:
            conditions.append("status = 'active'")
            conditions.append("COALESCE(superseded_by, '') = ''")

        parameters.append(limit)

        with self._connection_scope(connection) as active_connection:
            rows = active_connection.execute(
                f"""
                SELECT
                    {_MEMORY_FACT_COLUMNS}
                FROM memory_facts
                WHERE {' AND '.join(conditions)}
                ORDER BY version DESC, updated_at DESC, created_at DESC
                LIMIT ?
                """,
                tuple(parameters),
            ).fetchall()

        return [self._row_to_memory_fact(row) for row in rows]

    def get_current_effective_fact(
        self,
        *,
        tenant_id: str,
        scope_type: str,
        scope_id: str,
        subject_key: str,
        fact_key: str,
        connection: sqlite3.Connection | None = None,
    ) -> MemoryFact | None:
        with self._connection_scope(connection) as active_connection:
            row = active_connection.execute(
                """
                SELECT
                    """
                + _MEMORY_FACT_COLUMNS
                + """
                FROM memory_facts
                WHERE tenant_id = ?
                  AND scope_type = ?
                  AND scope_id = ?
                  AND subject_key = ?
                  AND fact_key = ?
                  AND status = 'active'
                  AND COALESCE(superseded_by, '') = ''
                ORDER BY version DESC, updated_at DESC, created_at DESC
                LIMIT 1
                """,
                (tenant_id, scope_type, scope_id, subject_key, fact_key),
            ).fetchone()

        return self._row_to_memory_fact(row) if row is not None else None

    def list_current_effective_by_group(
        self,
        *,
        tenant_id: str,
        scope_type: str,
        scope_id: str,
        consistency_group_id: str,
        connection: sqlite3.Connection | None = None,
    ) -> list[MemoryFact]:
        with self._connection_scope(connection) as active_connection:
            rows = active_connection.execute(
                """
                SELECT
                    """
                + _MEMORY_FACT_COLUMNS
                + """
                FROM memory_facts
                WHERE tenant_id = ?
                  AND scope_type = ?
                  AND scope_id = ?
                  AND consistency_group_id = ?
                  AND status = 'active'
                  AND COALESCE(superseded_by, '') = ''
                ORDER BY updated_at DESC, created_at DESC
                """,
                (tenant_id, scope_type, scope_id, consistency_group_id),
            ).fetchall()

        return [self._row_to_memory_fact(row) for row in rows]

    def update_memory_fact_status(
        self,
        memory_fact_id: str,
        status: str,
        *,
        superseded_by: str | None | object = _UNSET,
        connection: sqlite3.Connection | None = None,
        now: str | None = None,
    ) -> MemoryFact | None:
        now = now or utc_now_iso()
        set_clauses = ["status = ?", "updated_at = ?"]
        parameters: list[object] = [status, now]

        if superseded_by is not _UNSET:
            set_clauses.append("superseded_by = ?")
            parameters.append(_normalize_optional_text(superseded_by))

        parameters.append(memory_fact_id)

        with self._connection_scope(connection) as active_connection:
            active_connection.execute(
                f"""
                UPDATE memory_facts
                SET {', '.join(set_clauses)}
                WHERE id = ?
                """,
                tuple(parameters),
            )
            row = active_connection.execute(
                """
                SELECT
                    """
                + _MEMORY_FACT_COLUMNS
                + """
                FROM memory_facts
                WHERE id = ?
                """,
                (memory_fact_id,),
            ).fetchone()

        return self._row_to_memory_fact(row) if row is not None else None

    def update_retention_state(
        self,
        memory_fact_id: str,
        *,
        value_score: float | object = _UNSET,
        retention_level: str | object = _UNSET,
        ttl_seconds: int | None | object = _UNSET,
        expires_at: str | None | object = _UNSET,
        last_accessed_at: str | None | object = _UNSET,
        access_count: int | object = _UNSET,
        successful_use_count: int | object = _UNSET,
        decay_factor: float | object = _UNSET,
        archived_at: str | None | object = _UNSET,
        retrieval_visibility: str | object = _UNSET,
        forgetting_status: str | object = _UNSET,
        next_evaluation_at: str | None | object = _UNSET,
        retention_policy_id: str | None | object = _UNSET,
        archive_bucket: str | None | object = _UNSET,
        connection: sqlite3.Connection | None = None,
    ) -> MemoryFact | None:
        field_map = {
            "value_score": value_score,
            "retention_level": retention_level,
            "ttl_seconds": ttl_seconds,
            "expires_at": expires_at,
            "last_accessed_at": last_accessed_at,
            "access_count": access_count,
            "successful_use_count": successful_use_count,
            "decay_factor": decay_factor,
            "archived_at": archived_at,
            "retrieval_visibility": retrieval_visibility,
            "forgetting_status": forgetting_status,
            "next_evaluation_at": next_evaluation_at,
            "retention_policy_id": retention_policy_id,
            "archive_bucket": archive_bucket,
        }
        set_clauses: list[str] = []
        parameters: list[object] = []
        for column_name, value in field_map.items():
            if value is _UNSET:
                continue
            set_clauses.append(f"{column_name} = ?")
            if column_name in {
                "expires_at",
                "last_accessed_at",
                "archived_at",
                "next_evaluation_at",
                "retention_policy_id",
                "archive_bucket",
            }:
                parameters.append(_normalize_optional_text(value))
            elif column_name in {"retention_level", "retrieval_visibility", "forgetting_status"}:
                parameters.append(str(value))
            elif column_name in {"value_score", "decay_factor"}:
                parameters.append(float(value))
            else:
                parameters.append(value)

        if not set_clauses:
            return self.get_memory_fact_by_id(memory_fact_id, connection=connection)
        parameters.append(memory_fact_id)

        with self._connection_scope(connection) as active_connection:
            active_connection.execute(
                f"""
                UPDATE memory_facts
                SET {', '.join(set_clauses)}
                WHERE id = ?
                """,
                tuple(parameters),
            )
            row = active_connection.execute(
                """
                SELECT
                    """
                + _MEMORY_FACT_COLUMNS
                + """
                FROM memory_facts
                WHERE id = ?
                """,
                (memory_fact_id,),
            ).fetchone()

        return self._row_to_memory_fact(row) if row is not None else None

    def touch_memory_facts(
        self,
        memory_fact_ids: list[str],
        *,
        connection: sqlite3.Connection | None = None,
        now: str | None = None,
    ) -> None:
        if not memory_fact_ids:
            return
        now = now or utc_now_iso()
        with self._connection_scope(connection) as active_connection:
            active_connection.executemany(
                """
                UPDATE memory_facts
                SET last_accessed_at = ?,
                    access_count = COALESCE(access_count, 0) + 1,
                    next_evaluation_at = ?
                WHERE id = ?
                """,
                [(now, now, memory_fact_id) for memory_fact_id in memory_fact_ids],
            )

    def mark_successful_use(
        self,
        memory_fact_ids: list[str],
        *,
        connection: sqlite3.Connection | None = None,
        now: str | None = None,
    ) -> None:
        if not memory_fact_ids:
            return
        now = now or utc_now_iso()
        with self._connection_scope(connection) as active_connection:
            active_connection.executemany(
                """
                UPDATE memory_facts
                SET successful_use_count = COALESCE(successful_use_count, 0) + 1,
                    last_accessed_at = ?,
                    next_evaluation_at = ?
                WHERE id = ?
                """,
                [(now, now, memory_fact_id) for memory_fact_id in memory_fact_ids],
            )

    def list_due_for_retention_evaluation(
        self,
        *,
        now: str | None = None,
        tenant_id: str | None = None,
        limit: int = 100,
        connection: sqlite3.Connection | None = None,
    ) -> list[MemoryFact]:
        now = now or utc_now_iso()
        conditions = ["status != 'deleted'"]
        parameters: list[object] = []
        if tenant_id:
            conditions.append("tenant_id = ?")
            parameters.append(tenant_id)
        conditions.append(
            "("
            "COALESCE(next_evaluation_at, '') = '' "
            "OR next_evaluation_at <= ? "
            "OR (COALESCE(expires_at, '') != '' AND expires_at <= ?)"
            ")"
        )
        parameters.extend((now, now, limit))

        with self._connection_scope(connection) as active_connection:
            rows = active_connection.execute(
                f"""
                SELECT
                    {_MEMORY_FACT_COLUMNS}
                FROM memory_facts
                WHERE {' AND '.join(conditions)}
                ORDER BY
                    CASE
                        WHEN COALESCE(next_evaluation_at, '') = '' THEN updated_at
                        ELSE next_evaluation_at
                    END ASC,
                    updated_at ASC
                LIMIT ?
                """,
                tuple(parameters),
            ).fetchall()

        return [self._row_to_memory_fact(row) for row in rows]

    @contextmanager
    def _connection_scope(
        self,
        connection: sqlite3.Connection | None,
    ) -> Iterator[sqlite3.Connection]:
        if connection is not None:
            yield connection
            return

        with connect_state_db(self._config) as managed_connection:
            yield managed_connection

    @staticmethod
    def _normalize_create_payload(payload: MemoryFactCreate, memory_fact_id: str) -> MemoryFactCreate:
        normalized_content = payload.content.strip()
        normalized_subject_key = (payload.subject_key or "").strip() or f"{payload.scope_type}:{payload.scope_id}"
        normalized_fact_key = (payload.fact_key or "").strip() or (
            f"{payload.type}.legacy.{memory_fact_id.replace('-', '')[:12]}"
        )
        normalized_source_type = (
            (payload.source_type or "").strip()
            or _derive_source_type(payload.source_kind, payload.confirmed)
        )
        normalized_consistency_group = (
            (payload.consistency_group_id or "").strip() or f"{normalized_subject_key}|{normalized_fact_key}"
        )
        return MemoryFactCreate(
            tenant_id=payload.tenant_id,
            owner_user_id=payload.owner_user_id,
            project_id=payload.project_id,
            scope_type=payload.scope_type,
            scope_id=payload.scope_id,
            type=payload.type,
            content=normalized_content,
            source_session_id=payload.source_session_id,
            status=payload.status,
            source_kind=payload.source_kind,
            confirmed=payload.confirmed,
            subject_key=normalized_subject_key,
            fact_key=normalized_fact_key,
            version=int(payload.version or 1),
            superseded_by=_normalize_optional_text(payload.superseded_by),
            supersedes=_normalize_optional_text(payload.supersedes),
            correction_of=_normalize_optional_text(payload.correction_of),
            source_type=normalized_source_type,
            source_confidence=float(payload.source_confidence or 0.0),
            reviewed_by_human=payload.reviewed_by_human,
            consistency_group_id=normalized_consistency_group,
            value_score=float(payload.value_score or 0.0),
            retention_level=payload.retention_level or "normal",
            ttl_seconds=payload.ttl_seconds,
            expires_at=_normalize_optional_text(payload.expires_at),
            last_accessed_at=_normalize_optional_text(payload.last_accessed_at),
            access_count=max(0, int(payload.access_count or 0)),
            successful_use_count=max(0, int(payload.successful_use_count or 0)),
            decay_factor=float(payload.decay_factor or 1.0),
            archived_at=_normalize_optional_text(payload.archived_at),
            retrieval_visibility=payload.retrieval_visibility or "normal",
            forgetting_status=payload.forgetting_status or "none",
            next_evaluation_at=_normalize_optional_text(payload.next_evaluation_at),
            retention_policy_id=_normalize_optional_text(payload.retention_policy_id),
            archive_bucket=_normalize_optional_text(payload.archive_bucket),
        )

    @staticmethod
    def _row_to_memory_fact(row) -> MemoryFact:
        return MemoryFact(
            id=str(row["id"]),
            tenant_id=str(row["tenant_id"]),
            owner_user_id=str(row["owner_user_id"]),
            project_id=str(row["project_id"]),
            scope_type=str(row["scope_type"]),
            scope_id=str(row["scope_id"]),
            type=str(row["type"]),
            content=str(row["content"]),
            status=str(row["status"]),
            source_session_id=str(row["source_session_id"]),
            created_at=str(row["created_at"]),
            updated_at=str(row["updated_at"]),
            subject_key=str(row["subject_key"] or ""),
            fact_key=str(row["fact_key"] or ""),
            version=int(row["version"] or 1),
            superseded_by=_normalize_optional_text(row["superseded_by"]),
            supersedes=_normalize_optional_text(row["supersedes"]),
            correction_of=_normalize_optional_text(row["correction_of"]),
            source_type=str(row["source_type"] or "system_generated"),
            source_confidence=float(row["source_confidence"] or 0.0),
            reviewed_by_human=_db_to_bool(row["reviewed_by_human"]),
            consistency_group_id=_normalize_optional_text(row["consistency_group_id"]),
            value_score=float(row["value_score"] or 0.0),
            retention_level=str(row["retention_level"] or "normal"),
            ttl_seconds=int(row["ttl_seconds"]) if row["ttl_seconds"] is not None else None,
            expires_at=_normalize_optional_text(row["expires_at"]),
            last_accessed_at=_normalize_optional_text(row["last_accessed_at"]),
            access_count=int(row["access_count"] or 0),
            successful_use_count=int(row["successful_use_count"] or 0),
            decay_factor=float(row["decay_factor"] or 1.0),
            archived_at=_normalize_optional_text(row["archived_at"]),
            retrieval_visibility=str(row["retrieval_visibility"] or "normal"),
            forgetting_status=str(row["forgetting_status"] or "none"),
            next_evaluation_at=_normalize_optional_text(row["next_evaluation_at"]),
            retention_policy_id=_normalize_optional_text(row["retention_policy_id"]),
            archive_bucket=_normalize_optional_text(row["archive_bucket"]),
        )


def _derive_source_type(source_kind: str, confirmed: bool) -> str:
    if confirmed:
        return "user_confirmed"

    normalized_kind = str(source_kind or "").strip().lower()
    if normalized_kind in {"import", "imported"}:
        return "imported"
    if normalized_kind in {"system", "system_generated", "summary_extraction", "memory_extraction"}:
        return "system_generated"
    return "model_inferred"


def _normalize_optional_text(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _bool_to_db(value: bool | None) -> int | None:
    if value is None:
        return None
    return 1 if value else 0


def _db_to_bool(value) -> bool | None:
    if value is None:
        return None
    return bool(int(value))
