import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import sqlite3
import zipfile

try:
    import fitz
except ImportError:  # pragma: no cover - exercised when PyMuPDF is not installed.
    fitz = None

from app.llm import _build_local_answer
from app.config import AppConfig
from app.modules.system.request_concurrency import RequestConcurrencyGuard
from app.schemas import (
    ChatMessageCreate,
    ChatResult,
    KnowledgeBaseJob,
    MemoryFact,
    MemoryFactCreate,
    MemoryRequestContext,
    RetrievedChunk,
)
from app.services.abuse_guard import AbuseGuard
from app.services.audit_service import AuditService
from app.services.capabilities import (
    CapabilityAccessError,
    CapabilityAssembler,
    CapabilityContext,
    CapabilityDescriptor,
    CapabilityRegistry,
)
from app.services.capabilities.base import BaseTool
from app.services.chat_memory_llm_review_service import ChatMemoryLLMReviewService
from app.services.chat_memory_models import ChatMemoryCandidate
from app.services.chat_memory_service import ChatMemoryService
from app.services.governance_inspector import GovernanceInspector
from app.services.memory_access_policy import MemoryAccessPolicy
from app.services.memory_audit_service import MemoryAuditService
from app.services.memory_relevance_scorer import MemoryRelevanceScorer
from app.services.memory_repository import MemoryRepository
from app.services.memory_retrieval_models import MemoryCandidate, MemoryQuery
from app.services.memory_retrieval_planner import RetrievalPlanner
from app.services.memory_retriever import MemoryRetriever
from app.services.memory_scope import ScopeResolver
from app.services.memory_write_service import MemoryWriteService
from app.services.message_repository import MessageRepository
from app.services.persistence_health_service import PersistenceHealthService
from app.services.session_recovery_service import SessionRecoveryService
from app.services.session_repository import SessionRepository
from app.services.catalog_service import (
    list_document_catalog,
    mark_document_failed,
    mark_documents_indexed,
    sync_document_catalog,
    update_document_annotations,
)
from app.services.document_materialization_service import (
    load_materialized_document_preview,
    persist_materialized_document,
)
from app.services.document_service import (
    build_llama_documents_from_parsed_documents,
    build_document_preview_metadata,
    load_parsed_documents_from_paths,
    load_documents_from_paths,
    read_document_preview,
    read_document_preview_payload,
    rename_document,
)
from app.services.document_taxonomy import infer_document_category
from app.services.etl.models import ExtractedSegment, ParsedDocument
from app.services.knowledge_base_job_service import get_job, start_rebuild_job
from app.services.knowledge_base_service import (
    add_nodes_with_embeddings,
    create_nodes_from_documents,
    get_collection_count,
)
from app.services.knowledge_access_policy import KnowledgeAccessFilter
from app.services.knowledge_graph_service import (
    build_knowledge_graph,
    build_knowledge_graph_from_documents,
)
from app.services.log_service import filter_logs
from app.services.local_index_service import search_local_index_chunks
from app.services.rag_service import answer_with_rag, build_citations
from app.services.retrieval_service import rerank_chunks, retrieve_chunks, rewrite_question
from app.services.settings_service import build_config_from_settings_values, validate_app_settings
from app.services.storage_service import connect_state_db, get_state_db_path


def make_config(
    base_dir: Path,
    *,
    llm_api_key: str = "sk-test",
    embedding_api_key: str = "sk-embed",
) -> AppConfig:
    AbuseGuard.reset_all()
    RequestConcurrencyGuard.reset_all()
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
        memory_llm_review_enabled=False,
    )


def create_minimal_docx(file_path: Path) -> None:
    with zipfile.ZipFile(file_path, "w") as archive:
        archive.writestr(
            "[Content_Types].xml",
            """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
</Types>""",
        )
        archive.writestr(
            "_rels/.rels",
            """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>
</Relationships>""",
        )
        archive.writestr(
            "word/document.xml",
            """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
  <w:body>
    <w:p><w:r><w:t>Aurora Word parser heading</w:t></w:r></w:p>
    <w:p><w:r><w:t>Word paragraph for ETL verification.</w:t></w:r></w:p>
    <w:tbl>
      <w:tr>
        <w:tc><w:p><w:r><w:t>Name</w:t></w:r></w:p></w:tc>
        <w:tc><w:p><w:r><w:t>Owner</w:t></w:r></w:p></w:tc>
      </w:tr>
      <w:tr>
        <w:tc><w:p><w:r><w:t>Aurora</w:t></w:r></w:p></w:tc>
        <w:tc><w:p><w:r><w:t>QA Team</w:t></w:r></w:p></w:tc>
      </w:tr>
    </w:tbl>
  </w:body>
</w:document>""",
        )


