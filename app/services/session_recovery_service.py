"""Session recovery helpers for restoring recent chat context from persistence."""

from __future__ import annotations

from app.config import AppConfig
from app.schemas import MemoryRequestContext, SessionRecoverySnapshot
from app.services.message_repository import MessageRepository
from app.services.session_repository import SessionRepository


class SessionRecoveryService:
    """Recover the session shell and only the recent message window needed for chat."""

    def __init__(
        self,
        config: AppConfig,
        *,
        session_repository: SessionRepository | None = None,
        message_repository: MessageRepository | None = None,
    ) -> None:
        self._session_repository = session_repository or SessionRepository(config)
        self._message_repository = message_repository or MessageRepository(config)

    def recover_session(
        self,
        request_context: MemoryRequestContext,
        *,
        message_limit: int = 12,
    ) -> SessionRecoverySnapshot:
        session = self._session_repository.get_session(
            tenant_id=request_context.tenant_id,
            session_id=request_context.session_id,
        )
        if session is None or message_limit <= 0:
            return SessionRecoverySnapshot(
                session=session,
                messages=[],
                restored_from_persistence=False,
            )

        messages = self._message_repository.list_recent_by_session(
            tenant_id=request_context.tenant_id,
            session_id=request_context.session_id,
            limit=message_limit,
        )
        return SessionRecoverySnapshot(
            session=session,
            messages=messages,
            restored_from_persistence=bool(messages),
        )

    def build_recent_chat_history(
        self,
        snapshot: SessionRecoverySnapshot,
        *,
        fallback_history: list[dict[str, object]] | None = None,
        exclude_message_ids: tuple[str, ...] = (),
        message_limit: int = 12,
    ) -> list[dict[str, object]]:
        if message_limit <= 0:
            return []

        # We exclude the just-persisted user turn so the current question does not appear twice.
        persisted_messages = [
            item
            for item in snapshot.messages
            if item.id not in set(exclude_message_ids)
        ]
        if persisted_messages:
            trimmed_messages = persisted_messages[-message_limit:]
            return [
                {"role": item.role, "content": item.content}
                for item in trimmed_messages
                if item.content.strip()
            ]

        sanitized_fallback = [
            {
                "role": str(item.get("role", "")).strip(),
                "content": str(item.get("content", "")).strip(),
            }
            for item in (fallback_history or [])
            if str(item.get("role", "")).strip() and str(item.get("content", "")).strip()
        ]
        return sanitized_fallback[-message_limit:]
