"""Application-level audit trail for shared deployment and admin operations."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from uuid import uuid4

from app.schemas import ApplicationAuditRecord, AuthenticatedUser, MemoryRequestContext
from app.config import AppConfig
from app.services.persistence_utils import utc_now_iso
from app.services.storage_service import connect_state_db


class ApplicationAuditService:
    """Persist structured app audit events such as settings changes and permission denials."""

    def __init__(self, config: AppConfig) -> None:
        self._config = config

    def record_event(
        self,
        *,
        user: AuthenticatedUser | None,
        action: str,
        outcome: str,
        request_context: MemoryRequestContext | None = None,
        target_type: str = "",
        target_id: str = "",
        details: dict[str, object] | None = None,
        connection: sqlite3.Connection | None = None,
        created_at: str | None = None,
    ) -> ApplicationAuditRecord:
        record = ApplicationAuditRecord(
            id=str(uuid4()),
            tenant_id=(request_context.tenant_id if request_context else (user.tenant_id if user else self._config.tenant_id)),
            actor_user_id=(user.user_id if user else "system"),
            actor_role=(user.role if user else "system"),
            team_id=(user.team_id if user else ""),
            project_id=(request_context.project_id if request_context else ""),
            request_id=(request_context.request_id if request_context else ""),
            session_id=(request_context.session_id if request_context else ""),
            action=str(action or "").strip(),
            target_type=str(target_type or "").strip(),
            target_id=str(target_id or "").strip(),
            outcome=str(outcome or "").strip(),
            details_json=json.dumps(details or {}, ensure_ascii=False, sort_keys=True),
            created_at=created_at or utc_now_iso(),
        )
        with self._connection_scope(connection) as active_connection:
            active_connection.execute(
                """
                INSERT INTO application_audit_events (
                    id, tenant_id, actor_user_id, actor_role, team_id,
                    project_id, request_id, session_id, action, target_type,
                    target_id, outcome, details_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.id,
                    record.tenant_id,
                    record.actor_user_id,
                    record.actor_role,
                    record.team_id,
                    record.project_id,
                    record.request_id,
                    record.session_id,
                    record.action,
                    record.target_type,
                    record.target_id,
                    record.outcome,
                    record.details_json,
                    record.created_at,
                ),
            )
        return record

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
