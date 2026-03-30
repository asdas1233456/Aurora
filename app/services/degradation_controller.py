"""Centralized degradation decisions for governed memory and provider paths."""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import TypeVar

from app.config import AppConfig
from app.schemas import MemoryRequestContext
from app.services.audit_service import AuditService
from app.services.observability_service import ObservabilityService


logger = logging.getLogger(__name__)

T = TypeVar("T")


class DegradationController:
    """Fail open for observability/audit and degrade memory/provider paths safely."""

    def __init__(
        self,
        config: AppConfig,
        *,
        audit_service: AuditService | None = None,
        observability: ObservabilityService | None = None,
    ) -> None:
        self._audit_service = audit_service or AuditService(config)
        self._observability = observability or ObservabilityService(config)

    def protect_side_effect(
        self,
        operation_name: str,
        func: Callable[[], T],
        *,
        request_context: MemoryRequestContext | None = None,
        severity: str = "warning",
    ) -> T | None:
        try:
            return func()
        except Exception:
            self._observability.increment_metric(
                "governance_side_effect_failure_count",
                dimensions={"operation_name": operation_name},
            )
            self._observability.log_event(
                "governance.side_effect_failed",
                request_context=request_context,
                level="warning",
                payload={"operation_name": operation_name},
            )
            getattr(logger, severity.lower(), logger.warning)(
                "Governance side effect failed: %s",
                operation_name,
                exc_info=True,
            )
            return None

    def degrade_memory_retrieval(
        self,
        *,
        request_context: MemoryRequestContext,
        reason: str,
        payload: dict[str, object] | None = None,
    ) -> None:
        self._observability.increment_metric(
            "memory_retrieval_degraded_count",
            dimensions={"reason": reason},
        )
        self._observability.log_event(
            "memory.retrieval_degraded",
            request_context=request_context,
            level="warning",
            payload={"reason": reason, **dict(payload or {})},
        )

    def record_provider_fallback(
        self,
        *,
        request_context: MemoryRequestContext,
        provider: str,
        model: str,
        reason: str,
        payload: dict[str, object] | None = None,
    ) -> None:
        self._observability.increment_metric(
            "provider_fallback_count",
            dimensions={"provider": provider or "unknown", "reason": reason},
        )
        self._observability.log_event(
            "provider.fallback",
            request_context=request_context,
            level="warning",
            payload={
                "provider": provider,
                "model": model,
                "reason": reason,
                **dict(payload or {}),
            },
        )
        self.protect_side_effect(
            "security_event.provider_failure_fallback",
            lambda: self._audit_service.record_security_event(
                tenant_id=request_context.tenant_id,
                event_type="provider_failure_fallback",
                severity="medium",
                actor_user_id=request_context.user_id,
                session_id=request_context.session_id,
                request_id=request_context.request_id,
                event_payload={
                    "provider": provider,
                    "model": model,
                    "reason": reason,
                    **dict(payload or {}),
                },
            ),
            request_context=request_context,
        )
        self.protect_side_effect(
            "policy.provider_fallback",
            lambda: self._audit_service.record_policy_decision(
                request_id=request_context.request_id,
                policy_name="degradation_controller.provider_fallback",
                decision="fallback",
                reason=reason,
                target_type="provider_call",
                target_id=provider or "unknown_provider",
                payload={
                    "tenant_id": request_context.tenant_id,
                    "user_id": request_context.user_id,
                    "session_id": request_context.session_id,
                    "provider": provider,
                    "model": model,
                    **dict(payload or {}),
                },
            ),
            request_context=request_context,
        )
