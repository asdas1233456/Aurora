import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.config import AppConfig
from app.modules.system.request_concurrency import RequestConcurrencyGuard
from app.schemas import MemoryFactCreate, MemoryRequestContext
from app.services.abuse_guard import AbuseGuard
from app.services.lifecycle_maintenance_service import LifecycleMaintenanceService
from app.services.memory_repository import MemoryRepository
from app.services.memory_retriever import MemoryRetriever
from app.services.memory_write_service import MemoryWriteService
from app.services.retention_audit_service import RetentionAuditService


def make_config(base_dir: Path) -> AppConfig:
    AbuseGuard.reset_all()
    RequestConcurrencyGuard.reset_all()
    return AppConfig(
        base_dir=base_dir,
        data_dir=base_dir / "data",
        db_dir=base_dir / "db",
        logs_dir=base_dir / "logs",
        llm_provider="openai",
        embedding_provider="openai",
        llm_api_key="sk-test",
        embedding_api_key="sk-test",
        llm_model="gpt-4.1-mini",
        embedding_model="text-embedding-3-small",
        collection_name="test_collection",
        memory_llm_review_enabled=False,
    )


def iso_days_ago(days: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days)).isoformat(timespec="microseconds")


class MemoryRetentionFeatureTests(unittest.TestCase):
    def test_write_pipeline_initializes_retention_metadata_and_audit(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config = make_config(Path(temp_dir))
            service = MemoryWriteService(config)
            retention_audit = RetentionAuditService(config)
            context = MemoryRequestContext(
                request_id="req-retention-init",
                tenant_id="t1",
                user_id="u1",
                project_id="p1",
                session_id="s1",
            )

            result = service.write_memory_fact(
                context,
                service.build_create_payload(
                    context,
                    content="stack.framework: FastAPI",
                    memory_type="fact",
                    scope_type="project",
                    source_type="user_confirmed",
                    reviewed_by_human=True,
                ),
            )

            created = result.memory_fact
            audits = retention_audit.list_by_memory_fact_id("t1", created.id)

            self.assertGreater(created.value_score, 0.0)
            self.assertIn(created.retention_level, {"high", "critical"})
            self.assertEqual(created.retrieval_visibility, "normal")
            self.assertEqual(created.forgetting_status, "none")
            self.assertGreater(created.ttl_seconds or 0, 0)
            self.assertIsNotNone(created.expires_at)
            self.assertEqual(created.retention_policy_id, "project.fact.default")
            self.assertEqual(len(audits), 1)
            self.assertEqual(audits[0].action, "initialized")

    def test_lifecycle_hides_cold_session_memory_and_retriever_skips_it(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config = make_config(Path(temp_dir))
            repository = MemoryRepository(config)
            lifecycle = LifecycleMaintenanceService(config, repository=repository)
            retriever = MemoryRetriever(config, repository=repository)
            context = MemoryRequestContext(
                request_id="req-retention-hide",
                tenant_id="t1",
                user_id="u1",
                project_id="p1",
                session_id="s1",
            )

            cold_session = repository.create_memory_fact(
                MemoryFactCreate(
                    tenant_id="t1",
                    owner_user_id="u1",
                    project_id="p1",
                    scope_type="session",
                    scope_id="s1",
                    type="fact",
                    content="Temporary debugging hunch about a flaky login retry",
                    source_session_id="s1",
                    source_type="model_inferred",
                    source_confidence=0.55,
                ),
                now=iso_days_ago(14),
            )
            durable_project = repository.create_memory_fact(
                MemoryFactCreate(
                    tenant_id="t1",
                    owner_user_id="u1",
                    project_id="p1",
                    scope_type="project",
                    scope_id="p1",
                    type="fact",
                    content="stack.framework: FastAPI",
                    source_session_id="s1",
                    source_type="user_confirmed",
                    source_confidence=1.0,
                    reviewed_by_human=True,
                ),
                now=iso_days_ago(2),
            )

            report = lifecycle.run_due(limit=50)
            refreshed_session = repository.get_memory_fact_by_id(cold_session.id)
            results = retriever.retrieve(context, top_k=5)
            refreshed_project = repository.get_memory_fact_by_id(durable_project.id)

            self.assertGreaterEqual(report.hidden_count + report.expired_count + report.archived_count, 1)
            self.assertIsNotNone(refreshed_session)
            self.assertIn(refreshed_session.retrieval_visibility, {"hidden_from_default", "archive_only"})
            self.assertEqual([item.id for item in results], [durable_project.id])
            self.assertIsNotNone(refreshed_project)
            self.assertEqual(refreshed_project.access_count, 1)
            self.assertIsNotNone(refreshed_project.last_accessed_at)

    def test_lifecycle_archives_long_unused_expired_session_pending_issue(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config = make_config(Path(temp_dir))
            repository = MemoryRepository(config)
            lifecycle = LifecycleMaintenanceService(config, repository=repository)
            retention_audit = RetentionAuditService(config)

            pending_issue = repository.create_memory_fact(
                MemoryFactCreate(
                    tenant_id="t1",
                    owner_user_id="u1",
                    project_id="p1",
                    scope_type="session",
                    scope_id="s1",
                    type="pending_issue",
                    content="Need to check whether the current login issue is caused by a stale local token",
                    source_session_id="s1",
                    source_type="model_inferred",
                    source_confidence=0.5,
                ),
                now=iso_days_ago(20),
            )

            report = lifecycle.run_due(limit=50)
            refreshed = repository.get_memory_fact_by_id(pending_issue.id)
            audits = retention_audit.list_by_memory_fact_id("t1", pending_issue.id)

            self.assertGreaterEqual(report.archived_count, 1)
            self.assertIsNotNone(refreshed)
            self.assertEqual(refreshed.retrieval_visibility, "archive_only")
            self.assertEqual(refreshed.forgetting_status, "archived")
            self.assertIsNotNone(refreshed.archived_at)
            self.assertEqual(audits[-1].action, "archived")

    def test_high_value_project_fact_is_not_hidden_even_when_old(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config = make_config(Path(temp_dir))
            repository = MemoryRepository(config)
            lifecycle = LifecycleMaintenanceService(config, repository=repository)
            retriever = MemoryRetriever(config, repository=repository)
            context = MemoryRequestContext(
                request_id="req-retention-keep",
                tenant_id="t1",
                user_id="u1",
                project_id="p1",
                session_id="s1",
            )

            old_project_fact = repository.create_memory_fact(
                MemoryFactCreate(
                    tenant_id="t1",
                    owner_user_id="u1",
                    project_id="p1",
                    scope_type="project",
                    scope_id="p1",
                    type="decision",
                    content="decision.main_route: All API tests run through the FastAPI service boundary",
                    source_session_id="s1",
                    source_type="user_confirmed",
                    source_confidence=1.0,
                    reviewed_by_human=True,
                ),
                now=iso_days_ago(400),
            )

            lifecycle.run_due(limit=50)
            refreshed = repository.get_memory_fact_by_id(old_project_fact.id)
            results = retriever.retrieve(context, top_k=5)

            self.assertIsNotNone(refreshed)
            self.assertIn(refreshed.retrieval_visibility, {"normal", "deprioritized"})
            self.assertNotIn(refreshed.retrieval_visibility, {"hidden_from_default", "archive_only"})
            self.assertEqual([item.id for item in results], [old_project_fact.id])


if __name__ == "__main__":
    unittest.main()
