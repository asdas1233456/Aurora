"""Execute retention decisions and persist audit-friendly state changes."""

from __future__ import annotations

import sqlite3

from app.config import AppConfig
from app.schemas import ForgettingDecision, MemoryFact, MemoryRequestContext, MemoryValueAssessment
from app.services.audit_service import AuditService
from app.services.degradation_controller import DegradationController
from app.services.memory_repository import MemoryRepository
from app.services.observability_service import ObservabilityService
from app.services.retention_audit_service import RetentionAuditService


class ForgettingExecutor:
    """Persist value and forgetting state transitions after planning is complete."""

    def __init__(
        self,
        config: AppConfig,
        *,
        repository: MemoryRepository | None = None,
        audit_service: RetentionAuditService | None = None,
        governance_audit_service: AuditService | None = None,
        observability: ObservabilityService | None = None,
        degradation_controller: DegradationController | None = None,
    ) -> None:
        self._repository = repository or MemoryRepository(config)
        self._audit_service = audit_service or RetentionAuditService(config)
        self._governance_audit = governance_audit_service or AuditService(config)
        self._observability = observability or ObservabilityService(config)
        self._degradation_controller = degradation_controller or DegradationController(
            config,
            audit_service=self._governance_audit,
            observability=self._observability,
        )

    def execute(
        self,
        memory_fact: MemoryFact,
        *,
        assessment: MemoryValueAssessment,
        decision: ForgettingDecision,
        request_context: MemoryRequestContext | None = None,
        connection: sqlite3.Connection | None = None,
        dry_run: bool = False,
    ) -> bool:
        previous_state = {
            "value_score": memory_fact.value_score,
            "retention_level": memory_fact.retention_level,
            "retrieval_visibility": memory_fact.retrieval_visibility,
            "forgetting_status": memory_fact.forgetting_status,
            "archived_at": memory_fact.archived_at,
        }
        changed = self._has_changes(memory_fact, assessment=assessment, decision=decision)
        if dry_run:
            return changed

        if changed:
            updated = self._repository.update_retention_state(
                memory_fact.id,
                value_score=assessment.value_score,
                retention_level=assessment.retention_level,
                ttl_seconds=assessment.ttl_seconds,
                expires_at=assessment.expires_at,
                decay_factor=assessment.decay_factor,
                archived_at=decision.archived_at,
                retrieval_visibility=decision.retrieval_visibility,
                forgetting_status=decision.forgetting_status,
                next_evaluation_at=decision.next_evaluation_at,
                retention_policy_id=assessment.retention_policy_id,
                archive_bucket=decision.archive_bucket,
                connection=connection,
            )
            if updated is not None:
                memory_fact = updated

        if changed:
            self._audit_service.log_event(
                tenant_id=memory_fact.tenant_id,
                memory_fact_id=memory_fact.id,
                action=_audit_action(decision.action, previous_state),
                reason=decision.reason,
                value_score=assessment.value_score,
                retention_level=assessment.retention_level,
                retrieval_visibility=decision.retrieval_visibility,
                forgetting_status=decision.forgetting_status,
                policy_id=assessment.retention_policy_id or "",
                details={
                    "planner_action": decision.action,
                    "reasons": list(decision.reasons),
                    "assessment_reasons": list(assessment.reasons),
                    "score_breakdown": {
                        "scope_value": assessment.scope_value,
                        "type_value": assessment.type_value,
                        "recency_value": assessment.recency_value,
                        "usage_value": assessment.usage_value,
                        "source_value": assessment.source_value,
                        "correction_penalty": assessment.correction_penalty,
                        "expiration_penalty": assessment.expiration_penalty,
                    },
                    "previous_state": previous_state,
                    "next_state": {
                        "value_score": assessment.value_score,
                        "retention_level": assessment.retention_level,
                        "retrieval_visibility": decision.retrieval_visibility,
                        "forgetting_status": decision.forgetting_status,
                        "archived_at": decision.archived_at,
                    },
                },
                connection=connection,
            )
            if request_context is not None and decision.action == "archive":
                self._degradation_controller.protect_side_effect(
                    "audit.memory.archive",
                    lambda: self._governance_audit.record_memory_action(
                        request_context=request_context,
                        memory_fact_id=memory_fact.id,
                        action="archive",
                        scope_type=memory_fact.scope_type,
                        decision_reason=decision.reason,
                        connection=connection,
                    ),
                    request_context=request_context,
                )
        return changed

    @staticmethod
    def _has_changes(
        memory_fact: MemoryFact,
        *,
        assessment: MemoryValueAssessment,
        decision: ForgettingDecision,
    ) -> bool:
        current_value_score = round(float(memory_fact.value_score or 0.0), 2)
        next_value_score = round(float(assessment.value_score or 0.0), 2)
        return any(
            (
                current_value_score != next_value_score,
                memory_fact.retention_level != assessment.retention_level,
                memory_fact.ttl_seconds != assessment.ttl_seconds,
                (memory_fact.expires_at or "") != (assessment.expires_at or ""),
                round(float(memory_fact.decay_factor or 1.0), 4) != round(float(assessment.decay_factor or 1.0), 4),
                (memory_fact.archived_at or "") != (decision.archived_at or ""),
                memory_fact.retrieval_visibility != decision.retrieval_visibility,
                memory_fact.forgetting_status != decision.forgetting_status,
                (memory_fact.next_evaluation_at or "") != (decision.next_evaluation_at or ""),
                (memory_fact.retention_policy_id or "") != (assessment.retention_policy_id or ""),
                (memory_fact.archive_bucket or "") != (decision.archive_bucket or ""),
            )
        )


def _audit_action(planner_action: str, previous_state: dict[str, object]) -> str:
    if planner_action == "de-prioritize":
        return "deprioritized"
    if planner_action == "hide_from_default":
        return "hidden_from_default"
    if planner_action == "expire":
        return "expired"
    if planner_action == "archive":
        return "archived"
    if (
        str(previous_state.get("retrieval_visibility") or "normal") != "normal"
        or str(previous_state.get("forgetting_status") or "none") != "none"
    ):
        return "restored"
    return "evaluated"
