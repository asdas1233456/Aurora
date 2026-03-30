"""Guarded write operations for Aurora memory facts."""

from __future__ import annotations

from dataclasses import replace
from uuid import uuid4

from app.config import AppConfig
from app.schemas import MemoryFact, MemoryFactCreate, MemoryFactStatus, MemoryRequestContext, MemoryWriteResult, ScopeType
from app.services.abuse_guard import AbuseGuard, RateLimitExceededError
from app.services.access_governance_policy import AccessGovernancePolicy
from app.services.audit_service import AuditService
from app.services.conflict_resolver import ConflictResolver
from app.services.consistency_checker import ConsistencyChecker
from app.services.degradation_controller import DegradationController
from app.services.fact_identity_resolver import FactIdentityResolver
from app.services.memory_access_policy import MemoryAccessPolicy
from app.services.memory_repository import MemoryRepository
from app.services.memory_scope import ScopeResolver
from app.services.memory_value_evaluator import MemoryValueEvaluator
from app.services.observability_service import ObservabilityService
from app.services.persistence_utils import utc_now_iso
from app.services.prompt_injection_guard import PromptInjectionGuard
from app.services.retention_audit_service import RetentionAuditService
from app.services.retention_policy import RetentionPolicy
from app.services.sensitive_content_guard import SensitiveContentGuard
from app.services.storage_service import connect_state_db
from app.services.versioning_service import VersioningService


