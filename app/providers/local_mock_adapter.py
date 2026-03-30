"""Deterministic local mock adapter for business orchestration tests."""

from __future__ import annotations

import re

from app.config import AppConfig
from app.llm import _build_local_answer
from app.providers.base import ProviderAdapter
from app.schemas import BusinessRequest, BusinessResponse, Citation, RetrievedChunk


COMMAND_PATTERN = re.compile(r"`([^`\n]+)`|(?:^|\s)((?:adb|python|pytest|npm|git|curl|ls|ps|netstat|ss)[^\n]*)")


class LocalMockAdapter(ProviderAdapter):
    """Local deterministic adapter used when no remote provider is available."""

    provider_name = "local_mock"

    def __init__(self, config: AppConfig) -> None:
        self.model_name = config.llm_model or "local-mock-v1"

    def generate(self, request: BusinessRequest) -> BusinessResponse:
        retrieved_chunks = [
            RetrievedChunk(
                document_id=item.document_id,
                file_name=item.file_name,
                source_path=item.source_path,
                relative_path=item.relative_path,
                text=item.content,
                score=item.score,
                theme=item.theme,
                tags=item.tags,
            )
            for item in request.knowledge_context
        ]
        answer = _build_local_answer(request.user_query, retrieved_chunks)
        if request.memory_context:
            memory_summary = "；".join(item.content for item in request.memory_context[:2])
            answer = f"记忆上下文：{memory_summary}\n\n{answer}"

        citation_items = request.knowledge_context[:2] if request.output_contract.must_include_citations else []
        citations = [_build_citation(item) for item in citation_items]
        used_knowledge_ids = [item.knowledge_id for item in citation_items]
        used_memory_ids = [item.memory_id for item in request.memory_context]
        steps = _build_scene_steps(request)
        summary = _build_summary(answer)

        return BusinessResponse(
            answer=answer,
            citations=citations,
            confidence=0.66 if request.knowledge_context else 0.18,
            used_memory_ids=used_memory_ids,
            used_knowledge_ids=used_knowledge_ids,
            provider=self.provider_name,
            model=self.model_name,
            summary=summary,
            steps=steps,
            raw_response={
                "mode": "local_mock",
                "scene": request.scene,
                "knowledge_count": len(request.knowledge_context),
                "memory_count": len(request.memory_context),
            },
        )


def _build_citation(item) -> Citation:
    compact_text = " ".join(item.content.split())
    return Citation(
        knowledge_id=item.knowledge_id,
        document_id=item.document_id,
        file_name=item.file_name,
        source_path=item.source_path,
        relative_path=item.relative_path,
        snippet=compact_text[:220] + ("..." if len(compact_text) > 220 else ""),
        full_text=compact_text[:1200] + ("..." if len(compact_text) > 1200 else ""),
        score=item.score,
        theme=item.theme,
        tags=list(item.tags),
    )


def _build_summary(answer: str) -> str:
    normalized_lines = [line.strip() for line in answer.splitlines() if line.strip()]
    return normalized_lines[0] if normalized_lines else "未生成有效摘要。"


def _build_scene_steps(request: BusinessRequest) -> list[str]:
    if request.scene == "troubleshooting":
        return [
            "先确认问题复现范围和最近变更。",
            "根据知识库片段逐项核对配置、日志和依赖。",
            "如果现有证据不足，补充报错信息、执行环境和复现步骤。",
        ]
    if request.scene == "onboarding":
        return [
            "先阅读被引用的基础文档，建立术语和流程共识。",
            "按顺序执行文中的步骤，并记录每一步的输入与结果。",
            "遇到差异时回到知识库原文确认，不直接凭经验修改流程。",
        ]
    if request.scene == "command_lookup":
        commands = _extract_commands(request)
        if commands:
            return [f"可优先尝试：{command}" for command in commands[:3]]
        return [
            "先确认命令适用的操作系统和运行环境。",
            "执行前核对参数含义，避免直接在生产环境操作。",
        ]
    return [
        "优先根据知识库证据得出结论。",
        "如果证据不足，明确标注需要补充的信息。",
    ]


def _extract_commands(request: BusinessRequest) -> list[str]:
    commands: list[str] = []
    seen: set[str] = set()
    for item in request.knowledge_context:
        for match in COMMAND_PATTERN.finditer(item.content):
            candidate = next((group.strip() for group in match.groups() if group), "")
            if not candidate or candidate in seen:
                continue
            seen.add(candidate)
            commands.append(candidate)
    return commands
