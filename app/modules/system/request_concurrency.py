"""Process-local concurrency guard for high-cost HTTP actions."""

from __future__ import annotations

import threading
from dataclasses import dataclass


@dataclass(slots=True)
class ConcurrencyDecision:
    action_name: str
    allowed: bool
    active_count: int
    limit: int


class RequestConcurrencyGuard:
    """Track active in-flight requests for guarded actions."""

    _DEFAULT_LIMITS = {
        "chat_request": 8,
        "document_upload": 2,
        "knowledge_rebuild": 1,
        "log_read": 4,
        "provider_dry_run": 2,
    }
    _LOCK = threading.Lock()
    _ACTIVE_COUNTS: dict[str, int] = {}

    def __init__(self, *, limits: dict[str, int] | None = None) -> None:
        self._limits = limits or self._DEFAULT_LIMITS

    def try_acquire(self, action_name: str) -> ConcurrencyDecision:
        normalized_action = str(action_name or "").strip()
        limit = int(self._limits.get(normalized_action, 0) or 0)
        if limit <= 0:
            return ConcurrencyDecision(
                action_name=normalized_action,
                allowed=True,
                active_count=0,
                limit=0,
            )

        with self._LOCK:
            active_count = int(self._ACTIVE_COUNTS.get(normalized_action, 0) or 0)
            if active_count >= limit:
                return ConcurrencyDecision(
                    action_name=normalized_action,
                    allowed=False,
                    active_count=active_count,
                    limit=limit,
                )
            self._ACTIVE_COUNTS[normalized_action] = active_count + 1

        return ConcurrencyDecision(
            action_name=normalized_action,
            allowed=True,
            active_count=active_count + 1,
            limit=limit,
        )

    def release(self, action_name: str) -> None:
        normalized_action = str(action_name or "").strip()
        if not normalized_action:
            return

        with self._LOCK:
            active_count = int(self._ACTIVE_COUNTS.get(normalized_action, 0) or 0)
            if active_count <= 1:
                self._ACTIVE_COUNTS.pop(normalized_action, None)
                return
            self._ACTIVE_COUNTS[normalized_action] = active_count - 1

    @classmethod
    def reset_all(cls) -> None:
        with cls._LOCK:
            cls._ACTIVE_COUNTS.clear()
