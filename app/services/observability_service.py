"""Structured observability and lightweight metrics for memory governance."""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
from collections import defaultdict
from dataclasses import asdict
from time import perf_counter
from uuid import uuid4

from app.config import AppConfig
from app.schemas import (
    MemoryRequestContext,
    MemoryRetentionAuditRecord,
    SystemMetricSnapshotRecord,
)
from app.services.persistence_utils import utc_now_iso
from app.services.storage_service import connect_state_db


logger = logging.getLogger(__name__)


class _LiveMetricsStore:
    """Process-local counters keep the first version cheap and provider-agnostic."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._counters: dict[tuple[str, tuple[tuple[str, str], ...]], dict[str, float]] = defaultdict(
            lambda: {"count": 0.0, "sum": 0.0, "last": 0.0, "max": 0.0}
        )

    def increment(
        self,
        metric_name: str,
        *,
        value: float = 1.0,
        dimensions: dict[str, object] | None = None,
    ) -> None:
        self.observe(metric_name, value=value, dimensions=dimensions)

    def observe(
        self,
        metric_name: str,
        *,
        value: float,
        dimensions: dict[str, object] | None = None,
    ) -> None:
        normalized_dimensions = self._normalize_dimensions(dimensions)
        key = (metric_name, normalized_dimensions)
        with self._lock:
            bucket = self._counters[key]
            bucket["count"] += 1.0
            bucket["sum"] += float(value)
            bucket["last"] = float(value)
            bucket["max"] = max(float(bucket["max"]), float(value))

    def snapshot(self) -> list[dict[str, object]]:
        with self._lock:
            items = [
                {
                    "metric_name": metric_name,
                    "dimensions": dict(dimensions),
                    "count": values["count"],
                    "sum": values["sum"],
                    "last": values["last"],
                    "max": values["max"],
                    "avg": (values["sum"] / values["count"]) if values["count"] else 0.0,
                }
                for (metric_name, dimensions), values in self._counters.items()
            ]
        items.sort(key=lambda item: (str(item["metric_name"]), json.dumps(item["dimensions"], sort_keys=True)))
        return items

    @staticmethod
    def _normalize_dimensions(dimensions: dict[str, object] | None) -> tuple[tuple[str, str], ...]:
        return tuple(
            sorted(
                (
                    str(key),
                    str(value),
                )
                for key, value in (dimensions or {}).items()
                if value is not None and str(value) != ""
            )
        )


_LIVE_METRICS = _LiveMetricsStore()


class ObservabilityService:
    """Centralize structured logs and metrics without coupling to a metrics backend."""

    def __init__(self, config: AppConfig) -> None:
        self._config = config

    def log_event(
        self,
        event_name: str,
        *,
        request_context: MemoryRequestContext | None = None,
        level: str = "info",
        payload: dict[str, object] | None = None,
    ) -> None:
        normalized_payload = {
            "event": event_name,
            "created_at": utc_now_iso(),
            **self._request_fields(request_context),
            **dict(payload or {}),
        }
        message = json.dumps(normalized_payload, ensure_ascii=False, sort_keys=True)
        log_method = getattr(logger, level.lower(), logger.info)
        log_method(message)

    def record_metric(
        self,
        metric_name: str,
        *,
        value: float = 1.0,
        dimensions: dict[str, object] | None = None,
    ) -> None:
        _LIVE_METRICS.observe(metric_name, value=value, dimensions=dimensions)

    def increment_metric(
        self,
        metric_name: str,
        *,
        value: float = 1.0,
        dimensions: dict[str, object] | None = None,
    ) -> None:
        _LIVE_METRICS.increment(metric_name, value=value, dimensions=dimensions)

    def timed_operation(
        self,
        metric_name: str,
        *,
        dimensions: dict[str, object] | None = None,
    ):
        return _TimedMetric(self, metric_name, dimensions=dimensions)

    def build_retrieval_trace_payload(
        self,
        *,
        request_context: MemoryRequestContext,
        trace: dict[str, object],
    ) -> dict[str, object]:
        summary = dict(trace.get("summary") or {})
        return {
            **self._request_fields(request_context),
            "scene": trace.get("scene", ""),
            "selected_memory_ids": summary.get("selected_memory_ids", []),
            "total_candidates": summary.get("total_candidates", 0),
            "total_selected": summary.get("total_selected", 0),
            "readable_candidate_count": summary.get("readable_candidate_count", 0),
            "consistent_candidate_count": summary.get("consistent_candidate_count", 0),
            "dropped_count": summary.get("dropped_count", 0),
            "selected_context_chars": summary.get("selected_context_chars", 0),
            "error": summary.get("error", ""),
        }

    def build_retention_trace_payload(
        self,
        *,
        audit_record: MemoryRetentionAuditRecord,
        memory_id: str,
    ) -> dict[str, object]:
        return {
            "memory_fact_id": memory_id,
            "retention_action": audit_record.action,
            "retention_level": audit_record.retention_level,
            "retrieval_visibility": audit_record.retrieval_visibility,
            "forgetting_status": audit_record.forgetting_status,
            "policy_id": audit_record.policy_id,
            "value_score": audit_record.value_score,
        }

    def live_metrics(self) -> list[dict[str, object]]:
        return _LIVE_METRICS.snapshot()

    def capture_metric_snapshot(
        self,
        metric_name: str,
        *,
        metric_value: float,
        dimensions: dict[str, object] | None = None,
        connection: sqlite3.Connection | None = None,
        captured_at: str | None = None,
    ) -> SystemMetricSnapshotRecord | None:
        record = SystemMetricSnapshotRecord(
            id=str(uuid4()),
            metric_name=metric_name,
            metric_value=float(metric_value),
            dimensions_json=json.dumps(dimensions or {}, ensure_ascii=False, sort_keys=True),
            captured_at=captured_at or utc_now_iso(),
        )
        try:
            if connection is not None:
                self._insert_metric_snapshot(connection, record)
            else:
                with connect_state_db(self._config) as active_connection:
                    self._insert_metric_snapshot(active_connection, record)
        except Exception:
            logger.warning("Failed to persist metric snapshot %s.", metric_name, exc_info=True)
            return None
        return record

    def list_metric_snapshots(
        self,
        *,
        metric_name: str | None = None,
        limit: int = 50,
    ) -> list[SystemMetricSnapshotRecord]:
        query = [
            "SELECT id, metric_name, metric_value, dimensions_json, captured_at",
            "FROM system_metrics_snapshot",
        ]
        parameters: list[object] = []
        if metric_name:
            query.append("WHERE metric_name = ?")
            parameters.append(metric_name)
        query.append("ORDER BY captured_at DESC")
        query.append("LIMIT ?")
        parameters.append(limit)

        with connect_state_db(self._config) as connection:
            rows = connection.execute(" ".join(query), tuple(parameters)).fetchall()
        return [
            SystemMetricSnapshotRecord(
                id=str(row["id"]),
                metric_name=str(row["metric_name"]),
                metric_value=float(row["metric_value"] or 0.0),
                dimensions_json=str(row["dimensions_json"] or "{}"),
                captured_at=str(row["captured_at"]),
            )
            for row in rows
        ]

    @staticmethod
    def _insert_metric_snapshot(
        connection: sqlite3.Connection,
        record: SystemMetricSnapshotRecord,
    ) -> None:
        connection.execute(
            """
            INSERT INTO system_metrics_snapshot (
                id, metric_name, metric_value, dimensions_json, captured_at
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (
                record.id,
                record.metric_name,
                record.metric_value,
                record.dimensions_json,
                record.captured_at,
            ),
        )

    @staticmethod
    def _request_fields(request_context: MemoryRequestContext | None) -> dict[str, object]:
        if request_context is None:
            return {}
        return {
            "request_id": request_context.request_id,
            "tenant_id": request_context.tenant_id,
            "user_id": request_context.user_id,
            "session_id": request_context.session_id,
            "project_id": request_context.project_id,
            "actor_role": request_context.actor_role,
        }


class _TimedMetric:
    """Small helper so call sites can time a stage with `with` syntax."""

    def __init__(
        self,
        service: ObservabilityService,
        metric_name: str,
        *,
        dimensions: dict[str, object] | None = None,
    ) -> None:
        self._service = service
        self._metric_name = metric_name
        self._dimensions = dict(dimensions or {})
        self._started_at = 0.0

    def __enter__(self) -> "_TimedMetric":
        self._started_at = perf_counter()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        elapsed_ms = (perf_counter() - self._started_at) * 1000
        self._service.record_metric(
            self._metric_name,
            value=elapsed_ms,
            dimensions=self._dimensions,
        )
