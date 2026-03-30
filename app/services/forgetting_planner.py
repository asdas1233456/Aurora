"""Plan forgetting transitions without mutating storage directly."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.schemas import ForgettingDecision, MemoryFact, MemoryValueAssessment, RetentionPolicySnapshot
from app.services.persistence_utils import utc_now_iso


_DAY_SECONDS = 24 * 60 * 60


class ForgettingPlanner:
    """Translate value assessments into default-retrieval visibility decisions."""

    def plan(
        self,
        memory_fact: MemoryFact,
        *,
        assessment: MemoryValueAssessment,
        policy: RetentionPolicySnapshot,
        now: str | None = None,
    ) -> ForgettingDecision:
        now_iso = now or utc_now_iso()
        now_dt = _parse_iso_datetime(now_iso)
        reference_dt = _reference_datetime(memory_fact)
        age_seconds = max((now_dt - reference_dt).total_seconds(), 0.0)
        cooling_seconds = max(policy.cooling_after_seconds or (7 * _DAY_SECONDS), 12 * 60 * 60)
        archive_seconds = max(policy.archive_after_seconds or (90 * _DAY_SECONDS), cooling_seconds)
        expires_at_dt = _parse_optional_datetime(assessment.expires_at)
        reasons: list[str] = [f"policy:{policy.policy_id}", f"value_score:{assessment.value_score:.2f}"]

        if memory_fact.archived_at or memory_fact.retrieval_visibility == "archive_only":
            reasons.append("already_archived")
            return ForgettingDecision(
                retrieval_visibility="archive_only",
                forgetting_status="archived",
                archived_at=memory_fact.archived_at or now_iso,
                next_evaluation_at=(now_dt + timedelta(days=30)).isoformat(timespec="microseconds"),
                action="archive",
                reason="memory already left the hot path and remains audit-only",
                reasons=tuple(reasons),
                archive_bucket=assessment.archive_bucket or policy.archive_bucket,
            )

        explicitly_expired = expires_at_dt is not None and now_dt >= expires_at_dt
        if memory_fact.type == "pending_issue" and memory_fact.status != "active":
            explicitly_expired = True
            reasons.append("pending_issue_closed")
        if explicitly_expired:
            reasons.append("expired")
            if age_seconds >= archive_seconds or assessment.value_score < 25:
                return ForgettingDecision(
                    retrieval_visibility="archive_only",
                    forgetting_status="archived",
                    archived_at=memory_fact.archived_at or now_iso,
                    next_evaluation_at=(now_dt + timedelta(days=30)).isoformat(timespec="microseconds"),
                    action="archive",
                    reason="expired memory moved from the hot path into archive retention",
                    reasons=tuple(reasons),
                    archive_bucket=assessment.archive_bucket or policy.archive_bucket,
                )
            return ForgettingDecision(
                retrieval_visibility="hidden_from_default",
                forgetting_status="expired",
                archived_at=None,
                next_evaluation_at=(now_dt + timedelta(days=3)).isoformat(timespec="microseconds"),
                action="expire",
                reason="business TTL elapsed so the memory must stop participating in default retrieval",
                reasons=tuple(reasons),
                archive_bucket=assessment.archive_bucket or policy.archive_bucket,
            )

        if memory_fact.status in {"stale", "superseded", "conflict_pending_review"}:
            reasons.append(f"status:{memory_fact.status}")
            if age_seconds >= archive_seconds:
                return ForgettingDecision(
                    retrieval_visibility="archive_only",
                    forgetting_status="archived",
                    archived_at=memory_fact.archived_at or now_iso,
                    next_evaluation_at=(now_dt + timedelta(days=30)).isoformat(timespec="microseconds"),
                    action="archive",
                    reason="non-current memory is preserved for audit but removed from the hot path",
                    reasons=tuple(reasons),
                    archive_bucket=assessment.archive_bucket or policy.archive_bucket,
                )
            return ForgettingDecision(
                retrieval_visibility="hidden_from_default",
                forgetting_status="cooling",
                archived_at=None,
                next_evaluation_at=(now_dt + timedelta(days=7)).isoformat(timespec="microseconds"),
                action="hide_from_default",
                reason="non-current memory stays readable for history but should exit the default chain",
                reasons=tuple(reasons),
                archive_bucket=assessment.archive_bucket or policy.archive_bucket,
            )

        high_priority = assessment.retention_level in {"critical", "high"} or assessment.value_score >= 72
        if high_priority:
            reasons.append("high_priority_memory")
            if age_seconds >= cooling_seconds * 2 and assessment.value_score < 78:
                return ForgettingDecision(
                    retrieval_visibility="deprioritized",
                    forgetting_status="cooling",
                    archived_at=None,
                    next_evaluation_at=(now_dt + timedelta(days=14)).isoformat(timespec="microseconds"),
                    action="de-prioritize",
                    reason="high-value memory is still retained but cooled to reduce default-chain noise",
                    reasons=tuple(reasons),
                    archive_bucket=assessment.archive_bucket or policy.archive_bucket,
                )
            return ForgettingDecision(
                retrieval_visibility="normal",
                forgetting_status="none",
                archived_at=None,
                next_evaluation_at=assessment.next_evaluation_at,
                action="keep_normal",
                reason="current effective memory remains valuable enough for the default path",
                reasons=tuple(reasons),
                archive_bucket=assessment.archive_bucket or policy.archive_bucket,
            )

        if age_seconds >= archive_seconds and assessment.value_score < 35:
            reasons.append("long_term_cold_archive")
            return ForgettingDecision(
                retrieval_visibility="archive_only",
                forgetting_status="archived",
                archived_at=memory_fact.archived_at or now_iso,
                next_evaluation_at=(now_dt + timedelta(days=30)).isoformat(timespec="microseconds"),
                action="archive",
                reason="long-unused low-value memory moved to archive retention",
                reasons=tuple(reasons),
                archive_bucket=assessment.archive_bucket or policy.archive_bucket,
            )

        if age_seconds >= cooling_seconds * 2 or assessment.value_score < 28:
            reasons.append("hidden_cooling")
            return ForgettingDecision(
                retrieval_visibility="hidden_from_default",
                forgetting_status="cooling",
                archived_at=None,
                next_evaluation_at=(now_dt + timedelta(days=7)).isoformat(timespec="microseconds"),
                action="hide_from_default",
                reason="cold low-value memory should leave the default retrieval path but remain auditable",
                reasons=tuple(reasons),
                archive_bucket=assessment.archive_bucket or policy.archive_bucket,
            )

        if age_seconds >= cooling_seconds or assessment.value_score < 50:
            reasons.append("deprioritized_cooling")
            return ForgettingDecision(
                retrieval_visibility="deprioritized",
                forgetting_status="cooling",
                archived_at=None,
                next_evaluation_at=(now_dt + timedelta(days=7)).isoformat(timespec="microseconds"),
                action="de-prioritize",
                reason="memory stays visible but receives a retention-aware ranking penalty",
                reasons=tuple(reasons),
                archive_bucket=assessment.archive_bucket or policy.archive_bucket,
            )

        return ForgettingDecision(
            retrieval_visibility="normal",
            forgetting_status="none",
            archived_at=None,
            next_evaluation_at=assessment.next_evaluation_at,
            action="keep_normal",
            reason="current effective memory remains visible on the default chain",
            reasons=tuple(reasons),
            archive_bucket=assessment.archive_bucket or policy.archive_bucket,
        )


def _parse_iso_datetime(raw_value: str) -> datetime:
    parsed = datetime.fromisoformat(str(raw_value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _parse_optional_datetime(raw_value: str | None) -> datetime | None:
    if not raw_value:
        return None
    return _parse_iso_datetime(raw_value)


def _reference_datetime(memory_fact: MemoryFact) -> datetime:
    return _parse_iso_datetime(memory_fact.last_accessed_at or memory_fact.updated_at or memory_fact.created_at)
