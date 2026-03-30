"""Repository access for raw persisted chat messages."""

from __future__ import annotations

import json
from uuid import uuid4

from app.config import AppConfig
from app.schemas import ChatMessageCreate, ChatMessageRecord
from app.services.persistence_utils import utc_now_iso
from app.services.storage_service import connect_state_db


class MessageRepository:
    """Store and recover raw chat messages without mixing them into memory facts."""

    def __init__(self, config: AppConfig) -> None:
        self._config = config

    def create_message(self, payload: ChatMessageCreate) -> ChatMessageRecord:
        now = utc_now_iso()
        record = ChatMessageRecord(
            id=str(uuid4()),
            tenant_id=payload.tenant_id,
            session_id=payload.session_id,
            user_id=payload.user_id,
            role=payload.role,
            content=str(payload.content),
            provider=str(payload.provider or ""),
            model=str(payload.model or ""),
            citations_json=_normalize_json_text(payload.citations_json, "[]"),
            metadata_json=_normalize_json_text(payload.metadata_json, "{}"),
            created_at=now,
        )

        with connect_state_db(self._config) as connection:
            connection.execute(
                """
                INSERT INTO chat_messages (
                    id, tenant_id, session_id, user_id, role, content,
                    provider, model, citations_json, metadata_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.id,
                    record.tenant_id,
                    record.session_id,
                    record.user_id,
                    record.role,
                    record.content,
                    record.provider,
                    record.model,
                    record.citations_json,
                    record.metadata_json,
                    record.created_at,
                ),
            )
            connection.commit()

        return record

    def list_by_session(
        self,
        *,
        tenant_id: str,
        session_id: str,
        limit: int | None = None,
    ) -> list[ChatMessageRecord]:
        with connect_state_db(self._config) as connection:
            if limit is None:
                rows = connection.execute(
                    """
                    SELECT id, tenant_id, session_id, user_id, role, content,
                           provider, model, citations_json, metadata_json, created_at
                    FROM chat_messages
                    WHERE tenant_id = ? AND session_id = ?
                    ORDER BY created_at ASC, rowid ASC
                    """,
                    (tenant_id, session_id),
                ).fetchall()
            else:
                # The hot recovery path asks for the newest N messages first, then flips back to ASC.
                rows = connection.execute(
                    """
                    SELECT id, tenant_id, session_id, user_id, role, content,
                           provider, model, citations_json, metadata_json, created_at
                    FROM chat_messages
                    WHERE tenant_id = ? AND session_id = ?
                    ORDER BY created_at DESC, rowid DESC
                    LIMIT ?
                    """,
                    (tenant_id, session_id, limit),
                ).fetchall()
                rows = list(reversed(rows))

        return [self._row_to_record(row) for row in rows]

    def list_recent_by_session(
        self,
        *,
        tenant_id: str,
        session_id: str,
        limit: int,
    ) -> list[ChatMessageRecord]:
        return self.list_by_session(tenant_id=tenant_id, session_id=session_id, limit=limit)

    def count_by_session(
        self,
        *,
        tenant_id: str,
        session_id: str,
    ) -> int:
        with connect_state_db(self._config) as connection:
            row = connection.execute(
                """
                SELECT COUNT(*) AS item_count
                FROM chat_messages
                WHERE tenant_id = ? AND session_id = ?
                """,
                (tenant_id, session_id),
            ).fetchone()

        return int(row["item_count"]) if row is not None else 0

    def count_by_session_ids(
        self,
        *,
        tenant_id: str,
        session_ids: list[str],
    ) -> dict[str, int]:
        if not session_ids:
            return {}

        placeholders = ", ".join("?" for _ in session_ids)
        parameters: list[object] = [tenant_id, *session_ids]
        with connect_state_db(self._config) as connection:
            rows = connection.execute(
                f"""
                SELECT session_id, COUNT(*) AS item_count
                FROM chat_messages
                WHERE tenant_id = ? AND session_id IN ({placeholders})
                GROUP BY session_id
                """,
                tuple(parameters),
            ).fetchall()

        return {str(row["session_id"]): int(row["item_count"]) for row in rows}

    def get_latest_by_session(
        self,
        *,
        tenant_id: str,
        session_id: str,
    ) -> ChatMessageRecord | None:
        with connect_state_db(self._config) as connection:
            row = connection.execute(
                """
                SELECT id, tenant_id, session_id, user_id, role, content,
                       provider, model, citations_json, metadata_json, created_at
                FROM chat_messages
                WHERE tenant_id = ? AND session_id = ?
                ORDER BY created_at DESC, rowid DESC
                LIMIT 1
                """,
                (tenant_id, session_id),
            ).fetchone()

        return self._row_to_record(row) if row is not None else None

    @staticmethod
    def _row_to_record(row) -> ChatMessageRecord:
        return ChatMessageRecord(
            id=str(row["id"]),
            tenant_id=str(row["tenant_id"]),
            session_id=str(row["session_id"]),
            user_id=str(row["user_id"]),
            role=str(row["role"]),
            content=str(row["content"]),
            provider=str(row["provider"]),
            model=str(row["model"]),
            citations_json=str(row["citations_json"]),
            metadata_json=str(row["metadata_json"]),
            created_at=str(row["created_at"]),
        )


def _normalize_json_text(value: str, default_value: str) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        return default_value

    try:
        parsed = json.loads(normalized)
    except json.JSONDecodeError:
        return json.dumps({"raw": normalized}, ensure_ascii=False)

    return json.dumps(parsed, ensure_ascii=False)
