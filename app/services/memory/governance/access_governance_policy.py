"""Govern high-risk memory operations beyond basic scope isolation."""

from __future__ import annotations

from app.schemas import MemoryFact, MemoryFactCreate, MemoryRequestContext, PolicyEvaluation
from app.services.memory_access_policy import MemoryAccessPolicy
from app.services.memory_scope import ScopeResolver


_SCOPE_RISK_ORDER = {
    "session": 0,
    "user": 1,
    "project": 2,
    "team": 3,
    "global": 4,
}


class AccessGovernancePolicy:
    """Rule-driven governance layer that can later evolve into a policy engine."""

    def __init__(
        self,
        *,
        scope_resolver: ScopeResolver | None = None,
        access_policy: MemoryAccessPolicy | None = None,
    ) -> None:
        resolver = scope_resolver or ScopeResolver()
        self._access_policy = access_policy or MemoryAccessPolicy(resolver)

    def authorize_write(
        self,
        request_context: MemoryRequestContext,
        payload: MemoryFactCreate,
    ) -> PolicyEvaluation:
        if not self._access_policy.can_write(request_context, payload):
            event_type = (
                "unauthorized_scope_write_attempt"
                if payload.scope_type in {"team", "global"}
                else "policy_blocked_write"
            )
            return PolicyEvaluation(
                policy_name="access_governance.write_scope",
                decision="deny",
                allowed=False,
                severity="high" if payload.scope_type in {"team", "global"} else "medium",
                reason="write does not satisfy Aurora scope, actor role, or confirmation constraints",
                payload={
                    "scope_type": payload.scope_type,
                    "scope_id": payload.scope_id,
                    "event_type": event_type,
                },
            )

        if payload.scope_type in {"team", "global"} and request_context.actor_role not in {"system", "admin"}:
            return PolicyEvaluation(
                policy_name="access_governance.high_scope_actor",
                decision="deny",
                allowed=False,
                severity="high",
                reason="team/global memory writes require an internal system or admin actor",
                payload={"scope_type": payload.scope_type, "scope_id": payload.scope_id},
            )

        if payload.scope_type in {"team", "global"} and not payload.confirmed:
            return PolicyEvaluation(
                policy_name="access_governance.high_scope_confirmation",
                decision="deny",
                allowed=False,
                severity="high",
                reason="team/global memory writes must be explicitly confirmed before persistence",
                payload={"scope_type": payload.scope_type, "scope_id": payload.scope_id},
            )

        decision = "allow"
        reason = "write stayed inside the caller's allowed scope boundary"
        if self._is_scope_upgrade(request_context, payload):
            decision = "observe"
            reason = "write targets a broader scope and is allowed only because explicit shared/global gates were enabled"

        return PolicyEvaluation(
            policy_name="access_governance.write_scope",
            decision=decision,
            allowed=True,
            reason=reason,
            severity="low" if payload.scope_type in {"session", "user", "project"} else "medium",
            payload={"scope_type": payload.scope_type, "scope_id": payload.scope_id},
        )

    def authorize_status_change(
        self,
        request_context: MemoryRequestContext,
        memory_fact: MemoryFact,
        *,
        action_name: str,
    ) -> PolicyEvaluation:
        if not self._access_policy.can_read(request_context, memory_fact):
            return PolicyEvaluation(
                policy_name="access_governance.status_visibility",
                decision="deny",
                allowed=False,
                severity="high",
                reason="status mutation is denied because the caller cannot read the target memory",
                payload={"action_name": action_name, "memory_fact_id": memory_fact.id},
            )

        if action_name in {"delete", "redact"} and request_context.actor_role not in {"system", "admin"}:
            return PolicyEvaluation(
                policy_name="access_governance.high_risk_mutation",
                decision="deny",
                allowed=False,
                severity="high",
                reason="delete and redact operations require an admin or system actor",
                payload={"action_name": action_name, "memory_fact_id": memory_fact.id},
            )

        return PolicyEvaluation(
            policy_name="access_governance.status_visibility",
            decision="allow",
            allowed=True,
            severity="medium" if action_name in {"archive", "delete", "redact"} else "low",
            reason="caller can operate on the target memory within the current governance boundary",
            payload={"action_name": action_name, "memory_fact_id": memory_fact.id},
        )

    def authorize_batch_action(
        self,
        request_context: MemoryRequestContext,
        *,
        action_name: str,
    ) -> PolicyEvaluation:
        if request_context.actor_role not in {"system", "admin"}:
            return PolicyEvaluation(
                policy_name="access_governance.batch_operation",
                decision="deny",
                allowed=False,
                severity="high",
                reason="batch archive/correction operations are restricted to system or admin actors",
                payload={"action_name": action_name},
            )

        return PolicyEvaluation(
            policy_name="access_governance.batch_operation",
            decision="allow",
            allowed=True,
            severity="medium",
            reason="batch governance action executed under an internal actor boundary",
            payload={"action_name": action_name},
        )

    @staticmethod
    def _is_scope_upgrade(
        request_context: MemoryRequestContext,
        payload: MemoryFactCreate,
    ) -> bool:
        del request_context
        return _SCOPE_RISK_ORDER.get(payload.scope_type, 0) >= _SCOPE_RISK_ORDER["team"]
