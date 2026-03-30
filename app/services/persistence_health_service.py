"""Lightweight persistence inspection for Aurora's local storage layout."""

from __future__ import annotations

from app.config import AppConfig
from app.schemas import StorageInspectionReport
from app.services.storage_service import connect_state_db, table_exists


class PersistenceHealthService:
    """Inspect the local SQL state so operators can validate storage readiness."""

    def __init__(self, config: AppConfig) -> None:
        self._config = config

    def inspect(self) -> StorageInspectionReport:
        table_names = (
            "chat_sessions",
            "chat_messages",
            "memory_facts",
            "memory_access_audit",
            "memory_retention_audit",
            "security_events",
            "policy_decisions",
            "system_metrics_snapshot",
        )

        with connect_state_db(self._config) as connection:
            table_status = {name: table_exists(connection, name) for name in table_names}
            session_count = _count_rows(connection, "chat_sessions")
            message_count = _count_rows(connection, "chat_messages")
            memory_count = _count_rows(connection, "memory_facts")
            rows = connection.execute(
                """
                SELECT scope_type, COUNT(*) AS item_count
                FROM memory_facts
                GROUP BY scope_type
                ORDER BY scope_type ASC
                """
            ).fetchall()

        return StorageInspectionReport(
            table_status=table_status,
            session_count=session_count,
            message_count=message_count,
            memory_count=memory_count,
            memory_count_by_scope={str(row["scope_type"]): int(row["item_count"]) for row in rows},
        )


def _count_rows(connection, table_name: str) -> int:
    row = connection.execute(f"SELECT COUNT(*) AS item_count FROM {table_name}").fetchone()
    return int(row["item_count"]) if row is not None else 0
