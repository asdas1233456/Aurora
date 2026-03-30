import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from app.llm import _build_local_answer
from app.config import AppConfig
from app.schemas import RetrievedChunk
from app.services.catalog_service import (
    list_document_catalog,
    mark_document_failed,
    mark_documents_indexed,
    sync_document_catalog,
    update_document_annotations,
)
from app.services.document_service import load_documents_from_paths, rename_document
from app.services.document_taxonomy import infer_document_category
from app.services.knowledge_base_job_service import get_job, start_rebuild_job
from app.services.knowledge_base_service import (
    add_nodes_with_embeddings,
    create_nodes_from_documents,
    get_collection_count,
)
from app.services.knowledge_graph_service import build_knowledge_graph
from app.services.log_service import filter_logs
from app.services.rag_service import answer_with_rag
from app.services.retrieval_service import rerank_chunks, retrieve_chunks, rewrite_question
from app.services.settings_service import build_config_from_settings_values, validate_app_settings


def make_config(
    base_dir: Path,
    *,
    llm_api_key: str = "sk-test",
    embedding_api_key: str = "sk-embed",
) -> AppConfig:
    return AppConfig(
        base_dir=base_dir,
        data_dir=base_dir / "data",
        db_dir=base_dir / "db",
        logs_dir=base_dir / "logs",
        llm_provider="openai",
        embedding_provider="openai",
        llm_api_key=llm_api_key,
        embedding_api_key=embedding_api_key,
        llm_model="gpt-4.1-mini",
        embedding_model="text-embedding-3-small",
        collection_name="test_collection",
    )


