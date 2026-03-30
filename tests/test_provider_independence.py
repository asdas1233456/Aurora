import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.config import AppConfig
from app.providers.factory import ProviderFactory
from app.providers.local_mock_adapter import LocalMockAdapter
from app.providers.openai_compatible_adapter import OpenAICompatibleAdapter
from app.providers.registry import ProviderRegistry, build_default_provider_registry
from app.providers.router import ProviderRouter
from app.schemas import (
    BusinessRequest,
    BusinessResponse,
    Citation,
    ConversationTurn,
    GenerationConfig,
    KnowledgeContextItem,
    MemoryContextItem,
    MemoryFact,
    RetrievedChunk,
)
from app.services.abuse_guard import AbuseGuard
from app.services.capability_guard import ResponseNormalizer, build_output_contract, build_system_instruction
from app.services.rag_service import answer_with_rag, build_business_request


def make_config(
    base_dir: Path,
    *,
    llm_provider: str = "openai",
    llm_api_key: str = "sk-test",
    llm_api_base: str = "",
    embedding_api_key: str = "sk-embed",
) -> AppConfig:
    AbuseGuard.reset_all()
    return AppConfig(
        base_dir=base_dir,
        data_dir=base_dir / "data",
        db_dir=base_dir / "db",
        logs_dir=base_dir / "logs",
        llm_provider=llm_provider,
        embedding_provider="openai",
        llm_api_key=llm_api_key,
        llm_api_base=llm_api_base,
        embedding_api_key=embedding_api_key,
        llm_model="gpt-4.1-mini",
        embedding_model="text-embedding-3-small",
        collection_name="test_collection",
        memory_llm_review_enabled=False,
    )


class ProviderIndependenceTests(unittest.TestCase):
    def test_provider_registry_maps_openai_compatible_providers_to_shared_adapter(self):
        registry = build_default_provider_registry()

        self.assertIs(registry.resolve("openai"), OpenAICompatibleAdapter)
        self.assertIs(registry.resolve("deepseek"), OpenAICompatibleAdapter)
        self.assertIs(registry.resolve("qwen"), OpenAICompatibleAdapter)
        self.assertIs(registry.resolve("local_mock"), LocalMockAdapter)

    def test_provider_factory_uses_registry_and_creates_openai_compatible_adapter(self):
        config = make_config(
            Path(tempfile.mkdtemp()),
            llm_provider="deepseek",
            llm_api_base="https://api.example.com/v1",
        )

        adapter = ProviderFactory(config).create()

        self.assertIsInstance(adapter, OpenAICompatibleAdapter)

    def test_provider_registry_supports_custom_provider_registration(self):
        registry = ProviderRegistry()
        registry.register("local_mock", LocalMockAdapter, aliases=("offline_demo",))

        self.assertTrue(registry.supports("offline_demo"))
        self.assertIs(registry.resolve("offline_demo"), LocalMockAdapter)

    def test_provider_router_falls_back_to_local_mock_when_llm_not_ready(self):
        config = make_config(Path(tempfile.mkdtemp()), llm_api_key="")

        adapter = ProviderRouter(config).resolve()

        self.assertIsInstance(adapter, LocalMockAdapter)

    def test_response_normalizer_removes_invalid_citations_and_anchors_to_knowledge_context(self):
        request = BusinessRequest(
            scene="qa_query",
            user_query="What is the expected command?",
            system_instruction=build_system_instruction("qa_query"),
            conversation_context=[ConversationTurn(role="user", content="What is the expected command?")],
            memory_context=[],
            knowledge_context=[
                KnowledgeContextItem(
                    knowledge_id="kb-1",
                    document_id="doc-1",
                    file_name="commands.md",
                    source_path="commands.md",
                    relative_path="commands.md",
                    content="Use `pytest -q` to run the test subset.",
                    score=0.91,
                )
            ],
            output_contract=build_output_contract("qa_query"),
            safety_rules=["Do not fabricate citations."],
            generation_config=GenerationConfig(),
        )
        raw_response = BusinessResponse(
            answer="Run pytest in quiet mode.",
            citations=[
                Citation(
                    knowledge_id="ghost",
                    document_id="ghost-doc",
                    file_name="ghost.md",
                    source_path="ghost.md",
                    relative_path="ghost.md",
                    snippet="ghost",
                    full_text="ghost",
                    score=0.2,
                )
            ],
            confidence=0.5,
            used_memory_ids=[],
            used_knowledge_ids=["ghost"],
            provider="local_mock",
            model="mock-v1",
        )

        normalized = ResponseNormalizer().normalize(request, raw_response)

        self.assertEqual([item.knowledge_id for item in normalized.citations], ["kb-1"])
        self.assertEqual(normalized.used_knowledge_ids, ["kb-1"])
        self.assertIsNotNone(normalized.error_info)
        self.assertIn("ghost", normalized.error_info.details["invalid_citation_ids"])

    def test_build_business_request_keeps_memory_and_knowledge_context_separate(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config = make_config(Path(temp_dir))
            memory_fact = MemoryFact(
                id="mem-1",
                tenant_id="t1",
                owner_user_id="u1",
                project_id="p1",
                scope_type="project",
                scope_id="p1",
                type="decision",
                content="Project prefers structured troubleshooting answers.",
                status="active",
                source_session_id="s1",
                created_at="2026-03-30T00:00:00+00:00",
                updated_at="2026-03-30T00:00:00+00:00",
            )
            retrieved_chunk = RetrievedChunk(
                document_id="doc-1",
                file_name="troubleshooting.md",
                source_path="troubleshooting.md",
                relative_path="troubleshooting.md",
                text="Check logs first, then inspect environment drift.",
                score=0.88,
            )

            request = build_business_request(
                question="How should we troubleshoot flaky tests?",
                chat_history=[{"role": "user", "content": "How should we troubleshoot flaky tests?"}],
                retrieved_chunks=[retrieved_chunk],
                memory_facts=[memory_fact],
                config=config,
                retrieval_query="troubleshoot flaky tests",
                rewritten_question="",
                scene="troubleshooting",
                requested_top_k=None,
            )

        self.assertEqual(request.scene, "troubleshooting")
        self.assertEqual([item.memory_id for item in request.memory_context], ["mem-1"])
        self.assertEqual([item.knowledge_id for item in request.knowledge_context], ["kb-1"])
        self.assertEqual(request.memory_context[0].content, memory_fact.content)
        self.assertEqual(request.knowledge_context[0].content, retrieved_chunk.text)
        self.assertIn("steps", request.output_contract.required_sections)

    def test_answer_with_rag_formats_troubleshooting_scene_consistently(self):
        config = make_config(Path(tempfile.mkdtemp()), llm_api_key="")
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
                            text="Use logs and process checks to isolate the failing service.",
                            score=0.87,
                        )
                    ],
                    "service troubleshooting",
                    "",
                ),
            ):
                result = answer_with_rag(
                    "服务异常时怎么排查？",
                    [],
                    config,
                    scene="troubleshooting",
                )
        finally:
            pass

        self.assertIn("可能原因：", result.answer)
        self.assertIn("排查步骤：", result.answer)
        self.assertEqual(result.provider, "local_mock")


if __name__ == "__main__":
    unittest.main()
