"""Inspection helpers for the first-version operability and governance view."""

from __future__ import annotations

from app.config import AppConfig
from app.services.audit_service import AuditService
from app.services.observability_service import ObservabilityService
from app.services.storage_service import connect_state_db


class GovernanceInspector:
    """Aggregate recent governance signals for internal tooling and admin surfaces."""

    def __init__(
        self,
        config: AppConfig,
        *,
        audit_service: AuditService | None = None,
        observability: ObservabilityService | None = None,
    ) -> None:
        self._config = config
        self._audit_service = audit_service or AuditService(config)
        self._observability = observability or ObservabilityService(config)

    def build_summary(
        self,
        *,
        tenant_id: str,
        limit: int = 10,
        capture_snapshot: bool = False,
    ) -> dict[str, object]:
        with connect_state_db(self._config) as connection:
            hidden_memory_count = self._scalar(
                connection,
                """
                SELECT COUNT(*) AS item_count
                FROM memory_facts
                WHERE tenant_id = ? AND retrieval_visibility = 'hidden_from_default'
                """,
                (tenant_id,),
            )
            archive_only_count = self._scalar(
                connection,
                """
                SELECT COUNT(*) AS item_count
                FROM memory_facts
                WHERE tenant_id = ? AND retrieval_visibility = 'archive_only'
                """,
                (tenant_id,),
            )
            correction_backlog_count = self._scalar(
                connection,
                """
                SELECT COUNT(*) AS item_count
                FROM memory_facts
                WHERE tenant_id = ? AND status = 'conflict_pending_review'
                """,
                (tenant_id,),
            )
            archive_backlog_count = self._scalar(
                connection,
                """
                SELECT COUNT(*) AS item_count
                FROM memory_facts
                WHERE tenant_id = ?
                  AND forgetting_status IN ('cooling', 'expired')
                  AND retrieval_visibility != 'archive_only'
                """,
                (tenant_id,),
            )
            top_failing_policies = [
                {
                    "policy_name": str(row["policy_name"]),
                    "failure_count": int(row["failure_count"] or 0),
                }
                for row in connection.execute(
                    """
                    SELECT policy_name, COUNT(*) AS failure_count
                    FROM policy_decisions
                    WHERE decision IN ('deny', 'redact', 'review', 'fallback', 'throttle')
                    GROUP BY policy_name
                    ORDER BY failure_count DESC, policy_name ASC
                    LIMIT ?
                    """,
                    (limit,),
                ).fetchall()
            ]

        summary = {
            "tenant_id": tenant_id,
            "hidden_memory_count": hidden_memory_count,
            "archive_only_count": archive_only_count,
            "correction_backlog_count": correction_backlog_count,
            "archive_backlog_count": archive_backlog_count,
            "recent_security_events": [
                {
                    "id": item.id,
                    "event_type": item.event_type,
                    "severity": item.severity,
                    "request_id": item.request_id,
                    "status": item.status,
                    "created_at": item.created_at,
                }
                for item in self._audit_service.list_security_events(tenant_id=tenant_id, limit=limit)
            ],
            "recent_policy_decisions": [
                {
                    "id": item.id,
                    "request_id": item.request_id,
                    "policy_name": item.policy_name,
                    "decision": item.decision,
                    "reason": item.reason,
                    "created_at": item.created_at,
                }
                for item in self._audit_service.list_policy_decisions(limit=limit)
            ],
            "top_failing_policies": top_failing_policies,
            "live_metrics": self._observability.live_metrics(),
        }

        if capture_snapshot:
            self._observability.capture_metric_snapshot(
                "governance.hidden_memory_count",
                metric_value=float(hidden_memory_count),
                dimensions={"tenant_id": tenant_id},
            )
            self._observability.capture_metric_snapshot(
                "governance.correction_backlog_count",
                metric_value=float(correction_backlog_count),
                dimensions={"tenant_id": tenant_id},
            )
            self._observability.capture_metric_snapshot(
                "governance.archive_backlog_count",
                metric_value=float(archive_backlog_count),
                dimensions={"tenant_id": tenant_id},
            )

        return summary

    @staticmethod
    def _scalar(connection, query: str, parameters: tuple[object, ...]) -> int:
        row = connection.execute(query, parameters).fetchone()
        return int(row["item_count"]) if row is not None else 0
