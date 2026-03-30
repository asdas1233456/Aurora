"""Basic rate limiting and abuse protection for high-cost memory actions."""

from __future__ import annotations

import threading
import time
from collections import defaultdict, deque

from app.schemas import MemoryRequestContext, RateLimitDecision


class RateLimitExceededError(RuntimeError):
    """Raised when a governed action should fail fast instead of degrading."""


class AbuseGuard:
    """Process-local sliding-window limits for write, retrieval, and correction paths."""

    _DEFAULT_RULES = {
        "memory_write": {
            "user": (20, 60),
            "session": (30, 60),
            "tenant": (200, 60),
        },
        "memory_retrieval": {
            "user": (60, 60),
            "session": (90, 60),
            "tenant": (600, 60),
        },
        "memory_correction": {
            "user": (10, 60),
            "session": (15, 60),
            "tenant": (80, 60),
        },
        "memory_lifecycle": {
            "tenant": (12, 300),
        },
    }
    _LOCK = threading.Lock()
    _EVENTS: dict[tuple[str, str, str], deque[float]] = defaultdict(deque)

    def __init__(self, *, rules: dict[str, dict[str, tuple[int, int]]] | None = None) -> None:
        self._rules = rules or self._DEFAULT_RULES

    def check_and_consume(
        self,
        request_context: MemoryRequestContext,
        *,
        action_name: str,
        amount: int = 1,
    ) -> RateLimitDecision:
        limits = self._rules.get(action_name, {})
        now = time.time()
        scope_checks = (
            ("user", request_context.user_id),
            ("session", request_context.session_id),
            ("tenant", request_context.tenant_id),
        )
        for scope_name, scope_value in scope_checks:
            limit_config = limits.get(scope_name)
            if limit_config is None:
                continue
            limit, window_seconds = limit_config
            bucket_key = (action_name, scope_name, scope_value)
            with self._LOCK:
                bucket = self._EVENTS[bucket_key]
                self._prune(bucket, now, window_seconds)
                if len(bucket) + max(amount, 1) > limit:
                    retry_after = self._retry_after_seconds(bucket, now, window_seconds)
                    return RateLimitDecision(
                        action_name=action_name,
                        allowed=False,
                        reason=f"{scope_name} rate limit reached for {action_name}",
                        limited_scope=scope_name,
                        retry_after_seconds=retry_after,
                        limit=limit,
                        window_seconds=window_seconds,
                    )
                for _ in range(max(amount, 1)):
                    bucket.append(now)

        return RateLimitDecision(
            action_name=action_name,
            allowed=True,
            reason="action stayed within the configured abuse limits",
        )

    def active_bucket_count(self) -> int:
        with self._LOCK:
            return len(self._EVENTS)

    @classmethod
    def reset_all(cls) -> None:
        with cls._LOCK:
            cls._EVENTS.clear()

    @staticmethod
    def _prune(bucket: deque[float], now: float, window_seconds: int) -> None:
        floor = now - window_seconds
        while bucket and bucket[0] <= floor:
            bucket.popleft()

    @staticmethod
    def _retry_after_seconds(bucket: deque[float], now: float, window_seconds: int) -> int:
        if not bucket:
            return window_seconds
        retry_at = bucket[0] + window_seconds
        return max(int(retry_at - now) + 1, 1)
