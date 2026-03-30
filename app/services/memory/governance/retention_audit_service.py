"""Audit logging for retention evaluation and forgetting decisions."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from uuid import uuid4

from app.config import AppConfig
from app.schemas import MemoryRetentionAuditRecord, RetentionAuditAction
from app.services.persistence_utils import utc_now_iso
from app.services.storage_service import connect_state_db


class RetentionAuditService:
    """Persist explainable retention decisions for later tuning and audit."""

    def __init__(self, config: AppConfig) -> None:
        self._config = config

    def log_event(
        self,
        *,
        tenant_id: str,
        memory_fact_id: str,
        action: RetentionAuditAction,
        reason: str,
        value_score: float,
        retention_level: str,
        retrieval_visibility: str,
        forgetting_status: str,
        policy_id: str,
        details: dict[str, object] | None = None,
        connection: sqlite3.Connection | None = None,
        created_at: str | None = None,
    ) -> MemoryRetentionAuditRecord:
        record = MemoryRetentionAuditRecord(
            id=str(uuid4()),
            tenant_id=tenant_id,
            memory_fact_id=memory_fact_id,
            action=action,
            reason=reason.strip(),
            value_score=float(value_score or 0.0),
            retention_level=str(retention_level or "normal"),
            retrieval_visibility=str(retrieval_visibility or "normal"),
            forgetting_status=str(forgetting_status or "none"),
            policy_id=str(policy_id or "").strip(),
            details_json=json.dumps(details or {}, ensure_ascii=False, sort_keys=True),
            created_at=created_at or utc_now_iso(),
        )

        with self._connection_scope(connection) as active_connection:
            active_connection.execute(
                """
                INSERT INTO memory_retention_audit (
                    id, tenant_id, memory_fact_id, action, reason, value_score,
                    retention_level, retrieval_visibility, forgetting_status,
                    policy_id, details_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.id,
                    record.tenant_id,
                    record.memory_fact_id,
                    record.action,
                    record.reason,
                    record.value_score,
                    record.retention_level,
                    record.retrieval_visibility,
                    record.forgetting_status,
                    record.policy_id,
                    record.details_json,
                    record.created_at,
                ),
            )

        return record

    def list_by_memory_fact_id(
        self,
        tenant_id: str,
        memory_fact_id: str,
    ) -> list[MemoryRetentionAuditRecord]:
        with connect_state_db(self._config) as connection:
            rows = connection.execute(
                """
                SELECT id, tenant_id, memory_fact_id, action, reason, value_score,
                       retention_level, retrieval_visibility, forgetting_status,
                       policy_id, details_json, created_at
                FROM memory_retention_audit
                WHERE tenant_id = ? AND memory_fact_id = ?
                ORDER BY created_at ASC
                """,
                (tenant_id, memory_fact_id),
            ).fetchall()
        return [self._row_to_record(row) for row in rows]

    @staticmethod
    def _row_to_record(row) -> MemoryRetentionAuditRecord:
        return MemoryRetentionAuditRecord(
            id=str(row["id"]),
            tenant_id=str(row["tenant_id"]),
            memory_fact_id=str(row["memory_fact_id"]),
            action=str(row["action"]),
            reason=str(row["reason"] or ""),
            value_score=float(row["value_score"] or 0.0),
            retention_level=str(row["retention_level"] or "normal"),
            retrieval_visibility=str(row["retrieval_visibility"] or "normal"),
            forgetting_status=str(row["forgetting_status"] or "none"),
            policy_id=str(row["policy_id"] or ""),
            details_json=str(row["details_json"] or "{}"),
            created_at=str(row["created_at"]),
        )

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
