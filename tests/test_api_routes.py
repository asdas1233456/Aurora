import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.api.dependencies import get_app_config, get_runtime_config
from app.config import AppConfig
from app.schemas import (
    ChatMessageCreate,
    ChatResult,
    KnowledgeBaseJob,
    MemoryFactCreate,
    MemoryRequestContext,
    RetrievedChunk,
)
from app.services.abuse_guard import AbuseGuard
from app.services.chat_memory_models import ChatMemoryCandidate
from app.services.memory_audit_service import MemoryAuditService
from app.services.memory_repository import MemoryRepository
from app.services.message_repository import MessageRepository
from app.services.session_repository import SessionRepository
from app.services.storage_service import connect_state_db
from app.server import app


def make_test_config(base_dir: Path) -> AppConfig:
    AbuseGuard.reset_all()
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
        memory_llm_review_enabled=False,
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

    @patch("app.api.routes.providers.retrieve_chunks")
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

    @patch("app.api.routes.providers.retrieve_chunks")
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

    def test_internal_provider_api_requires_internal_header(self):
        response = self.client.get("/api/v1/internal/providers")
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

    def test_internal_chat_api_requires_internal_header(self):
        response = self.client.get(
            "/api/v1/internal/chat/sessions",
            params={"tenant_id": "t1"},
        )
        self.assertEqual(response.status_code, 403)


if __name__ == "__main__":
    unittest.main()
