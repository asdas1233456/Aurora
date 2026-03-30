"""Business capability guardrails for provider-independent chat output."""

from __future__ import annotations

from collections import OrderedDict
import logging
import math

from app.providers.base import ProviderAdapter
from app.schemas import (
    BusinessErrorInfo,
    BusinessRequest,
    BusinessResponse,
    BusinessScene,
    Citation,
    KnowledgeContextItem,
    OutputContract,
)


logger = logging.getLogger(__name__)

SCENE_RULES: dict[BusinessScene, dict[str, object]] = {
    "qa_query": {
        "required_sections": ["answer", "citations"],
        "scene_specific_rules": [
            "Lead with the conclusion first.",
            "Support the conclusion with knowledge citations when available.",
            "Do not present memory context as formal evidence.",
        ],
        "instruction": (
            "Aurora is a local knowledge workbench for software testing teams. "
            "Provide clear conclusions for test knowledge questions and keep answers evidence-based."
        ),
        "fallback_message": "根据当前知识库证据，我还无法稳定确认这个问题的结论。",
    },
    "troubleshooting": {
        "required_sections": ["answer", "steps"],
        "scene_specific_rules": [
            "Prioritize likely causes before detailed explanation.",
            "Provide ordered troubleshooting steps.",
            "Say what extra context is required if the evidence is insufficient.",
        ],
        "instruction": (
            "Aurora is troubleshooting software testing systems and workflows. "
            "Keep the output operational, structured, and safe for incident triage."
        ),
        "fallback_message": "现有知识片段不足以稳定定位原因，请补充报错信息、运行环境和复现步骤。",
    },
    "onboarding": {
        "required_sections": ["answer", "steps", "citations"],
        "scene_specific_rules": [
            "Prefer step-by-step guidance.",
            "Include document references that a new teammate can open directly.",
            "Keep recommendations executable for newcomers.",
        ],
        "instruction": (
            "Aurora is onboarding software testing teammates. "
            "Keep the response easy to execute, explicit, and linked to source documentation."
        ),
        "fallback_message": "当前资料不足以给出完整上手方案，请补充目标系统、角色边界或相关文档。",
    },
    "command_lookup": {
        "required_sections": ["answer", "steps", "citations"],
        "scene_specific_rules": [
            "State the command or command family first.",
            "Explain important parameters or prerequisites.",
            "Include usage cautions and applicable scenarios.",
        ],
        "instruction": (
            "Aurora is answering command lookup questions for software testing teams. "
            "Keep commands explicit and include safe-usage notes."
        ),
        "fallback_message": "当前知识库没有足够证据确认这条命令或参数说明，请补充目标环境和执行目的。",
    },
}


class OutputContractValidator:
    """Validates response citations against the supplied knowledge context."""

    def validate(
        self,
        request: BusinessRequest,
        response: BusinessResponse,
    ) -> tuple[list[Citation], list[str], list[str], list[str]]:
        # Aurora-owned knowledge ids are the source of truth; provider-declared citations are treated as claims.
        knowledge_by_id = {item.knowledge_id: item for item in request.knowledge_context}
        knowledge_by_source = {item.source_path: item for item in request.knowledge_context}
        knowledge_by_document = {item.document_id: item for item in request.knowledge_context}
        valid_by_id: OrderedDict[str, Citation] = OrderedDict()
        invalid_ids: list[str] = []

        for citation in response.citations:
            knowledge_item = None
            if citation.knowledge_id:
                knowledge_item = knowledge_by_id.get(citation.knowledge_id)
            if knowledge_item is None and citation.source_path:
                knowledge_item = knowledge_by_source.get(citation.source_path)
            if knowledge_item is None and citation.document_id:
                knowledge_item = knowledge_by_document.get(citation.document_id)
            if knowledge_item is None:
                invalid_ids.append(citation.knowledge_id or citation.document_id or citation.source_path)
                continue
            valid_by_id[knowledge_item.knowledge_id] = _citation_from_knowledge_item(knowledge_item)

        for knowledge_id in response.used_knowledge_ids:
            knowledge_item = knowledge_by_id.get(knowledge_id)
            if knowledge_item is None:
                invalid_ids.append(knowledge_id)
                continue
            valid_by_id[knowledge_item.knowledge_id] = _citation_from_knowledge_item(knowledge_item)

        if (
            request.output_contract.must_include_citations
            and not valid_by_id
            and request.knowledge_context
            and not _looks_like_insufficient_answer(response.answer)
        ):
            # If the provider answered confidently but skipped citations, attach the top evidence deterministically.
            for item in request.knowledge_context[:2]:
                valid_by_id[item.knowledge_id] = _citation_from_knowledge_item(item)

        valid_memory_ids = [
            memory_id
            for memory_id in response.used_memory_ids
            if memory_id in {item.memory_id for item in request.memory_context}
        ]
        valid_knowledge_ids = list(valid_by_id.keys())
        return list(valid_by_id.values()), valid_knowledge_ids, valid_memory_ids, invalid_ids