class DocumentServiceTests(unittest.TestCase):
    def test_rename_document_inside_data_directory(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config = make_config(Path(temp_dir))
            config.data_dir.mkdir(parents=True, exist_ok=True)
            source_path = config.data_dir / "notes.md"
            source_path.write_text("hello aurora", encoding="utf-8")

            result = rename_document(str(source_path), "renamed_notes.md", config.data_dir)

            self.assertEqual(result.new_name, "renamed_notes.md")
            self.assertFalse(source_path.exists())
            self.assertTrue((config.data_dir / "renamed_notes.md").exists())

    def test_rename_document_rejects_existing_target(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config = make_config(Path(temp_dir))
            config.data_dir.mkdir(parents=True, exist_ok=True)
            source_path = config.data_dir / "notes.md"
            target_path = config.data_dir / "taken.md"
            source_path.write_text("source", encoding="utf-8")
            target_path.write_text("target", encoding="utf-8")

            with self.assertRaises(FileExistsError):
                rename_document(str(source_path), "taken.md", config.data_dir)


class CatalogServiceTests(unittest.TestCase):
    def test_catalog_tracks_pending_indexed_changed_failed_and_annotations(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config = make_config(Path(temp_dir))
            config.data_dir.mkdir(parents=True, exist_ok=True)
            file_path = config.data_dir / "01_python_testing.md"
            file_path.write_text("python baseline", encoding="utf-8")

            documents = list_document_catalog(config)
            self.assertEqual(len(documents), 1)
            self.assertEqual(documents[0].status, "pending")

            mark_documents_indexed(
                config,
                {
                    documents[0].path: {
                        "content_hash": documents[0].content_hash,
                        "chunk_count": 3,
                    }
                },
            )

            indexed_documents = list_document_catalog(config)
            self.assertEqual(indexed_documents[0].status, "indexed")
            self.assertEqual(indexed_documents[0].chunk_count, 3)

            file_path.write_text("python updated", encoding="utf-8")
            changed_documents, _ = sync_document_catalog(config, full_scan=True)
            self.assertEqual(changed_documents[0].status, "changed")

            mark_document_failed(
                config,
                changed_documents[0].path,
                error="embedding failed",
                content_hash=changed_documents[0].content_hash,
            )
            failed_documents = list_document_catalog(config)
            self.assertEqual(failed_documents[0].status, "failed")
            self.assertIn("embedding failed", failed_documents[0].last_error)

            updated_documents = update_document_annotations(
                config,
                [failed_documents[0].path],
                theme="Regression Suite",
                tags=["python", "automation", "python"],
            )
            self.assertEqual(updated_documents[0].theme, "Regression Suite")
            self.assertEqual(updated_documents[0].tags, ["python", "automation"])


class LogServiceTests(unittest.TestCase):
    def test_filter_logs_by_level_keyword_and_time(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config = make_config(Path(temp_dir))
            config.logs_dir.mkdir(parents=True, exist_ok=True)
            config.app_log_path.write_text(
                "\n".join(
                    [
                        "2026-03-25 10:00:00 | INFO | aurora | boot",
                        "2026-03-25 10:05:00 | ERROR | aurora | rebuild failed",
                        "2026-03-25 10:10:00 | INFO | aurora | rebuild success",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )

            lines = filter_logs(
                config,
                level="ERROR",
                keyword="rebuild",
                start_time="2026-03-25 10:00",
                end_time="2026-03-25 10:06",
            )

            self.assertEqual(len(lines), 1)
            self.assertIn("rebuild failed", lines[0])


class KnowledgeGraphTests(unittest.TestCase):
    def test_build_knowledge_graph_creates_root_category_type_and_document_nodes(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config = make_config(Path(temp_dir))
            config.data_dir.mkdir(parents=True, exist_ok=True)
            (config.data_dir / "01_python_testing.md").write_text("python", encoding="utf-8")
            (config.data_dir / "02_linux_commands.txt").write_text("linux", encoding="utf-8")
            update_document_annotations(
                config,
                [str((config.data_dir / "01_python_testing.md").resolve(strict=False))],
                theme="Custom Python",
                tags=["python"],
            )

            graph = build_knowledge_graph(config)

            node_types = {node.node_type for node in graph.nodes}
            self.assertIn("root", node_types)
            self.assertIn("category", node_types)
            self.assertIn("file_type", node_types)
            self.assertIn("document", node_types)
            self.assertEqual(graph.summary["document_count"], 2)
            self.assertGreater(graph.summary["edge_count"], 0)
            self.assertIn("Custom Python", {node.label for node in graph.nodes})

    def test_infer_document_category_handles_numbered_file_names(self):
        self.assertEqual(infer_document_category("01_python_testing.md"), "Python Testing")


class RetrievalTests(unittest.TestCase):
    def test_rewrite_question_uses_previous_user_turn_for_follow_up(self):
        rewritten = rewrite_question(
            "那弱网测试怎么做？",
            [
                {"role": "user", "content": "移动端登录流程要怎么测？"},
                {"role": "assistant", "content": "可以从功能和异常场景入手。"},
            ],
        )
        self.assertIn("移动端登录流程要怎么测？", rewritten)

    def test_rerank_chunks_prefers_lexical_match(self):
        chunks = [
            RetrievedChunk(
                document_id="doc-a",
                file_name="a.md",
                source_path="a.md",
                relative_path="a.md",
                text="这里主要介绍 ADB 连接设备和前台 activity 查看方法。",
                score=0.2,
                vector_score=0.2,
            ),
            RetrievedChunk(
                document_id="doc-b",
                file_name="b.md",
                source_path="b.md",
                relative_path="b.md",
                text="这是一段和 Linux 端口占用相关的排查说明。",
                score=0.9,
                vector_score=0.9,
            ),
        ]

        reranked = rerank_chunks(
            chunks,
            question="ADB 怎么看前台 activity",
            retrieval_query="ADB 怎么看前台 activity",
            top_k=2,
        )

        self.assertEqual(reranked[0].file_name, "a.md")
        self.assertGreater(reranked[0].lexical_score, reranked[1].lexical_score)

    def test_local_retrieval_falls_back_when_embedding_is_missing(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config = make_config(Path(temp_dir), llm_api_key="", embedding_api_key="")
            config.data_dir.mkdir(parents=True, exist_ok=True)
            file_path = config.data_dir / "04_python_testing.md"
            file_path.write_text(
                "Python 单元测试要重点关注夹具、断言、边界条件和失败日志。",
                encoding="utf-8",
            )

            documents = load_documents_from_paths([file_path], config.data_dir)
            nodes = create_nodes_from_documents(config, documents)
            inserted = add_nodes_with_embeddings(config, nodes)

            self.assertGreater(inserted, 0)
            self.assertEqual(get_collection_count(config), inserted)

            chunks, retrieval_query, rewritten = retrieve_chunks(
                "Python 单元测试重点看什么？",
                config,
                top_k=2,
            )

            self.assertTrue(chunks)
            self.assertIn("python", chunks[0].file_name.lower())
            self.assertTrue(retrieval_query)
            self.assertEqual(rewritten, "")

    def test_local_retrieval_prefers_relevant_section_for_port_question(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config = make_config(Path(temp_dir), llm_api_key="", embedding_api_key="")
            config.data_dir.mkdir(parents=True, exist_ok=True)
            file_path = config.data_dir / "03_linux_commands.md"
            file_path.write_text(
                """# Linux 常用命令

## 进程与端口检查

### 查看进程

```bash
ps -ef
ps -ef | grep python
```

### 查看端口占用

```bash
netstat -ano | grep 8080
ss -lntp
```

## 文件与目录操作

### 查看当前目录

```bash
ls -la
pwd
```
""",
                encoding="utf-8",
            )

            documents = load_documents_from_paths([file_path], config.data_dir)
            nodes = create_nodes_from_documents(config, documents)
            add_nodes_with_embeddings(config, nodes)

            chunks, _, _ = retrieve_chunks(
                "Linux 中如何快速定位端口占用问题？",
                config,
                top_k=2,
            )

            self.assertTrue(chunks)
            self.assertIn("查看端口占用", chunks[0].text)
            self.assertTrue("netstat" in chunks[0].text or "ss -lntp" in chunks[0].text)
            self.assertNotIn("查看当前目录", chunks[0].text)


class KnowledgeBaseJobTests(unittest.TestCase):
    @patch("app.services.knowledge_base_job_service.get_collection_count", return_value=2)
    @patch("app.services.knowledge_base_job_service.add_nodes_with_embeddings", return_value=2)
    @patch("app.services.knowledge_base_job_service.create_nodes_from_documents")
    @patch("app.services.knowledge_base_job_service.load_documents_from_paths")
    @patch("app.services.knowledge_base_job_service.delete_document_chunks")
    def test_start_rebuild_job_updates_catalog_status(
        self,
        mock_delete_document_chunks,
        mock_load_documents_from_paths,
        mock_create_nodes_from_documents,
        mock_add_nodes_with_embeddings,
        mock_get_collection_count,
    ):
        with tempfile.TemporaryDirectory() as temp_dir:
            config = make_config(Path(temp_dir))
            config.data_dir.mkdir(parents=True, exist_ok=True)
            (config.data_dir / "01_python_testing.md").write_text("python", encoding="utf-8")

            mock_load_documents_from_paths.return_value = [SimpleNamespace()]
            mock_create_nodes_from_documents.return_value = [SimpleNamespace(), SimpleNamespace()]

            job = start_rebuild_job(config)

            for _ in range(100):
                latest_job = get_job(config, job.job_id)
                if latest_job and latest_job.status in {"completed", "completed_with_errors", "failed", "cancelled"}:
                    break
                time.sleep(0.05)
            else:
                self.fail("Knowledge base job did not finish in time.")

            self.assertIsNotNone(latest_job)
            self.assertEqual(latest_job.status, "completed")
            documents = list_document_catalog(config)
            self.assertEqual(documents[0].status, "indexed")
            self.assertEqual(documents[0].chunk_count, 2)
            self.assertTrue(mock_add_nodes_with_embeddings.called)
            self.assertTrue((config.db_dir / "knowledge_base_jobs.json").exists())

    @patch("app.services.knowledge_base_job_service.get_collection_count", return_value=0)
    @patch("app.services.knowledge_base_job_service.add_nodes_with_embeddings", return_value=1)
    @patch("app.services.knowledge_base_job_service.create_nodes_from_documents")
    @patch("app.services.knowledge_base_job_service.load_documents_from_paths")
    def test_scan_mode_discovers_external_files_but_sync_mode_does_not(
        self,
        mock_load_documents_from_paths,
        mock_create_nodes_from_documents,
        mock_add_nodes_with_embeddings,
        mock_get_collection_count,
    ):
        with tempfile.TemporaryDirectory() as temp_dir:
            config = make_config(Path(temp_dir))
            config.data_dir.mkdir(parents=True, exist_ok=True)
            first_path = config.data_dir / "01_python_testing.md"
            second_path = config.data_dir / "02_linux_commands.md"
            first_path.write_text("python", encoding="utf-8")

            initial_documents = list_document_catalog(config)
            mark_documents_indexed(
                config,
                {
                    initial_documents[0].path: {
                        "content_hash": initial_documents[0].content_hash,
                        "chunk_count": 1,
                    }
                },
            )
            second_path.write_text("linux", encoding="utf-8")

            mock_load_documents_from_paths.return_value = [SimpleNamespace()]
            mock_create_nodes_from_documents.return_value = [SimpleNamespace()]

            sync_job = start_rebuild_job(config, mode="sync")
            for _ in range(100):
                latest_sync_job = get_job(config, sync_job.job_id)
                if latest_sync_job and latest_sync_job.status in {"completed", "completed_with_errors", "failed", "cancelled"}:
                    break
                time.sleep(0.05)
            else:
                self.fail("Sync knowledge base job did not finish in time.")

            self.assertIsNotNone(latest_sync_job)
            self.assertEqual(latest_sync_job.mode, "sync")
            self.assertEqual(len(list_document_catalog(config)), 1)
            self.assertFalse(mock_add_nodes_with_embeddings.called)

            scan_job = start_rebuild_job(config, mode="scan")
            for _ in range(100):
                latest_scan_job = get_job(config, scan_job.job_id)
                if latest_scan_job and latest_scan_job.status in {"completed", "completed_with_errors", "failed", "cancelled"}:
                    break
                time.sleep(0.05)
            else:
                self.fail("Scan knowledge base job did not finish in time.")

            self.assertIsNotNone(latest_scan_job)
            self.assertEqual(latest_scan_job.mode, "scan")
            self.assertEqual(len(list_document_catalog(config)), 2)
            self.assertTrue(mock_add_nodes_with_embeddings.called)


class OfflineAnswerTests(unittest.TestCase):
    def test_answer_with_rag_falls_back_to_local_extractive_mode(self):
        config = make_config(Path(tempfile.mkdtemp()), llm_api_key="", embedding_api_key="")
        try:
            with patch(
                "app.services.rag_service.retrieve_chunks",
                return_value=(
                    [
                        RetrievedChunk(
                            document_id="doc-linux",
                            file_name="linux.md",
                            source_path="linux.md",
                            relative_path="linux.md",
                            text="Linux 下可以通过 lsof -i 或 ss -lntp 查看端口占用情况。",
                            score=0.82,
                            vector_score=0.82,
                        )
                    ],
                    "Linux 端口占用怎么查",
                    "",
                ),
            ):
                result = answer_with_rag("Linux 端口占用怎么查？", [], config)
        finally:
            pass

        self.assertIn("本地演示模式", result.answer)
        self.assertEqual(result.retrieved_count, 1)
        self.assertEqual(len(result.citations), 1)
        self.assertTrue("lsof -i" in result.answer or "ss -lntp" in result.answer)

    def test_local_answer_extracts_section_title_and_commands(self):
        answer = _build_local_answer(
            "Linux 中如何快速定位端口占用问题？",
            [
                RetrievedChunk(
                    document_id="doc-linux",
                    file_name="linux.md",
                    source_path="linux.md",
                    relative_path="linux.md",
                    text="""### 查看端口占用
所属章节：Linux 常用命令 / 进程与端口检查

```bash
netstat -ano | grep 8080
ss -lntp
```

- 可以先确认目标端口是否已经被监听。
""",
                    score=0.91,
                    vector_score=0.91,
                )
            ],
        )

        self.assertIn("本地演示模式", answer)
        self.assertIn("查看端口占用", answer)
        self.assertTrue("netstat -ano | grep 8080" in answer or "ss -lntp" in answer)


class SettingsValidationTests(unittest.TestCase):
    def test_validate_app_settings_reports_invalid_fields(self):
        errors = validate_app_settings(
            {
                "LLM_PROVIDER": "openai",
                "EMBEDDING_PROVIDER": "openai",
                "LLM_API_KEY": "",
                "EMBEDDING_API_KEY": "",
                "LLM_API_BASE": "",
                "EMBEDDING_API_BASE": "",
                "LLM_MODEL": "",
                "EMBEDDING_MODEL": "",
                "LLM_TEMPERATURE": "3",
                "LLM_TIMEOUT": "0",
                "LLM_MAX_TOKENS": "20",
                "CHUNK_SIZE": "200",
                "CHUNK_OVERLAP": "300",
                "TOP_K": "30",
                "MAX_HISTORY_TURNS": "30",
                "NO_ANSWER_MIN_SCORE": "2",
                "CHROMA_COLLECTION_NAME": "",
                "LOG_LEVEL": "TRACE",
                "API_PORT": "70000",
            }
        )

        self.assertIn("LLM_API_KEY", errors)
        self.assertIn("EMBEDDING_API_KEY", errors)
        self.assertIn("LLM_MODEL", errors)
        self.assertIn("CHUNK_OVERLAP", errors)
        self.assertIn("NO_ANSWER_MIN_SCORE", errors)
        self.assertIn("LOG_LEVEL", errors)
        self.assertIn("API_PORT", errors)

    def test_build_config_from_settings_values_merges_new_fields(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config = make_config(Path(temp_dir))
            next_config = build_config_from_settings_values(
                config,
                {
                    "TOP_K": "8",
                    "NO_ANSWER_MIN_SCORE": "0.35",
                    "CHROMA_COLLECTION_NAME": "qa_docs",
                },
            )

            self.assertEqual(next_config.default_top_k, 8)
            self.assertEqual(next_config.no_answer_min_score, 0.35)
            self.assertEqual(next_config.collection_name, "qa_docs")


if __name__ == "__main__":
    unittest.main()
