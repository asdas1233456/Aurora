import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.api.dependencies import get_app_config, get_runtime_config
from app.config import AppConfig
from app.schemas import KnowledgeBaseJob
from app.server import app


def make_test_config(base_dir: Path) -> AppConfig:
    return AppConfig(
        base_dir=base_dir,
        data_dir=base_dir / "data",
        db_dir=base_dir / "db",
        logs_dir=base_dir / "logs",
        llm_provider="openai",
        embedding_provider="openai",
        llm_api_key="sk-test",
        embedding_api_key="sk-embed",
        llm_model="gpt-4.1-mini",
        embedding_model="text-embedding-3-small",
        collection_name="test_collection",
    )


class ApiRouteTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.config = make_test_config(Path(self.temp_dir.name))
        self.config.ensure_directories()
        self.sample_path = self.config.data_dir / "notes.md"
        self.sample_path.write_text("# Notes\n\nAurora api route acceptance content.", encoding="utf-8")

        app.dependency_overrides[get_app_config] = lambda: self.config
        app.dependency_overrides[get_runtime_config] = lambda: self.config
        self.client = TestClient(app)

    def tearDown(self):
        app.dependency_overrides.clear()
        self.client.close()
        self.temp_dir.cleanup()

    def test_documents_list_and_preview_hide_absolute_paths(self):
        response = self.client.get("/api/v1/documents")
        self.assertEqual(response.status_code, 200)

        payload = response.json()
        self.assertEqual(len(payload), 1)
        document = payload[0]
        self.assertIn("document_id", document)
        self.assertEqual(document["name"], "notes.md")
        self.assertEqual(document["relative_path"], "notes.md")
        self.assertNotIn("path", document)

        preview_response = self.client.get(
            "/api/v1/documents/preview",
            params={"document_id": document["document_id"]},
        )
        self.assertEqual(preview_response.status_code, 200)
        preview_payload = preview_response.json()
        self.assertEqual(preview_payload["document_id"], document["document_id"])
        self.assertIn("Aurora api route acceptance content.", preview_payload["preview"])

    def test_system_bootstrap_returns_combined_workspace_payload(self):
        response = self.client.get("/api/v1/system/bootstrap")
        self.assertEqual(response.status_code, 200)

        payload = response.json()
        self.assertIn("overview", payload)
        self.assertIn("knowledge_status", payload)
        self.assertIn("documents", payload)
        self.assertIn("graph", payload)
        self.assertEqual(payload["overview"]["source_file_count"], 1)
        self.assertEqual(payload["knowledge_status"]["document_count"], 1)
        self.assertEqual(len(payload["documents"]), 1)
        self.assertNotIn("path", payload["documents"][0])

    def test_rename_metadata_and_delete_use_document_ids(self):
        list_response = self.client.get("/api/v1/documents")
        document = list_response.json()[0]
        document_id = document["document_id"]

        metadata_response = self.client.patch(
            "/api/v1/documents/metadata",
            json={
                "document_ids": [document_id],
                "theme": "Acceptance",
                "tags": ["p1", "api"],
            },
        )
        self.assertEqual(metadata_response.status_code, 200)
        updated_document = next(
            item for item in metadata_response.json() if item["document_id"] == document_id
        )
        self.assertEqual(updated_document["theme"], "Acceptance")
        self.assertEqual(updated_document["tags"], ["p1", "api"])
        self.assertNotIn("path", updated_document)

        rename_response = self.client.put(
            "/api/v1/documents/rename",
            json={"document_id": document_id, "new_name": "renamed-notes.md"},
        )
        self.assertEqual(rename_response.status_code, 200)
        rename_payload = rename_response.json()
        self.assertEqual(rename_payload["document_id"], document_id)
        self.assertEqual(rename_payload["new_relative_path"], "renamed-notes.md")
        self.assertNotIn("old_path", rename_payload)
        self.assertNotIn("new_path", rename_payload)

        delete_response = self.client.request(
            "DELETE",
            "/api/v1/documents",
            json={"document_ids": [document_id]},
        )
        self.assertEqual(delete_response.status_code, 200)
        delete_payload = delete_response.json()
        self.assertEqual(delete_payload["deleted_ids"], [document_id])
        self.assertEqual(delete_payload["missing_ids"], [])
        self.assertFalse((self.config.data_dir / "renamed-notes.md").exists())

    @patch("app.api.routes.knowledge_base.rebuild_knowledge_base")
    def test_knowledge_base_routes_accept_sync_and_scan_modes(self, mock_rebuild_knowledge_base):
        mock_rebuild_knowledge_base.side_effect = [
            KnowledgeBaseJob(
                job_id="job-sync",
                status="queued",
                mode="sync",
                stage="queued",
                progress=0.0,
                message="queued",
            ),
            KnowledgeBaseJob(
                job_id="job-scan",
                status="queued",
                mode="scan",
                stage="queued",
                progress=0.0,
                message="queued",
            ),
        ]

        sync_response = self.client.post("/api/v1/knowledge-base/rebuild", json={"mode": "sync"})
        self.assertEqual(sync_response.status_code, 200)
        self.assertEqual(sync_response.json()["mode"], "sync")

        scan_response = self.client.post("/api/v1/knowledge-base/scan")
        self.assertEqual(scan_response.status_code, 200)
        self.assertEqual(scan_response.json()["mode"], "scan")


if __name__ == "__main__":
    unittest.main()
