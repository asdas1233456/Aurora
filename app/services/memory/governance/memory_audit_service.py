"""Backward-compatible wrapper over the centralized audit service."""

from __future__ import annotations

from app.config import AppConfig
from app.schemas import MemoryAccessAuditRecord, MemoryAuditAction, MemoryRequestContext
from app.services.audit_service import AuditService


class MemoryAuditService:
    """Preserve the old interface while all new writes go through AuditService."""

    def __init__(self, config: AppConfig) -> None:
        self._audit_service = AuditService(config)

    def log_action(
        self,
        request_context: MemoryRequestContext,
        *,
        memory_fact_id: str,
        action: MemoryAuditAction,
        connection=None,
        scope_type: str = "",
        retrieval_stage: str = "",
        decision_reason: str = "",
    ) -> MemoryAccessAuditRecord:
        return self._audit_service.record_memory_action(
            request_context=request_context,
            memory_fact_id=memory_fact_id,
            action=action,
            scope_type=scope_type,
            retrieval_stage=retrieval_stage,
            decision_reason=decision_reason,
            connection=connection,
        )

    def record_memory_action(
        self,
        *,
        request_context: MemoryRequestContext,
        memory_fact_id: str,
        action: MemoryAuditAction,
        scope_type: str = "",
        retrieval_stage: str = "",
        decision_reason: str = "",
        connection=None,
    ) -> MemoryAccessAuditRecord:
        return self.log_action(
            request_context,
            memory_fact_id=memory_fact_id,
            action=action,
            connection=connection,
            scope_type=scope_type,
            retrieval_stage=retrieval_stage,
            decision_reason=decision_reason,
        )

    def list_by_request_id(self, tenant_id: str, request_id: str) -> list[MemoryAccessAuditRecord]:
        return self._audit_service.list_memory_actions_by_request(tenant_id, request_id)

    def list_by_session_id(self, tenant_id: str, session_id: str) -> list[MemoryAccessAuditRecord]:
        return self._audit_service.list_memory_actions_by_session(tenant_id, session_id)

    def list_by_memory_fact_id(
        self,
        tenant_id: str,
        memory_fact_id: str,
    ) -> list[MemoryAccessAuditRecord]:
        return self._audit_service.list_memory_actions_by_fact(tenant_id, memory_fact_id)
