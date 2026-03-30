"""Trust guard that prevents untrusted content from becoming high-value shared memory."""

from __future__ import annotations

from app.schemas import MemoryFactCreate, PolicyEvaluation


class PromptInjectionGuard:
    """Keep low-trust sources away from team/global long-term memory by default."""

    _LOW_TRUST_SOURCE_KINDS = {
        "knowledge_base_document",
        "external_document",
        "import",
        "imported",
    }

    def evaluate_write(
        self,
        payload: MemoryFactCreate,
    ) -> PolicyEvaluation:
        target_is_high_scope = payload.scope_type in {"team", "global"}
        source_kind = str(payload.source_kind or "").strip().lower()
        source_type = str(payload.source_type or "").strip().lower()

        if not target_is_high_scope:
            return PolicyEvaluation(
                policy_name="prompt_injection_guard.source_trust",
                decision="allow",
                allowed=True,
                severity="low",
                reason="write stayed below team/global scope, so low-trust source promotion rules did not apply",
                payload={"scope_type": payload.scope_type, "source_kind": source_kind, "source_type": source_type},
            )

        if source_kind in self._LOW_TRUST_SOURCE_KINDS:
            return PolicyEvaluation(
                policy_name="prompt_injection_guard.source_trust",
                decision="deny",
                allowed=False,
                severity="high",
                reason="external or imported content cannot be promoted directly into team/global long-term memory",
                payload={"scope_type": payload.scope_type, "source_kind": source_kind, "source_type": source_type},
            )

        if source_type in {"model_inferred", "system_generated"} and not payload.reviewed_by_human:
            return PolicyEvaluation(
                policy_name="prompt_injection_guard.source_trust",
                decision="deny",
                allowed=False,
                severity="high",
                reason="model-inferred memory requires human review before team/global persistence",
                payload={"scope_type": payload.scope_type, "source_kind": source_kind, "source_type": source_type},
            )

        if not payload.confirmed and not payload.reviewed_by_human:
            return PolicyEvaluation(
                policy_name="prompt_injection_guard.source_trust",
                decision="review",
                allowed=False,
                severity="medium",
                reason="shared long-term memory requires confirmation or review for trust elevation",
                payload={"scope_type": payload.scope_type, "source_kind": source_kind, "source_type": source_type},
            )

        return PolicyEvaluation(
            policy_name="prompt_injection_guard.source_trust",
            decision="allow",
            allowed=True,
            severity="medium",
            reason="shared-scope write passed the first trust-elevation rules",
            payload={"scope_type": payload.scope_type, "source_kind": source_kind, "source_type": source_type},
        )