class ResponseNormalizer:
    """Normalizes scene output so upstream business behavior stays stable."""

    def __init__(self, validator: OutputContractValidator | None = None) -> None:
        self.validator = validator or OutputContractValidator()

    def normalize(self, request: BusinessRequest, response: BusinessResponse) -> BusinessResponse:
        citations, used_knowledge_ids, used_memory_ids, invalid_citation_ids = self.validator.validate(
            request,
            response,
        )
        summary = _clean_text(response.summary) or _derive_summary(response.answer)
        steps = _normalize_steps(response.steps, request.scene)
        answer = _clean_text(response.answer)

        citation_required = request.output_contract.must_include_citations
        if not answer or (citation_required and not citations and request.knowledge_context):
            answer = _scene_fallback_message(request.scene)
            summary = summary or answer
            if not steps:
                steps = _default_steps(request.scene)

        formatted_answer = _format_scene_answer(
            scene=request.scene,
            summary=summary or answer,
            answer=answer,
            steps=steps,
            citations=citations,
        )

        error_info = response.error_info
        if invalid_citation_ids:
            details = dict(error_info.details) if error_info else {}
            details["invalid_citation_ids"] = invalid_citation_ids
            error_info = BusinessErrorInfo(
                code=error_info.code if error_info else "citations_normalized",
                message=error_info.message if error_info else "Some provider citations were removed during validation.",
                retryable=error_info.retryable if error_info else False,
                details=details,
            )

        return BusinessResponse(
            answer=formatted_answer,
            citations=citations,
            confidence=_normalize_confidence(response.confidence),
            used_memory_ids=used_memory_ids,
            used_knowledge_ids=used_knowledge_ids,
            provider=response.provider,
            model=response.model,
            summary=summary or answer,
            steps=steps,
            raw_response=response.raw_response,
            error_info=error_info,
        )


class CapabilityGuard:
    """Runs provider generation behind a stable Aurora capability contract."""

    def __init__(self, normalizer: ResponseNormalizer | None = None) -> None:
        self.normalizer = normalizer or ResponseNormalizer()

    def generate(self, adapter: ProviderAdapter, request: BusinessRequest) -> BusinessResponse:
        try:
            response = adapter.generate(request)
        except Exception as exc:
            logger.exception("Provider generation failed for scene=%s.", request.scene)
            response = _build_fallback_response(
                request=request,
                provider=getattr(adapter, "provider_name", "unknown"),
                model=getattr(adapter, "model_name", ""),
                error_info=BusinessErrorInfo(
                    code="provider_generation_failed",
                    message="Provider generation failed; Aurora returned a controlled fallback response.",
                    retryable=True,
                    details={"exception_type": exc.__class__.__name__},
                ),
            )

        if _is_low_quality_response(response):
            # Empty or low-signal model output is normalized into the same fallback path as hard provider failures.
            response = _build_fallback_response(
                request=request,
                provider=response.provider or getattr(adapter, "provider_name", "unknown"),
                model=response.model or getattr(adapter, "model_name", ""),
                error_info=BusinessErrorInfo(
                    code="low_quality_response",
                    message="Provider returned an empty or low-quality response; Aurora used a fallback response.",
                ),
            )

        return self.normalizer.normalize(request, response)


def infer_scene(question: str) -> BusinessScene:
    normalized = str(question or "").strip().lower()
    if any(marker in normalized for marker in ("command", "命令", "参数", "adb", "curl", "pytest", "npm", "git ")):
        return "command_lookup"
    if any(marker in normalized for marker in ("排查", "故障", "异常", "报错", "失败", "定位", "修复", "troubleshoot", "error")):
        return "troubleshooting"
    if any(marker in normalized for marker in ("上手", "入门", "新人", "onboarding", "开始", "接手")):
        return "onboarding"
    return "qa_query"


def build_output_contract(scene: BusinessScene) -> OutputContract:
    rule = SCENE_RULES[scene]
    preferred_style = "step_by_step" if scene in {"troubleshooting", "onboarding"} else "structured"
    return OutputContract(
        must_include_answer=True,
        must_include_citations=scene in {"qa_query", "onboarding", "command_lookup"},
        preferred_style=preferred_style,
        fallback_behavior="say_insufficient_context",
        required_sections=list(rule["required_sections"]),
        scene_specific_rules=list(rule["scene_specific_rules"]),
        refusal_behavior="acknowledge_limits_without_fabrication",
    )


def build_system_instruction(scene: BusinessScene) -> str:
    return str(SCENE_RULES[scene]["instruction"])


def chunk_text(text: str, chunk_size: int = 48):
    for start in range(0, len(text), chunk_size):
        yield text[start : start + chunk_size]


def _is_low_quality_response(response: BusinessResponse) -> bool:
    answer = _clean_text(response.answer)
    if not answer:
        return True
    return len(answer) < 6 and not response.citations


