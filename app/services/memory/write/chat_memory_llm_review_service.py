"""LLM-reviewed memory extraction for backend-only chat assimilation."""

from __future__ import annotations

import json
import re
from typing import Any

from openai import OpenAI

from app.config import AppConfig, is_local_mock_provider
from app.schemas import ChatResult, MemoryRequestContext, ScopeType
from app.services.chat_memory_models import ChatMemoryCandidate
from app.services.observability_service import ObservabilityService


_JSON_BLOCK_PATTERN = re.compile(r"```(?:json)?\s*(\{.*\})\s*```", re.DOTALL)
_KEY_TOKEN_PATTERN = re.compile(r"[^a-z0-9_]+")
_SUBJECT_PATTERN = re.compile(r"^(session|user|project):([a-z0-9._-]+)$")
_STRUCTURED_KEY_PATTERN = re.compile(r"^(?P<key>[A-Za-z][A-Za-z0-9_.-]{1,63})\s*[:=]")
_MAX_CONTENT_LENGTH = 180
_ALLOWED_MEMORY_TYPES = {"fact", "preference", "decision", "pending_issue"}


class ChatMemoryLLMReviewService:
    """Review a chat turn for additional stable memory candidates."""

    def __init__(
        self,
        config: AppConfig,
        *,
        observability: ObservabilityService | None = None,
        client: OpenAI | None = None,
    ) -> None:
        self._config = config
        self._observability = observability or ObservabilityService(config)
        self._client = client

    def is_enabled(self) -> bool:
        return bool(
            self._config.memory_llm_review_enabled
            and self._config.memory_llm_review_max_candidates > 0
            and self._config.llm_api_ready
            and not is_local_mock_provider(self._config.llm_provider)
        )

    def review_turn(
        self,
        *,
        request_context: MemoryRequestContext,
        user_message: str,
        assistant_result: ChatResult,
        scene: str | None,
        rule_candidates: list[ChatMemoryCandidate],
    ) -> list[ChatMemoryCandidate]:
        if not self.is_enabled():
            return []

        response = self._client_instance().chat.completions.create(
            model=self._config.llm_model,
            temperature=0.0,
            max_tokens=min(max(self._config.memory_llm_review_max_candidates * 220, 300), 900),
            messages=[
                {"role": "system", "content": self._build_system_prompt()},
                {
                    "role": "user",
                    "content": self._build_user_prompt(
                        user_message=user_message,
                        assistant_result=assistant_result,
                        scene=scene,
                        rule_candidates=rule_candidates,
                    ),
                },
            ],
        )

        content = _extract_content_text(response.choices[0].message.content if response.choices else "")
        payload = _parse_payload(content)
        raw_candidates = payload.get("candidates")
        normalized_candidates: list[ChatMemoryCandidate] = []
        if isinstance(raw_candidates, list):
            for item in raw_candidates:
                candidate = self._normalize_candidate(item)
                if candidate is not None:
                    normalized_candidates.append(candidate)

        result = normalized_candidates[: self._config.memory_llm_review_max_candidates]
        self._observability.log_event(
            "memory.auto_write_llm_review_completed",
            request_context=request_context,
            payload={
                "scene": scene or "",
                "candidate_count": len(result),
                "provider": self._config.llm_provider,
                "model": self._config.llm_model,
            },
        )
        return result

    def _client_instance(self) -> OpenAI:
        if self._client is not None:
            return self._client

        client_kwargs: dict[str, object] = {
            "api_key": self._config.llm_api_key_for_client,
            "timeout": self._config.llm_timeout,
        }
        if self._config.llm_api_base:
            client_kwargs["base_url"] = self._config.llm_api_base
        self._client = OpenAI(**client_kwargs)
        return self._client

    def _build_system_prompt(self) -> str:
        return (
            "You review one Aurora chat turn and return only additional, durable memory candidates.\n"
            "Return JSON only.\n"
            'Schema: {"candidates":[{"content":"string","memory_type":"fact|preference|decision|pending_issue",'
            '"scope_type":"session|user|project","fact_key":"optional.dot.key","subject_key":"optional",'
            '"confidence":0.0,"reason":"short string"}]}\n'
            "Rules:\n"
            "- Prefer an empty list over weak candidates.\n"
            "- Use the user message as the source of truth. The assistant answer may only clarify wording.\n"
            "- Do not repeat candidates already listed in Existing Rule Candidates.\n"
            "- Ignore secrets, tokens, passwords, API keys, personal data, long logs, stack traces, and raw file paths.\n"
            "- Ignore one-off instructions that are not useful in future turns.\n"
            "- For preferences use user scope.\n"
            "- For pending_issue use session scope.\n"
            "- For decisions use project scope.\n"
            "- For facts prefer project scope unless the detail is clearly temporary for the current session.\n"
            "- Keep content compact and reusable. Prefer structured content like key: value when possible.\n"
            "- Keep content under 180 characters.\n"
            f"- Return at most {self._config.memory_llm_review_max_candidates} candidates.\n"
            f"- Only include candidates with confidence >= {self._config.memory_llm_review_min_confidence:.2f}."
        )

    def _build_user_prompt(
        self,
        *,
        user_message: str,
        assistant_result: ChatResult,
        scene: str | None,
        rule_candidates: list[ChatMemoryCandidate],
    ) -> str:
        assistant_excerpt = (assistant_result.summary or assistant_result.answer or "").strip()
        if len(assistant_excerpt) > 500:
            assistant_excerpt = assistant_excerpt[:500].rstrip() + "..."
        rule_block = "\n".join(
            f"- [{index}] type={item.memory_type} scope={item.scope_type} fact_key={item.fact_key or ''} content={item.content}"
            for index, item in enumerate(rule_candidates, start=1)
        ) or "(none)"
        return (
            f"Scene: {scene or 'qa_query'}\n\n"
            "[User Message]\n"
            f"{str(user_message or '').strip()}\n\n"
            "[Assistant Excerpt]\n"
            f"{assistant_excerpt or '(empty)'}\n\n"
            "[Existing Rule Candidates]\n"
            f"{rule_block}\n\n"
            "Return only additional candidates that are worth storing for future business turns."
        )

    def _normalize_candidate(self, item: Any) -> ChatMemoryCandidate | None:
        if not isinstance(item, dict):
            return None

        memory_type = str(item.get("memory_type") or "").strip().lower()
        if memory_type not in _ALLOWED_MEMORY_TYPES:
            return None

        confidence = _coerce_confidence(item.get("confidence"))
        if confidence < self._config.memory_llm_review_min_confidence:
            return None

        fact_key = _normalize_fact_key(str(item.get("fact_key") or ""))
        content = _normalize_content(str(item.get("content") or ""))
        if not content:
            return None

        if memory_type == "preference":
            preference_fact_key = fact_key or _match_preference_fact_key(content)
            if preference_fact_key:
                fact_key = preference_fact_key
                content = _preference_content_for(preference_fact_key)

        if not fact_key:
            fact_key = _structured_fact_key_from_content(content)

        scope_type = _normalize_scope_type(str(item.get("scope_type") or ""), memory_type)
        subject_key = _normalize_subject_key(str(item.get("subject_key") or ""))
        return ChatMemoryCandidate(
            content=content,
            memory_type=memory_type,  # type: ignore[arg-type]
            scope_type=scope_type,
            confirmed=False,
            source_kind="memory_llm_review",
            source_type="model_inferred",
            source_confidence=confidence,
            reviewed_by_human=False,
            subject_key=subject_key or None,
            fact_key=fact_key or None,
            origin="llm_review",
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
    block_match = _JSON_BLOCK_PATTERN.search(normalized)
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


def _coerce_confidence(value: Any) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, min(1.0, number))


