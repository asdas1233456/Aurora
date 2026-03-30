"""Transparent rule-based value evaluation for Aurora memory facts."""

from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone

from app.schemas import MemoryFact, MemoryValueAssessment, RetentionPolicySnapshot
from app.services.persistence_utils import utc_now_iso
from app.services.retention_policy import RetentionPolicy


_RETENTION_ORDER = ["temporary", "low", "normal", "high", "critical"]
_SCOPE_VALUE = {
    "session": 0.55,
    "user": 0.68,
    "project": 0.86,
    "team": 0.82,
    "global": 0.78,
}
_TYPE_VALUE = {
    "fact": 0.82,
    "decision": 0.78,
    "preference": 0.62,
    "pending_issue": 0.58,
}
_SOURCE_VALUE = {
    "user_confirmed": 1.0,
    "imported": 0.88,
    "system_generated": 0.72,
    "model_inferred": 0.55,
}


class MemoryValueEvaluator:
    """Compute explainable value scores without requiring learned models."""

    def __init__(self, retention_policy: RetentionPolicy | None = None) -> None:
        self._retention_policy = retention_policy or RetentionPolicy()

    def evaluate(
        self,
        memory_fact: MemoryFact,
        *,
        policy: RetentionPolicySnapshot | None = None,
        now: str | None = None,
    ) -> MemoryValueAssessment:
        now_iso = now or utc_now_iso()
        now_dt = _parse_iso_datetime(now_iso)
        resolved_policy = policy or self._retention_policy.resolve(memory_fact)
        reference_dt = _reference_datetime(memory_fact)

        scope_value = float(_SCOPE_VALUE.get(memory_fact.scope_type, 0.5))
        type_value = float(_TYPE_VALUE.get(memory_fact.type, 0.5))
        recency_value = self._recency_value(
            reference_dt=reference_dt,
            now_dt=now_dt,
            policy=resolved_policy,
        )
        usage_value = self._usage_value(memory_fact)
        source_value = self._source_value(memory_fact)
        correction_penalty = self._correction_penalty(memory_fact)
        expires_at_dt = self._expires_at(memory_fact, resolved_policy, reference_dt)
        expiration_penalty = self._expiration_penalty(memory_fact, expires_at_dt, now_dt)

        positive_score = (
            scope_value * 0.20
            + type_value * 0.20
            + recency_value * 0.15
            + usage_value * 0.20
            + source_value * 0.15
        )
        penalty_score = correction_penalty * 0.10 + expiration_penalty * 0.10
        normalized_score = max(0.0, min(1.0, (positive_score - penalty_score) / 0.90))
        value_score = round(normalized_score * 100.0, 2)

        retention_level = self._retention_level(
            memory_fact=memory_fact,
            base_level=resolved_policy.retention_level,
            value_score=value_score,
        )
        next_evaluation_at = self._next_evaluation_at(
            memory_fact=memory_fact,
            policy=resolved_policy,
            now_dt=now_dt,
            expires_at_dt=expires_at_dt,
        )
        reasons = (
            f"policy:{resolved_policy.policy_id}",
            f"scope_value:{scope_value:.2f}",
            f"type_value:{type_value:.2f}",
            f"recency_value:{recency_value:.2f}",
            f"usage_value:{usage_value:.2f}",
            f"source_value:{source_value:.2f}",
            f"correction_penalty:{correction_penalty:.2f}",
            f"expiration_penalty:{expiration_penalty:.2f}",
        )
        return MemoryValueAssessment(
            value_score=value_score,
            scope_value=scope_value,
            type_value=type_value,
            recency_value=recency_value,
            usage_value=usage_value,
            source_value=source_value,
            correction_penalty=correction_penalty,
            expiration_penalty=expiration_penalty,
            retention_level=retention_level,
            ttl_seconds=resolved_policy.ttl_seconds,
            expires_at=expires_at_dt.isoformat(timespec="microseconds") if expires_at_dt else None,
            decay_factor=resolved_policy.decay_factor,
            next_evaluation_at=next_evaluation_at,
            retention_policy_id=resolved_policy.policy_id,
            archive_bucket=resolved_policy.archive_bucket,
            reasons=reasons,
        )

    @staticmethod
    def _recency_value(
        *,
        reference_dt: datetime,
        now_dt: datetime,
        policy: RetentionPolicySnapshot,
    ) -> float:
        age_seconds = max((now_dt - reference_dt).total_seconds(), 0.0)
        ttl_seconds = policy.ttl_seconds or 30 * 24 * 60 * 60
        ratio = age_seconds / max(float(ttl_seconds), 1.0)
        if ratio <= 0.10:
            return 1.0
        if ratio <= 0.35:
            return 0.84
        if ratio <= 0.75:
            return 0.66
        if ratio <= 1.00:
            return 0.48
        if ratio <= 2.00:
            return 0.28
        return 0.14

    @staticmethod
    def _usage_value(memory_fact: MemoryFact) -> float:
        access_signal = min(math.log1p(max(memory_fact.access_count, 0)) / math.log(10), 1.0)
        success_signal = min(math.log1p(max(memory_fact.successful_use_count, 0)) / math.log(6), 1.0)
        return min(1.0, access_signal * 0.45 + success_signal * 0.55)

    @staticmethod
    def _source_value(memory_fact: MemoryFact) -> float:
        source_value = float(_SOURCE_VALUE.get(memory_fact.source_type, 0.55))
        if memory_fact.reviewed_by_human:
            source_value = min(1.0, source_value + 0.05)
        return source_value

    @staticmethod
    def _correction_penalty(memory_fact: MemoryFact) -> float:
        if memory_fact.superseded_by:
            return 0.95
        if memory_fact.status == "conflict_pending_review":
            return 0.90
        if memory_fact.status == "superseded":
            return 0.85
        if memory_fact.status == "stale":
            return 0.45
        return 0.0

    @staticmethod
    def _expires_at(
        memory_fact: MemoryFact,
        policy: RetentionPolicySnapshot,
        reference_dt: datetime,
    ) -> datetime | None:
        if memory_fact.expires_at:
            return _parse_iso_datetime(memory_fact.expires_at)
        if policy.ttl_seconds is None:
            return None
        return reference_dt + timedelta(seconds=int(policy.ttl_seconds))

    @staticmethod
    def _expiration_penalty(
        memory_fact: MemoryFact,
        expires_at_dt: datetime | None,
        now_dt: datetime,
    ) -> float:
        if memory_fact.type == "pending_issue" and memory_fact.status != "active":
            return 1.0
        if expires_at_dt is None:
            return 0.0
        if now_dt >= expires_at_dt:
            return 1.0
        remaining_seconds = max((expires_at_dt - now_dt).total_seconds(), 0.0)
        if remaining_seconds <= 24 * 60 * 60:
            return 0.35
        return 0.0

    @staticmethod
    def _retention_level(
        *,
        memory_fact: MemoryFact,
        base_level: str,
        value_score: float,
    ) -> str:
        try:
            index = _RETENTION_ORDER.index(base_level)
        except ValueError:
            index = _RETENTION_ORDER.index("normal")

        if value_score >= 85:
            index = min(index + 1, len(_RETENTION_ORDER) - 1)
        elif value_score < 35:
            index = max(index - 2, 0)
        elif value_score < 55:
            index = max(index - 1, 0)
        elif value_score >= 72:
            index = min(index + 1, len(_RETENTION_ORDER) - 1)

        if memory_fact.scope_type == "session":
            index = min(index, _RETENTION_ORDER.index("low"))
        if memory_fact.type == "pending_issue":
            index = min(index, _RETENTION_ORDER.index("normal"))
        if memory_fact.scope_type in {"team", "global"} and memory_fact.type in {"fact", "decision"}:
            index = max(index, _RETENTION_ORDER.index("high"))
        return _RETENTION_ORDER[index]

    @staticmethod
    def _next_evaluation_at(
        *,
        memory_fact: MemoryFact,
        policy: RetentionPolicySnapshot,
        now_dt: datetime,
        expires_at_dt: datetime | None,
    ) -> str | None:
        if memory_fact.retrieval_visibility == "archive_only" or memory_fact.forgetting_status == "archived":
            return (now_dt + timedelta(days=30)).isoformat(timespec="microseconds")

        base_seconds = policy.cooling_after_seconds or policy.ttl_seconds or (7 * 24 * 60 * 60)
        interval_seconds = max(
            min(int(base_seconds / max(policy.decay_factor, 0.2)), 30 * 24 * 60 * 60),
            6 * 60 * 60,
        )
        next_dt = now_dt + timedelta(seconds=interval_seconds)
        if expires_at_dt is not None and next_dt > expires_at_dt:
            next_dt = expires_at_dt
        return next_dt.isoformat(timespec="microseconds")


def _parse_iso_datetime(raw_value: str) -> datetime:
    parsed = datetime.fromisoformat(str(raw_value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _reference_datetime(memory_fact: MemoryFact) -> datetime:
    reference = memory_fact.last_accessed_at or memory_fact.updated_at or memory_fact.created_at
    return _parse_iso_datetime(reference)
