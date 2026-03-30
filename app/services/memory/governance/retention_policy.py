"""Rule-driven retention policy resolution for governed memory facts."""

from __future__ import annotations

from dataclasses import replace

from app.schemas import MemoryFact, RetentionPolicySnapshot


_DAY_SECONDS = 24 * 60 * 60
_HOUR_SECONDS = 60 * 60


class RetentionPolicy:
    """Resolve first-version retention rules without introducing heavy policy engines."""

    def __init__(
        self,
        *,
        overrides: dict[tuple[str, str], RetentionPolicySnapshot] | None = None,
    ) -> None:
        self._rules = self._default_rules()
        if overrides:
            self._rules.update(dict(overrides))

    def resolve(self, memory_fact: MemoryFact) -> RetentionPolicySnapshot:
        rule = self._rules.get((memory_fact.scope_type, memory_fact.type))
        if rule is None:
            rule = self._rules.get((memory_fact.scope_type, "fact"))
        if rule is None:
            rule = RetentionPolicySnapshot(
                policy_id=f"{memory_fact.scope_type}.{memory_fact.type}.fallback",
                ttl_seconds=30 * _DAY_SECONDS,
                decay_factor=1.0,
                retention_level="normal",
                cooling_after_seconds=7 * _DAY_SECONDS,
                archive_after_seconds=90 * _DAY_SECONDS,
                expires_after_seconds=30 * _DAY_SECONDS,
                archive_bucket=f"hot/{memory_fact.scope_type}/{memory_fact.type}",
            )

        resolved_rule = replace(rule)
        if memory_fact.source_type == "user_confirmed" and resolved_rule.retention_level in {"low", "temporary"}:
            resolved_rule = replace(resolved_rule, retention_level="normal")
        if (
            memory_fact.type == "preference"
            and memory_fact.scope_type == "user"
            and memory_fact.source_type == "user_confirmed"
            and resolved_rule.retention_level == "normal"
        ):
            resolved_rule = replace(resolved_rule, retention_level="high")
        if memory_fact.scope_type in {"team", "global"} and memory_fact.type in {"fact", "decision"}:
            if resolved_rule.retention_level != "critical":
                resolved_rule = replace(resolved_rule, retention_level="high")
        if memory_fact.type == "pending_issue" and memory_fact.status != "active":
            resolved_rule = replace(
                resolved_rule,
                ttl_seconds=min(resolved_rule.ttl_seconds or (7 * _DAY_SECONDS), 2 * _DAY_SECONDS),
                cooling_after_seconds=min(
                    resolved_rule.cooling_after_seconds or (2 * _DAY_SECONDS),
                    12 * _HOUR_SECONDS,
                ),
                expires_after_seconds=min(
                    resolved_rule.expires_after_seconds or (2 * _DAY_SECONDS),
                    12 * _HOUR_SECONDS,
                ),
                archive_after_seconds=min(
                    resolved_rule.archive_after_seconds or (30 * _DAY_SECONDS),
                    14 * _DAY_SECONDS,
                ),
            )
        return resolved_rule

    @staticmethod
    def _default_rules() -> dict[tuple[str, str], RetentionPolicySnapshot]:
        return {
            ("session", "fact"): RetentionPolicySnapshot(
                policy_id="session.fact.default",
                ttl_seconds=3 * _DAY_SECONDS,
                decay_factor=1.25,
                retention_level="low",
                cooling_after_seconds=24 * _HOUR_SECONDS,
                expires_after_seconds=3 * _DAY_SECONDS,
                archive_after_seconds=30 * _DAY_SECONDS,
                archive_bucket="warm/session/fact",
            ),
            ("session", "preference"): RetentionPolicySnapshot(
                policy_id="session.preference.default",
                ttl_seconds=7 * _DAY_SECONDS,
                decay_factor=1.1,
                retention_level="temporary",
                cooling_after_seconds=2 * _DAY_SECONDS,
                expires_after_seconds=7 * _DAY_SECONDS,
                archive_after_seconds=45 * _DAY_SECONDS,
                archive_bucket="warm/session/preference",
            ),
            ("session", "decision"): RetentionPolicySnapshot(
                policy_id="session.decision.default",
                ttl_seconds=5 * _DAY_SECONDS,
                decay_factor=1.15,
                retention_level="temporary",
                cooling_after_seconds=2 * _DAY_SECONDS,
                expires_after_seconds=5 * _DAY_SECONDS,
                archive_after_seconds=45 * _DAY_SECONDS,
                archive_bucket="warm/session/decision",
            ),
            ("session", "pending_issue"): RetentionPolicySnapshot(
                policy_id="session.pending_issue.default",
                ttl_seconds=12 * _HOUR_SECONDS,
                decay_factor=1.6,
                retention_level="temporary",
                cooling_after_seconds=6 * _HOUR_SECONDS,
                expires_after_seconds=12 * _HOUR_SECONDS,
                archive_after_seconds=7 * _DAY_SECONDS,
                archive_bucket="warm/session/pending_issue",
            ),
            ("user", "fact"): RetentionPolicySnapshot(
                policy_id="user.fact.default",
                ttl_seconds=120 * _DAY_SECONDS,
                decay_factor=0.85,
                retention_level="normal",
                cooling_after_seconds=30 * _DAY_SECONDS,
                expires_after_seconds=120 * _DAY_SECONDS,
                archive_after_seconds=365 * _DAY_SECONDS,
                archive_bucket="warm/user/fact",
            ),
            ("user", "preference"): RetentionPolicySnapshot(
                policy_id="user.preference.default",
                ttl_seconds=180 * _DAY_SECONDS,
                decay_factor=0.65,
                retention_level="normal",
                cooling_after_seconds=45 * _DAY_SECONDS,
                expires_after_seconds=180 * _DAY_SECONDS,
                archive_after_seconds=540 * _DAY_SECONDS,
                archive_bucket="warm/user/preference",
            ),
            ("user", "decision"): RetentionPolicySnapshot(
                policy_id="user.decision.default",
                ttl_seconds=90 * _DAY_SECONDS,
                decay_factor=0.8,
                retention_level="normal",
                cooling_after_seconds=30 * _DAY_SECONDS,
                expires_after_seconds=90 * _DAY_SECONDS,
                archive_after_seconds=365 * _DAY_SECONDS,
                archive_bucket="warm/user/decision",
            ),
            ("user", "pending_issue"): RetentionPolicySnapshot(
                policy_id="user.pending_issue.default",
                ttl_seconds=14 * _DAY_SECONDS,
                decay_factor=1.2,
                retention_level="low",
                cooling_after_seconds=7 * _DAY_SECONDS,
                expires_after_seconds=14 * _DAY_SECONDS,
                archive_after_seconds=60 * _DAY_SECONDS,
                archive_bucket="warm/user/pending_issue",
            ),
            ("project", "fact"): RetentionPolicySnapshot(
                policy_id="project.fact.default",
                ttl_seconds=720 * _DAY_SECONDS,
                decay_factor=0.45,
                retention_level="high",
                cooling_after_seconds=180 * _DAY_SECONDS,
                expires_after_seconds=720 * _DAY_SECONDS,
                archive_after_seconds=1440 * _DAY_SECONDS,
                archive_bucket="hot/project/fact",
            ),
            ("project", "preference"): RetentionPolicySnapshot(
                policy_id="project.preference.default",
                ttl_seconds=120 * _DAY_SECONDS,
                decay_factor=0.9,
                retention_level="normal",
                cooling_after_seconds=45 * _DAY_SECONDS,
                expires_after_seconds=120 * _DAY_SECONDS,
                archive_after_seconds=360 * _DAY_SECONDS,
                archive_bucket="warm/project/preference",
            ),
            ("project", "decision"): RetentionPolicySnapshot(
                policy_id="project.decision.default",
                ttl_seconds=540 * _DAY_SECONDS,
                decay_factor=0.55,
                retention_level="high",
                cooling_after_seconds=180 * _DAY_SECONDS,
                expires_after_seconds=540 * _DAY_SECONDS,
                archive_after_seconds=1080 * _DAY_SECONDS,
                archive_bucket="hot/project/decision",
            ),
            ("project", "pending_issue"): RetentionPolicySnapshot(
                policy_id="project.pending_issue.default",
                ttl_seconds=21 * _DAY_SECONDS,
                decay_factor=1.25,
                retention_level="normal",
                cooling_after_seconds=7 * _DAY_SECONDS,
                expires_after_seconds=21 * _DAY_SECONDS,
                archive_after_seconds=120 * _DAY_SECONDS,
                archive_bucket="warm/project/pending_issue",
            ),
            ("team", "fact"): RetentionPolicySnapshot(
                policy_id="team.fact.default",
                ttl_seconds=540 * _DAY_SECONDS,
                decay_factor=0.4,
                retention_level="high",
                cooling_after_seconds=180 * _DAY_SECONDS,
                expires_after_seconds=540 * _DAY_SECONDS,
                archive_after_seconds=1080 * _DAY_SECONDS,
                archive_bucket="hot/team/fact",
            ),
            ("team", "decision"): RetentionPolicySnapshot(
                policy_id="team.decision.default",
                ttl_seconds=540 * _DAY_SECONDS,
                decay_factor=0.45,
                retention_level="high",
                cooling_after_seconds=180 * _DAY_SECONDS,
                expires_after_seconds=540 * _DAY_SECONDS,
                archive_after_seconds=1080 * _DAY_SECONDS,
                archive_bucket="hot/team/decision",
            ),
            ("team", "preference"): RetentionPolicySnapshot(
                policy_id="team.preference.default",
                ttl_seconds=180 * _DAY_SECONDS,
                decay_factor=0.8,
                retention_level="normal",
                cooling_after_seconds=60 * _DAY_SECONDS,
                expires_after_seconds=180 * _DAY_SECONDS,
                archive_after_seconds=540 * _DAY_SECONDS,
                archive_bucket="warm/team/preference",
            ),
            ("team", "pending_issue"): RetentionPolicySnapshot(
                policy_id="team.pending_issue.default",
                ttl_seconds=14 * _DAY_SECONDS,
                decay_factor=1.15,
                retention_level="low",
                cooling_after_seconds=7 * _DAY_SECONDS,
                expires_after_seconds=14 * _DAY_SECONDS,
                archive_after_seconds=90 * _DAY_SECONDS,
                archive_bucket="warm/team/pending_issue",
            ),
            ("global", "fact"): RetentionPolicySnapshot(
                policy_id="global.fact.default",
                ttl_seconds=720 * _DAY_SECONDS,
                decay_factor=0.35,
                retention_level="critical",
                cooling_after_seconds=240 * _DAY_SECONDS,
                expires_after_seconds=720 * _DAY_SECONDS,
                archive_after_seconds=1440 * _DAY_SECONDS,
                archive_bucket="hot/global/fact",
            ),
            ("global", "decision"): RetentionPolicySnapshot(
                policy_id="global.decision.default",
                ttl_seconds=720 * _DAY_SECONDS,
                decay_factor=0.4,
                retention_level="critical",
                cooling_after_seconds=240 * _DAY_SECONDS,
                expires_after_seconds=720 * _DAY_SECONDS,
                archive_after_seconds=1440 * _DAY_SECONDS,
                archive_bucket="hot/global/decision",
            ),
            ("global", "preference"): RetentionPolicySnapshot(
                policy_id="global.preference.default",
                ttl_seconds=180 * _DAY_SECONDS,
                decay_factor=0.75,
                retention_level="normal",
                cooling_after_seconds=60 * _DAY_SECONDS,
                expires_after_seconds=180 * _DAY_SECONDS,
                archive_after_seconds=720 * _DAY_SECONDS,
                archive_bucket="warm/global/preference",
            ),
            ("global", "pending_issue"): RetentionPolicySnapshot(
                policy_id="global.pending_issue.default",
                ttl_seconds=14 * _DAY_SECONDS,
                decay_factor=1.1,
                retention_level="low",
                cooling_after_seconds=7 * _DAY_SECONDS,
                expires_after_seconds=14 * _DAY_SECONDS,
                archive_after_seconds=90 * _DAY_SECONDS,
                archive_bucket="warm/global/pending_issue",
            ),
        }