def create_minimal_xlsx(file_path: Path) -> None:
    with zipfile.ZipFile(file_path, "w") as archive:
        archive.writestr(
            "[Content_Types].xml",
            """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>
  <Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>
</Types>""",
        )
        archive.writestr(
            "_rels/.rels",
            """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>
</Relationships>""",
        )
        archive.writestr(
            "xl/workbook.xml",
            """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"
          xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
  <sheets>
    <sheet name="Cases" sheetId="1" r:id="rId1"/>
  </sheets>
</workbook>""",
        )
        archive.writestr(
            "xl/_rels/workbook.xml.rels",
            """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>
</Relationships>""",
        )
        archive.writestr(
            "xl/worksheets/sheet1.xml",
            """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
  <sheetData>
    <row r="1">
      <c r="A1" t="inlineStr"><is><t>Case ID</t></is></c>
      <c r="B1" t="inlineStr"><is><t>Priority</t></is></c>
    </row>
    <row r="2">
      <c r="A2" t="inlineStr"><is><t>API-001</t></is></c>
      <c r="B2" t="inlineStr"><is><t>P0</t></is></c>
    </row>
  </sheetData>
</worksheet>""",
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

    def test_load_documents_from_paths_supports_structured_text_templates(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config = make_config(Path(temp_dir))
            config.data_dir.mkdir(parents=True, exist_ok=True)
            csv_path = config.data_dir / "api_cases.csv"
            json_path = config.data_dir / "bug_report.json"
            yaml_path = config.data_dir / "quality_gate.yaml"
            sql_path = config.data_dir / "checks.sql"

            csv_path.write_text("case_id,module,priority\nAPI-001,Login,P0\n", encoding="utf-8")
            json_path.write_text('{"title":"登录失败","severity":"high"}\n', encoding="utf-8")
            yaml_path.write_text("quality_gate:\n  coverage: 80\n", encoding="utf-8")
            sql_path.write_text("SELECT COUNT(*) AS total_users FROM users;\n", encoding="utf-8")

            documents = load_documents_from_paths(
                [csv_path, json_path, yaml_path, sql_path],
                config.data_dir,
            )

            self.assertEqual(len(documents), 4)
            self.assertEqual(documents[0].metadata["relative_path"], "api_cases.csv")
            self.assertIn("case_id,module,priority", documents[0].get_content())
            self.assertIn('"severity":"high"', documents[1].get_content())
            self.assertIn("quality_gate:", documents[2].get_content())
            self.assertIn("COUNT(*)", documents[3].get_content())

    def test_read_document_preview_supports_structured_text_templates(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config = make_config(Path(temp_dir))
            config.data_dir.mkdir(parents=True, exist_ok=True)
            preview_path = config.data_dir / "release_gate.yaml"
            preview_path.write_text(
                "release_gate:\n  smoke: required\n  rollback: ready\n",
                encoding="utf-8",
            )

            preview = read_document_preview(preview_path, max_chars=200)

            self.assertIn("release_gate:", preview)
            self.assertIn("rollback: ready", preview)

    @unittest.skipIf(fitz is None, "PyMuPDF is not installed")
    def test_load_documents_from_paths_splits_pdf_into_page_level_documents(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config = make_config(Path(temp_dir))
            config.data_dir.mkdir(parents=True, exist_ok=True)
            pdf_path = config.data_dir / "guide.pdf"

            pdf = fitz.open()
            first_page = pdf.new_page()
            first_page.insert_text((72, 72), "Aurora PDF page one\nsetup instructions")
            second_page = pdf.new_page()
            second_page.insert_text((72, 72), "Aurora PDF page two\nruntime checklist")
            pdf.save(pdf_path)
            pdf.close()

            documents = load_documents_from_paths([pdf_path], config.data_dir)

            self.assertEqual(len(documents), 2)
            self.assertEqual(documents[0].metadata["page_number"], 1)
            self.assertEqual(documents[1].metadata["page_number"], 2)
            self.assertEqual(documents[0].metadata["source_type"], "pdf")
            self.assertIn("Page 1", documents[0].get_content())
            self.assertIn("setup instructions", documents[0].get_content())
            self.assertIn("runtime checklist", documents[1].get_content())

    def test_load_documents_from_paths_supports_docx_and_xlsx(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config = make_config(Path(temp_dir))
            config.data_dir.mkdir(parents=True, exist_ok=True)
            docx_path = config.data_dir / "guide.docx"
            xlsx_path = config.data_dir / "cases.xlsx"
            create_minimal_docx(docx_path)
            create_minimal_xlsx(xlsx_path)

            documents = load_documents_from_paths([docx_path, xlsx_path], config.data_dir)

            self.assertEqual(len(documents), 2)
            self.assertIn("Word parser heading", documents[0].get_content())
            self.assertIn("Table 1", documents[0].get_content())
            self.assertIn("Sheet: Cases", documents[1].get_content())
            self.assertIn("API-001", documents[1].get_content())

    def test_read_document_preview_payload_exposes_xlsx_sheet_metadata(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config = make_config(Path(temp_dir))
            config.data_dir.mkdir(parents=True, exist_ok=True)
            xlsx_path = config.data_dir / "cases.xlsx"
            create_minimal_xlsx(xlsx_path)

            preview_payload = read_document_preview_payload(
                xlsx_path,
                max_chars=500,
                document_id="doc-xlsx",
            )

            self.assertEqual(preview_payload.document_id, "doc-xlsx")
            self.assertEqual(preview_payload.metadata.file_type, "xlsx")
            self.assertEqual(preview_payload.metadata.sheet_count, 1)
            self.assertEqual(preview_payload.metadata.sheet_names, ["Cases"])
            self.assertEqual(preview_payload.metadata.segment_count, 1)
            self.assertIn("API-001", preview_payload.preview)

    def test_build_document_preview_metadata_collects_pdf_page_numbers(self):
        parsed_document = ParsedDocument(
            source_id="pdf-source-1",
            source_path="C:/docs/guide.pdf",
            relative_path="guide.pdf",
            file_name="guide.pdf",
            file_type="pdf",
            parser_name="pypdf_pdf_parser",
            content_markdown="# guide.pdf",
            content_json={
                "file_type": "pdf",
                "parser_name": "pypdf_pdf_parser",
                "page_count": 2,
            },
            segments=[
                ExtractedSegment(
                    segment_id="seg-1",
                    sequence=1,
                    content_text="Page one content",
                    content_markdown="## Page 1\n\nPage one content",
                    page_number=1,
                    metadata={"segment_kind": "page", "source_type": "pdf"},
                ),
                ExtractedSegment(
                    segment_id="seg-2",
                    sequence=2,
                    content_text="Page two content",
                    content_markdown="## Page 2\n\nPage two content",
                    page_number=2,
                    metadata={"segment_kind": "page", "source_type": "pdf"},
                ),
            ],
        )

        metadata = build_document_preview_metadata(parsed_document)

        self.assertEqual(metadata.file_type, "pdf")
        self.assertEqual(metadata.parser_name, "pypdf_pdf_parser")
        self.assertEqual(metadata.page_count, 2)
        self.assertEqual(metadata.page_numbers, [1, 2])
        self.assertEqual(metadata.segment_count, 2)

    def test_materialized_document_preview_reads_from_structured_storage(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config = make_config(Path(temp_dir), llm_api_key="", embedding_api_key="")
            config.data_dir.mkdir(parents=True, exist_ok=True)
            file_path = config.data_dir / "guide.md"
            file_path.write_text(
                "# Aurora Guide\n\nStructured preview text for the materialized storage test.\n",
                encoding="utf-8",
            )

            document = list_document_catalog(config)[0]
            parsed_documents = load_parsed_documents_from_paths(
                [file_path],
                config.data_dir,
                metadata_by_path={
                    document.path: {
                        "document_id": document.document_id,
                        "theme": document.theme,
                        "tags": document.tags,
                    }
                },
            )
            parsed_document = parsed_documents[0]
            llama_documents = build_llama_documents_from_parsed_documents(parsed_documents)
            nodes = create_nodes_from_documents(config, llama_documents)

            materialized_payload = persist_materialized_document(
                config,
                document=document,
                parsed_document=parsed_document,
                nodes=nodes,
                content_hash=document.content_hash,
            )
            mark_documents_indexed(
                config,
                {
                    document.path: {
                        "content_hash": document.content_hash,
                        "chunk_count": len(nodes),
                        **materialized_payload,
                    }
                },
            )

            stored_document = list_document_catalog(config)[0]
            preview_payload = load_materialized_document_preview(
                config,
                document=stored_document,
                max_chars=500,
            )

            self.assertIsNotNone(preview_payload)
            assert preview_payload is not None
            self.assertEqual(stored_document.active_version_id, materialized_payload["version_id"])
            self.assertEqual(preview_payload.metadata.file_type, "md")
            self.assertEqual(preview_payload.metadata.segment_count, 1)
            self.assertIn("Structured preview text", preview_payload.preview)

            with connect_state_db(config) as connection:
                version_count = connection.execute(
                    "SELECT COUNT(*) AS count FROM document_versions"
                ).fetchone()
                segment_count = connection.execute(
                    "SELECT COUNT(*) AS count FROM document_segments"
                ).fetchone()
                chunk_count = connection.execute(
                    "SELECT COUNT(*) AS count FROM document_chunks"
                ).fetchone()

            self.assertEqual(int(version_count["count"]), 1)
            self.assertEqual(int(segment_count["count"]), 1)
            self.assertGreaterEqual(int(chunk_count["count"]), 1)

    @patch("app.services.etl.parsers.url_parser.requests.get")
    def test_load_documents_from_paths_supports_url_shortcuts(self, mock_get):
        with tempfile.TemporaryDirectory() as temp_dir:
            config = make_config(Path(temp_dir))
            config.data_dir.mkdir(parents=True, exist_ok=True)
            url_path = config.data_dir / "aurora.url"
            url_path.write_text("[InternetShortcut]\nURL=https://example.test/aurora\n", encoding="utf-8")
            mock_get.return_value = FakeHttpResponse(
                text="""
                <html>
                  <head><title>Aurora Docs</title></head>
                  <body>
                    <main>
                      <h1>Knowledge Base</h1>
                      <p>URL parser verification content.</p>
                    </main>
                  </body>
                </html>
                """,
            )

            documents = load_documents_from_paths([url_path], config.data_dir)
            preview = read_document_preview(url_path, max_chars=500)

            self.assertEqual(len(documents), 1)
            self.assertIn("Knowledge Base", documents[0].get_content())
            self.assertIn("URL parser verification content.", preview)

            preview_payload = read_document_preview_payload(
                url_path,
                max_chars=500,
                document_id="doc-url",
            )
            self.assertEqual(preview_payload.metadata.file_type, "url")
            self.assertEqual(preview_payload.metadata.source_url, "https://example.test/aurora")
            self.assertEqual(preview_payload.metadata.resolved_url, "https://example.test/aurora")
            self.assertEqual(preview_payload.metadata.title, "Aurora Docs")

    @patch("app.services.etl.parsers.url_parser.requests.get")
    def test_url_shortcut_parser_falls_back_to_title_and_meta_description(self, mock_get):
        with tempfile.TemporaryDirectory() as temp_dir:
            config = make_config(Path(temp_dir))
            config.data_dir.mkdir(parents=True, exist_ok=True)
            url_path = config.data_dir / "spa-shell.url"
            url_path.write_text("[InternetShortcut]\nURL=https://example.test/spa\n", encoding="utf-8")
            mock_get.return_value = FakeHttpResponse(
                text="""
                <html>
                  <head>
                    <title>Aurora SPA Shell</title>
                    <meta name="description" content="Single-page application landing shell." />
                  </head>
                  <body>
                    <div id="root"></div>
                  </body>
                </html>
                """,
                url="https://example.test/spa",
            )

            documents = load_documents_from_paths([url_path], config.data_dir)
            preview = read_document_preview(url_path, max_chars=500)

            self.assertEqual(len(documents), 1)
            self.assertIn("Aurora SPA Shell", documents[0].get_content())
            self.assertIn("Single-page application landing shell.", preview)

class StorageServiceTests(unittest.TestCase):
    def test_connect_state_db_upgrades_legacy_document_access_schema(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config = make_config(Path(temp_dir))
            db_path = get_state_db_path(config)

            legacy_connection = sqlite3.connect(db_path)
            legacy_connection.executescript(
                """
                CREATE TABLE documents (
                    document_id TEXT PRIMARY KEY,
                    path TEXT NOT NULL UNIQUE,
                    relative_path TEXT NOT NULL,
                    name TEXT NOT NULL,
                    extension TEXT NOT NULL,
                    size_bytes INTEGER NOT NULL DEFAULT 0,
                    updated_at TEXT NOT NULL DEFAULT '',
                    stat_size_bytes INTEGER NOT NULL DEFAULT 0,
                    stat_updated_at TEXT NOT NULL DEFAULT '',
                    content_hash TEXT NOT NULL DEFAULT '',
                    indexed_hash TEXT NOT NULL DEFAULT '',
                    last_processed_hash TEXT NOT NULL DEFAULT '',
                    theme TEXT NOT NULL DEFAULT '',
                    tags_json TEXT NOT NULL DEFAULT '[]',
                    citation_count INTEGER NOT NULL DEFAULT 0,
                    chunk_count INTEGER NOT NULL DEFAULT 0,
                    last_indexed_at TEXT NOT NULL DEFAULT '',
                    last_error TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL DEFAULT 'pending',
                    created_at TEXT NOT NULL DEFAULT '',
                    updated_row_at TEXT NOT NULL DEFAULT '',
                    active_version_id TEXT NOT NULL DEFAULT '',
                    file_type TEXT NOT NULL DEFAULT '',
                    parser_name TEXT NOT NULL DEFAULT '',
                    segment_count INTEGER NOT NULL DEFAULT 0,
                    page_count INTEGER NOT NULL DEFAULT 0,
                    sheet_count INTEGER NOT NULL DEFAULT 0,
                    title TEXT NOT NULL DEFAULT '',
                    source_url TEXT NOT NULL DEFAULT '',
                    resolved_url TEXT NOT NULL DEFAULT ''
                );

                CREATE TABLE document_versions (
                    version_id TEXT PRIMARY KEY,
                    document_id TEXT NOT NULL,
                    source_document_id TEXT NOT NULL DEFAULT '',
                    source_path TEXT NOT NULL DEFAULT '',
                    relative_path TEXT NOT NULL DEFAULT '',
                    file_name TEXT NOT NULL DEFAULT '',
                    content_hash TEXT NOT NULL DEFAULT '',
                    file_type TEXT NOT NULL DEFAULT '',
                    parser_name TEXT NOT NULL DEFAULT '',
                    segment_count INTEGER NOT NULL DEFAULT 0,
                    page_count INTEGER NOT NULL DEFAULT 0,
                    sheet_count INTEGER NOT NULL DEFAULT 0,
                    title TEXT NOT NULL DEFAULT '',
                    source_url TEXT NOT NULL DEFAULT '',
                    resolved_url TEXT NOT NULL DEFAULT '',
                    manifest_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL DEFAULT ''
                );

                CREATE TABLE document_chunks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    chunk_id TEXT NOT NULL DEFAULT '',
                    version_id TEXT NOT NULL,
                    document_id TEXT NOT NULL,
                    segment_id TEXT DEFAULT NULL,
                    source_path TEXT NOT NULL DEFAULT '',
                    file_name TEXT NOT NULL DEFAULT '',
                    relative_path TEXT NOT NULL DEFAULT '',
                    text TEXT NOT NULL DEFAULT '',
                    theme TEXT NOT NULL DEFAULT '',
                    tags_json TEXT NOT NULL DEFAULT '[]',
                    tags_text TEXT NOT NULL DEFAULT '',
                    page_number INTEGER DEFAULT NULL,
                    sheet_name TEXT NOT NULL DEFAULT '',
                    parser_name TEXT NOT NULL DEFAULT '',
                    source_type TEXT NOT NULL DEFAULT '',
                    position INTEGER NOT NULL DEFAULT 0,
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL DEFAULT ''
                );

                CREATE TABLE local_chunks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    external_chunk_id TEXT NOT NULL DEFAULT '',
                    document_id TEXT NOT NULL DEFAULT '',
                    source_path TEXT NOT NULL,
                    file_name TEXT NOT NULL,
                    relative_path TEXT NOT NULL,
                    text TEXT NOT NULL,
                    theme TEXT NOT NULL DEFAULT '',
                    tags_json TEXT NOT NULL DEFAULT '[]',
                    tags_text TEXT NOT NULL DEFAULT '',
                    page_number INTEGER DEFAULT NULL,
                    parser_name TEXT NOT NULL DEFAULT '',
                    source_type TEXT NOT NULL DEFAULT '',
                    position INTEGER NOT NULL DEFAULT 0
                );

                INSERT INTO documents (
                    document_id,
                    path,
                    relative_path,
                    name,
                    extension,
                    status
                ) VALUES (
                    'doc-legacy',
                    'C:/legacy/guide.md',
                    'guide.md',
                    'guide.md',
                    '.md',
                    'indexed'
                );

                INSERT INTO document_versions (
                    version_id,
                    document_id,
                    source_path,
                    relative_path,
                    file_name
                ) VALUES (
                    'ver-legacy',
                    'doc-legacy',
                    'C:/legacy/guide.md',
                    'guide.md',
                    'guide.md'
                );

                INSERT INTO document_chunks (
                    chunk_id,
                    version_id,
                    document_id,
                    source_path,
                    file_name,
                    relative_path,
                    text,
                    position
                ) VALUES (
                    'chunk-legacy',
                    'ver-legacy',
                    'doc-legacy',
                    'C:/legacy/guide.md',
                    'guide.md',
                    'guide.md',
                    'legacy chunk',
                    0
                );

                INSERT INTO local_chunks (
                    external_chunk_id,
                    document_id,
                    source_path,
                    file_name,
                    relative_path,
                    text,
                    position
                ) VALUES (
                    'local-legacy',
                    'doc-legacy',
                    'C:/legacy/guide.md',
                    'guide.md',
                    'guide.md',
                    'legacy local chunk',
                    0
                );
                """
            )
            legacy_connection.commit()
            legacy_connection.close()

            with connect_state_db(config) as connection:
                document_columns = {
                    str(row["name"]) for row in connection.execute("PRAGMA table_info(documents)")
                }
                document_version_columns = {
                    str(row["name"]) for row in connection.execute("PRAGMA table_info(document_versions)")
                }
                document_chunk_columns = {
                    str(row["name"]) for row in connection.execute("PRAGMA table_info(document_chunks)")
                }
                local_chunk_columns = {
                    str(row["name"]) for row in connection.execute("PRAGMA table_info(local_chunks)")
                }
                index_names = {
                    str(row["name"])
                    for row in connection.execute(
                        "SELECT name FROM sqlite_master WHERE type = 'index' AND name LIKE 'idx_%_access'"
                    )
                }
                document_access_row = connection.execute(
                    """
                    SELECT tenant_id, owner_user_id, department_id, is_public
                    FROM documents
                    WHERE document_id = 'doc-legacy'
                    """
                ).fetchone()
                local_chunk_access_row = connection.execute(
                    """
                    SELECT tenant_id, owner_user_id, department_id, is_public
                    FROM local_chunks
                    WHERE external_chunk_id = 'local-legacy'
                    """
                ).fetchone()

            self.assertTrue(
                {"tenant_id", "owner_user_id", "department_id", "is_public"}.issubset(document_columns)
            )
            self.assertTrue(
                {"tenant_id", "owner_user_id", "department_id", "is_public"}.issubset(
                    document_version_columns
                )
            )
            self.assertTrue(
                {"tenant_id", "owner_user_id", "department_id", "is_public"}.issubset(
                    document_chunk_columns
                )
            )
            self.assertTrue(
                {"tenant_id", "owner_user_id", "department_id", "is_public"}.issubset(local_chunk_columns)
            )
            self.assertEqual(
                index_names,
                {
                    "idx_documents_access",
                    "idx_document_versions_access",
                    "idx_document_chunks_access",
                    "idx_local_chunks_access",
                },
            )
            self.assertEqual(dict(document_access_row), {
                "tenant_id": "",
                "owner_user_id": "",
                "department_id": "",
                "is_public": 1,
            })
            self.assertEqual(dict(local_chunk_access_row), {
                "tenant_id": "",
                "owner_user_id": "",
                "department_id": "",
                "is_public": 1,
            })


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

    def test_build_knowledge_graph_includes_governance_summary_and_document_meta(self):
        config = make_config(Path(tempfile.mkdtemp()))
        documents = [
            SimpleNamespace(
                document_id="doc-indexed",
                name="release-notes.md",
                relative_path="release-notes.md",
                updated_at="2026-04-03T10:00:00",
                extension="md",
                size_bytes=4096,
                theme="Release",
                tags=["release", "notes"],
                status="indexed",
                chunk_count=12,
                citation_count=4,
                last_indexed_at="2026-04-03T10:10:00",
                last_error="",
                title="Release Notes",
                source_url="",
                resolved_url="",
                path="release-notes.md",
            ),
            SimpleNamespace(
                document_id="doc-failed",
                name="incident.csv",
                relative_path="incident.csv",
                updated_at="2026-04-03T09:00:00",
                extension="csv",
                size_bytes=2048,
                theme="Operations",
                tags=[],
                status="failed",
                chunk_count=3,
                citation_count=0,
                last_indexed_at="",
                last_error="parse failed",
                title="Incident Report",
                source_url="https://example.test/report",
                resolved_url="https://example.test/report",
                path="incident.csv",
            ),
        ]

        graph = build_knowledge_graph_from_documents(config, documents)

        self.assertEqual(graph.summary["indexed_document_count"], 1)
        self.assertEqual(graph.summary["attention_document_count"], 1)
        self.assertEqual(graph.summary["tagged_document_count"], 1)
        self.assertEqual(graph.summary["untagged_document_count"], 1)
        self.assertEqual(graph.summary["citation_covered_document_count"], 1)
        self.assertIn("Release", {item["label"] for item in graph.summary["top_categories"]})
        self.assertIn("MD", {item["label"] for item in graph.summary["top_file_types"]})

        failed_document_node = next(
            node for node in graph.nodes if node.node_type == "document" and node.meta["document_id"] == "doc-failed"
        )
        self.assertEqual(failed_document_node.meta["status"], "failed")
        self.assertEqual(failed_document_node.meta["last_error"], "parse failed")
        self.assertEqual(failed_document_node.meta["source_url"], "https://example.test/report")
        self.assertEqual(failed_document_node.meta["resolved_url"], "https://example.test/report")

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

    def test_local_retrieval_filters_private_chunks_by_access_metadata(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config = make_config(Path(temp_dir), llm_api_key="", embedding_api_key="")
            config.data_dir.mkdir(parents=True, exist_ok=True)

            owner_path = config.data_dir / "owner.md"
            department_path = config.data_dir / "department.md"
            hidden_path = config.data_dir / "hidden.md"
            public_path = config.data_dir / "public.md"

            owner_path.write_text(
                "# Owner\n\nAurora visibility marker owner scope keeps fixture isolation readable.",
                encoding="utf-8",
            )
            department_path.write_text(
                "# Department\n\nAurora visibility marker department scope keeps fixture isolation readable.",
                encoding="utf-8",
            )
            hidden_path.write_text(
                "# Hidden\n\nAurora visibility marker hidden scope keeps fixture isolation readable.",
                encoding="utf-8",
            )
            public_path.write_text(
                "# Public\n\nAurora visibility marker public scope keeps fixture isolation readable.",
                encoding="utf-8",
            )

            documents = load_documents_from_paths(
                [owner_path, department_path, hidden_path, public_path],
                config.data_dir,
                metadata_by_path={
                    str(owner_path.resolve()): {
                        "document_id": "doc-owner",
                        "tenant_id": "t1",
                        "user_id": "u1",
                        "is_public": False,
                    },
                    str(department_path.resolve()): {
                        "document_id": "doc-department",
                        "tenant_id": "t1",
                        "user_id": "u2",
                        "department_id": "qa",
                        "is_public": False,
                    },
                    str(hidden_path.resolve()): {
                        "document_id": "doc-hidden",
                        "tenant_id": "t1",
                        "user_id": "u2",
                        "department_id": "ops",
                        "is_public": False,
                    },
                    str(public_path.resolve()): {
                        "document_id": "doc-public",
                        "tenant_id": "t2",
                        "user_id": "u9",
                        "is_public": True,
                    },
                },
            )
            nodes = create_nodes_from_documents(config, documents)
            inserted = add_nodes_with_embeddings(config, nodes)

            self.assertEqual(inserted, 4)

            chunks, _, _ = retrieve_chunks(
                "Aurora visibility marker fixture isolation",
                config,
                top_k=10,
                access_filter=KnowledgeAccessFilter(
                    tenant_id="t1",
                    user_id="u1",
                    department_id="qa",
                    allow_public=True,
                ),
            )

            retrieved_document_ids = {chunk.document_id for chunk in chunks}
            self.assertIn("doc-owner", retrieved_document_ids)
            self.assertIn("doc-department", retrieved_document_ids)
            self.assertIn("doc-public", retrieved_document_ids)
            self.assertNotIn("doc-hidden", retrieved_document_ids)

    def test_local_index_like_search_works_without_fts_alias_mismatch(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config = make_config(Path(temp_dir), llm_api_key="", embedding_api_key="")
            config.data_dir.mkdir(parents=True, exist_ok=True)
            file_path = config.data_dir / "linux_ports.md"
            file_path.write_text(
                "# Linux 端口排查\n\nss -lntp 和 netstat 都可以帮助定位端口占用问题。",
                encoding="utf-8",
            )

            documents = load_documents_from_paths([file_path], config.data_dir)
            nodes = create_nodes_from_documents(config, documents)
            add_nodes_with_embeddings(config, nodes)

            with connect_state_db(config) as connection:
                connection.execute("DROP TABLE IF EXISTS local_chunks_fts")
                connection.commit()

            chunks = search_local_index_chunks(
                config,
                "端口占用",
                access_filter=KnowledgeAccessFilter(),
            )

            self.assertTrue(chunks)
            self.assertIn("linux", chunks[0]["file_name"].lower())


class CapabilityRegistryTests(unittest.TestCase):
    def test_assembler_exposes_builtin_capabilities_without_duplication(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config = make_config(Path(temp_dir))
            assembler = CapabilityAssembler(config)
            context = CapabilityContext(
                request_id="req-capabilities",
                tenant_id="t1",
                user_id="u1",
                project_id="p1",
                session_id="s1",
                invocation_source="api",
            )

            assembly = assembler.assemble(context)

            self.assertIn("kb.retrieve", assembly.tools)
            self.assertIn("kb.rebuild", assembly.commands)
            self.assertIn("kb.document_preview", assembly.resources)

    def test_model_context_hides_non_model_rebuild_command(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config = make_config(Path(temp_dir))
            assembler = CapabilityAssembler(config)
            model_context = CapabilityContext(
                request_id="req-model",
                tenant_id="t1",
                user_id="u1",
                project_id="p1",
                session_id="s1",
                invocation_source="model",
            )

            assembly = assembler.assemble(model_context)

            self.assertIn("kb.retrieve", assembly.tools)
            self.assertNotIn("kb.rebuild", assembly.commands)
            with self.assertRaises(CapabilityAccessError):
                assembler.require_command("kb.rebuild", model_context)

    def test_assembler_applies_descriptor_metadata_visibility_rules(self):
        class ScopedTool(BaseTool):
            descriptor = CapabilityDescriptor(
                name="test.scoped",
                capability_type="tool",
                display_name="Scoped Tool",
                description="Tool visible only for one scoped capability context.",
                metadata={
                    "allowed_tenant_ids": ("t1",),
                    "allowed_department_ids": ("qa",),
                    "allowed_scenes": ("troubleshooting",),
                    "required_context_metadata": {
                        "connector_enabled": True,
                        "access_tier": ("internal", "admin"),
                    },
                },
            )

            def execute(self, payload, context):
                return {"ok": True}

        with tempfile.TemporaryDirectory() as temp_dir:
            config = make_config(Path(temp_dir))
            registry = CapabilityRegistry()
            registry.register(ScopedTool.descriptor, lambda runtime_config: ScopedTool(runtime_config))
            assembler = CapabilityAssembler(config, registry=registry)

            allowed_context = CapabilityContext(
                request_id="req-scoped-allowed",
                tenant_id="t1",
                user_id="u1",
                project_id="p1",
                session_id="s1",
                department_id="qa",
                scene="troubleshooting",
                invocation_source="api",
                metadata={"connector_enabled": True, "access_tier": "internal"},
            )
            hidden_context = CapabilityContext(
                request_id="req-scoped-hidden",
                tenant_id="t1",
                user_id="u1",
                project_id="p1",
                session_id="s1",
                department_id="ops",
                scene="troubleshooting",
                invocation_source="api",
                metadata={"connector_enabled": True, "access_tier": "internal"},
            )

            self.assertIn("test.scoped", assembler.assemble(allowed_context).tools)
            self.assertNotIn("test.scoped", assembler.assemble(hidden_context).tools)
            with self.assertRaises(CapabilityAccessError):
                assembler.require_tool("test.scoped", hidden_context)

    @patch("app.services.capabilities.builtin.rag_query_tool.retrieve_chunks")
    def test_retrieve_tool_delegates_to_existing_retrieval_service(self, mock_retrieve_chunks):
        mock_retrieve_chunks.return_value = ([], "rewritten query", "")

        with tempfile.TemporaryDirectory() as temp_dir:
            config = make_config(Path(temp_dir))
            assembler = CapabilityAssembler(config)
            context = CapabilityContext(
                request_id="req-retrieve",
                tenant_id="t1",
                user_id="u1",
                project_id="p1",
                session_id="s1",
                invocation_source="system",
            )

            tool = assembler.require_tool("kb.retrieve", context)
            result = tool.execute(
                {
                    "question": "pytest 怎么跑单个测试？",
                    "top_k": 3,
                    "chat_history": [{"role": "user", "content": "pytest 命令"}],
                },
                context,
            )

            self.assertEqual(result, ([], "rewritten query", ""))
            mock_retrieve_chunks.assert_called_once_with(
                question="pytest 怎么跑单个测试？",
                config=config,
                top_k=3,
                chat_history=[{"role": "user", "content": "pytest 命令"}],
                access_filter=KnowledgeAccessFilter(
                    tenant_id="t1",
                    user_id="u1",
                    department_id="",
                    allow_public=True,
                ),
            )

    @patch("app.services.capabilities.builtin.kb_rebuild_command.start_rebuild_job")
    def test_rebuild_command_delegates_to_existing_job_service(self, mock_start_rebuild_job):
        mock_start_rebuild_job.return_value = KnowledgeBaseJob(
            job_id="job-capability",
            status="queued",
            mode="sync",
            stage="queued",
            progress=0.0,
            message="queued",
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            config = make_config(Path(temp_dir))
            assembler = CapabilityAssembler(config)
            context = CapabilityContext(
                request_id="req-rebuild",
                tenant_id="t1",
                user_id="u1",
                project_id="p1",
                session_id="s1",
                invocation_source="api",
            )

            command = assembler.require_command("kb.rebuild", context)
            job = command.invoke({"mode": "scan"}, context)

            self.assertEqual(job.job_id, "job-capability")
            mock_start_rebuild_job.assert_called_once_with(config, mode="scan")


class KnowledgeBaseJobTests(unittest.TestCase):
    @patch(
        "app.services.knowledge_base_job_service.persist_materialized_document",
        return_value={
            "version_id": "version-1",
            "file_type": "md",
            "parser_name": "plain_text_reader",
            "segment_count": 1,
            "page_count": 0,
            "sheet_count": 0,
            "title": "",
            "source_url": "",
            "resolved_url": "",
        },
    )
    @patch("app.services.knowledge_base_job_service.get_collection_count", return_value=2)
    @patch("app.services.knowledge_base_job_service.add_nodes_with_embeddings", return_value=2)
    @patch("app.services.knowledge_base_job_service.create_nodes_from_documents")
    @patch("app.services.knowledge_base_job_service.build_llama_documents_from_parsed_documents")
    @patch("app.services.knowledge_base_job_service.load_parsed_documents_from_paths")
    @patch("app.services.knowledge_base_job_service.delete_retrieval_document_chunks")
    def test_start_rebuild_job_updates_catalog_status(
        self,
        mock_delete_retrieval_document_chunks,
        mock_load_parsed_documents_from_paths,
        mock_build_llama_documents_from_parsed_documents,
        mock_create_nodes_from_documents,
        mock_add_nodes_with_embeddings,
        mock_get_collection_count,
        mock_persist_materialized_document,
    ):
        with tempfile.TemporaryDirectory() as temp_dir:
            config = make_config(Path(temp_dir))
            config.data_dir.mkdir(parents=True, exist_ok=True)
            source_path = config.data_dir / "01_python_testing.md"
            source_path.write_text("python", encoding="utf-8")

            mock_load_parsed_documents_from_paths.return_value = [
                ParsedDocument(
                    source_id="source-1",
                    source_path=str(source_path.resolve(strict=False)),
                    relative_path="01_python_testing.md",
                    file_name="01_python_testing.md",
                    file_type="md",
                    parser_name="plain_text_reader",
                    content_markdown="# Python",
                    content_json={"file_type": "md", "parser_name": "plain_text_reader"},
                    segments=[
                        ExtractedSegment(
                            segment_id="seg-1",
                            sequence=1,
                            content_text="python",
                            content_markdown="# Python",
                        )
                    ],
                )
            ]
            mock_build_llama_documents_from_parsed_documents.return_value = [SimpleNamespace()]
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
            self.assertEqual(documents[0].active_version_id, "version-1")
            self.assertTrue(mock_add_nodes_with_embeddings.called)
            self.assertTrue(mock_persist_materialized_document.called)
            self.assertTrue((config.db_dir / "knowledge_base_jobs.json").exists())

    @patch(
        "app.services.knowledge_base_job_service.persist_materialized_document",
        return_value={
            "version_id": "version-2",
            "file_type": "md",
            "parser_name": "plain_text_reader",
            "segment_count": 1,
            "page_count": 0,
            "sheet_count": 0,
            "title": "",
            "source_url": "",
            "resolved_url": "",
        },
    )
    @patch("app.services.knowledge_base_job_service.get_collection_count", return_value=0)
    @patch("app.services.knowledge_base_job_service.add_nodes_with_embeddings", return_value=1)
    @patch("app.services.knowledge_base_job_service.create_nodes_from_documents")
    @patch("app.services.knowledge_base_job_service.build_llama_documents_from_parsed_documents")
    @patch("app.services.knowledge_base_job_service.load_parsed_documents_from_paths")
    def test_scan_mode_discovers_external_files_but_sync_mode_does_not(
        self,
        mock_load_parsed_documents_from_paths,
        mock_build_llama_documents_from_parsed_documents,
        mock_create_nodes_from_documents,
        mock_add_nodes_with_embeddings,
        mock_get_collection_count,
        mock_persist_materialized_document,
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

            mock_load_parsed_documents_from_paths.return_value = [
                ParsedDocument(
                    source_id="source-2",
                    source_path=str(second_path.resolve(strict=False)),
                    relative_path="02_linux_commands.md",
                    file_name="02_linux_commands.md",
                    file_type="md",
                    parser_name="plain_text_reader",
                    content_markdown="# Linux",
                    content_json={"file_type": "md", "parser_name": "plain_text_reader"},
                    segments=[
                        ExtractedSegment(
                            segment_id="seg-2",
                            sequence=1,
                            content_text="linux",
                            content_markdown="# Linux",
                        )
                    ],
                )
            ]
            mock_build_llama_documents_from_parsed_documents.return_value = [SimpleNamespace()]
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
            self.assertTrue(mock_persist_materialized_document.called)


class OfflineAnswerTests(unittest.TestCase):
    def test_build_citations_include_chunk_and_page_metadata(self):
        citations = build_citations(
            [
                RetrievedChunk(
                    document_id="doc-pdf",
                    file_name="guide.pdf",
                    source_path="guide.pdf",
                    relative_path="guide.pdf",
                    text="Deployment checklist on page 3.",
                    score=0.91,
                    vector_score=0.91,
                    chunk_id="chunk-123",
                    page_number=3,
                    source_type="pdf",
                )
            ]
        )

        self.assertEqual(citations[0].chunk_id, "chunk-123")
        self.assertEqual(citations[0].page_number, 3)

    def test_answer_with_rag_falls_back_to_local_extractive_mode(self):
        config = make_config(Path(tempfile.mkdtemp()), llm_api_key="", embedding_api_key="")
        try:
            with patch(
                "app.services.capabilities.builtin.rag_query_tool.retrieve_chunks",
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

- 可以先确认目标端口是否已经被监听。""",
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
            }
        )

        self.assertIn("LLM_API_KEY", errors)
        self.assertIn("EMBEDDING_API_KEY", errors)
        self.assertIn("LLM_MODEL", errors)
        self.assertIn("CHUNK_OVERLAP", errors)
        self.assertIn("NO_ANSWER_MIN_SCORE", errors)
        self.assertIn("LOG_LEVEL", errors)

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


class MemoryIsolationTests(unittest.TestCase):
    def test_scope_resolver_builds_ordered_allowed_scopes(self):
        resolver = ScopeResolver()
        context = MemoryRequestContext(
            request_id="req-1",
            tenant_id="t1",
            user_id="u1",
            project_id="p1",
            session_id="s1",
        )

        resolved = resolver.resolve(context)

        self.assertEqual(
            [(item.scope_type, item.scope_id) for item in resolved.allowed_scopes],
            [
                ("session", "s1"),
                ("user", "u1"),
                ("project", "p1"),
                ("team", "team_default"),
                ("global", "global_default"),
            ],
        )

    def test_memory_access_policy_blocks_cross_scope_reads_and_global_write(self):
        policy = MemoryAccessPolicy()
        context = MemoryRequestContext(
            request_id="req-2",
            tenant_id="t1",
            user_id="u1",
            project_id="p1",
            session_id="s1",
        )

        same_user_fact = MemoryFact(
            id="m-user",
            tenant_id="t1",
            owner_user_id="u1",
            project_id="p1",
            scope_type="user",
            scope_id="u1",
            type="preference",
            content="Prefer tables",
            status="active",
            source_session_id="s1",
            created_at="2026-03-30T00:00:00+00:00",
            updated_at="2026-03-30T00:00:00+00:00",
        )
        other_user_fact = MemoryFact(
            id="m-other-user",
            tenant_id="t1",
            owner_user_id="u2",
            project_id="p1",
            scope_type="user",
            scope_id="u2",
            type="preference",
            content="Other user preference",
            status="active",
            source_session_id="s2",
            created_at="2026-03-30T00:00:00+00:00",
            updated_at="2026-03-30T00:00:00+00:00",
        )
        other_project_fact = MemoryFact(
            id="m-other-project",
            tenant_id="t1",
            owner_user_id="u1",
            project_id="p2",
            scope_type="project",
            scope_id="p2",
            type="fact",
            content="Different project fact",
            status="active",
            source_session_id="s1",
            created_at="2026-03-30T00:00:00+00:00",
            updated_at="2026-03-30T00:00:00+00:00",
        )
        other_session_fact = MemoryFact(
            id="m-other-session",
            tenant_id="t1",
            owner_user_id="u1",
            project_id="p1",
            scope_type="session",
            scope_id="s2",
            type="fact",
            content="Different session fact",
            status="active",
            source_session_id="s2",
            created_at="2026-03-30T00:00:00+00:00",
            updated_at="2026-03-30T00:00:00+00:00",
        )

        self.assertTrue(policy.can_read(context, same_user_fact))
        self.assertFalse(policy.can_read(context, other_user_fact))
        self.assertFalse(policy.can_read(context, other_project_fact))
        self.assertFalse(policy.can_read(context, other_session_fact))

        denied_global_write = MemoryFactCreate(
            tenant_id="t1",
            owner_user_id="u1",
            project_id="p1",
            scope_type="global",
            scope_id="global_default",
            type="fact",
            content="Do not allow this from normal chat",
            source_session_id="s1",
            confirmed=True,
        )
        self.assertFalse(policy.can_write(context, denied_global_write))

    def test_memory_retriever_returns_only_allowed_scopes_and_audits_retrieve(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config = make_config(Path(temp_dir))
            repository = MemoryRepository(config)
            audit_service = MemoryAuditService(config)
            retriever = MemoryRetriever(config, repository=repository, audit_service=audit_service)
            context = MemoryRequestContext(
                request_id="req-retrieve",
                tenant_id="t1",
                user_id="u1",
                project_id="p1",
                session_id="s1",
            )

            allowed_fact = repository.create_memory_fact(
                MemoryFactCreate(
                    tenant_id="t1",
                    owner_user_id="u1",
                    project_id="p1",
                    scope_type="session",
                    scope_id="s1",
                    type="fact",
                    content="Current session is focused on scope isolation",
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
                    content="Other user's preference",
                    source_session_id="s2",
                )
            )
            stale_fact = repository.create_memory_fact(
                MemoryFactCreate(
                    tenant_id="t1",
                    owner_user_id="u1",
                    project_id="p1",
                    scope_type="project",
                    scope_id="p1",
                    type="fact",
                    content="Stale project fact",
                    source_session_id="s1",
                )
            )
            repository.update_memory_fact_status(stale_fact.id, "stale")

            results = retriever.retrieve(context, top_k=5)

            self.assertEqual([item.id for item in results], [allowed_fact.id])
            audits = audit_service.list_by_request_id("t1", "req-retrieve")
            self.assertEqual(len(audits), 1)
            self.assertEqual(audits[0].action, "retrieve")
            self.assertEqual(audits[0].memory_fact_id, allowed_fact.id)

    def test_troubleshooting_retrieval_prefers_project_pending_issue_over_user_preference(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config = make_config(Path(temp_dir))
            repository = MemoryRepository(config)
            retriever = MemoryRetriever(config, repository=repository)
            context = MemoryRequestContext(
                request_id="req-troubleshooting-retrieval",
                tenant_id="t1",
                user_id="u1",
                project_id="p1",
                session_id="s1",
            )

            pending_issue = repository.create_memory_fact(
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

            bundle = retriever.retrieve_bundle(
                context,
                scene="troubleshooting",
                user_query="Why does the login API return 500 during startup?",
                top_k=4,
            )

            self.assertEqual(bundle.selected_memories[0].memory_fact_id, pending_issue.id)
            self.assertNotIn("preference", {item.type for item in bundle.selected_memories})
            self.assertEqual(bundle.memory_context[0].memory_id, pending_issue.id)

    def test_command_lookup_can_return_empty_bundle_when_only_irrelevant_preference_exists(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config = make_config(Path(temp_dir))
            repository = MemoryRepository(config)
            retriever = MemoryRetriever(config, repository=repository)
            context = MemoryRequestContext(
                request_id="req-command-empty",
                tenant_id="t1",
                user_id="u1",
                project_id="p1",
                session_id="s1",
            )

            repository.create_memory_fact(
                MemoryFactCreate(
                    tenant_id="t1",
                    owner_user_id="u1",
                    project_id="p1",
                    scope_type="user",
                    scope_id="u1",
                    type="preference",
                    content="Prefer bullet answers.",
                    source_session_id="s1",
                    source_type="user_confirmed",
                    source_confidence=0.95,
                )
            )

            bundle = retriever.retrieve_bundle(
                context,
                scene="command_lookup",
                user_query="What is the git command to list branches?",
                top_k=2,
            )

            self.assertEqual(bundle.total_selected, 0)
            self.assertEqual(bundle.memory_context, [])
            self.assertIn(
                bundle.dropped_candidates[0].drop_reason,
                {"scene_filtered_low_value_preference", "below_min_relevance", "below_injection_threshold"},
            )

    def test_onboarding_scene_can_prefer_project_decision_over_session_temporary_override(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config = make_config(Path(temp_dir))
            repository = MemoryRepository(config)
            retriever = MemoryRetriever(config, repository=repository)
            context = MemoryRequestContext(
                request_id="req-onboarding-priority",
                tenant_id="t1",
                user_id="u1",
                project_id="p1",
                session_id="s1",
            )

            project_decision = repository.create_memory_fact(
                MemoryFactCreate(
                    tenant_id="t1",
                    owner_user_id="u1",
                    project_id="p1",
                    scope_type="project",
                    scope_id="p1",
                    type="decision",
                    content="architecture.entrypoint: Use the FastAPI service layer for onboarding flows.",
                    source_session_id="s1",
                    subject_key="project:aurora",
                    fact_key="architecture.entrypoint",
                    source_type="imported",
                    source_confidence=0.9,
                )
            )
            session_override = repository.create_memory_fact(
                MemoryFactCreate(
                    tenant_id="t1",
                    owner_user_id="u1",
                    project_id="p1",
                    scope_type="session",
                    scope_id="s1",
                    type="decision",
                    content="architecture.entrypoint: Temporary demo script for this session only.",
                    source_session_id="s1",
                    subject_key="project:aurora",
                    fact_key="architecture.entrypoint",
                    source_type="system_generated",
                    source_confidence=0.4,
                )
            )

            bundle = retriever.retrieve_bundle(
                context,
                scene="onboarding",
                user_query="How should a new teammate understand the architecture entrypoint?",
                top_k=4,
            )

            self.assertEqual([item.memory_fact_id for item in bundle.selected_memories], [project_decision.id])
            self.assertTrue(
                any(
                    item.memory_fact_id == session_override.id
                    and item.drop_reason.startswith("shadowed_by_same_identity")
                    for item in bundle.dropped_candidates
                )
            )

    def test_retrieval_planner_recognizes_chinese_contextual_cues(self):
        planner = RetrievalPlanner()
        context = MemoryRequestContext(
            request_id="req-chinese-cues",
            tenant_id="t1",
            user_id="u1",
            project_id="p1",
            session_id="s1",
        )
        resolved = ScopeResolver().resolve(context)
        query = MemoryQuery(
            tenant_id="t1",
            user_id="u1",
            project_id="p1",
            session_id="s1",
            scene="qa_query",
            user_query="当前我们在讨论什么上下文？",
            allowed_scopes=resolved.allowed_scopes,
            top_k=2,
        )

        plan = planner.plan(query, planner.build_scene_policy("qa_query"))

        self.assertEqual(plan.enable_reason, "scene_and_contextual_signal")
        self.assertIn("当前", plan.query_cues)
        self.assertIn("我们", plan.query_cues)
        self.assertIn("上下文", plan.query_cues)

    def test_memory_relevance_scorer_adds_contextual_boost_for_chinese_query(self):
        query = MemoryQuery(
            tenant_id="t1",
            user_id="u1",
            project_id="p1",
            session_id="s1",
            scene="troubleshooting",
            user_query="当前我们在讨论登录排查上下文",
            allowed_scopes=(),
            top_k=2,
        )
        candidate = MemoryCandidate.from_fact(
            MemoryFact(
                id="mem-session",
                tenant_id="t1",
                owner_user_id="u1",
                project_id="p1",
                scope_type="session",
                scope_id="s1",
                type="fact",
                content="登录排查上下文记录",
                status="active",
                source_session_id="s1",
                created_at="2026-03-30T10:00:00Z",
                updated_at="2026-03-30T10:00:00Z",
            )
        )

        signal = MemoryRelevanceScorer().score(query, candidate)

        self.assertGreater(signal.score, 0.26)
        self.assertIn("contextual_scope_boost=session", signal.matched_reason)

    def test_memory_injection_builder_caps_content_length_in_bundle(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config = make_config(Path(temp_dir))
            repository = MemoryRepository(config)
            retriever = MemoryRetriever(config, repository=repository)
            context = MemoryRequestContext(
                request_id="req-injection-cap",
                tenant_id="t1",
                user_id="u1",
                project_id="p1",
                session_id="s1",
            )
            long_content = (
                "onboarding.architecture: "
                + "Aurora keeps memory retrieval and knowledge retrieval separated. " * 12
            ).strip()
            fact = repository.create_memory_fact(
                MemoryFactCreate(
                    tenant_id="t1",
                    owner_user_id="u1",
                    project_id="p1",
                    scope_type="project",
                    scope_id="p1",
                    type="decision",
                    content=long_content,
                    source_session_id="s1",
                    subject_key="project:aurora",
                    fact_key="onboarding.architecture",
                    source_type="imported",
                    source_confidence=0.9,
                )
            )

            bundle = retriever.retrieve_bundle(
                context,
                scene="onboarding",
                user_query="新人应该如何理解 onboarding architecture？",
                top_k=2,
            )

            self.assertEqual([item.memory_fact_id for item in bundle.selected_memories], [fact.id])
            self.assertLessEqual(
                len(bundle.memory_context[0].content),
                bundle.retrieval_plan.max_injection_chars_per_memory,
            )
            self.assertTrue(bundle.memory_context[0].content.endswith("..."))
            self.assertEqual(
                bundle.retrieval_trace["summary"]["selected_context_chars"],
                len(bundle.memory_context[0].content),
            )

    def test_memory_write_service_enforces_safe_write_rules(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config = make_config(Path(temp_dir))
            service = MemoryWriteService(config)
            audit_service = MemoryAuditService(config)
            context = MemoryRequestContext(
                request_id="req-write",
                tenant_id="t1",
                user_id="u1",
                project_id="p1",
                session_id="s1",
            )

            created = service.create_memory_fact(
                context,
                service.build_create_payload(
                    context,
                    content="Current thread is discussing scope isolation",
                    memory_type="fact",
                ),
            )
            read_back = service.get_memory_fact_by_id(context, created.id)
            updated = service.update_memory_fact_status(
                context,
                memory_fact_id=created.id,
                status="superseded",
            )

            self.assertIsNotNone(read_back)
            self.assertIsNotNone(updated)
            self.assertEqual(updated.status, "superseded")

            with self.assertRaises(PermissionError):
                service.create_memory_fact(
                    context,
                    MemoryFactCreate(
                        tenant_id="t1",
                        owner_user_id="u1",
                        project_id="p1",
                        scope_type="global",
                        scope_id="global_default",
                        type="fact",
                        content="Forbidden global fact",
                        source_session_id="s1",
                        confirmed=True,
                    ),
                )

            with self.assertRaises(PermissionError):
                service.create_memory_fact(
                    context,
                    MemoryFactCreate(
                        tenant_id="t1",
                        owner_user_id="u1",
                        project_id="p1",
                        scope_type="session",
                        scope_id="s1",
                        type="fact",
                        content="KB excerpt should never become memory directly",
                        source_session_id="s1",
                        source_kind="knowledge_base_document",
                    ),
                )

            actions = [item.action for item in audit_service.list_by_request_id("t1", "req-write")]
            self.assertIn("create", actions)
            self.assertIn("read", actions)
            self.assertIn("deprecate", actions)

    def test_sensitive_content_guard_blocks_secret_write_and_records_governance_events(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config = make_config(Path(temp_dir))
            service = MemoryWriteService(config)
            audit_service = AuditService(config)
            context = MemoryRequestContext(
                request_id="req-sensitive-block",
                tenant_id="t1",
                user_id="u1",
                project_id="p1",
                session_id="s1",
            )

            with self.assertRaises(PermissionError):
                service.create_memory_fact(
                    context,
                    service.build_create_payload(
                        context,
                        content="api_key=sk-abcdefghijklmnop",
                        memory_type="fact",
                    ),
                )

            security_events = audit_service.list_security_events(tenant_id="t1", limit=10)
            policy_decisions = audit_service.list_policy_decisions(request_id="req-sensitive-block", limit=10)

            self.assertEqual(security_events[0].event_type, "sensitive_memory_detected")
            self.assertEqual(policy_decisions[0].policy_name, "sensitive_content_guard.scan")
            self.assertEqual(policy_decisions[0].decision, "deny")

    def test_memory_retrieval_rate_limit_degrades_to_empty_bundle(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config = make_config(Path(temp_dir))
            repository = MemoryRepository(config)
            audit_service = AuditService(config)
            retriever = MemoryRetriever(
                config,
                repository=repository,
                abuse_guard=AbuseGuard(
                    rules={
                        "memory_retrieval": {
                            "user": (1, 60),
                            "session": (1, 60),
                            "tenant": (1, 60),
                        }
                    }
                ),
                audit_service=audit_service,
            )
            context = MemoryRequestContext(
                request_id="req-rate-limit-1",
                tenant_id="t-rate-limit",
                user_id="u-rate-limit",
                project_id="p1",
                session_id="s-rate-limit",
            )
            repository.create_memory_fact(
                MemoryFactCreate(
                    tenant_id="t-rate-limit",
                    owner_user_id="u-rate-limit",
                    project_id="p1",
                    scope_type="session",
                    scope_id="s-rate-limit",
                    type="fact",
                    content="Current thread is watching retrieval rate limits.",
                    source_session_id="s-rate-limit",
                )
            )

            first_bundle = retriever.retrieve_bundle(
                context,
                scene="qa_query",
                user_query="What are we watching?",
                top_k=3,
            )
            second_bundle = retriever.retrieve_bundle(
                MemoryRequestContext(
                    request_id="req-rate-limit-2",
                    tenant_id="t-rate-limit",
                    user_id="u-rate-limit",
                    project_id="p1",
                    session_id="s-rate-limit",
                ),
                scene="qa_query",
                user_query="What are we watching now?",
                top_k=3,
            )

            self.assertEqual(first_bundle.total_selected, 1)
            self.assertEqual(second_bundle.total_selected, 0)
            self.assertIn("rate_limited", second_bundle.retrieval_trace["summary"]["error"])
            self.assertEqual(
                audit_service.list_security_events(tenant_id="t-rate-limit", limit=5)[0].event_type,
                "rate_limit_triggered",
            )

    def test_governance_inspector_summarizes_hidden_memory_and_recent_findings(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config = make_config(Path(temp_dir))
            repository = MemoryRepository(config)
            audit_service = AuditService(config)
            repository.create_memory_fact(
                MemoryFactCreate(
                    tenant_id="t1",
                    owner_user_id="u1",
                    project_id="p1",
                    scope_type="project",
                    scope_id="p1",
                    type="fact",
                    content="Cold memory awaiting archive.",
                    source_session_id="s1",
                    retrieval_visibility="hidden_from_default",
                    forgetting_status="cooling",
                )
            )
            audit_service.record_security_event(
                tenant_id="t1",
                event_type="policy_blocked_write",
                severity="medium",
                actor_user_id="u1",
                session_id="s1",
                request_id="req-governance-summary",
                event_payload={"reason": "demo"},
            )
            audit_service.record_policy_decision(
                request_id="req-governance-summary",
                policy_name="sensitive_content_guard.scan",
                decision="deny",
                reason="demo denial",
                target_type="memory_write",
                target_id="project:p1",
                payload={"tenant_id": "t1"},
            )

            summary = GovernanceInspector(config).build_summary(
                tenant_id="t1",
                limit=5,
                capture_snapshot=True,
            )

            self.assertEqual(summary["hidden_memory_count"], 1)
            self.assertEqual(summary["archive_backlog_count"], 1)
            self.assertEqual(summary["recent_security_events"][0]["event_type"], "policy_blocked_write")
            self.assertEqual(summary["top_failing_policies"][0]["policy_name"], "sensitive_content_guard.scan")

    def test_consistency_update_supersedes_previous_version_and_retriever_hides_old_value(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config = make_config(Path(temp_dir))
            service = MemoryWriteService(config)
            repository = MemoryRepository(config)
            retriever = MemoryRetriever(config)
            context = MemoryRequestContext(
                request_id="req-consistency-update",
                tenant_id="t1",
                user_id="u1",
                project_id="p1",
                session_id="s1",
            )

            first = service.write_memory_fact(
                context,
                service.build_create_payload(
                    context,
                    content="stack.framework: Flask",
                    memory_type="fact",
                    scope_type="project",
                    source_type="model_inferred",
                ),
            )
            second = service.write_memory_fact(
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

            first_row = repository.get_memory_fact_by_id(first.memory_fact.id)
            self.assertEqual(first.operation, "insert")
            self.assertEqual(second.operation, "update")
            self.assertIsNotNone(first_row)
            self.assertEqual(first_row.status, "superseded")
            self.assertEqual(first_row.superseded_by, second.memory_fact.id)
            self.assertEqual(second.memory_fact.version, 2)
            self.assertEqual(second.memory_fact.supersedes, first.memory_fact.id)

            results = retriever.retrieve(context, top_k=5)
            self.assertEqual([item.id for item in results], [second.memory_fact.id])

    def test_consistency_correction_marks_old_fact_superseded_and_preserves_history(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config = make_config(Path(temp_dir))
            service = MemoryWriteService(config)
            context = MemoryRequestContext(
                request_id="req-consistency-correction",
                tenant_id="t1",
                user_id="u1",
                project_id="p1",
                session_id="s1",
            )

            original = service.write_memory_fact(
                context,
                service.build_create_payload(
                    context,
                    content="env.api_base: http://legacy.local",
                    memory_type="fact",
                    scope_type="project",
                    source_type="model_inferred",
                ),
            )
            corrected = service.write_memory_fact(
                context,
                service.build_create_payload(
                    context,
                    content="env.api_base: http://127.0.0.1:8000",
                    memory_type="fact",
                    scope_type="project",
                    correction_of=original.memory_fact.id,
                    source_type="user_confirmed",
                    reviewed_by_human=True,
                ),
            )

            history = service.list_memory_history(context, corrected.memory_fact.id, limit=10)

            self.assertEqual(corrected.operation, "correction")
            self.assertEqual(corrected.memory_fact.correction_of, original.memory_fact.id)
            self.assertEqual(history[0].id, corrected.memory_fact.id)
            self.assertEqual(history[1].id, original.memory_fact.id)
            self.assertEqual(history[1].status, "superseded")

    def test_conflict_pending_review_does_not_enter_default_retrieval(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config = make_config(Path(temp_dir))
            service = MemoryWriteService(config)
            retriever = MemoryRetriever(config)
            context = MemoryRequestContext(
                request_id="req-consistency-conflict",
                tenant_id="t1",
                user_id="u1",
                project_id="p1",
                session_id="s1",
            )

            current = service.write_memory_fact(
                context,
                service.build_create_payload(
                    context,
                    content="architecture.memory_strategy: scoped_facts",
                    memory_type="decision",
                    scope_type="project",
                    source_type="imported",
                    source_confidence=0.85,
                ),
            )
            pending = service.write_memory_fact(
                context,
                service.build_create_payload(
                    context,
                    content="architecture.memory_strategy: summary_only",
                    memory_type="decision",
                    scope_type="project",
                    source_type="model_inferred",
                    source_confidence=0.55,
                ),
            )

            results = retriever.retrieve(context, top_k=5)
            self.assertEqual(pending.operation, "conflict")
            self.assertEqual(pending.memory_fact.status, "conflict_pending_review")
            self.assertEqual([item.id for item in results], [current.memory_fact.id])

    def test_retriever_prefers_session_fact_over_project_fact_for_same_identity(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config = make_config(Path(temp_dir))
            service = MemoryWriteService(config)
            retriever = MemoryRetriever(config)
            context = MemoryRequestContext(
                request_id="req-scope-priority",
                tenant_id="t1",
                user_id="u1",
                project_id="p1",
                session_id="s1",
            )

            project_fact = service.write_memory_fact(
                context,
                service.build_create_payload(
                    context,
                    content="env.api_base: https://prod.internal",
                    memory_type="fact",
                    scope_type="project",
                    subject_key="project:aurora",
                    fact_key="env.api_base",
                    source_type="imported",
                ),
            )
            session_fact = service.write_memory_fact(
                context,
                service.build_create_payload(
                    context,
                    content="env.api_base: http://127.0.0.1:8000",
                    memory_type="fact",
                    scope_type="session",
                    subject_key="project:aurora",
                    fact_key="env.api_base",
                    source_type="user_confirmed",
                    reviewed_by_human=True,
                ),
            )

            results = retriever.retrieve(context, top_k=5)
            self.assertEqual([item.id for item in results], [session_fact.memory_fact.id])
            self.assertEqual(project_fact.memory_fact.status, "active")

    def test_coexisting_response_style_preferences_remain_active_together(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config = make_config(Path(temp_dir))
            service = MemoryWriteService(config)
            retriever = MemoryRetriever(config)
            context = MemoryRequestContext(
                request_id="req-coexist",
                tenant_id="t1",
                user_id="u1",
                project_id="p1",
                session_id="s1",
            )

            first = service.write_memory_fact(
                context,
                service.build_create_payload(
                    context,
                    content="Prefer table answers",
                    memory_type="preference",
                    source_type="user_confirmed",
                ),
            )
            second = service.write_memory_fact(
                context,
                service.build_create_payload(
                    context,
                    content="Prefer step by step answers",
                    memory_type="preference",
                    source_type="user_confirmed",
                ),
            )

            results = retriever.retrieve(context, top_k=5)
            self.assertEqual(first.operation, "insert")
            self.assertEqual(second.operation, "coexist")
            self.assertEqual({item.fact_key for item in results}, {
                "preference.response_style.table",
                "preference.response_style.step_by_step",
            })
            self.assertEqual(len(results), 2)


class ChatMemoryServiceTests(unittest.TestCase):
    def test_auto_assimilation_persists_explicit_response_style_preference(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config = make_config(Path(temp_dir))
            service = ChatMemoryService(config)
            repository = MemoryRepository(config)
            context = MemoryRequestContext(
                request_id="req-auto-pref",
                tenant_id="t1",
                user_id="u1",
                project_id="p1",
                session_id="s1",
            )

            report = service.assimilate_turn(
                request_context=context,
                user_message="之后请用表格回答，然后帮我总结一下项目结构。",
                assistant_result=ChatResult(
                    answer="ok",
                    citations=[],
                    retrieved_count=0,
                ),
                scene="qa_query",
            )

            user_memories = repository.list_by_filters(
                tenant_id="t1",
                scope_type="user",
                scope_id="u1",
                limit=10,
            )

            self.assertEqual(report.candidate_count, 1)
            self.assertEqual(report.operations, ["insert"])
            self.assertEqual(len(user_memories), 1)
            self.assertEqual(user_memories[0].fact_key, "preference.response_style.table")
            self.assertEqual(user_memories[0].content, "Prefer table answers")

    def test_auto_assimilation_persists_structured_project_fact_once(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config = make_config(Path(temp_dir))
            service = ChatMemoryService(config)
            repository = MemoryRepository(config)
            context = MemoryRequestContext(
                request_id="req-auto-fact",
                tenant_id="t1",
                user_id="u1",
                project_id="p1",
                session_id="s1",
            )

            report = service.assimilate_turn(
                request_context=context,
                user_message="记住：stack.framework: FastAPI。现在告诉我启动命令。",
                assistant_result=ChatResult(
                    answer="ok",
                    citations=[],
                    retrieved_count=0,
                ),
                scene="onboarding",
            )

            project_memories = repository.list_by_filters(
                tenant_id="t1",
                scope_type="project",
                scope_id="p1",
                limit=10,
            )

            self.assertEqual(report.candidate_count, 1)
            self.assertEqual(len(project_memories), 1)
            self.assertEqual(project_memories[0].fact_key, "stack.framework")
            self.assertEqual(project_memories[0].content, "stack.framework: FastAPI")

    def test_auto_assimilation_merges_rule_and_llm_review_candidates(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config = make_config(Path(temp_dir))
            repository = MemoryRepository(config)

            class FakeReviewService:
                def review_turn(self, **kwargs):
                    return [
                        ChatMemoryCandidate(
                            content="default backend port: 8000",
                            memory_type="fact",
                            scope_type="project",
                            confirmed=False,
                            source_kind="memory_llm_review",
                            source_type="model_inferred",
                            source_confidence=0.93,
                            reviewed_by_human=False,
                            fact_key="env.default_backend_port",
                            origin="llm_review",
                        )
                    ]

            service = ChatMemoryService(config, llm_review_service=FakeReviewService())
            context = MemoryRequestContext(
                request_id="req-auto-hybrid",
                tenant_id="t1",
                user_id="u1",
                project_id="p1",
                session_id="s1",
            )

            report = service.assimilate_turn(
                request_context=context,
                user_message="Please answer in table format next time.",
                assistant_result=ChatResult(
                    answer="ok",
                    citations=[],
                    retrieved_count=0,
                ),
                scene="qa_query",
            )

            user_memories = repository.list_by_filters(
                tenant_id="t1",
                scope_type="user",
                scope_id="u1",
                limit=10,
            )
            project_memories = repository.list_by_filters(
                tenant_id="t1",
                scope_type="project",
                scope_id="p1",
                limit=10,
            )

            self.assertEqual(report.candidate_count, 2)
            self.assertEqual(report.rule_candidate_count, 1)
            self.assertEqual(report.llm_candidate_count, 1)
            self.assertEqual(report.failed_candidate_count, 0)
            self.assertEqual(len(user_memories), 1)
            self.assertEqual(user_memories[0].fact_key, "preference.response_style.table")
            self.assertEqual(len(project_memories), 1)
            self.assertEqual(project_memories[0].fact_key, "env.default_backend_port")

    def test_auto_assimilation_keeps_rule_write_when_llm_review_fails(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config = make_config(Path(temp_dir))
            repository = MemoryRepository(config)

            class BrokenReviewService:
                def review_turn(self, **kwargs):
                    raise RuntimeError("review failed")

            service = ChatMemoryService(config, llm_review_service=BrokenReviewService())
            context = MemoryRequestContext(
                request_id="req-auto-review-fail",
                tenant_id="t1",
                user_id="u1",
                project_id="p1",
                session_id="s1",
            )

            report = service.assimilate_turn(
                request_context=context,
                user_message="Please keep answers concise.",
                assistant_result=ChatResult(
                    answer="ok",
                    citations=[],
                    retrieved_count=0,
                ),
                scene="qa_query",
            )

            user_memories = repository.list_by_filters(
                tenant_id="t1",
                scope_type="user",
                scope_id="u1",
                limit=10,
            )

            self.assertEqual(report.candidate_count, 1)
            self.assertEqual(report.rule_candidate_count, 1)
            self.assertEqual(report.llm_candidate_count, 0)
            self.assertEqual(report.failed_candidate_count, 0)
            self.assertEqual(len(user_memories), 1)
            self.assertEqual(user_memories[0].fact_key, "preference.response_style.concise")


class ChatMemoryLLMReviewServiceTests(unittest.TestCase):
    def test_review_turn_normalizes_high_confidence_candidates(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config = make_config(Path(temp_dir))
            config.memory_llm_review_enabled = True

            response = SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        message=SimpleNamespace(
                            content=(
                                '{"candidates":['
                                '{"content":"Please be concise","memory_type":"preference","scope_type":"project",'
                                '"fact_key":"preference.response_style.concise","confidence":0.91},'
                                '{"content":"ignore me","memory_type":"fact","scope_type":"project","confidence":0.2}'
                                "]}"
                            )
                        )
                    )
                ]
            )
            client = SimpleNamespace(
                chat=SimpleNamespace(
                    completions=SimpleNamespace(create=lambda **kwargs: response)
                )
            )
            service = ChatMemoryLLMReviewService(config, client=client)
            context = MemoryRequestContext(
                request_id="req-llm-review",
                tenant_id="t1",
                user_id="u1",
                project_id="p1",
                session_id="s1",
            )

            candidates = service.review_turn(
                request_context=context,
                user_message="Please be concise when you answer later.",
                assistant_result=ChatResult(answer="ok", citations=[], retrieved_count=0),
                scene="qa_query",
                rule_candidates=[],
            )

            self.assertEqual(len(candidates), 1)
            self.assertEqual(candidates[0].memory_type, "preference")
            self.assertEqual(candidates[0].scope_type, "user")
            self.assertEqual(candidates[0].fact_key, "preference.response_style.concise")
            self.assertEqual(candidates[0].content, "Prefer concise answers")
            self.assertEqual(candidates[0].source_type, "model_inferred")
            self.assertEqual(candidates[0].origin, "llm_review")


class SessionPersistenceTests(unittest.TestCase):
    def test_message_repository_and_recovery_service_restore_recent_window(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config = make_config(Path(temp_dir))
            session_repository = SessionRepository(config)
            message_repository = MessageRepository(config)
            recovery_service = SessionRecoveryService(
                config,
                session_repository=session_repository,
                message_repository=message_repository,
            )
            context = MemoryRequestContext(
                request_id="req-session-recovery",
                tenant_id="t1",
                user_id="u1",
                project_id="p1",
                session_id="s1",
            )

            session_repository.ensure_session(context, "Persistent Session")
            for role, content in [
                ("user", "first user turn"),
                ("assistant", "first assistant turn"),
                ("user", "second user turn"),
                ("assistant", "second assistant turn"),
            ]:
                message_repository.create_message(
                    ChatMessageCreate(
                        tenant_id="t1",
                        session_id="s1",
                        user_id="u1",
                        role=role,
                        content=content,
                    )
                )

            snapshot = recovery_service.recover_session(context, message_limit=3)
            history = recovery_service.build_recent_chat_history(snapshot, message_limit=2)

            self.assertIsNotNone(snapshot.session)
            self.assertEqual(snapshot.session.title, "Persistent Session")
            self.assertTrue(snapshot.restored_from_persistence)
            self.assertEqual(
                [item.content for item in snapshot.messages],
                [
                    "first assistant turn",
                    "second user turn",
                    "second assistant turn",
                ],
            )
            self.assertEqual(
                history,
                [
                    {"role": "user", "content": "second user turn"},
                    {"role": "assistant", "content": "second assistant turn"},
                ],
            )

    def test_persistence_health_service_reports_layered_counts(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config = make_config(Path(temp_dir))
            session_repository = SessionRepository(config)
            message_repository = MessageRepository(config)
            memory_repository = MemoryRepository(config)
            inspector = PersistenceHealthService(config)
            context = MemoryRequestContext(
                request_id="req-inspect",
                tenant_id="t1",
                user_id="u1",
                project_id="p1",
                session_id="s-inspect",
            )

            session_repository.ensure_session(context, "Inspect Me")
            message_repository.create_message(
                ChatMessageCreate(
                    tenant_id="t1",
                    session_id="s-inspect",
                    user_id="u1",
                    role="user",
                    content="hello storage",
                )
            )
            memory_repository.create_memory_fact(
                MemoryFactCreate(
                    tenant_id="t1",
                    owner_user_id="u1",
                    project_id="p1",
                    scope_type="session",
                    scope_id="s-inspect",
                    type="fact",
                    content="Storage is layered",
                    source_session_id="s-inspect",
                )
            )

            report = inspector.inspect()

            self.assertEqual(report.table_status["chat_sessions"], True)
            self.assertEqual(report.table_status["chat_messages"], True)
            self.assertEqual(report.session_count, 1)
            self.assertEqual(report.message_count, 1)
            self.assertEqual(report.memory_count, 1)
            self.assertEqual(report.memory_count_by_scope["session"], 1)


if __name__ == "__main__":
    unittest.main()



