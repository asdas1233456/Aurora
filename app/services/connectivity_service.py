"""Provider-aware connectivity checks built on Aurora business contracts."""

from __future__ import annotations

from datetime import datetime
import time

from app.providers.factory import ProviderFactory
from app.schemas import (
    BusinessRequest,
    ConversationTurn,
    GenerationConfig,
    OutputContract,
    SettingsConnectionReport,
    ConnectionCheckResult,
)
from app.config import AppConfig
from app.services.capability_guard import CapabilityGuard
from app.services.knowledge_base_service import build_embedding_model
from app.services.settings_service import build_config_from_settings_values, validate_app_settings


def test_settings_connections(
    config: AppConfig,
    values: dict[str, object],
) -> SettingsConnectionReport:
    runtime_config = build_config_from_settings_values(config, values)
    merged_values = {
        "LLM_PROVIDER": runtime_config.llm_provider,
        "EMBEDDING_PROVIDER": runtime_config.embedding_provider,
        "LLM_API_KEY": runtime_config.llm_api_key,
        "LLM_API_BASE": runtime_config.llm_api_base,
        "LLM_MODEL": runtime_config.llm_model,
        "LLM_TEMPERATURE": str(runtime_config.llm_temperature),
        "LLM_TIMEOUT": str(runtime_config.llm_timeout),
        "LLM_MAX_TOKENS": str(runtime_config.llm_max_tokens),
        "EMBEDDING_API_KEY": runtime_config.embedding_api_key,
        "EMBEDDING_API_BASE": runtime_config.embedding_api_base,
        "EMBEDDING_MODEL": runtime_config.embedding_model,
        "CHUNK_SIZE": str(runtime_config.chunk_size),
        "CHUNK_OVERLAP": str(runtime_config.chunk_overlap),
        "TOP_K": str(runtime_config.default_top_k),
        "MAX_HISTORY_TURNS": str(runtime_config.max_history_turns),
        "NO_ANSWER_MIN_SCORE": str(runtime_config.no_answer_min_score),
        "CHROMA_COLLECTION_NAME": runtime_config.collection_name,
        "LOG_LEVEL": runtime_config.log_level,
        "API_HOST": runtime_config.api_host,
        "API_PORT": str(runtime_config.api_port),
        "CORS_ORIGINS": runtime_config.cors_origins,
    }
    validation_errors = validate_app_settings(merged_values)
    if validation_errors:
        failed_result = ConnectionCheckResult(
            ok=False,
            latency_ms=0.0,
            message="配置校验失败，请先修正错误字段。",
        )
        return SettingsConnectionReport(
            llm=failed_result,
            embedding=failed_result,
            checked_at=_now_text(),
        )

    return SettingsConnectionReport(
        llm=_test_llm(runtime_config),
        embedding=_test_embedding(runtime_config),
        checked_at=_now_text(),
    )


def _test_llm(config: AppConfig) -> ConnectionCheckResult:
    started_at = time.perf_counter()
    try:
        adapter = ProviderFactory(config).create()
        request = BusinessRequest(
            scene="qa_query",
            user_query="Reply with pong.",
            system_instruction="You are a connection test.",
            conversation_context=[ConversationTurn(role="user", content="Reply with pong.")],
            memory_context=[],
            knowledge_context=[],
            output_contract=OutputContract(
                must_include_answer=True,
                must_include_citations=False,
                preferred_style="concise",
                fallback_behavior="best_effort",
                required_sections=["answer"],
                scene_specific_rules=["Return a short connection test response."],
            ),
            safety_rules=["Return a short answer.", "Do not fabricate citations."],
            generation_config=GenerationConfig(
                temperature=0.0,
                max_tokens=min(config.llm_max_tokens, 32),
                timeout_seconds=config.llm_timeout,
            ),
        )
        response = CapabilityGuard().generate(adapter, request)
        latency_ms = (time.perf_counter() - started_at) * 1000
        if response.answer:
            return ConnectionCheckResult(ok=True, latency_ms=latency_ms, message="LLM 连通性测试成功。")
        return ConnectionCheckResult(ok=False, latency_ms=latency_ms, message="LLM 连通性测试失败：返回空响应。")
    except Exception as exc:
        latency_ms = (time.perf_counter() - started_at) * 1000
        return ConnectionCheckResult(ok=False, latency_ms=latency_ms, message=f"LLM 连通性测试失败：{exc}")


def _test_embedding(config: AppConfig) -> ConnectionCheckResult:
    started_at = time.perf_counter()
    try:
        embed_model = build_embedding_model(config)
        embed_model.get_text_embedding_batch(["aurora connectivity check"], show_progress=False)
        latency_ms = (time.perf_counter() - started_at) * 1000
        return ConnectionCheckResult(ok=True, latency_ms=latency_ms, message="Embedding 连通性测试成功。")
    except Exception as exc:
        latency_ms = (time.perf_counter() - started_at) * 1000
        return ConnectionCheckResult(ok=False, latency_ms=latency_ms, message=f"Embedding 连通性测试失败：{exc}")


def _now_text() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")