def _normalize_scope_type(raw_scope: str, memory_type: str) -> ScopeType:
    normalized = str(raw_scope or "").strip().lower()
    if memory_type == "preference":
        return "user"
    if memory_type == "decision":
        return "project"
    if memory_type == "pending_issue":
        return "session"
    if normalized in {"session", "project"}:
        return normalized  # type: ignore[return-value]
    return "project"


def _normalize_fact_key(raw_key: str) -> str:
    tokens = [token for token in _KEY_TOKEN_PATTERN.split(str(raw_key or "").strip().lower()) if token]
    return ".".join(tokens)


def _normalize_subject_key(raw_key: str) -> str:
    normalized = str(raw_key or "").strip().lower()
    match = _SUBJECT_PATTERN.match(normalized)
    if match is None:
        return ""
    return f"{match.group(1)}:{match.group(2)}"


def _normalize_content(raw_content: str) -> str:
    normalized = " ".join(str(raw_content or "").split()).strip().strip("`\"'")
    if not normalized:
        return ""
    if len(normalized) > _MAX_CONTENT_LENGTH:
        normalized = normalized[: _MAX_CONTENT_LENGTH - 3].rstrip(" ,.;:") + "..."
    return normalized


def _structured_fact_key_from_content(content: str) -> str:
    match = _STRUCTURED_KEY_PATTERN.match(content.strip())
    if match is None:
        return ""
    return _normalize_fact_key(match.group("key"))


def _match_preference_fact_key(content: str) -> str:
    lowered = content.lower()
    if "table" in lowered:
        return "preference.response_style.table"
    if "step by step" in lowered or "step-by-step" in lowered or "steps" in lowered:
        return "preference.response_style.step_by_step"
    if "concise" in lowered or "brief" in lowered:
        return "preference.response_style.concise"
    return ""


def _preference_content_for(fact_key: str) -> str:
    if fact_key == "preference.response_style.table":
        return "Prefer table answers"
    if fact_key == "preference.response_style.step_by_step":
        return "Prefer step by step answers"
    if fact_key == "preference.response_style.concise":
        return "Prefer concise answers"
    return f"Prefer {fact_key}"
