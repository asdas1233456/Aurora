"""Resolve ambiguous memory write outcomes with conservative business rules."""

from __future__ import annotations

from dataclasses import replace

from app.schemas import ConsistencyCheckResult, ResolvedMemoryFactIdentity


class ConflictResolver:
    """Keep the first-stage resolver conservative and easy to audit."""

    def resolve(
        self,
        check_result: ConsistencyCheckResult,
        identity: ResolvedMemoryFactIdentity,
    ) -> ConsistencyCheckResult:
        if check_result.operation != "conflict":
            return check_result

        if identity.allows_coexistence and check_result.current_fact is None:
            return replace(
                check_result,
                operation="coexist",
                status="active",
                reason="fact family supports coexistence, so the new value remains active beside peers",
            )

        # Stage 1 prefers a reviewable pending state over guessing which value is correct.
        return replace(
            check_result,
            operation="conflict",
            status="conflict_pending_review",
        )
