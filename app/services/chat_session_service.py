"""Backward-compatible service wrapper for chat session persistence."""

from __future__ import annotations

from app.config import AppConfig
from app.schemas import ChatSessionRecord, MemoryRequestContext
from app.services.session_repository import SessionRepository


class ChatSessionService:
    """Keep the old service surface while the repository owns storage access."""

    def __init__(self, config: AppConfig) -> None:
        self._repository = SessionRepository(config)

    def ensure_session(self, request_context: MemoryRequestContext, title: str) -> ChatSessionRecord:
        return self._repository.ensure_session(request_context, title)
