"""Centralized audit and governance persistence helpers."""

from __future__ import annotations

import json
import logging
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from uuid import uuid4

from app.config import AppConfig
from app.schemas import (
    MemoryAccessAuditRecord,
    MemoryAuditAction,
    MemoryRequestContext,
    PolicyDecisionRecord,
    PolicyDecisionState,
    SecurityEventRecord,
    SecurityEventStatus,
    SecurityEventType,
    SecuritySeverity,
)
from app.services.persistence_utils import utc_now_iso
from app.services.storage_service import connect_state_db


logger = logging.getLogger(__name__)


class AuditService:
    """Single entry point for memory audit, policy decisions, and security events."""

    def __init__(self, config: AppConfig) -> None:
        self._config = config

    def record_memory_action(
        self,
        *,
        request_context: MemoryRequestContext,
        memory_fact_id: str,
        action: MemoryAuditAction,
        scope_type: str = "",
        retrieval_stage: str = "",
        decision_reason: str = "",
        connection: sqlite3.Connection | None = None,
        created_at: str | None = None,
    ) -> MemoryAccessAuditRecord:
        record = MemoryAccessAuditRecord(
            id=str(uuid4()),
            tenant_id=request_context.tenant_id,
            request_id=request_context.request_id,
            memory_fact_id=memory_fact_id,
            action=action,
            actor_user_id=request_context.user_id,
            session_id=request_context.session_id,
            scope_type=scope_type.strip(),
            retrieval_stage=retrieval_stage.strip(),
            decision_reason=decision_reason.strip(),
            created_at=created_at or utc_now_iso(),
        )
        with self._connection_scope(connection) as active_connection:
            active_connection.execute(
                """
                INSERT INTO memory_access_audit (
                    id, tenant_id, request_id, memory_fact_id, action,
                    actor_user_id, session_id, scope_type, retrieval_stage,
                    decision_reason, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.id,
                    record.tenant_id,
                    record.request_id,
                    record.memory_fact_id,
                    record.action,
                    record.actor_user_id,
                    record.session_id,
                    record.scope_type,
                    record.retrieval_stage,
                    record.decision_reason,
                    record.created_at,
                ),
            )
        return record

    def record_policy_decision(
        self,
        *,
        request_id: str,
        policy_name: str,
        decision: PolicyDecisionState,
        reason: str,
        target_type: str,
        target_id: str,
        payload: dict[str, object] | None = None,
        connection: sqlite3.Connection | None = None,
        created_at: str | None = None,
    ) -> PolicyDecisionRecord:
        record = PolicyDecisionRecord(
            id=str(uuid4()),
            request_id=str(request_id or "").strip() or "unknown_request",
            policy_name=policy_name.strip(),
            decision=decision,
            reason=reason.strip(),
            target_type=target_type.strip(),
            target_id=target_id.strip(),
            payload_json=json.dumps(payload or {}, ensure_ascii=False, sort_keys=True),
            created_at=created_at or utc_now_iso(),
        )
        with self._connection_scope(connection) as active_connection:
            active_connection.execute(
                """
                INSERT INTO policy_decisions (
                    id, request_id, policy_name, decision, reason,
                    target_type, target_id, payload_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.id,
                    record.request_id,
                    record.policy_name,
                    record.decision,
                    record.reason,
                    record.target_type,
                    record.target_id,
                    record.payload_json,
                    record.created_at,
                ),
            )
        return record

    def record_security_event(
        self,
        *,
        tenant_id: str,
        event_type: SecurityEventType,
        severity: SecuritySeverity,
        actor_user_id: str,
        session_id: str,
        request_id: str,
        event_payload: dict[str, object] | None = None,
        status: SecurityEventStatus = "open",
        target_memory_fact_id: str | None = None,
        connection: sqlite3.Connection | None = None,
        created_at: str | None = None,
        resolved_at: str | None = None,
    ) -> SecurityEventRecord:
        record = SecurityEventRecord(
            id=str(uuid4()),
            tenant_id=tenant_id.strip(),
            event_type=event_type,
            severity=severity,
            actor_user_id=actor_user_id.strip() or "system",
            session_id=session_id.strip() or "system",
            target_memory_fact_id=(target_memory_fact_id or "").strip() or None,
            request_id=request_id.strip() or "unknown_request",
            event_payload_json=json.dumps(event_payload or {}, ensure_ascii=False, sort_keys=True),
            status=status,
            created_at=created_at or utc_now_iso(),
            resolved_at=(resolved_at or "").strip() or None,
        )
        with self._connection_scope(connection) as active_connection:
            active_connection.execute(
                """
                INSERT INTO security_events (
                    id, tenant_id, event_type, severity, actor_user_id,
                    session_id, target_memory_fact_id, request_id, event_payload_json,
                    status, created_at, resolved_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.id,
                    record.tenant_id,
                    record.event_type,
                    record.severity,
                    record.actor_user_id,
                    record.session_id,
                    record.target_memory_fact_id,
                    record.request_id,
                    record.event_payload_json,
                    record.status,
                    record.created_at,
                    record.resolved_at,
                ),
            )
        return record

    def list_memory_actions_by_request(
        self,
        tenant_id: str,
        request_id: str,
    ) -> list[MemoryAccessAuditRecord]:
        with connect_state_db(self._config) as connection:
            rows = connection.execute(
                """
                SELECT id, tenant_id, request_id, memory_fact_id, action,
                       actor_user_id, session_id, scope_type, retrieval_stage,
                       decision_reason, created_at
                FROM memory_access_audit
                WHERE tenant_id = ? AND request_id = ?
                ORDER BY created_at ASC
                """,
                (tenant_id, request_id),
            ).fetchall()
        return [self._row_to_memory_action(row) for row in rows]

    def list_memory_actions_by_session(
        self,
        tenant_id: str,
        session_id: str,
    ) -> list[MemoryAccessAuditRecord]:
        with connect_state_db(self._config) as connection:
            rows = connection.execute(
                """
                SELECT id, tenant_id, request_id, memory_fact_id, action,
                       actor_user_id, session_id, scope_type, retrieval_stage,
                       decision_reason, created_at
                FROM memory_access_audit
                WHERE tenant_id = ? AND session_id = ?
                ORDER BY created_at ASC
                """,
                (tenant_id, session_id),
            ).fetchall()
        return [self._row_to_memory_action(row) for row in rows]

    def list_memory_actions_by_fact(
        self,
        tenant_id: str,
        memory_fact_id: str,
    ) -> list[MemoryAccessAuditRecord]:
        with connect_state_db(self._config) as connection:
            rows = connection.execute(
                """
                SELECT id, tenant_id, request_id, memory_fact_id, action,
                       actor_user_id, session_id, scope_type, retrieval_stage,
                       decision_reason, created_at
                FROM memory_access_audit
                WHERE tenant_id = ? AND memory_fact_id = ?
                ORDER BY created_at ASC
                """,
                (tenant_id, memory_fact_id),
            ).fetchall()
        return [self._row_to_memory_action(row) for row in rows]

    def list_policy_decisions(
        self,
        *,
        request_id: str | None = None,
        limit: int = 50,
        decision: str | None = None,
    ) -> list[PolicyDecisionRecord]:
        query = [
            "SELECT id, request_id, policy_name, decision, reason, target_type, target_id, payload_json, created_at",
            "FROM policy_decisions",
        ]
        conditions: list[str] = []
        parameters: list[object] = []
        if request_id:
            conditions.append("request_id = ?")
            parameters.append(request_id)
        if decision:
            conditions.append("decision = ?")
            parameters.append(decision)
        if conditions:
            query.append("WHERE " + " AND ".join(conditions))
        query.append("ORDER BY created_at DESC")
        query.append("LIMIT ?")
        parameters.append(limit)

        with connect_state_db(self._config) as connection:
            rows = connection.execute(" ".join(query), tuple(parameters)).fetchall()
        return [
            PolicyDecisionRecord(
                id=str(row["id"]),
                request_id=str(row["request_id"]),
                policy_name=str(row["policy_name"]),
                decision=str(row["decision"]),
                reason=str(row["reason"] or ""),
                target_type=str(row["target_type"] or ""),
                target_id=str(row["target_id"] or ""),
                payload_json=str(row["payload_json"] or "{}"),
                created_at=str(row["created_at"]),
            )
            for row in rows
        ]

    def list_security_events(
        self,
        *,
        tenant_id: str,
        limit: int = 50,
        status: str | None = None,
    ) -> list[SecurityEventRecord]:
        query = [
            """
            SELECT id, tenant_id, event_type, severity, actor_user_id, session_id,
                   target_memory_fact_id, request_id, event_payload_json, status,
                   created_at, resolved_at
            FROM security_events
            WHERE tenant_id = ?
            """
        ]
        parameters: list[object] = [tenant_id]
        if status:
            query.append("AND status = ?")
            parameters.append(status)
        query.append("ORDER BY created_at DESC")
        query.append("LIMIT ?")
        parameters.append(limit)

        with connect_state_db(self._config) as connection:
            rows = connection.execute(" ".join(query), tuple(parameters)).fetchall()
        return [self._row_to_security_event(row) for row in rows]

    @staticmethod
    def _row_to_memory_action(row) -> MemoryAccessAuditRecord:
        return MemoryAccessAuditRecord(
            id=str(row["id"]),
            tenant_id=str(row["tenant_id"]),
            request_id=str(row["request_id"]),
            memory_fact_id=str(row["memory_fact_id"]),
            action=str(row["action"]),
            actor_user_id=str(row["actor_user_id"]),
            session_id=str(row["session_id"]),
            scope_type=str(row["scope_type"] or ""),
            retrieval_stage=str(row["retrieval_stage"] or ""),
            decision_reason=str(row["decision_reason"] or ""),
            created_at=str(row["created_at"]),
        )

    @staticmethod
    def _row_to_security_event(row) -> SecurityEventRecord:
        return SecurityEventRecord(
            id=str(row["id"]),
            tenant_id=str(row["tenant_id"]),
            event_type=str(row["event_type"]),
            severity=str(row["severity"]),
            actor_user_id=str(row["actor_user_id"] or ""),
            session_id=str(row["session_id"] or ""),
            target_memory_fact_id=str(row["target_memory_fact_id"]) if row["target_memory_fact_id"] else None,
            request_id=str(row["request_id"] or ""),
            event_payload_json=str(row["event_payload_json"] or "{}"),
            status=str(row["status"] or "open"),
            created_at=str(row["created_at"]),
            resolved_at=str(row["resolved_at"]) if row["resolved_at"] else None,
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
