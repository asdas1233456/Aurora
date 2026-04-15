import tempfile
import time
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from app.api.dependencies import get_app_config, get_runtime_config
from app.bootstrap.http_app import app
from app.config import AppConfig
from app.modules.system.request_concurrency import RequestConcurrencyGuard
from app.services.abuse_guard import AbuseGuard
from app.services.storage_service import connect_state_db


def make_final_acceptance_config(base_dir: Path) -> AppConfig:
    AbuseGuard.reset_all()
    RequestConcurrencyGuard.reset_all()
    return AppConfig(
        base_dir=base_dir,
        data_dir=base_dir / "data",
        db_dir=base_dir / "db",
        logs_dir=base_dir / "logs",
        tenant_id="t-final",
        deployment_mode="single_instance",
        auth_mode="trusted_header",
        llm_provider="local_mock",
        embedding_provider="openai",
        llm_model="local-mock-v1",
        embedding_model="text-embedding-3-small",
        embedding_api_key="sk-final-embed",
        collection_name="final_acceptance_collection",
        memory_llm_review_enabled=False,
        upload_max_file_bytes=1024 * 1024,
        upload_max_batch_files=8,
    )


class FinalAcceptanceApiTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.config = make_final_acceptance_config(Path(self.temp_dir.name))
        self.config.ensure_directories()
        (self.config.data_dir / "final-acceptance-seed.md").write_text(
            "# Final acceptance seed\n\nAurora release verification knowledge.",
            encoding="utf-8",
        )
        (self.config.logs_dir / "app.log").write_text(
            "2026-04-15 INFO final acceptance log line\n",
            encoding="utf-8",
        )

        app.dependency_overrides[get_app_config] = lambda: self.config
        app.dependency_overrides[get_runtime_config] = lambda: self.config
        self.client = TestClient(app)
        self.client.headers.update(self.auth_headers())

    def tearDown(self):
        app.dependency_overrides.clear()
        self.client.close()
        self.temp_dir.cleanup()

    def auth_headers(
        self,
        *,
        user_id: str = "final-admin",
        role: str = "admin",
        project_ids: list[str] | None = None,
        active_project_id: str | None = None,
    ) -> dict[str, str]:
        allowed_project_ids = project_ids or ["p-final"]
        return {
            self.config.auth_header_user_id: user_id,
            self.config.auth_header_display_name: "Final Acceptance Admin",
            self.config.auth_header_email: "final-admin@example.internal",
            self.config.auth_header_role: role,
            self.config.auth_header_team_id: "team-final",
            self.config.auth_header_project_ids: ",".join(allowed_project_ids),
            self.config.auth_active_project_header: active_project_id or allowed_project_ids[0],
        }

    def test_smoke_and_api_contracts_are_ready_for_launch(self):
        health = self.client.get("/health")
        self.assertEqual(health.status_code, 200)
        self.assertEqual(health.json()["status"], "ok")

        ready = self.client.get("/ready")
        self.assertEqual(ready.status_code, 200)
        ready_payload = ready.json()
        self.assertEqual(ready_payload["status"], "ready")
        self.assertTrue(all(ready_payload["storage"]["table_status"].values()))

        contract_endpoints = [
            ("/api/v1/system/bootstrap", {"overview", "knowledge_status", "documents", "graph", "auth"}),
            ("/api/v1/documents", None),
            ("/api/v1/knowledge-base/status", {"ready", "chunk_count", "document_count", "current_job"}),
            ("/api/v1/graph", {"nodes", "edges"}),
            ("/api/v1/logs", {"summary", "filters", "lines"}),
            ("/api/v1/settings", {"llm_provider", "embedding_provider", "operations_managed_fields"}),
            ("/api/v1/runtime/config", {"description", "managed_by_ops"}),
        ]

        for path, expected_keys in contract_endpoints:
            with self.subTest(path=path):
                response = self.client.get(path)
                self.assertEqual(response.status_code, 200)
                payload = response.json()
                if expected_keys is not None:
                    self.assertTrue(expected_keys.issubset(set(payload.keys())))

        bootstrap = self.client.get("/api/v1/system/bootstrap").json()
        self.assertEqual(bootstrap["overview"]["auth_mode"], "trusted_header")
        self.assertTrue(bootstrap["overview"]["llm_api_ready"])
        self.assertTrue(bootstrap["overview"]["embedding_api_ready"])
        self.assertGreaterEqual(bootstrap["overview"]["source_file_count"], 1)
        self.assertGreaterEqual(bootstrap["overview"]["pending_file_count"], 0)
        self.assertEqual(bootstrap["overview"]["failed_file_count"], 0)

    def test_security_permissions_and_project_scope_are_enforced(self):
        unauthenticated = TestClient(app)
        try:
            response = unauthenticated.get("/api/v1/system/bootstrap")
        finally:
            unauthenticated.close()
        self.assertEqual(response.status_code, 401)

        viewer_headers = self.auth_headers(role="viewer")
        self.assertEqual(self.client.get("/api/v1/documents", headers=viewer_headers).status_code, 200)
        self.assertEqual(self.client.get("/api/v1/settings", headers=viewer_headers).status_code, 403)
        self.assertEqual(self.client.delete("/api/v1/logs", headers=viewer_headers).status_code, 403)
        self.assertEqual(
            self.client.post("/api/v1/knowledge-base/rebuild", headers=viewer_headers, json={"mode": "sync"}).status_code,
            403,
        )

        denied_project = self.client.get(
            "/api/v1/system/bootstrap",
            headers=self.auth_headers(project_ids=["p-final"], active_project_id="p-other"),
        )
        self.assertEqual(denied_project.status_code, 403)

        settings_rejection = self.client.put(
            "/api/v1/settings",
            json={"values": {"LLM_API_KEY": "sk-forbidden"}},
        )
        self.assertEqual(settings_rejection.status_code, 400)
        self.assertEqual(settings_rejection.json()["detail"]["forbidden_keys"], ["LLM_API_KEY"])

        with connect_state_db(self.config) as connection:
            events = connection.execute(
                """
                SELECT action, outcome
                FROM application_audit_events
                WHERE action IN ('project.access', 'settings.update')
                ORDER BY created_at ASC
                """
            ).fetchall()
        self.assertGreaterEqual(len(events), 2)
        self.assertIn(("project.access", "denied"), [(row["action"], row["outcome"]) for row in events])
        self.assertIn(("settings.update", "failed"), [(row["action"], row["outcome"]) for row in events])

    def test_document_lifecycle_beta_flow_and_audit_trail(self):
        file_name = "final-acceptance-beta.md"
        upload = self.client.post(
            "/api/v1/documents/upload",
            files={"files": (file_name, b"# Beta flow\n\nUpload preview delete acceptance.", "text/markdown")},
        )
        self.assertEqual(upload.status_code, 200)
        self.assertEqual(upload.json()["saved_count"], 1)

        documents = self.client.get("/api/v1/documents").json()
        uploaded = next(item for item in documents if item["name"] == file_name)
        self.assertNotIn("path", uploaded)

        preview = self.client.get("/api/v1/documents/preview", params={"document_id": uploaded["document_id"]})
        self.assertEqual(preview.status_code, 200)
        self.assertIn("Upload preview delete acceptance.", preview.json()["preview"])

        metadata = self.client.patch(
            "/api/v1/documents/metadata",
            json={
                "document_ids": [uploaded["document_id"]],
                "theme": "Final Acceptance",
                "tags": ["release", "beta"],
            },
        )
        self.assertEqual(metadata.status_code, 200)
        self.assertEqual(metadata.json()[0]["theme"], "Final Acceptance")

        renamed = self.client.put(
            "/api/v1/documents/rename",
            json={"document_id": uploaded["document_id"], "new_name": "final-acceptance-beta-renamed.md"},
        )
        self.assertEqual(renamed.status_code, 200)
        self.assertEqual(renamed.json()["new_name"], "final-acceptance-beta-renamed.md")

        deleted = self.client.request(
            "DELETE",
            "/api/v1/documents",
            json={"document_ids": [uploaded["document_id"]]},
        )
        self.assertEqual(deleted.status_code, 200)
        self.assertEqual(deleted.json()["deleted_count"], 1)

        with connect_state_db(self.config) as connection:
            actions = [
                row["action"]
                for row in connection.execute(
                    """
                    SELECT action
                    FROM application_audit_events
                    WHERE action LIKE 'documents.%'
                    ORDER BY created_at ASC
                    """
                ).fetchall()
            ]
        self.assertEqual(
            actions,
            ["documents.upload", "documents.metadata.update", "documents.rename", "documents.delete"],
        )

    def test_chat_settings_and_negative_paths_remain_safe(self):
        chat = self.client.post(
            "/api/v1/chat/ask",
            json={
                "question": "Final acceptance health probe",
                "scene": "qa_query",
                "top_k": 1,
                "session_title": "Final acceptance",
            },
        )
        self.assertEqual(chat.status_code, 200)
        chat_payload = chat.json()
        self.assertIn("session_id", chat_payload)
        self.assertTrue(chat_payload["answer"])

        invalid_rebuild = self.client.post("/api/v1/knowledge-base/rebuild", json={"mode": "destroy"})
        self.assertEqual(invalid_rebuild.status_code, 422)

        unsupported_upload = self.client.post(
            "/api/v1/documents/upload",
            files={"files": ("malware.exe", b"MZ", "application/x-msdownload")},
        )
        self.assertEqual(unsupported_upload.status_code, 400)
        self.assertTrue(list(self.config.upload_quarantine_dir.glob("*.json")))

    def test_api_performance_and_short_stability_budget(self):
        timed_paths = [
            "/api/v1/system/bootstrap",
            "/api/v1/documents",
            "/api/v1/knowledge-base/status",
            "/api/v1/graph",
            "/api/v1/logs",
        ]
        samples_ms: list[float] = []

        for _ in range(6):
            for path in timed_paths:
                started = time.perf_counter()
                response = self.client.get(path)
                elapsed_ms = (time.perf_counter() - started) * 1000
                self.assertEqual(response.status_code, 200)
                samples_ms.append(elapsed_ms)

        sorted_samples = sorted(samples_ms)
        p95_ms = sorted_samples[int(len(sorted_samples) * 0.95) - 1]
        self.assertLess(p95_ms, 1500, f"API p95 too slow: {p95_ms:.2f} ms")

        for index in range(25):
            path = timed_paths[index % len(timed_paths)]
            with self.subTest(iteration=index, path=path):
                response = self.client.get(path)
                self.assertEqual(response.status_code, 200)
