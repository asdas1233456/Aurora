"""OpenAI-compatible adapter that maps Aurora business contracts to chat completions."""

from __future__ import annotations

import json
import re
from typing import Any

from openai import OpenAI

from app.config import AppConfig
from app.providers.base import ProviderAdapter
from app.schemas import BusinessRequest, BusinessResponse


JSON_BLOCK_PATTERN = re.compile(r"```(?:json)?\s*(\{.*\})\s*```", re.DOTALL)


class OpenAICompatibleAdapter(ProviderAdapter):
    """Adapter for providers that speak the OpenAI-compatible chat protocol."""

    def __init__(self, config: AppConfig) -> None:
        if not config.llm_api_ready:
            raise ValueError(
                "LLM API configuration is incomplete. Please check provider, key, base URL, and model."
            )

        client_kwargs: dict[str, object] = {
            "api_key": config.llm_api_key_for_client,
            "timeout": config.llm_timeout,
        }
        if config.llm_api_base:
            client_kwargs["base_url"] = config.llm_api_base

        self.client = OpenAI(**client_kwargs)
        self.provider_name = config.llm_provider
        self.model_name = config.llm_model
        self.temperature = config.llm_temperature
        self.max_tokens = config.llm_max_tokens

    def generate(self, request: BusinessRequest) -> BusinessResponse:
        response = self.client.chat.completions.create(
            model=self.model_name,
            temperature=request.generation_config.temperature,
            max_tokens=request.generation_config.max_tokens,
            messages=[
                {"role": "system", "content": _build_system_message(request)},
                {"role": "user", "content": _build_user_message(request)},
            ],
        )
        # Compatible providers may wrap the contract JSON in markdown or extra prose, so parse defensively.
        content = _extract_content_text(response.choices[0].message.content if response.choices else "")
        payload = _parse_payload(content)

        answer = _coerce_text(payload.get("answer")) or content.strip()
        summary = _coerce_text(payload.get("summary"))
        steps = _coerce_string_list(payload.get("steps"))
        cited_ids = _coerce_citation_ids(payload.get("citations"))
        used_memory_ids = _coerce_string_list(payload.get("used_memory_ids"))
        confidence = _coerce_confidence(payload.get("confidence"))

        return BusinessResponse(
            answer=answer,
            citations=[],
            confidence=confidence,
            used_memory_ids=used_memory_ids,
            used_knowledge_ids=cited_ids,
            provider=self.provider_name,
            model=self.model_name,
            summary=summary,
            steps=steps,
            raw_response={
                "provider_content": content,
                "finish_reason": getattr(response.choices[0], "finish_reason", "") if response.choices else "",
                "response_id": getattr(response, "id", ""),
            },
        )


def _build_system_message(request: BusinessRequest) -> str:
    contract = request.output_contract
    rules = "\n".join(f"- {rule}" for rule in request.safety_rules)
    return (
        f"{request.system_instruction}\n\n"
        "You are producing Aurora business output for a software testing team.\n"
        "Memory context is background context only; it is not knowledge evidence.\n"
        "Knowledge context is the only source that may be cited.\n"
        "Never fabricate a citation or a knowledge id.\n"
        "If the knowledge evidence is insufficient, say so explicitly.\n"
        "Return a JSON object only.\n"
        "The JSON schema is:\n"
        "{"
        '"answer": "string", '
        '"summary": "string", '
        '"steps": ["string"], '
        '"citations": ["knowledge_id"], '
        '"used_memory_ids": ["memory_id"], '
        '"confidence": 0.0'
        "}\n"
        f"Preferred style: {contract.preferred_style}\n"
        f"Must include answer: {str(contract.must_include_answer).lower()}\n"
        f"Must include citations: {str(contract.must_include_citations).lower()}\n"
        f"Fallback behavior: {contract.fallback_behavior}\n"
        f"Refusal behavior: {contract.refusal_behavior}\n"
        "Safety rules:\n"
        f"{rules or '- None'}"
    )


def _build_user_message(request: BusinessRequest) -> str:
    required_sections = ", ".join(request.output_contract.required_sections) or "answer"
    scene_rules = "\n".join(f"- {rule}" for rule in request.output_contract.scene_specific_rules)
    return (
        f"Scene: {request.scene}\n"
        f"User query: {request.user_query}\n\n"
        "[Conversation Context]\n"
        f"{_format_conversation(request)}\n\n"
        "[Memory Context]\n"
        f"{_format_memory(request)}\n\n"
        "[Knowledge Context]\n"
        f"{_format_knowledge(request)}\n\n"
        "[Output Contract]\n"
        f"Required sections: {required_sections}\n"
        f"Scene-specific rules:\n{scene_rules or '- None'}\n\n"
        "Important reminders:\n"
        "- Use knowledge ids from the Knowledge Context block when citing.\n"
        "- Do not cite memory ids as evidence.\n"
        "- If evidence is weak or missing, answer conservatively.\n"
        "- Keep the JSON compact and valid."
    )


def _format_conversation(request: BusinessRequest) -> str:
    if not request.conversation_context:
        return "(empty)"
    return "\n".join(
        f"[{item.role}] {item.content.strip()}"
        for item in request.conversation_context
        if item.content.strip()
    ) or "(empty)"


def _format_memory(request: BusinessRequest) -> str:
    if not request.memory_context:
        return "(none)"
    return "\n".join(
        f"[{item.memory_id}] scope={item.scope_type}:{item.scope_id} type={item.memory_type} content={item.content}"
        for item in request.memory_context
    )


def _format_knowledge(request: BusinessRequest) -> str:
    if not request.knowledge_context:
        return "(none)"
    return "\n\n".join(
        (
            f"[{item.knowledge_id}] file={item.file_name} path={item.relative_path} "
            f"page={item.page_number or 'na'} chunk={item.chunk_id or 'na'} score={item.score}\n"
            f"{item.content}"
        )
        for item in request.knowledge_context
    )


def _extract_content_text(content: Any) -> str:
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            text = getattr(item, "text", None)
            if text:
                parts.append(str(text))
                continue
            if isinstance(item, dict) and item.get("text"):
                parts.append(str(item["text"]))
        return "\n".join(parts).strip()
    return str(content or "").strip()


def _parse_payload(content: str) -> dict[str, Any]:
    normalized = content.strip()
    if not normalized:
        return {}

    candidates = [normalized]
    block_match = JSON_BLOCK_PATTERN.search(normalized)
    if block_match:
        candidates.insert(0, block_match.group(1).strip())

    left = normalized.find("{")
    right = normalized.rfind("}")
    if left != -1 and right != -1 and left < right:
        candidates.append(normalized[left : right + 1])

    for candidate in candidates:
        try:
            loaded = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(loaded, dict):
            return loaded

    return {}


def _coerce_text(value: Any) -> str:
    return str(value or "").strip()


def _coerce_string_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    return []


def _coerce_citation_ids(value: Any) -> list[str]:
    citation_ids: list[str] = []
    if not isinstance(value, list):
        return citation_ids
    for item in value:
        if isinstance(item, str) and item.strip():
            citation_ids.append(item.strip())
            continue
        if isinstance(item, dict):
            knowledge_id = str(item.get("knowledge_id") or item.get("id") or "").strip()
            if knowledge_id:
                citation_ids.append(knowledge_id)
    return citation_ids


def _coerce_confidence(value: Any) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, min(1.0, number))
