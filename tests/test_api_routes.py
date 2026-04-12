import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.api.dependencies import get_app_config, get_runtime_config
from app.config import AppConfig
from app.schemas import (
    Citation,
    ChatMessageCreate,
    ChatResult,
    KnowledgeBaseJob,
    MemoryFactCreate,
    MemoryRequestContext,
    RetrievedChunk,
)
from app.modules.system.request_concurrency import RequestConcurrencyGuard
from app.services.abuse_guard import AbuseGuard
from app.services.chat_memory_models import ChatMemoryCandidate
from app.services.memory_audit_service import MemoryAuditService
from app.services.memory_repository import MemoryRepository
from app.services.message_repository import MessageRepository
from app.services.session_repository import SessionRepository
from app.services.storage_service import connect_state_db
from app.bootstrap.http_app import app


def make_test_config(base_dir: Path) -> AppConfig:
    AbuseGuard.reset_all()
    RequestConcurrencyGuard.reset_all()
    return AppConfig(
        base_dir=base_dir,
        data_dir=base_dir / "data",
        db_dir=base_dir / "db",
        logs_dir=base_dir / "logs",
        tenant_id="t1",
        auth_mode="trusted_header",
        llm_provider="openai",
        embedding_provider="openai",
        llm_api_key="sk-test",
        embedding_api_key="sk-embed",
        llm_model="gpt-4.1-mini",
        embedding_model="text-embedding-3-small",
        collection_name="test_collection",
        memory_llm_review_enabled=False,
    )