class MemoryWriteService:
    """Validate writes before persisting memory facts."""

    def __init__(
        self,
        config: AppConfig,
        *,
        repository: MemoryRepository | None = None,
        access_policy: MemoryAccessPolicy | None = None,
        audit_service: AuditService | None = None,
        scope_resolver: ScopeResolver | None = None,
        identity_resolver: FactIdentityResolver | None = None,
        consistency_checker: ConsistencyChecker | None = None,
        conflict_resolver: ConflictResolver | None = None,
        versioning_service: VersioningService | None = None,
        retention_policy: RetentionPolicy | None = None,
        value_evaluator: MemoryValueEvaluator | None = None,
        retention_audit_service: RetentionAuditService | None = None,
        governance_policy: AccessGovernancePolicy | None = None,
        sensitive_guard: SensitiveContentGuard | None = None,
        prompt_injection_guard: PromptInjectionGuard | None = None,
        abuse_guard: AbuseGuard | None = None,
        observability: ObservabilityService | None = None,
        degradation_controller: DegradationController | None = None,
    ) -> None:
        self._repository = repository or MemoryRepository(config)
        self._scope_resolver = scope_resolver or ScopeResolver()
        self._access_policy = access_policy or MemoryAccessPolicy(self._scope_resolver)
        self._audit_service = audit_service or AuditService(config)
        self._identity_resolver = identity_resolver or FactIdentityResolver()
        self._consistency_checker = consistency_checker or ConsistencyChecker(self._repository)
        self._conflict_resolver = conflict_resolver or ConflictResolver()
        self._versioning_service = versioning_service or VersioningService(self._repository)
        self._retention_policy = retention_policy or RetentionPolicy()
        self._value_evaluator = value_evaluator or MemoryValueEvaluator(self._retention_policy)
        self._retention_audit_service = retention_audit_service or RetentionAuditService(config)
        self._governance_policy = governance_policy or AccessGovernancePolicy(
            scope_resolver=self._scope_resolver,
            access_policy=self._access_policy,
        )
        self._sensitive_guard = sensitive_guard or SensitiveContentGuard()
        self._prompt_injection_guard = prompt_injection_guard or PromptInjectionGuard()
        self._abuse_guard = abuse_guard or AbuseGuard()
        self._observability = observability or ObservabilityService(config)
        self._degradation_controller = degradation_controller or DegradationController(
            config,
            audit_service=self._audit_service,
            observability=self._observability,
        )
        self._config = config

    def build_create_payload(
        self,
        request_context: MemoryRequestContext,
        *,
        content: str,
        memory_type: str,
        scope_type: ScopeType | None = None,
        scope_id: str | None = None,
        source_kind: str = "chat",
        confirmed: bool = False,
        subject_key: str | None = None,
        fact_key: str | None = None,
        correction_of: str | None = None,
        source_type: str | None = None,
        source_confidence: float = 0.0,
        reviewed_by_human: bool | None = None,
        consistency_group_id: str | None = None,
    ) -> MemoryFactCreate:
        normalized_content = content.strip()
        if not normalized_content:
            raise ValueError("Memory content must not be empty.")

        final_scope_type = scope_type or self.default_scope_for_type(memory_type)
        # Callers can override scope_id for internal/manual validation, but policy still re-checks it.
        return MemoryFactCreate(
            tenant_id=request_context.tenant_id,
            owner_user_id=request_context.user_id,
            project_id=request_context.project_id,
            scope_type=final_scope_type,
            scope_id=(scope_id or self._scope_id_for(request_context, final_scope_type)).strip(),
            type=memory_type,
            content=normalized_content,
            source_session_id=request_context.session_id,
            source_kind=source_kind,
            confirmed=confirmed,
            subject_key=subject_key,
            fact_key=fact_key,
            correction_of=correction_of,
            source_type=source_type,
            source_confidence=source_confidence,
            reviewed_by_human=reviewed_by_human,
            consistency_group_id=consistency_group_id,
        )

    def create_memory_fact(
        self,
        request_context: MemoryRequestContext,
        payload: MemoryFactCreate,
    ) -> MemoryFact:
        return self.write_memory_fact(request_context, payload).memory_fact

    def write_memory_fact(
        self,
        request_context: MemoryRequestContext,
        payload: MemoryFactCreate,
    ) -> MemoryWriteResult:
        rate_limit_action = "memory_correction" if payload.correction_of else "memory_write"
        rate_limit = self._abuse_guard.check_and_consume(
            request_context,
            action_name=rate_limit_action,
        )
        if not rate_limit.allowed:
            self._handle_rate_limit(
                request_context,
                rate_limit_action=rate_limit_action,
                payload=payload,
                rate_limit_reason=rate_limit.reason,
                retry_after_seconds=rate_limit.retry_after_seconds,
            )
            if payload.correction_of:
                self._observability.increment_metric("correction_rejected_count")
            raise RateLimitExceededError(rate_limit.reason)

        if payload.scope_type in {"team", "global"}:
            self._observability.increment_metric(
                "scope_upgrade_attempt_count",
                dimensions={"scope_type": payload.scope_type},
            )

        if payload.correction_of:
            self._observability.increment_metric("correction_request_count")

        content_decision = self._sensitive_guard.scan(payload.content)
        if content_decision.action == "block":
            self._observability.increment_metric("memory_write_rejected_count")
            self._observability.increment_metric("sensitive_memory_block_count")
            if payload.correction_of:
                self._observability.increment_metric("correction_rejected_count")
            self._record_policy_decision(
                request_context,
                policy_name="sensitive_content_guard.scan",
                decision="deny",
                reason=content_decision.reason,
                target_type="memory_write",
                target_id=f"{payload.scope_type}:{payload.scope_id}",
                payload={
                    "scope_type": payload.scope_type,
                    "scope_id": payload.scope_id,
                    "findings": [item.rule_id for item in content_decision.findings],
                },
            )
            self._record_security_event(
                request_context,
                event_type="sensitive_memory_detected",
                severity=content_decision.severity,
                payload={
                    "scope_type": payload.scope_type,
                    "scope_id": payload.scope_id,
                    "reason": content_decision.reason,
                    "findings": [item.rule_id for item in content_decision.findings],
                },
            )
            raise PermissionError("Sensitive content cannot be persisted into long-term memory.")

        redaction_applied = content_decision.action == "redact" and content_decision.sanitized_content != payload.content
        if redaction_applied:
            payload = replace(payload, content=content_decision.sanitized_content)
            self._observability.increment_metric("redaction_applied_count")
            self._record_policy_decision(
                request_context,
                policy_name="sensitive_content_guard.scan",
                decision="redact",
                reason=content_decision.reason,
                target_type="memory_write",
                target_id=f"{payload.scope_type}:{payload.scope_id}",
                payload={
                    "scope_type": payload.scope_type,
                    "scope_id": payload.scope_id,
                    "findings": [item.rule_id for item in content_decision.findings],
                },
            )
            self._record_security_event(
                request_context,
                event_type="sensitive_memory_detected",
                severity=content_decision.severity,
                payload={
                    "scope_type": payload.scope_type,
                    "scope_id": payload.scope_id,
                    "reason": content_decision.reason,
                    "findings": [item.rule_id for item in content_decision.findings],
                },
            )

        governance_decision = self._governance_policy.authorize_write(request_context, payload)
        if payload.scope_type in {"team", "global"} or not governance_decision.allowed:
            self._record_policy_decision(
                request_context,
                policy_name=governance_decision.policy_name,
                decision=governance_decision.decision,
                reason=governance_decision.reason,
                target_type="memory_write",
                target_id=f"{payload.scope_type}:{payload.scope_id}",
                payload=governance_decision.payload,
            )
        if not governance_decision.allowed:
            self._observability.increment_metric("memory_write_rejected_count")
            self._observability.increment_metric("unauthorized_access_attempt_count")
            if payload.correction_of:
                self._observability.increment_metric("correction_rejected_count")
            self._record_security_event(
                request_context,
                event_type=(
                    "unauthorized_scope_write_attempt"
                    if payload.scope_type in {"team", "global"}
                    else "policy_blocked_write"
                ),
                severity=governance_decision.severity,
                payload={
                    "scope_type": payload.scope_type,
                    "scope_id": payload.scope_id,
                    "reason": governance_decision.reason,
                },
            )
            raise PermissionError(governance_decision.reason)

        trust_decision = self._prompt_injection_guard.evaluate_write(payload)
        if payload.scope_type in {"team", "global"} or not trust_decision.allowed:
            self._record_policy_decision(
                request_context,
                policy_name=trust_decision.policy_name,
                decision=trust_decision.decision,
                reason=trust_decision.reason,
                target_type="memory_write",
                target_id=f"{payload.scope_type}:{payload.scope_id}",
                payload=trust_decision.payload,
            )
        if not trust_decision.allowed:
            self._observability.increment_metric("memory_write_rejected_count")
            self._observability.increment_metric("suspicious_content_detected_count")
            if payload.correction_of:
                self._observability.increment_metric("correction_rejected_count")
            self._record_security_event(
                request_context,
                event_type="suspicious_prompt_injection",
                severity=trust_decision.severity,
                payload={
                    "scope_type": payload.scope_type,
                    "scope_id": payload.scope_id,
                    "reason": trust_decision.reason,
                    **trust_decision.payload,
                },
            )
            raise PermissionError(trust_decision.reason)

        self._observability.log_event(
            "memory.write_requested",
            request_context=request_context,
            payload={
                "scope_type": payload.scope_type,
                "memory_type": payload.type,
                "correction_of": payload.correction_of or "",
                "source_type": payload.source_type or "",
                "source_kind": payload.source_kind,
            },
        )

        with connect_state_db(self._config) as connection:
            identity = self._identity_resolver.resolve(payload)
            check_result = self._consistency_checker.check(
                payload,
                identity,
                connection=connection,
            )
            resolved_result = self._conflict_resolver.resolve(check_result, identity)

            if resolved_result.operation == "noop":
                current_fact = resolved_result.current_fact
                if current_fact is None:
                    raise ValueError("Consistency checker returned noop without a current fact.")
                self._safe_record_memory_action(
                    request_context=request_context,
                    memory_fact_id=current_fact.id,
                    action="read",
                    scope_type=current_fact.scope_type,
                    decision_reason=resolved_result.reason,
                    connection=connection,
                )
                return MemoryWriteResult(
                    memory_fact=current_fact,
                    operation=resolved_result.operation,
                    reason=resolved_result.reason,
                    subject_key=identity.subject_key,
                    fact_key=identity.fact_key,
                    consistency_group_id=identity.consistency_group_id,
                )

            versioned_payload = self._versioning_service.build_versioned_payload(
                payload,
                identity,
                resolved_result,
            )
            created_memory_fact_id = str(uuid4())
            write_timestamp = utc_now_iso()
            draft_memory_fact = self._build_draft_memory_fact(
                created_memory_fact_id,
                versioned_payload,
                created_at=write_timestamp,
            )
            retention_policy = self._retention_policy.resolve(draft_memory_fact)
            retention_assessment = self._value_evaluator.evaluate(
                draft_memory_fact,
                policy=retention_policy,
                now=write_timestamp,
            )
            initialized_payload = self._apply_retention_assessment(
                versioned_payload,
                retention_assessment,
            )
            superseded_fact_ids = self._versioning_service.apply_supersession(
                created_memory_fact_id,
                resolved_result,
                connection=connection,
                now=write_timestamp,
            )
            created = self._repository.create_memory_fact(
                initialized_payload,
                connection=connection,
                memory_fact_id=created_memory_fact_id,
                now=write_timestamp,
            )

            primary_action = self._primary_action_for_operation(resolved_result.operation)
            self._safe_record_memory_action(
                request_context=request_context,
                memory_fact_id=created.id,
                action=primary_action,
                scope_type=created.scope_type,
                decision_reason=resolved_result.reason,
                connection=connection,
            )
            if redaction_applied:
                self._safe_record_memory_action(
                    request_context=request_context,
                    memory_fact_id=created.id,
                    action="redact",
                    scope_type=created.scope_type,
                    decision_reason=content_decision.reason,
                    connection=connection,
                )

            retention_record = self._degradation_controller.protect_side_effect(
                "retention.initialized",
                lambda: self._retention_audit_service.log_event(
                    tenant_id=created.tenant_id,
                    memory_fact_id=created.id,
                    action="initialized",
                    reason="retention metadata initialized after scope, consistency, and correction governance",
                    value_score=created.value_score,
                    retention_level=created.retention_level,
                    retrieval_visibility=created.retrieval_visibility,
                    forgetting_status=created.forgetting_status,
                    policy_id=retention_assessment.retention_policy_id or "",
                    details={
                        "policy_id": retention_assessment.retention_policy_id,
                        "ttl_seconds": retention_assessment.ttl_seconds,
                        "expires_at": retention_assessment.expires_at,
                        "decay_factor": retention_assessment.decay_factor,
                        "reasons": list(retention_assessment.reasons),
                    },
                    connection=connection,
                    created_at=write_timestamp,
                ),
                request_context=request_context,
            )
            if retention_record is not None:
                self._observability.log_event(
                    "memory.retention_initialized",
                    request_context=request_context,
                    payload=self._observability.build_retention_trace_payload(
                        audit_record=retention_record,
                        memory_id=created.id,
                    ),
                )
            for superseded_fact_id in superseded_fact_ids:
                self._safe_record_memory_action(
                    request_context=request_context,
                    memory_fact_id=superseded_fact_id,
                    action="deprecate",
                    scope_type=created.scope_type,
                    decision_reason=resolved_result.reason,
                    connection=connection,
                )

            self._observability.increment_metric("memory_create_count")
            if resolved_result.operation == "correction":
                self._observability.increment_metric("correction_applied_count")
            if superseded_fact_ids:
                self._observability.increment_metric(
                    "superseded_memory_count",
                    value=float(len(superseded_fact_ids)),
                )
            self._observability.log_event(
                "memory.write_completed",
                request_context=request_context,
                payload={
                    "memory_fact_id": created.id,
                    "scope_type": created.scope_type,
                    "memory_type": created.type,
                    "operation": resolved_result.operation,
                    "superseded_fact_ids": superseded_fact_ids,
                    "value_score": created.value_score,
                    "retention_level": created.retention_level,
                },
            )
            return MemoryWriteResult(
                memory_fact=created,
                operation=resolved_result.operation,
                reason=resolved_result.reason,
                subject_key=identity.subject_key,
                fact_key=identity.fact_key,
                consistency_group_id=identity.consistency_group_id,
                superseded_fact_ids=superseded_fact_ids,
            )

    def get_memory_fact_by_id(
        self,
        request_context: MemoryRequestContext,
        memory_fact_id: str,
    ) -> MemoryFact | None:
        resolved_context = self._scope_resolver.resolve(request_context)
        memory_fact = self._repository.get_memory_fact_by_id(memory_fact_id)
        if memory_fact is None:
            return None
        if not self._access_policy.can_read(resolved_context, memory_fact):
            return None

        self._safe_record_memory_action(
            request_context=request_context,
            memory_fact_id=memory_fact.id,
            action="read",
            scope_type=memory_fact.scope_type,
        )
        return memory_fact

    def list_memory_history(
        self,
        request_context: MemoryRequestContext,
        memory_fact_id: str,
        *,
        limit: int = 20,
    ) -> list[MemoryFact]:
        base_fact = self.get_memory_fact_by_id(request_context, memory_fact_id)
        if base_fact is None:
            return []

        items = self._repository.list_by_filters(
            tenant_id=base_fact.tenant_id,
            scope_type=base_fact.scope_type,
            scope_id=base_fact.scope_id,
            consistency_group_id=base_fact.consistency_group_id,
            limit=limit,
        )
        visible_items = [
            item
            for item in items
            if self._access_policy.can_read(request_context, item)
        ]
        visible_items.sort(key=lambda item: (item.version, item.updated_at, item.created_at), reverse=True)
        return visible_items

    def update_memory_fact_status(
        self,
        request_context: MemoryRequestContext,
        *,
        memory_fact_id: str,
        status: MemoryFactStatus,
    ) -> MemoryFact | None:
        existing = self.get_memory_fact_by_id(request_context, memory_fact_id)
        if existing is None:
            return None

        candidate = MemoryFactCreate(
            tenant_id=existing.tenant_id,
            owner_user_id=existing.owner_user_id,
            project_id=existing.project_id,
            scope_type=existing.scope_type,
            scope_id=existing.scope_id,
            type=existing.type,
            content=existing.content,
            source_session_id=existing.source_session_id,
            status=status,
            confirmed=True,
            subject_key=existing.subject_key,
            fact_key=existing.fact_key,
            version=existing.version,
            superseded_by=existing.superseded_by,
            supersedes=existing.supersedes,
            correction_of=existing.correction_of,
            source_type=existing.source_type,
            source_confidence=existing.source_confidence,
            reviewed_by_human=existing.reviewed_by_human,
            consistency_group_id=existing.consistency_group_id,
        )

        action_name = "delete" if status == "deleted" else "update"
        governance_decision = self._governance_policy.authorize_status_change(
            request_context,
            existing,
            action_name=action_name,
        )
        if action_name in {"delete"} or not governance_decision.allowed:
            self._record_policy_decision(
                request_context,
                policy_name=governance_decision.policy_name,
                decision=governance_decision.decision,
                reason=governance_decision.reason,
                target_type="memory_fact",
                target_id=existing.id,
                payload=governance_decision.payload,
            )
        if not governance_decision.allowed:
            self._observability.increment_metric("unauthorized_access_attempt_count")
            raise PermissionError(governance_decision.reason)

        resolved_context = self._scope_resolver.resolve(request_context)
        if not self._access_policy.can_write(resolved_context, candidate):
            raise PermissionError("This request is not allowed to update the memory fact.")

        updated = self._repository.update_memory_fact_status(memory_fact_id, status)
        if updated is not None:
            self._repository.update_retention_state(
                updated.id,
                next_evaluation_at=utc_now_iso(),
            )
            audit_action = "delete" if status == "deleted" else ("deprecate" if status == "superseded" else "update")
            self._safe_record_memory_action(
                request_context=request_context,
                memory_fact_id=updated.id,
                action=audit_action,
                scope_type=updated.scope_type,
                decision_reason=f"status_changed_to:{status}",
            )
        return updated

    @staticmethod
    def _primary_action_for_operation(operation: str) -> str:
        if operation == "correction":
            return "correct"
        if operation == "update":
            return "update"
        return "create"

    def _safe_record_memory_action(
        self,
        *,
        request_context: MemoryRequestContext,
        memory_fact_id: str,
        action: str,
        scope_type: str = "",
        retrieval_stage: str = "",
        decision_reason: str = "",
        connection=None,
    ) -> None:
        self._degradation_controller.protect_side_effect(
            f"audit.memory.{action}",
            lambda: self._audit_service.record_memory_action(
                request_context=request_context,
                memory_fact_id=memory_fact_id,
                action=action,
                scope_type=scope_type,
                retrieval_stage=retrieval_stage,
                decision_reason=decision_reason,
                connection=connection,
            ),
            request_context=request_context,
        )

    def _record_policy_decision(
        self,
        request_context: MemoryRequestContext,
        *,
        policy_name: str,
        decision: str,
        reason: str,
        target_type: str,
        target_id: str,
        payload: dict[str, object] | None = None,
    ) -> None:
        self._degradation_controller.protect_side_effect(
            f"policy.{policy_name}",
            lambda: self._audit_service.record_policy_decision(
                request_id=request_context.request_id,
                policy_name=policy_name,
                decision=decision,
                reason=reason,
                target_type=target_type,
                target_id=target_id,
                payload={
                    "tenant_id": request_context.tenant_id,
                    "user_id": request_context.user_id,
                    "session_id": request_context.session_id,
                    **dict(payload or {}),
                },
            ),
            request_context=request_context,
        )

    def _record_security_event(
        self,
        request_context: MemoryRequestContext,
        *,
        event_type: str,
        severity: str,
        payload: dict[str, object] | None = None,
        target_memory_fact_id: str | None = None,
    ) -> None:
        self._degradation_controller.protect_side_effect(
            f"security.{event_type}",
            lambda: self._audit_service.record_security_event(
                tenant_id=request_context.tenant_id,
                event_type=event_type,
                severity=severity,
                actor_user_id=request_context.user_id,
                session_id=request_context.session_id,
                request_id=request_context.request_id,
                target_memory_fact_id=target_memory_fact_id,
                event_payload=payload,
            ),
            request_context=request_context,
        )

    def _handle_rate_limit(
        self,
        request_context: MemoryRequestContext,
        *,
        rate_limit_action: str,
        payload: MemoryFactCreate,
        rate_limit_reason: str,
        retry_after_seconds: int,
    ) -> None:
        self._observability.increment_metric("rate_limit_trigger_count")
        self._record_policy_decision(
            request_context,
            policy_name="abuse_guard.rate_limit",
            decision="throttle",
            reason=rate_limit_reason,
            target_type="memory_write",
            target_id=f"{payload.scope_type}:{payload.scope_id}",
            payload={
                "action_name": rate_limit_action,
                "retry_after_seconds": retry_after_seconds,
            },
        )
        self._record_security_event(
            request_context,
            event_type="rate_limit_triggered",
            severity="medium",
            payload={
                "action_name": rate_limit_action,
                "scope_type": payload.scope_type,
                "scope_id": payload.scope_id,
                "retry_after_seconds": retry_after_seconds,
                "reason": rate_limit_reason,
            },
        )
        self._observability.log_event(
            "memory.rate_limited",
            request_context=request_context,
            level="warning",
            payload={
                "action_name": rate_limit_action,
                "scope_type": payload.scope_type,
                "scope_id": payload.scope_id,
                "retry_after_seconds": retry_after_seconds,
                "reason": rate_limit_reason,
            },
        )

    @staticmethod
    def default_scope_for_type(memory_type: str) -> ScopeType:
        if memory_type == "preference":
            return "user"
        if memory_type in {"decision", "pending_issue"}:
            return "project"
        return "session"

    @staticmethod
    def _scope_id_for(request_context: MemoryRequestContext, scope_type: ScopeType) -> str:
        if scope_type == "session":
            return request_context.session_id
        if scope_type == "user":
            return request_context.user_id
        if scope_type == "project":
            return request_context.project_id
        if scope_type == "team":
            return request_context.team_id
        return request_context.global_scope_id

    @staticmethod
    def _build_draft_memory_fact(
        memory_fact_id: str,
        payload: MemoryFactCreate,
        *,
        created_at: str,
    ) -> MemoryFact:
        return MemoryFact(
            id=memory_fact_id,
            tenant_id=payload.tenant_id,
            owner_user_id=payload.owner_user_id,
            project_id=payload.project_id,
            scope_type=payload.scope_type,
            scope_id=payload.scope_id,
            type=payload.type,
            content=payload.content,
            status=payload.status,
            source_session_id=payload.source_session_id,
            created_at=created_at,
            updated_at=created_at,
            subject_key=payload.subject_key or "",
            fact_key=payload.fact_key or "",
            version=int(payload.version or 1),
            superseded_by=payload.superseded_by,
            supersedes=payload.supersedes,
            correction_of=payload.correction_of,
            source_type=payload.source_type or "system_generated",
            source_confidence=float(payload.source_confidence or 0.0),
            reviewed_by_human=payload.reviewed_by_human,
            consistency_group_id=payload.consistency_group_id,
        )

    @staticmethod
    def _apply_retention_assessment(
        payload: MemoryFactCreate,
        assessment,
    ) -> MemoryFactCreate:
        initial_visibility = "normal" if payload.status == "active" else "hidden_from_default"
        initial_forgetting_status = "none" if payload.status == "active" else "cooling"
        return MemoryFactCreate(
            tenant_id=payload.tenant_id,
            owner_user_id=payload.owner_user_id,
            project_id=payload.project_id,
            scope_type=payload.scope_type,
            scope_id=payload.scope_id,
            type=payload.type,
            content=payload.content,
            source_session_id=payload.source_session_id,
            status=payload.status,
            source_kind=payload.source_kind,
            confirmed=payload.confirmed,
            subject_key=payload.subject_key,
            fact_key=payload.fact_key,
            version=payload.version,
            superseded_by=payload.superseded_by,
            supersedes=payload.supersedes,
            correction_of=payload.correction_of,
            source_type=payload.source_type,
            source_confidence=payload.source_confidence,
            reviewed_by_human=payload.reviewed_by_human,
            consistency_group_id=payload.consistency_group_id,
            value_score=assessment.value_score,
            retention_level=assessment.retention_level,
            ttl_seconds=assessment.ttl_seconds,
            expires_at=assessment.expires_at,
            last_accessed_at=payload.last_accessed_at,
            access_count=payload.access_count,
            successful_use_count=payload.successful_use_count,
            decay_factor=assessment.decay_factor,
            archived_at=payload.archived_at,
            retrieval_visibility=initial_visibility,
            forgetting_status=initial_forgetting_status,
            next_evaluation_at=assessment.next_evaluation_at,
            retention_policy_id=assessment.retention_policy_id,
            archive_bucket=assessment.archive_bucket,
        )