def _build_fallback_response(
    *,
    request: BusinessRequest,
    provider: str,
    model: str,
    error_info: BusinessErrorInfo,
) -> BusinessResponse:
    summary = _scene_fallback_message(request.scene)
    steps = _default_steps(request.scene)
    citations = []
    used_knowledge_ids: list[str] = []
    if request.output_contract.must_include_citations and request.knowledge_context:
        citations = [_citation_from_knowledge_item(item) for item in request.knowledge_context[:1]]
        used_knowledge_ids = [item.knowledge_id for item in request.knowledge_context[:1]]

    return BusinessResponse(
        answer=summary,
        citations=citations,
        confidence=0.0,
        used_memory_ids=[],
        used_knowledge_ids=used_knowledge_ids,
        provider=provider,
        model=model,
        summary=summary,
        steps=steps,
        error_info=error_info,
    )


def _citation_from_knowledge_item(item: KnowledgeContextItem) -> Citation:
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


def _scene_fallback_message(scene: BusinessScene) -> str:
    return str(SCENE_RULES[scene]["fallback_message"])


def _normalize_confidence(value: float) -> float:
    if math.isnan(value) or math.isinf(value):
        return 0.0
    return max(0.0, min(1.0, float(value)))


def _clean_text(text: str) -> str:
    return str(text or "").strip()


def _derive_summary(answer: str) -> str:
    normalized_lines = [line.strip(" -") for line in str(answer or "").splitlines() if line.strip()]
    return normalized_lines[0] if normalized_lines else ""


def _normalize_steps(steps: list[str], scene: BusinessScene) -> list[str]:
    cleaned = [str(item).strip() for item in steps if str(item).strip()]
    deduplicated: list[str] = []
    seen: set[str] = set()
    for item in cleaned:
        if item in seen:
            continue
        seen.add(item)
        deduplicated.append(item)
    return deduplicated or _default_steps(scene)


def _default_steps(scene: BusinessScene) -> list[str]:
    if scene == "troubleshooting":
        return [
            "确认问题是否稳定复现，以及影响范围。",
            "补充日志、错误信息、环境版本和最近变更。",
            "回到知识库和会话上下文重新核对证据。",
        ]
    if scene == "onboarding":
        return [
            "先阅读被引用文档，确认术语和流程。",
            "按顺序执行步骤并记录每一步结果。",
            "遇到差异时回到原文核对，不直接猜测。",
        ]
    if scene == "command_lookup":
        return [
            "执行前确认命令适用环境和权限边界。",
            "先理解参数含义，再在安全环境中验证。",
        ]
    return [
        "先核对当前知识库证据。",
        "如果结论仍不充分，补充更具体的问题上下文。",
    ]


def _format_scene_answer(
    *,
    scene: BusinessScene,
    summary: str,
    answer: str,
    steps: list[str],
    citations: list[Citation],
) -> str:
    if scene == "qa_query":
        lines = [
            "结论：",
            summary or answer,
        ]
        if answer and answer != summary:
            lines.extend(["", "说明：", answer])
        lines.extend(["", "引用："])
        if citations:
            lines.extend(
                f"- [{item.knowledge_id}] {item.file_name}"
                for item in citations
            )
        else:
            lines.append("- 当前没有足够可核对的知识库引用。")
        return "\n".join(lines)

    if scene == "troubleshooting":
        return "\n".join(
            [
                "可能原因：",
                summary or answer,
                "",
                "排查步骤：",
                *[f"{index}. {item}" for index, item in enumerate(steps, start=1)],
                "",
                "还需上下文：",
                "如仍无法定位，请补充报错日志、环境信息和复现步骤。",
            ]
        )

    if scene == "onboarding":
        lines = [
            "步骤说明：",
            *[f"{index}. {item}" for index, item in enumerate(steps, start=1)],
            "",
            "相关文档：",
        ]
        if citations:
            lines.extend(f"- [{item.knowledge_id}] {item.file_name}" for item in citations)
        else:
            lines.append("- 当前没有可直接引用的文档。")
        lines.extend(
            [
                "",
                "新人建议：",
                summary or answer,
            ]
        )
        return "\n".join(lines)

    lines = [
        "命令建议：",
        summary or answer,
        "",
        "参数说明：",
        *[f"- {item}" for item in steps],
        "",
        "使用注意：",
        "执行前确认命令适用环境、参数含义和权限边界。",
        "",
        "适用场景：",
    ]
    if citations:
        lines.extend(f"- [{item.knowledge_id}] {item.file_name}" for item in citations)
    else:
        lines.append("- 当前没有可直接引用的知识片段。")
    return "\n".join(lines)


def _looks_like_insufficient_answer(answer: str) -> bool:
    normalized = str(answer or "").strip().lower()
    return any(
        marker in normalized
        for marker in ("不足", "无法确认", "不确定", "insufficient", "not enough", "cannot confirm")
    )