class FakeHttpResponse:
    def __init__(
        self,
        *,
        text: str,
        url: str = "https://example.test/aurora",
        content_type: str = "text/html; charset=utf-8",
        status_code: int = 200,
    ) -> None:
        self.text = text
        self.url = url
        self.status_code = status_code
        self.headers = {"Content-Type": content_type}

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


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
        self.client.headers.update(self.auth_headers())

    def tearDown(self):
        app.dependency_overrides.clear()
        self.client.close()
        self.temp_dir.cleanup()

    def auth_headers(
        self,
        *,
        user_id: str = "u1",
        role: str = "admin",
        team_id: str = "team-platform",
        project_ids: list[str] | None = None,
        active_project_id: str | None = None,
        display_name: str = "Aurora Admin",
        email: str = "aurora-admin@example.internal",
    ) -> dict[str, str]:
        allowed_project_ids = project_ids or ["p1"]
        return {
            self.config.auth_header_user_id: user_id,
            self.config.auth_header_display_name: display_name,
            self.config.auth_header_email: email,
            self.config.auth_header_role: role,
            self.config.auth_header_team_id: team_id,
            self.config.auth_header_project_ids: ",".join(allowed_project_ids),
            self.config.auth_active_project_header: active_project_id or allowed_project_ids[0],
        }

    def internal_headers(self, **overrides) -> dict[str, str]:
        headers = dict(self.auth_headers(**overrides))
        headers["X-Aurora-Internal-Api"] = "true"
        return headers

    def test_business_api_requires_authentication(self):
        unauthenticated_client = TestClient(app)
        try:
            response = unauthenticated_client.get("/api/v1/system/bootstrap")
        finally:
            unauthenticated_client.close()

        self.assertEqual(response.status_code, 401)

    def test_member_cannot_access_admin_operations(self):
        member_headers = self.auth_headers(role="member")

        settings_response = self.client.get("/api/v1/settings", headers=member_headers)
        self.assertEqual(settings_response.status_code, 403)

        clear_logs_response = self.client.delete("/api/v1/logs", headers=member_headers)
        self.assertEqual(clear_logs_response.status_code, 403)

        rebuild_response = self.client.post(
            "/api/v1/knowledge-base/rebuild",
            headers=member_headers,
            json={"mode": "sync"},
        )
        self.assertEqual(rebuild_response.status_code, 403)

        internal_response = self.client.get("/api/v1/internal/providers", headers=member_headers)
        self.assertEqual(internal_response.status_code, 403)

    def test_active_project_must_stay_within_authorized_scope(self):
        headers = self.auth_headers(project_ids=["p1"], active_project_id="p2")

        response = self.client.get("/api/v1/system/bootstrap", headers=headers)

        self.assertEqual(response.status_code, 403)
        self.assertEqual(
            response.json()["detail"],
            "You do not have access to the requested project.",
        )
        with connect_state_db(self.config) as connection:
            audit_row = connection.execute(
                """
                SELECT action, outcome, target_id
                FROM application_audit_events
                WHERE action = 'project.access'
                ORDER BY created_at DESC
                LIMIT 1
                """
            ).fetchone()
        self.assertIsNotNone(audit_row)
        self.assertEqual(audit_row["outcome"], "denied")
        self.assertEqual(audit_row["target_id"], "p2")

    def test_settings_reject_operations_managed_keys_and_audit_failure(self):
        response = self.client.put(
            "/api/v1/settings",
            json={"values": {"LLM_API_KEY": "sk-should-not-pass"}},
        )

        self.assertEqual(response.status_code, 400)
        payload = response.json()["detail"]
        self.assertIn("forbidden_keys", payload)
        self.assertEqual(payload["forbidden_keys"], ["LLM_API_KEY"])

        test_response = self.client.post(
            "/api/v1/settings/test",
            json={"values": {"EMBEDDING_API_KEY": "embed-should-not-pass"}},
        )
        self.assertEqual(test_response.status_code, 400)
        self.assertEqual(
            test_response.json()["detail"]["forbidden_keys"],
            ["EMBEDDING_API_KEY"],
        )

        with connect_state_db(self.config) as connection:
            rows = connection.execute(
                """
                SELECT action, outcome, details_json
                FROM application_audit_events
                WHERE action IN ('settings.update', 'settings.test')
                ORDER BY created_at ASC
                """
            ).fetchall()
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["outcome"], "failed")
        self.assertIn("LLM_API_KEY", rows[0]["details_json"])
        self.assertEqual(rows[1]["outcome"], "failed")
        self.assertIn("EMBEDDING_API_KEY", rows[1]["details_json"])

    def test_upload_rejects_oversized_files_and_quarantines_them(self):
        self.config.upload_max_file_bytes = 8

        response = self.client.post(
            "/api/v1/documents/upload",
            files={"files": ("too-large.md", b"0123456789", "text/markdown")},
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("exceeds the upload limit", response.json()["detail"])

        quarantine_metadata_files = sorted(self.config.upload_quarantine_dir.glob("*.json"))
        self.assertTrue(quarantine_metadata_files)
        metadata_text = quarantine_metadata_files[-1].read_text(encoding="utf-8")
        self.assertIn('"reason": "file_too_large"', metadata_text)

    @patch("app.api.routes.knowledge_base.get_current_rebuild_job")
    def test_rebuild_rejects_concurrent_active_job(self, mock_get_current_rebuild_job):
        mock_get_current_rebuild_job.return_value = KnowledgeBaseJob(
            job_id="job-running",
            status="running",
            mode="sync",
            stage="indexing",
            progress=0.42,
            message="running",
        )

        response = self.client.post("/api/v1/knowledge-base/rebuild", json={"mode": "sync"})

        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["detail"]["active_job_id"], "job-running")
        with connect_state_db(self.config) as connection:
            audit_row = connection.execute(
                """
                SELECT action, outcome, details_json
                FROM application_audit_events
                WHERE action = 'knowledge_base.rebuild'
                ORDER BY created_at DESC
                LIMIT 1
                """
            ).fetchone()
        self.assertIsNotNone(audit_row)
        self.assertEqual(audit_row["outcome"], "denied")
        self.assertIn("job_in_progress", audit_row["details_json"])

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
        self.assertIn("metadata", preview_payload)
        self.assertEqual(preview_payload["metadata"]["file_type"], "md")
        self.assertEqual(preview_payload["metadata"]["segment_count"], 1)

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
        self.assertEqual(payload["graph"]["summary"]["document_count"], 1)
        self.assertIn("indexed_document_count", payload["graph"]["summary"])
        self.assertIn("attention_document_count", payload["graph"]["summary"])
        self.assertIn("status_counts", payload["graph"]["summary"])
        document_node = next(
            node for node in payload["graph"]["nodes"] if node["node_type"] == "document"
        )
        self.assertEqual(document_node["meta"]["document_id"], payload["documents"][0]["document_id"])
        self.assertIn("chunk_count", document_node["meta"])
        self.assertIn("citation_count", document_node["meta"])
        self.assertNotIn("path", document_node["meta"])

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

        second_delete_response = self.client.request(
            "DELETE",
            "/api/v1/documents",
            json={"document_ids": [document_id]},
        )
        self.assertEqual(second_delete_response.status_code, 200)
        second_delete_payload = second_delete_response.json()
        self.assertEqual(second_delete_payload["deleted_ids"], [])
        self.assertEqual(second_delete_payload["missing_ids"], [document_id])

    def test_upload_preview_accepts_structured_text_document_types(self):
        upload_response = self.client.post(
            "/api/v1/documents/upload",
            files={
                "files": (
                    "api_test_cases.csv",
                    b"case_id,module,priority\nAPI-001,Login,P0\n",
                    "text/csv",
                )
            },
        )
        self.assertEqual(upload_response.status_code, 200)
        payload = upload_response.json()
        self.assertEqual(payload["saved_count"], 1)
        self.assertEqual(payload["saved_files"], ["api_test_cases.csv"])

        list_response = self.client.get("/api/v1/documents")
        documents = list_response.json()
        uploaded_document = next(
            item for item in documents if item["name"] == "api_test_cases.csv"
        )
        self.assertEqual(uploaded_document["extension"], "csv")

        preview_response = self.client.get(
            "/api/v1/documents/preview",
            params={"document_id": uploaded_document["document_id"]},
        )
        self.assertEqual(preview_response.status_code, 200)
        self.assertIn("API-001", preview_response.json()["preview"])

    @patch("app.services.etl.parsers.url_parser.requests.get")
    def test_upload_preview_accepts_url_shortcuts(self, mock_get):
        mock_get.return_value = FakeHttpResponse(
            text="""
            <html>
              <head><title>Aurora Shortcut</title></head>
              <body>
                <main>
                  <h1>Shortcut Preview</h1>
                  <p>Imported from URL shortcut.</p>
                </main>
              </body>
            </html>
            """,
        )

        upload_response = self.client.post(
            "/api/v1/documents/upload",
            files={
                "files": (
                    "aurora-shortcut.url",
                    b"[InternetShortcut]\nURL=https://example.test/aurora\n",
                    "text/plain",
                )
            },
        )
        self.assertEqual(upload_response.status_code, 200)

        list_response = self.client.get("/api/v1/documents")
        documents = list_response.json()
        uploaded_document = next(
            item for item in documents if item["name"] == "aurora-shortcut.url"
        )
        self.assertEqual(uploaded_document["extension"], "url")

        preview_response = self.client.get(
            "/api/v1/documents/preview",
            params={"document_id": uploaded_document["document_id"]},
        )
        self.assertEqual(preview_response.status_code, 200)
        preview_payload = preview_response.json()
        self.assertIn("Shortcut Preview", preview_payload["preview"])
        self.assertEqual(preview_payload["metadata"]["file_type"], "url")
        self.assertEqual(preview_payload["metadata"]["title"], "Aurora Shortcut")
        self.assertEqual(
            preview_payload["metadata"]["source_url"],
            "https://example.test/aurora",
        )
        self.assertEqual(
            preview_payload["metadata"]["resolved_url"],
            "https://example.test/aurora",
        )

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

    @patch("app.api.chat.answer_with_rag")
    def test_chat_route_loads_scoped_memory_and_persists_chat_session(self, mock_answer_with_rag):
        repository = MemoryRepository(self.config)
        scoped_fact = repository.create_memory_fact(
            MemoryFactCreate(
                tenant_id="t1",
                owner_user_id="u1",
                project_id="p1",
                scope_type="session",
                scope_id="s1",
                type="fact",
                content="Current chat is focused on scope isolation",
                source_session_id="s1",
            )
        )
        repository.create_memory_fact(
            MemoryFactCreate(
                tenant_id="t1",
                owner_user_id="u2",
                project_id="p1",
                scope_type="user",
                scope_id="u2",
                type="preference",
                content="Other user preference",
                source_session_id="s2",
            )
        )

        mock_answer_with_rag.return_value = ChatResult(
            answer="memory-aware answer",
            citations=[],
            retrieved_count=0,
            memory_count=1,
        )

        response = self.client.post(
            "/api/v1/chat/ask",
            json={
                "question": "What are we discussing?",
                "chat_history": [],
                "tenant_id": "t1",
                "user_id": "u1",
                "project_id": "p1",
                "session_id": "s1",
                "session_title": "Scope Isolation",
                "request_id": "req-chat-route",
            },
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["session_id"], "s1")
        self.assertNotIn("memory_count", payload)
        self.assertNotIn("used_memory_ids", payload)

        passed_memory_context = mock_answer_with_rag.call_args.kwargs["memory_context"]
        self.assertEqual([item["memory_id"] if isinstance(item, dict) else item.memory_id for item in passed_memory_context], [scoped_fact.id])
        self.assertEqual(mock_answer_with_rag.call_args.kwargs["chat_history"], [])

        with connect_state_db(self.config) as connection:
            session_row = connection.execute(
                "SELECT title, tenant_id, user_id, project_id FROM chat_sessions WHERE id = ?",
                ("s1",),
            ).fetchone()
            message_rows = connection.execute(
                """
                SELECT role, content
                FROM chat_messages
                WHERE tenant_id = ? AND session_id = ?
                ORDER BY created_at ASC
                """,
                ("t1", "s1"),
            ).fetchall()

        self.assertIsNotNone(session_row)
        self.assertEqual(session_row["title"], "Scope Isolation")
        self.assertEqual(session_row["tenant_id"], "t1")
        self.assertEqual(session_row["user_id"], "u1")
        self.assertEqual(session_row["project_id"], "p1")
        self.assertEqual(
            [(row["role"], row["content"]) for row in message_rows],
            [
                ("user", "What are we discussing?"),
                ("assistant", "memory-aware answer"),
            ],
        )

        audits = MemoryAuditService(self.config).list_by_request_id("t1", "req-chat-route")
        self.assertEqual(len(audits), 2)
        self.assertEqual(audits[0].action, "retrieve")
        self.assertEqual(audits[0].memory_fact_id, scoped_fact.id)
        self.assertEqual(audits[1].action, "inject")

    @patch("app.api.chat.answer_with_rag")
    def test_chat_route_exposes_chunk_and_page_in_citations(self, mock_answer_with_rag):
        mock_answer_with_rag.return_value = ChatResult(
            answer="citation aware answer",
            citations=[
                Citation(
                    knowledge_id="kb-1",
                    document_id="doc-pdf",
                    file_name="guide.pdf",
                    source_path="guide.pdf",
                    relative_path="guide.pdf",
                    snippet="Page 2 snippet",
                    full_text="Page 2 snippet with more context",
                    score=0.93,
                    chunk_id="chunk-2",
                    page_number=2,
                )
            ],
            retrieved_count=1,
            memory_count=0,
            used_knowledge_ids=["kb-1"],
        )

        response = self.client.post(
            "/api/v1/chat/ask",
            json={
                "question": "What is on page 2?",
                "chat_history": [],
                "tenant_id": "t1",
                "user_id": "u1",
                "project_id": "p1",
                "session_id": "s-citation-page",
                "request_id": "req-citation-page",
            },
        )

        self.assertEqual(response.status_code, 200)
        citation = response.json()["citations"][0]
        self.assertEqual(citation["chunk_id"], "chunk-2")
        self.assertEqual(citation["page_number"], 2)

    @patch("app.api.chat.answer_with_rag")
    def test_chat_route_recovers_recent_messages_from_persistence(self, mock_answer_with_rag):
        mock_answer_with_rag.side_effect = [
            ChatResult(
                answer="first answer",
                citations=[],
                retrieved_count=0,
                memory_count=0,
            ),
            ChatResult(
                answer="second answer",
                citations=[],
                retrieved_count=0,
                memory_count=0,
            ),
        ]

        first_response = self.client.post(
            "/api/v1/chat/ask",
            json={
                "question": "How does persistence work?",
                "chat_history": [],
                "tenant_id": "t1",
                "user_id": "u1",
                "project_id": "p1",
                "session_id": "s-recover",
                "session_title": "Persistence",
                "request_id": "req-persist-1",
            },
        )
        self.assertEqual(first_response.status_code, 200)

        second_response = self.client.post(
            "/api/v1/chat/ask",
            json={
                "question": "What about audit logs?",
                "chat_history": [{"role": "assistant", "content": "frontend stale context"}],
                "tenant_id": "t1",
                "user_id": "u1",
                "project_id": "p1",
                "session_id": "s-recover",
                "session_title": "Persistence",
                "request_id": "req-persist-2",
            },
        )
        self.assertEqual(second_response.status_code, 200)

        second_call_history = mock_answer_with_rag.call_args_list[1].kwargs["chat_history"]
        self.assertEqual(
            second_call_history,
            [
                {"role": "user", "content": "How does persistence work?"},
                {"role": "assistant", "content": "first answer"},
            ],
        )

        with connect_state_db(self.config) as connection:
            rows = connection.execute(
                """
                SELECT role, content
                FROM chat_messages
                WHERE tenant_id = ? AND session_id = ?
                ORDER BY created_at ASC
                """,
                ("t1", "s-recover"),
            ).fetchall()

        self.assertEqual(
            [(row["role"], row["content"]) for row in rows],
            [
                ("user", "How does persistence work?"),
                ("assistant", "first answer"),
                ("user", "What about audit logs?"),
                ("assistant", "second answer"),
            ],
        )

    @patch("app.api.chat.answer_with_rag")
    @patch("app.api.chat.MemoryRetriever.retrieve_bundle")
    def test_chat_route_degrades_to_knowledge_only_when_memory_retrieval_fails(
        self,
        mock_retrieve_bundle,
        mock_answer_with_rag,
    ):
        mock_retrieve_bundle.side_effect = RuntimeError("memory subsystem unavailable")
        mock_answer_with_rag.return_value = ChatResult(
            answer="knowledge-only answer",
            citations=[],
            retrieved_count=0,
            memory_count=0,
        )

        response = self.client.post(
            "/api/v1/chat/ask",
            json={
                "question": "Can Aurora keep answering when memory is down?",
                "chat_history": [],
                "tenant_id": "t1",
                "user_id": "u1",
                "project_id": "p1",
                "session_id": "s-degrade",
                "request_id": "req-chat-degrade",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertNotIn("memory_count", response.json())
        self.assertNotIn("used_memory_ids", response.json())
        self.assertEqual(mock_answer_with_rag.call_args.kwargs["memory_context"], [])

    @patch("app.api.chat.answer_with_rag")
    def test_chat_route_auto_persists_structured_project_fact_for_future_turns_without_public_leak(
        self,
        mock_answer_with_rag,
    ):
        mock_answer_with_rag.side_effect = [
            ChatResult(
                answer="first answer",
                citations=[],
                retrieved_count=0,
            ),
            ChatResult(
                answer="second answer",
                citations=[],
                retrieved_count=0,
                memory_count=1,
            ),
        ]

        first_response = self.client.post(
            "/api/v1/chat/ask",
            json={
                "question": "记住：stack.framework: FastAPI。现在帮我总结一下项目结构。",
                "chat_history": [],
                "tenant_id": "t1",
                "user_id": "u1",
                "project_id": "p1",
                "session_id": "s-fact-1",
                "request_id": "req-fact-1",
            },
        )
        self.assertEqual(first_response.status_code, 200)
        self.assertNotIn("memory_count", first_response.json())
        self.assertNotIn("used_memory_ids", first_response.json())

        memories = MemoryRepository(self.config).list_by_filters(
            tenant_id="t1",
            scope_type="project",
            scope_id="p1",
            limit=10,
        )
        self.assertEqual(len(memories), 1)
        self.assertEqual(memories[0].fact_key, "stack.framework")

        second_response = self.client.post(
            "/api/v1/chat/ask",
            json={
                "question": "我们项目当前的 framework 是什么？",
                "chat_history": [],
                "tenant_id": "t1",
                "user_id": "u1",
                "project_id": "p1",
                "session_id": "s-fact-2",
                "request_id": "req-fact-2",
            },
        )
        self.assertEqual(second_response.status_code, 200)

        second_call_memory = mock_answer_with_rag.call_args_list[1].kwargs["memory_context"]
        self.assertEqual(
            [item["memory_id"] if isinstance(item, dict) else item.memory_id for item in second_call_memory],
            [memories[0].id],
        )

    @patch("app.services.chat_memory_llm_review_service.ChatMemoryLLMReviewService.review_turn")
    @patch("app.api.chat.answer_with_rag")
    def test_chat_route_llm_review_persists_project_fact_for_future_turn_without_public_leak(
        self,
        mock_answer_with_rag,
        mock_review_turn,
    ):
        self.config.memory_llm_review_enabled = True
        mock_answer_with_rag.side_effect = [
            ChatResult(
                answer="first answer",
                citations=[],
                retrieved_count=0,
            ),
            ChatResult(
                answer="second answer",
                citations=[],
                retrieved_count=0,
                memory_count=1,
            ),
        ]
        mock_review_turn.side_effect = [
            [
                ChatMemoryCandidate(
                    content="default backend port: 8000",
                    memory_type="fact",
                    scope_type="project",
                    confirmed=False,
                    source_kind="memory_llm_review",
                    source_type="model_inferred",
                    source_confidence=0.92,
                    reviewed_by_human=False,
                    fact_key="env.default_backend_port",
                    origin="llm_review",
                )
            ],
            [],
        ]

        first_response = self.client.post(
            "/api/v1/chat/ask",
            json={
                "question": "Our default backend port stays 8000 for this project. Please outline the startup flow.",
                "chat_history": [],
                "tenant_id": "t1",
                "user_id": "u1",
                "project_id": "p1",
                "session_id": "s-llm-fact-1",
                "request_id": "req-llm-fact-1",
            },
        )
        self.assertEqual(first_response.status_code, 200)
        self.assertNotIn("memory_count", first_response.json())
        self.assertNotIn("used_memory_ids", first_response.json())

        memories = MemoryRepository(self.config).list_by_filters(
            tenant_id="t1",
            scope_type="project",
            scope_id="p1",
            limit=10,
        )
        self.assertEqual(len(memories), 1)
        self.assertEqual(memories[0].fact_key, "env.default_backend_port")

        second_response = self.client.post(
            "/api/v1/chat/ask",
            json={
                "question": "What is the default backend port?",
                "chat_history": [],
                "tenant_id": "t1",
                "user_id": "u1",
                "project_id": "p1",
                "session_id": "s-llm-fact-2",
                "request_id": "req-llm-fact-2",
            },
        )
        self.assertEqual(second_response.status_code, 200)

        second_call_memory = mock_answer_with_rag.call_args_list[1].kwargs["memory_context"]
        self.assertEqual(
            [item["memory_id"] if isinstance(item, dict) else item.memory_id for item in second_call_memory],
            [memories[0].id],
        )

    @patch("app.api.chat.ChatMemoryService.assimilate_turn")
    @patch("app.api.chat.answer_with_rag")
    def test_chat_route_keeps_serving_when_auto_memory_assimilation_fails(
        self,
        mock_answer_with_rag,
        mock_assimilate_turn,
    ):
        mock_answer_with_rag.return_value = ChatResult(
            answer="still works",
            citations=[],
            retrieved_count=0,
        )
        mock_assimilate_turn.side_effect = RuntimeError("auto memory failed")

        response = self.client.post(
            "/api/v1/chat/ask",
            json={
                "question": "请记住我们项目使用 FastAPI。现在继续。",
                "chat_history": [],
                "tenant_id": "t1",
                "user_id": "u1",
                "project_id": "p1",
                "session_id": "s-memory-fail",
                "request_id": "req-memory-fail",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertNotIn("memory_count", response.json())
        self.assertEqual(
            MemoryRepository(self.config).list_by_filters(tenant_id="t1", limit=10),
            [],
        )
        with connect_state_db(self.config) as connection:
            message_count = connection.execute(
                "SELECT COUNT(*) AS count FROM chat_messages WHERE tenant_id = ? AND session_id = ?",
                ("t1", "s-memory-fail"),
            ).fetchone()["count"]
        self.assertEqual(message_count, 2)

    @patch("app.api.chat.answer_with_rag")
    def test_chat_stream_does_not_expose_memory_metadata_to_public_clients(self, mock_answer_with_rag):
        mock_answer_with_rag.return_value = ChatResult(
            answer="stream answer",
            citations=[],
            retrieved_count=0,
            memory_count=1,
            used_memory_ids=["mem-1"],
        )

        response = self.client.post(
            "/api/v1/chat/stream",
            json={
                "question": "What are we discussing?",
                "chat_history": [],
                "tenant_id": "t1",
                "user_id": "u1",
                "project_id": "p1",
                "session_id": "s-stream-hidden",
                "request_id": "req-stream-hidden",
            },
        )

        self.assertEqual(response.status_code, 200)
        events = [
            json.loads(line.decode("utf-8") if isinstance(line, bytes) else line)
            for line in response.iter_lines()
            if line
        ]
        meta_event = next(item for item in events if item["type"] == "meta")
        done_event = next(item for item in events if item["type"] == "done")

        self.assertNotIn("memory_count", meta_event)
        self.assertNotIn("used_memory_ids", meta_event)
        self.assertNotIn("memory_count", done_event)
        self.assertNotIn("used_memory_ids", done_event)

    def test_internal_memory_api_supports_manual_create_list_update_and_audit(self):
        headers = {"X-Aurora-Internal-Api": "true"}

        create_response = self.client.post(
            "/api/v1/internal/memory/facts",
            headers=headers,
            json={
                "content": "Aurora 当前优先实现记忆系统第一特性",
                "type": "fact",
                "scope_type": "project",
                "tenant_id": "t1",
                "user_id": "u1",
                "project_id": "p1",
                "session_id": "s1",
                "session_title": "Manual Memory Validation",
                "request_id": "req-manual-create",
            },
        )
        self.assertEqual(create_response.status_code, 200)
        create_payload = create_response.json()
        fact_id = create_payload["item"]["id"]
        self.assertEqual(create_payload["item"]["scope_type"], "project")
        self.assertEqual(create_payload["item"]["scope_id"], "p1")
        self.assertEqual(create_payload["consistency"]["operation"], "insert")

        list_response = self.client.get(
            "/api/v1/internal/memory/facts",
            headers=headers,
            params={
                "tenant_id": "t1",
                "user_id": "u1",
                "project_id": "p1",
                "session_id": "s1",
                "request_id": "req-manual-list",
                "limit": 5,
            },
        )
        self.assertEqual(list_response.status_code, 200)
        list_payload = list_response.json()
        self.assertEqual(list_payload["count"], 1)
        self.assertEqual(list_payload["items"][0]["id"], fact_id)
        self.assertEqual(
            [(item["scope_type"], item["scope_id"]) for item in list_payload["allowed_scopes"][:3]],
            [("session", "s1"), ("user", "u1"), ("project", "p1")],
        )

        get_response = self.client.get(
            f"/api/v1/internal/memory/facts/{fact_id}",
            headers=headers,
            params={
                "tenant_id": "t1",
                "user_id": "u1",
                "project_id": "p1",
                "session_id": "s1",
                "request_id": "req-manual-read",
            },
        )
        self.assertEqual(get_response.status_code, 200)
        self.assertEqual(get_response.json()["item"]["content"], "Aurora 当前优先实现记忆系统第一特性")

        update_response = self.client.patch(
            f"/api/v1/internal/memory/facts/{fact_id}/status",
            headers=headers,
            json={
                "status": "superseded",
                "tenant_id": "t1",
                "user_id": "u1",
                "project_id": "p1",
                "session_id": "s1",
                "request_id": "req-manual-update",
            },
        )
        self.assertEqual(update_response.status_code, 200)
        self.assertEqual(update_response.json()["item"]["status"], "superseded")

        create_audit_response = self.client.get(
            "/api/v1/internal/memory/audit/request/req-manual-create",
            headers=headers,
            params={"tenant_id": "t1"},
        )
        self.assertEqual(create_audit_response.status_code, 200)
        self.assertEqual(create_audit_response.json()["items"][0]["action"], "create")

        list_audit_response = self.client.get(
            "/api/v1/internal/memory/audit/request/req-manual-list",
            headers=headers,
            params={"tenant_id": "t1"},
        )
        self.assertEqual(list_audit_response.status_code, 200)
        self.assertEqual(list_audit_response.json()["items"][0]["action"], "retrieve")

    def test_internal_memory_retrieval_preview_api_returns_bundle_and_trace(self):
        headers = {"X-Aurora-Internal-Api": "true"}
        repository = MemoryRepository(self.config)
        issue_fact = repository.create_memory_fact(
            MemoryFactCreate(
                tenant_id="t1",
                owner_user_id="u1",
                project_id="p1",
                scope_type="project",
                scope_id="p1",
                type="pending_issue",
                content="Known issue: login API returns 500 when REDIS_URL is missing.",
                source_session_id="s1",
                source_type="imported",
                source_confidence=0.92,
            )
        )
        repository.create_memory_fact(
            MemoryFactCreate(
                tenant_id="t1",
                owner_user_id="u1",
                project_id="p1",
                scope_type="user",
                scope_id="u1",
                type="preference",
                content="Prefer concise answers.",
                source_session_id="s1",
                source_type="user_confirmed",
                source_confidence=0.95,
            )
        )

        response = self.client.post(
            "/api/v1/internal/memory/retrieve",
            headers=headers,
            json={
                "scene": "troubleshooting",
                "question": "Why does the login API return 500 during startup?",
                "tenant_id": "t1",
                "user_id": "u1",
                "project_id": "p1",
                "session_id": "s1",
                "request_id": "req-preview-memory",
            },
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["bundle"]["total_selected"], 1)
        self.assertEqual(payload["bundle"]["selected_memories"][0]["memory_fact_id"], issue_fact.id)
        self.assertIn("retrieval_trace", payload["bundle"])
        self.assertEqual(payload["bundle"]["retrieval_plan"]["scene"], "troubleshooting")
        self.assertIn("max_injection_chars_per_memory", payload["bundle"]["retrieval_plan"])
        self.assertEqual(payload["bundle"]["retrieval_trace"]["retrieval_metadata"]["preview"], True)
        self.assertEqual(payload["bundle"]["memory_context"][0]["memory_id"], issue_fact.id)

    def test_internal_governance_api_lists_security_events_after_sensitive_write_block(self):
        headers = {"X-Aurora-Internal-Api": "true"}

        blocked_response = self.client.post(
            "/api/v1/internal/memory/facts",
            headers=headers,
            json={
                "content": "authorization: bearer sk-abcdefghijklmnop",
                "type": "fact",
                "scope_type": "project",
                "tenant_id": "t1",
                "user_id": "u1",
                "project_id": "p1",
                "session_id": "s1",
                "request_id": "req-sensitive-api",
            },
        )
        self.assertEqual(blocked_response.status_code, 403)

        security_response = self.client.get(
            "/api/v1/internal/memory/security-events",
            headers=headers,
            params={"tenant_id": "t1", "limit": 5},
        )
        self.assertEqual(security_response.status_code, 200)
        security_payload = security_response.json()
        self.assertEqual(security_payload["items"][0]["event_type"], "sensitive_memory_detected")

        policy_response = self.client.get(
            "/api/v1/internal/memory/policy-decisions",
            headers=headers,
            params={"request_id": "req-sensitive-api", "limit": 5},
        )
        self.assertEqual(policy_response.status_code, 200)
        self.assertEqual(policy_response.json()["items"][0]["decision"], "deny")

        summary_response = self.client.get(
            "/api/v1/internal/memory/governance/summary",
            headers=headers,
            params={"tenant_id": "t1", "limit": 5, "capture_snapshot": True},
        )
        self.assertEqual(summary_response.status_code, 200)
        self.assertIn(
            summary_response.json()["summary"]["recent_security_events"][0]["event_type"],
            {"sensitive_memory_detected", "policy_blocked_write"},
        )

    def test_internal_memory_api_exposes_consistency_result_and_history(self):
        headers = {"X-Aurora-Internal-Api": "true"}

        first_response = self.client.post(
            "/api/v1/internal/memory/facts",
            headers=headers,
            json={
                "content": "stack.framework: Flask",
                "type": "fact",
                "scope_type": "project",
                "tenant_id": "t1",
                "user_id": "u1",
                "project_id": "p1",
                "session_id": "s1",
                "request_id": "req-history-1",
                "source_type": "model_inferred",
            },
        )
        self.assertEqual(first_response.status_code, 200)
        first_payload = first_response.json()

        second_response = self.client.post(
            "/api/v1/internal/memory/facts",
            headers=headers,
            json={
                "content": "stack.framework: FastAPI",
                "type": "fact",
                "scope_type": "project",
                "tenant_id": "t1",
                "user_id": "u1",
                "project_id": "p1",
                "session_id": "s1",
                "request_id": "req-history-2",
                "source_type": "user_confirmed",
                "reviewed_by_human": True,
            },
        )
        self.assertEqual(second_response.status_code, 200)
        second_payload = second_response.json()
        self.assertEqual(second_payload["consistency"]["operation"], "update")
        self.assertEqual(second_payload["consistency"]["superseded_fact_ids"], [first_payload["item"]["id"]])

        history_response = self.client.get(
            f"/api/v1/internal/memory/facts/{second_payload['item']['id']}/history",
            headers=headers,
            params={
                "tenant_id": "t1",
                "user_id": "u1",
                "project_id": "p1",
                "session_id": "s1",
                "request_id": "req-history-list",
            },
        )
        self.assertEqual(history_response.status_code, 200)
        history_payload = history_response.json()
        self.assertEqual(history_payload["count"], 2)
        self.assertEqual(history_payload["items"][0]["id"], second_payload["item"]["id"])
        self.assertEqual(history_payload["items"][1]["id"], first_payload["item"]["id"])

    def test_internal_memory_api_keeps_global_write_guarded(self):
        denied_response = self.client.post(
            "/api/v1/internal/memory/facts",
            headers={"X-Aurora-Internal-Api": "true"},
            json={
                "content": "Global rule from manual API should stay guarded",
                "type": "fact",
                "scope_type": "global",
                "tenant_id": "t1",
                "user_id": "u1",
                "project_id": "p1",
                "session_id": "s1",
                "request_id": "req-global-denied",
                "confirmed": True,
            },
        )
        self.assertEqual(denied_response.status_code, 403)

        allowed_response = self.client.post(
            "/api/v1/internal/memory/facts",
            headers={
                "X-Aurora-Internal-Api": "true",
                "X-Aurora-Actor-Role": "admin",
                "X-Aurora-Allow-Global-Write": "true",
            },
            json={
                "content": "Sensitive content does not enter long-term memory by default",
                "type": "fact",
                "scope_type": "global",
                "tenant_id": "t1",
                "user_id": "u1",
                "project_id": "p1",
                "session_id": "s1",
                "request_id": "req-global-allowed",
                "confirmed": True,
            },
        )
        self.assertEqual(allowed_response.status_code, 200)
        self.assertEqual(allowed_response.json()["item"]["scope_type"], "global")

    @patch("app.services.capabilities.builtin.rag_query_tool.retrieve_chunks")
    def test_internal_provider_api_lists_resolves_and_runs_dry_run(self, mock_retrieve_chunks):
        mock_retrieve_chunks.return_value = (
            [
                RetrievedChunk(
                    document_id="doc-provider",
                    file_name="provider.md",
                    source_path="provider.md",
                    relative_path="provider.md",
                    text="Use `pytest -q` to run a focused test subset.",
                    score=0.86,
                )
            ],
            "pytest focused subset",
            "",
        )

        headers = {"X-Aurora-Internal-Api": "true"}

        list_response = self.client.get("/api/v1/internal/providers", headers=headers)
        self.assertEqual(list_response.status_code, 200)
        list_payload = list_response.json()
        self.assertGreaterEqual(list_payload["count"], 2)
        provider_names = {item["provider_name"] for item in list_payload["items"]}
        self.assertIn("openai", provider_names)
        self.assertIn("local_mock", provider_names)

        resolve_response = self.client.post(
            "/api/v1/internal/providers/resolve",
            headers=headers,
            json={"provider": "deepseek", "model": "deepseek-chat"},
        )
        self.assertEqual(resolve_response.status_code, 200)
        resolve_payload = resolve_response.json()
        self.assertEqual(resolve_payload["requested_provider"], "deepseek")
        self.assertEqual(resolve_payload["resolved_provider"], "local_mock")
        self.assertTrue(resolve_payload["using_fallback"])
        self.assertEqual(resolve_payload["fallback_reason"], "llm_api_not_ready")

        dry_run_response = self.client.post(
            "/api/v1/internal/providers/dry-run",
            headers=headers,
            json={
                "provider": "local_mock",
                "question": "How do we run a focused pytest subset?",
                "chat_history": [],
                "tenant_id": "t1",
                "user_id": "u1",
                "project_id": "p1",
                "session_id": "s-provider-dry-run",
                "request_id": "req-provider-dry-run",
            },
        )
        self.assertEqual(dry_run_response.status_code, 200)
        dry_run_payload = dry_run_response.json()
        self.assertEqual(dry_run_payload["provider_resolution"]["resolved_provider"], "local_mock")
        self.assertEqual(dry_run_payload["business_response"]["provider"], "local_mock")
        self.assertEqual(len(dry_run_payload["business_request"]["knowledge_context"]), 1)
        self.assertEqual(dry_run_payload["retrieval"]["retrieved_count"], 1)
        self.assertIn("pytest", dry_run_payload["business_response"]["answer"].lower())
        with connect_state_db(self.config) as connection:
            persisted_sessions = connection.execute("SELECT COUNT(*) AS count FROM chat_sessions").fetchone()["count"]
            persisted_messages = connection.execute("SELECT COUNT(*) AS count FROM chat_messages").fetchone()["count"]
        self.assertEqual(persisted_sessions, 0)
        self.assertEqual(persisted_messages, 0)

    @patch("app.services.capabilities.builtin.rag_query_tool.retrieve_chunks")
    @patch("app.api.chat.answer_with_rag")
    def test_features_one_two_three_coexist_without_cross_boundary_side_effects(
        self,
        mock_answer_with_rag,
        mock_retrieve_chunks,
    ):
        repository = MemoryRepository(self.config)
        scoped_fact = repository.create_memory_fact(
            MemoryFactCreate(
                tenant_id="t1",
                owner_user_id="u1",
                project_id="p1",
                scope_type="session",
                scope_id="s-cross-feature",
                type="fact",
                content="Current session discusses the integrated feature baseline",
                source_session_id="s-cross-feature",
            )
        )
        repository.create_memory_fact(
            MemoryFactCreate(
                tenant_id="t1",
                owner_user_id="u2",
                project_id="p1",
                scope_type="user",
                scope_id="u2",
                type="preference",
                content="This memory must stay isolated from u1",
                source_session_id="s-other",
            )
        )

        mock_answer_with_rag.return_value = ChatResult(
            answer="integrated answer",
            citations=[],
            retrieved_count=0,
            memory_count=1,
            used_memory_ids=[scoped_fact.id],
        )
        mock_retrieve_chunks.return_value = (
            [
                RetrievedChunk(
                    document_id="doc-cross",
                    file_name="cross.md",
                    source_path="cross.md",
                    relative_path="cross.md",
                    text="Focused troubleshooting should start with recent context and scoped evidence.",
                    score=0.84,
                )
            ],
            "scoped retrieval",
            "",
        )

        chat_response = self.client.post(
            "/api/v1/chat/ask",
            json={
                "question": "How does the integrated feature baseline work?",
                "chat_history": [],
                "tenant_id": "t1",
                "user_id": "u1",
                "project_id": "p1",
                "session_id": "s-cross-feature",
                "session_title": "Cross Feature Session",
                "request_id": "req-cross-chat",
            },
        )
        self.assertEqual(chat_response.status_code, 200)
        self.assertNotIn("memory_count", chat_response.json())
        self.assertNotIn("used_memory_ids", chat_response.json())

        with connect_state_db(self.config) as connection:
            persisted_sessions_after_chat = connection.execute(
                "SELECT COUNT(*) AS count FROM chat_sessions"
            ).fetchone()["count"]
            persisted_messages_after_chat = connection.execute(
                "SELECT COUNT(*) AS count FROM chat_messages"
            ).fetchone()["count"]

        self.assertEqual(persisted_sessions_after_chat, 1)
        self.assertEqual(persisted_messages_after_chat, 2)

        dry_run_response = self.client.post(
            "/api/v1/internal/providers/dry-run",
            headers={"X-Aurora-Internal-Api": "true"},
            json={
                "provider": "local_mock",
                "question": "Can we validate providers without mutating persisted chat state?",
                "chat_history": [],
                "tenant_id": "t1",
                "user_id": "u1",
                "project_id": "p1",
                "session_id": "s-cross-feature",
                "request_id": "req-cross-dry-run",
            },
        )
        self.assertEqual(dry_run_response.status_code, 200)
        dry_run_payload = dry_run_response.json()
        self.assertEqual(dry_run_payload["retrieval"]["memory_count"], 1)
        self.assertEqual(dry_run_payload["business_request"]["memory_context"][0]["memory_id"], scoped_fact.id)

        with connect_state_db(self.config) as connection:
            persisted_sessions_after_dry_run = connection.execute(
                "SELECT COUNT(*) AS count FROM chat_sessions"
            ).fetchone()["count"]
            persisted_messages_after_dry_run = connection.execute(
                "SELECT COUNT(*) AS count FROM chat_messages"
            ).fetchone()["count"]

        self.assertEqual(persisted_sessions_after_dry_run, 1)
        self.assertEqual(persisted_messages_after_dry_run, 2)

    def test_internal_provider_api_requires_admin_permission(self):
        response = self.client.get(
            "/api/v1/internal/providers",
            headers=self.auth_headers(role="member"),
        )
        self.assertEqual(response.status_code, 403)

    def test_internal_chat_api_lists_session_details_and_recovery(self):
        session_repository = SessionRepository(self.config)
        message_repository = MessageRepository(self.config)
        first_context = MemoryRequestContext(
            request_id="req-session-1",
            tenant_id="t1",
            user_id="u1",
            project_id="p1",
            session_id="s-chat-1",
        )
        second_context = MemoryRequestContext(
            request_id="req-session-2",
            tenant_id="t1",
            user_id="u1",
            project_id="p1",
            session_id="s-chat-2",
        )

        session_repository.ensure_session(first_context, "First Session")
        message_repository.create_message(
            ChatMessageCreate(
                tenant_id="t1",
                session_id="s-chat-1",
                user_id="u1",
                role="user",
                content="first question",
            )
        )
        message_repository.create_message(
            ChatMessageCreate(
                tenant_id="t1",
                session_id="s-chat-1",
                user_id="u1",
                role="assistant",
                content="first answer",
            )
        )

        session_repository.ensure_session(second_context, "Second Session")
        message_repository.create_message(
            ChatMessageCreate(
                tenant_id="t1",
                session_id="s-chat-2",
                user_id="u1",
                role="user",
                content="latest question",
            )
        )
        session_repository.update_last_active(tenant_id="t1", session_id="s-chat-2")

        headers = {"X-Aurora-Internal-Api": "true"}
        list_response = self.client.get(
            "/api/v1/internal/chat/sessions",
            headers=headers,
            params={"tenant_id": "t1", "user_id": "u1", "project_id": "p1", "limit": 10},
        )
        self.assertEqual(list_response.status_code, 200)
        list_payload = list_response.json()
        self.assertEqual(list_payload["count"], 2)
        self.assertEqual(list_payload["items"][0]["session"]["id"], "s-chat-2")
        self.assertEqual(list_payload["items"][0]["message_count"], 1)
        self.assertEqual(list_payload["items"][1]["session"]["id"], "s-chat-1")
        self.assertEqual(list_payload["items"][1]["message_count"], 2)

        detail_response = self.client.get(
            "/api/v1/internal/chat/sessions/s-chat-1",
            headers=headers,
            params={"tenant_id": "t1", "user_id": "u1"},
        )
        self.assertEqual(detail_response.status_code, 200)
        detail_payload = detail_response.json()
        self.assertEqual(detail_payload["item"]["title"], "First Session")
        self.assertEqual(detail_payload["message_count"], 2)
        self.assertEqual(detail_payload["last_message"]["role"], "assistant")
        self.assertEqual(detail_payload["last_message"]["content"], "first answer")

        recover_response = self.client.get(
            "/api/v1/internal/chat/sessions/s-chat-1/recover",
            headers=headers,
            params={"tenant_id": "t1", "request_id": "req-recover-chat", "message_limit": 2},
        )
        self.assertEqual(recover_response.status_code, 200)
        recover_payload = recover_response.json()
        self.assertTrue(recover_payload["restored_from_persistence"])
        self.assertEqual(recover_payload["message_count"], 2)
        self.assertEqual(
            [(item["role"], item["content"]) for item in recover_payload["recent_messages"]],
            [("user", "first question"), ("assistant", "first answer")],
        )
        self.assertEqual(
            recover_payload["recovered_chat_history"],
            [
                {"role": "user", "content": "first question"},
                {"role": "assistant", "content": "first answer"},
            ],
        )
        self.assertEqual(recover_payload["request_context"]["session_id"], "s-chat-1")
        self.assertEqual(recover_payload["request_context"]["user_id"], "u1")

    def test_public_chat_session_routes_list_messages_and_rename_owned_sessions(self):
        session_repository = SessionRepository(self.config)
        message_repository = MessageRepository(self.config)
        request_context = MemoryRequestContext(
            request_id="req-chat-public",
            tenant_id="t1",
            user_id="u1",
            project_id="p1",
            session_id="s-public-1",
        )
        session_repository.ensure_session(request_context, "Alpha Session")
        message_repository.create_message(
            ChatMessageCreate(
                tenant_id="t1",
                session_id="s-public-1",
                user_id="u1",
                role="user",
                content="How do I inspect the current Activity?",
            )
        )
        message_repository.create_message(
            ChatMessageCreate(
                tenant_id="t1",
                session_id="s-public-1",
                user_id="u1",
                role="assistant",
                content="Use adb shell dumpsys window windows.",
            )
        )

        list_response = self.client.get("/api/v1/chat/sessions")
        self.assertEqual(list_response.status_code, 200)
        list_payload = list_response.json()
        self.assertEqual(list_payload["count"], 1)
        self.assertEqual(list_payload["items"][0]["session"]["id"], "s-public-1")
        self.assertEqual(list_payload["items"][0]["message_count"], 2)
        self.assertEqual(list_payload["items"][0]["last_message"]["role"], "assistant")

        detail_response = self.client.get("/api/v1/chat/sessions/s-public-1")
        self.assertEqual(detail_response.status_code, 200)
        detail_payload = detail_response.json()
        self.assertEqual(detail_payload["session"]["title"], "Alpha Session")
        self.assertEqual(detail_payload["message_count"], 2)

        messages_response = self.client.get("/api/v1/chat/sessions/s-public-1/messages")
        self.assertEqual(messages_response.status_code, 200)
        messages_payload = messages_response.json()
        self.assertEqual(
            [(item["role"], item["content"]) for item in messages_payload["messages"]],
            [
                ("user", "How do I inspect the current Activity?"),
                ("assistant", "Use adb shell dumpsys window windows."),
            ],
        )

        rename_response = self.client.patch(
            "/api/v1/chat/sessions/s-public-1",
            json={"title": "Renamed Session"},
        )
        self.assertEqual(rename_response.status_code, 200)
        self.assertEqual(rename_response.json()["session"]["title"], "Renamed Session")

    @patch("app.api.routes.chat.prepare_stream_answer")
    def test_chat_sse_root_and_graph_alias_filter(self, mock_prepare_stream_answer):
        mock_prepare_stream_answer.return_value = (
            iter(["Aurora", " answer"]),
            [
                Citation(
                    knowledge_id="k1",
                    document_id="d1",
                    file_name="notes.md",
                    source_path="data/notes.md",
                    relative_path="notes.md",
                    snippet="Aurora api route acceptance content.",
                    full_text="Aurora api route acceptance content.",
                    score=0.91,
                )
            ],
            1,
            0,
            18.5,
            "rewritten",
            "adb current activity",
            0.82,
            "summary",
            "openai",
            "gpt-4.1-mini",
            ["retrieve", "answer"],
            [],
            ["k1"],
            None,
        )

        with self.client.stream(
            "POST",
            "/api/v1/chat",
            json={
                "question": "ADB 怎么查看当前前台 Activity？",
                "chat_history": [],
                "session_id": "sse-session-1",
            },
        ) as response:
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.headers["content-type"].split(";")[0], "text/event-stream")
            stream_text = "".join(response.iter_text())

        self.assertIn("event: meta", stream_text)
        self.assertIn("event: delta", stream_text)
        self.assertIn("event: done", stream_text)
        self.assertIn('"answer": "Aurora answer"', stream_text)

        graph_response = self.client.get("/api/v1/graph", params={"type": "md"})
        self.assertEqual(graph_response.status_code, 200)
        self.assertEqual(graph_response.json()["summary"]["document_count"], 1)

        empty_graph_response = self.client.get("/api/v1/graph", params={"type": "pdf"})
        self.assertEqual(empty_graph_response.status_code, 200)
        self.assertEqual(empty_graph_response.json()["summary"]["document_count"], 0)

    def test_internal_chat_api_requires_admin_permission(self):
        response = self.client.get(
            "/api/v1/internal/chat/sessions",
            headers=self.auth_headers(role="member"),
            params={"tenant_id": "t1"},
        )
        self.assertEqual(response.status_code, 403)


if __name__ == "__main__":
    unittest.main()
