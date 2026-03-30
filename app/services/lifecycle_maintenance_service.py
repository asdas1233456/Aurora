"""Background-friendly lifecycle maintenance for memory retention and forgetting."""

from __future__ import annotations

from app.config import AppConfig
from app.schemas import LifecycleMaintenanceReport, MemoryRequestContext
from app.services.access_governance_policy import AccessGovernancePolicy
from app.services.audit_service import AuditService
from app.services.forgetting_executor import ForgettingExecutor
from app.services.forgetting_planner import ForgettingPlanner
from app.services.memory_repository import MemoryRepository
from app.services.memory_value_evaluator import MemoryValueEvaluator
from app.services.observability_service import ObservabilityService
from app.services.persistence_utils import utc_now_iso
from app.services.retention_policy import RetentionPolicy
from app.services.storage_service import connect_state_db


class LifecycleMaintenanceService:
    """Run value recomputation and forgetting transitions outside the retrieval hot path."""

    def __init__(
        self,
        config: AppConfig,
        *,
        repository: MemoryRepository | None = None,
        retention_policy: RetentionPolicy | None = None,
        evaluator: MemoryValueEvaluator | None = None,
        planner: ForgettingPlanner | None = None,
        executor: ForgettingExecutor | None = None,
        governance_policy: AccessGovernancePolicy | None = None,
        audit_service: AuditService | None = None,
        observability: ObservabilityService | None = None,
    ) -> None:
        self._config = config
        self._repository = repository or MemoryRepository(config)
        self._retention_policy = retention_policy or RetentionPolicy()
        self._evaluator = evaluator or MemoryValueEvaluator(self._retention_policy)
        self._planner = planner or ForgettingPlanner()
        self._governance_policy = governance_policy or AccessGovernancePolicy()
        self._audit_service = audit_service or AuditService(config)
        self._observability = observability or ObservabilityService(config)
        self._executor = executor or ForgettingExecutor(
            config,
            repository=self._repository,
            governance_audit_service=self._audit_service,
            observability=self._observability,
        )

    def run_due(
        self,
        *,
        tenant_id: str | None = None,
        limit: int = 100,
        dry_run: bool = False,
        request_context: MemoryRequestContext | None = None,
    ) -> LifecycleMaintenanceReport:
        evaluated_count = 0
        updated_count = 0
        unchanged_count = 0
        deprioritized_count = 0
        hidden_count = 0
        expired_count = 0
        archived_count = 0
        touched_memory_ids: list[str] = []
        run_now = utc_now_iso()
        system_request_context = request_context or MemoryRequestContext(
            request_id=f"lifecycle:{run_now}",
            tenant_id=tenant_id or "local_tenant",
            user_id="system",
            project_id="system",
            session_id="system:lifecycle",
            actor_role="system",
            allow_shared_scope_write=True,
            allow_global_write=True,
        )
        batch_decision = self._governance_policy.authorize_batch_action(
            system_request_context,
            action_name="lifecycle_maintenance",
        )
        self._audit_service.record_policy_decision(
            request_id=system_request_context.request_id,
            policy_name=batch_decision.policy_name,
            decision=batch_decision.decision,
            reason=batch_decision.reason,
            target_type="lifecycle_maintenance",
            target_id=system_request_context.tenant_id,
            payload=batch_decision.payload,
        )
        if not batch_decision.allowed:
            raise PermissionError(batch_decision.reason)

        with connect_state_db(self._config) as connection:
            due_facts = self._repository.list_due_for_retention_evaluation(
                now=run_now,
                tenant_id=tenant_id,
                limit=limit,
                connection=connection,
            )
            for memory_fact in due_facts:
                evaluated_count += 1
                policy = self._retention_policy.resolve(memory_fact)
                assessment = self._evaluator.evaluate(memory_fact, policy=policy, now=run_now)
                decision = self._planner.plan(memory_fact, assessment=assessment, policy=policy, now=run_now)
                changed = self._executor.execute(
                    memory_fact,
                    assessment=assessment,
                    decision=decision,
                    request_context=system_request_context,
                    connection=connection,
                    dry_run=dry_run,
                )
                if changed:
                    updated_count += 1
                    touched_memory_ids.append(memory_fact.id)
                    if decision.action == "de-prioritize":
                        deprioritized_count += 1
                    elif decision.action == "hide_from_default":
                        hidden_count += 1
                    elif decision.action == "expire":
                        expired_count += 1
                    elif decision.action == "archive":
                        archived_count += 1
                else:
                    unchanged_count += 1

        if deprioritized_count:
            self._observability.increment_metric(
                "retention_deprioritized_count",
                value=float(deprioritized_count),
                dimensions={"tenant_id": system_request_context.tenant_id},
            )
        if archived_count:
            self._observability.increment_metric(
                "retention_archived_count",
                value=float(archived_count),
                dimensions={"tenant_id": system_request_context.tenant_id},
            )
        if expired_count:
            self._observability.increment_metric(
                "expired_memory_count",
                value=float(expired_count),
                dimensions={"tenant_id": system_request_context.tenant_id},
            )

        return LifecycleMaintenanceReport(
            evaluated_count=evaluated_count,
            updated_count=updated_count,
            unchanged_count=unchanged_count,
            deprioritized_count=deprioritized_count,
            hidden_count=hidden_count,
            expired_count=expired_count,
            archived_count=archived_count,
            dry_run=dry_run,
            touched_memory_ids=touched_memory_ids,
        )
