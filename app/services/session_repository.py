"""Repository access for persisted chat session shells."""

from __future__ import annotations

from app.config import AppConfig
from app.schemas import ChatSessionRecord, MemoryRequestContext
from app.services.persistence_utils import utc_now_iso
from app.services.storage_service import connect_state_db


class SessionRepository:
    """Persist and query the lightweight chat session shell."""

    def __init__(self, config: AppConfig) -> None:
        self._config = config

    def ensure_session(self, request_context: MemoryRequestContext, title: str) -> ChatSessionRecord:
        session_title = title.strip() or "New chat"
        now = utc_now_iso()

        with connect_state_db(self._config) as connection:
            existing = connection.execute(
                """
                SELECT id, tenant_id, user_id, project_id, title, status, created_at, last_active_at
                FROM chat_sessions
                WHERE id = ?
                """,
                (request_context.session_id,),
            ).fetchone()

            if existing is None:
                connection.execute(
                    """
                    INSERT INTO chat_sessions (
                        id, tenant_id, user_id, project_id, title, status, created_at, last_active_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        request_context.session_id,
                        request_context.tenant_id,
                        request_context.user_id,
                        request_context.project_id,
                        session_title,
                        "active",
                        now,
                        now,
                    ),
                )
                connection.commit()
                return ChatSessionRecord(
                    id=request_context.session_id,
                    tenant_id=request_context.tenant_id,
                    user_id=request_context.user_id,
                    project_id=request_context.project_id,
                    title=session_title,
                    status="active",
                    created_at=now,
                    last_active_at=now,
                )

            if str(existing["tenant_id"]) != request_context.tenant_id:
                raise ValueError("Session id already exists under another tenant.")
            if str(existing["user_id"]) != request_context.user_id:
                raise ValueError("Session id already belongs to another user.")
            if str(existing["project_id"]) != request_context.project_id:
                raise ValueError("Session id already belongs to another project.")

            next_title = session_title if not str(existing["title"] or "").strip() else str(existing["title"])
            connection.execute(
                """
                UPDATE chat_sessions
                SET user_id = ?, project_id = ?, title = ?, status = ?, last_active_at = ?
                WHERE id = ? AND tenant_id = ?
                """,
                (
                    request_context.user_id,
                    request_context.project_id,
                    next_title,
                    "active",
                    now,
                    request_context.session_id,
                    request_context.tenant_id,
                ),
            )
            connection.commit()

            return ChatSessionRecord(
                id=str(existing["id"]),
                tenant_id=str(existing["tenant_id"]),
                user_id=request_context.user_id,
                project_id=request_context.project_id,
                title=next_title,
                status="active",
                created_at=str(existing["created_at"]),
                last_active_at=now,
            )

    def get_session(
        self,
        *,
        tenant_id: str,
        session_id: str,
    ) -> ChatSessionRecord | None:
        with connect_state_db(self._config) as connection:
            row = connection.execute(
                """
                SELECT id, tenant_id, user_id, project_id, title, status, created_at, last_active_at
                FROM chat_sessions
                WHERE tenant_id = ? AND id = ?
                """,
                (tenant_id, session_id),
            ).fetchone()

        return self._row_to_record(row) if row is not None else None

    def list_sessions(
        self,
        *,
        tenant_id: str,
        user_id: str | None = None,
        project_id: str | None = None,
        status: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[ChatSessionRecord]:
        conditions = ["tenant_id = ?"]
        parameters: list[object] = [tenant_id]

        if user_id:
            conditions.append("user_id = ?")
            parameters.append(user_id)
        if project_id:
            conditions.append("project_id = ?")
            parameters.append(project_id)
        if status:
            conditions.append("status = ?")
            parameters.append(status)

        parameters.extend((limit, offset))

        with connect_state_db(self._config) as connection:
            rows = connection.execute(
                f"""
                SELECT id, tenant_id, user_id, project_id, title, status, created_at, last_active_at
                FROM chat_sessions
                WHERE {' AND '.join(conditions)}
                ORDER BY last_active_at DESC, created_at DESC
                LIMIT ? OFFSET ?
                """,
                tuple(parameters),
            ).fetchall()

        return [self._row_to_record(row) for row in rows]

    def update_last_active(
        self,
        *,
        tenant_id: str,
        session_id: str,
    ) -> ChatSessionRecord | None:
        now = utc_now_iso()
        with connect_state_db(self._config) as connection:
            connection.execute(
                """
                UPDATE chat_sessions
                SET last_active_at = ?, status = 'active'
                WHERE tenant_id = ? AND id = ?
                """,
                (now, tenant_id, session_id),
            )
            connection.commit()
            row = connection.execute(
                """
                SELECT id, tenant_id, user_id, project_id, title, status, created_at, last_active_at
                FROM chat_sessions
                WHERE tenant_id = ? AND id = ?
                """,
                (tenant_id, session_id),
            ).fetchone()

        return self._row_to_record(row) if row is not None else None

    def update_title(
        self,
        *,
        tenant_id: str,
        session_id: str,
        title: str,
    ) -> ChatSessionRecord | None:
        next_title = title.strip()
        if not next_title:
            raise ValueError("Session title cannot be empty.")

        with connect_state_db(self._config) as connection:
            connection.execute(
                """
                UPDATE chat_sessions
                SET title = ?
                WHERE tenant_id = ? AND id = ?
                """,
                (next_title, tenant_id, session_id),
            )
            connection.commit()
            row = connection.execute(
                """
                SELECT id, tenant_id, user_id, project_id, title, status, created_at, last_active_at
                FROM chat_sessions
                WHERE tenant_id = ? AND id = ?
                """,
                (tenant_id, session_id),
            ).fetchone()

        return self._row_to_record(row) if row is not None else None

    @staticmethod
    def _row_to_record(row) -> ChatSessionRecord:
        return ChatSessionRecord(
            id=str(row["id"]),
            tenant_id=str(row["tenant_id"]),
            user_id=str(row["user_id"]),
            project_id=str(row["project_id"]),
            title=str(row["title"]),
            status=str(row["status"]),
            created_at=str(row["created_at"]),
            last_active_at=str(row["last_active_at"]),
        )
