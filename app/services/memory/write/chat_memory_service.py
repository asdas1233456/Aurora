"""Backend-only memory assimilation for public chat turns."""

from __future__ import annotations

import re

from app.config import AppConfig
from app.schemas import ChatResult, MemoryRequestContext, MemoryFactType, ScopeType
from app.services.chat_memory_llm_review_service import ChatMemoryLLMReviewService
from app.services.chat_memory_models import ChatMemoryAssimilationReport, ChatMemoryCandidate
from app.services.memory_write_service import MemoryWriteService
from app.services.observability_service import ObservabilityService


_STRUCTURED_PAIR_PATTERN = re.compile(
    r"(?P<key>[A-Za-z][A-Za-z0-9_.-]{1,63})\s*[:=]\s*(?P<value>[^\n,，。！？!?]{1,180})"
)
_REMEMBER_PATTERN = re.compile(
    r"(?:请\s*)?(?:帮我\s*)?(?:记住|记一下|记下|记好|记着)\s*[:：]?\s*(?P<statement>.+)",
    re.IGNORECASE,
)
_KEY_TOKEN_PATTERN = re.compile(r"[^a-z0-9_]+")
_DECISION_HINTS = ("决定", "统一", "采用", "should use", "decide", "decision", "strategy", "route", "policy")
_ISSUE_HINTS = ("报错", "异常", "失败", "error", "exception", "timeout", "500", "404", "503")
_TABLE_HINTS = ("表格",)
_STEP_BY_STEP_HINTS = ("分步骤", "一步一步", "步骤回答")
_CONCISE_HINTS = ("简洁", "简短", "简明")


class ChatMemoryService:
    """Assimilate explicit user intent into governed memory facts."""

    def __init__(
        self,
        config: AppConfig,
        *,
        write_service: MemoryWriteService | None = None,
        observability: ObservabilityService | None = None,
        llm_review_service: ChatMemoryLLMReviewService | None = None,
    ) -> None:
        self._config = config
        self._write_service = write_service or MemoryWriteService(config)
        self._observability = observability or ObservabilityService(config)
        self._llm_review_service = llm_review_service or ChatMemoryLLMReviewService(
            config,
            observability=self._observability,
        )

    def assimilate_turn(
        self,
        *,
        request_context: MemoryRequestContext,
        user_message: str,
        assistant_result: ChatResult,
        scene: str | None,
    ) -> ChatMemoryAssimilationReport:
        rule_candidates = self._extract_rule_candidates(
            user_message=user_message,
            assistant_result=assistant_result,
            scene=scene,
        )
        llm_candidates = self._extract_llm_candidates(
            request_context=request_context,
            user_message=user_message,
            assistant_result=assistant_result,
            scene=scene,
            rule_candidates=rule_candidates,
        )
        candidates = self._merge_candidates(rule_candidates, llm_candidates)[: self._config.memory_auto_write_max_candidates]

        report = ChatMemoryAssimilationReport(
            candidate_count=len(candidates),
            rule_candidate_count=len(rule_candidates),
            llm_candidate_count=len(llm_candidates),
        )
        if not candidates:
            return report

        for candidate in candidates:
            try:
                payload = self._write_service.build_create_payload(
                    request_context,
                    content=candidate.content,
                    memory_type=candidate.memory_type,
                    scope_type=candidate.scope_type,
                    source_kind=candidate.source_kind,
                    confirmed=candidate.confirmed,
                    subject_key=candidate.subject_key,
                    fact_key=candidate.fact_key,
                    source_type=candidate.source_type,
                    source_confidence=candidate.source_confidence,
                    reviewed_by_human=candidate.reviewed_by_human,
                )
                write_result = self._write_service.write_memory_fact(request_context, payload)
            except Exception as exc:
                report.failed_candidate_count += 1
                self._observability.increment_metric(
                    "memory_auto_write_candidate_failure_count",
                    dimensions={
                        "scene": scene or "",
                        "origin": candidate.origin,
                        "memory_type": candidate.memory_type,
                    },
                )
                self._observability.log_event(
                    "memory.auto_write_candidate_failed",
                    request_context=request_context,
                    level="warning",
                    payload={
                        "scene": scene or "",
                        "origin": candidate.origin,
                        "memory_type": candidate.memory_type,
                        "scope_type": candidate.scope_type,
                        "error": f"{exc.__class__.__name__}: {exc}",
                    },
                )
                continue

            report.persisted_memory_ids.append(write_result.memory_fact.id)
            report.operations.append(write_result.operation)

        if report.rule_candidate_count:
            self._observability.record_metric(
                "memory_auto_write_rule_candidate_count",
                value=float(report.rule_candidate_count),
                dimensions={"scene": scene or ""},
            )
        if report.llm_candidate_count:
            self._observability.record_metric(
                "memory_auto_write_llm_candidate_count",
                value=float(report.llm_candidate_count),
                dimensions={"scene": scene or ""},
            )
        if report.persisted_memory_ids:
            self._observability.increment_metric(
                "memory_auto_write_success_count",
                value=float(len(report.persisted_memory_ids)),
                dimensions={"scene": scene or ""},
            )
        self._observability.log_event(
            "memory.auto_write_completed",
            request_context=request_context,
            payload={
                "scene": scene or "",
                "candidate_count": report.candidate_count,
                "rule_candidate_count": report.rule_candidate_count,
                "llm_candidate_count": report.llm_candidate_count,
                "failed_candidate_count": report.failed_candidate_count,
                "persisted_memory_ids": list(report.persisted_memory_ids),
                "operations": list(report.operations),
            },
        )
        return report

    def _extract_rule_candidates(
        self,
        *,
        user_message: str,
        assistant_result: ChatResult,
        scene: str | None,
    ) -> list[ChatMemoryCandidate]:
        del assistant_result

        normalized_message = " ".join(str(user_message or "").split()).strip()
        if not normalized_message:
            return []

        candidates: list[ChatMemoryCandidate] = []

        remembered_statement = self._extract_remembered_statement(normalized_message)
        if remembered_statement:
            candidates.append(self._candidate_from_statement(remembered_statement, scene=scene))

        preference_candidate = self._extract_response_style_preference(normalized_message)
        if preference_candidate is not None:
            candidates.append(preference_candidate)

        candidates.extend(self._extract_structured_candidates(normalized_message))
        return self._merge_candidates(candidates, [])

    def _extract_llm_candidates(
        self,
        *,
        request_context: MemoryRequestContext,
        user_message: str,
        assistant_result: ChatResult,
        scene: str | None,
        rule_candidates: list[ChatMemoryCandidate],
    ) -> list[ChatMemoryCandidate]:
        try:
            return self._llm_review_service.review_turn(
                request_context=request_context,
                user_message=user_message,
                assistant_result=assistant_result,
                scene=scene,
                rule_candidates=rule_candidates,
            )
        except Exception as exc:
            self._observability.increment_metric(
                "memory_auto_write_llm_review_failure_count",
                dimensions={"scene": scene or "", "provider": self._config.llm_provider},
            )
            self._observability.log_event(
                "memory.auto_write_llm_review_failed",
                request_context=request_context,
                level="warning",
                payload={
                    "scene": scene or "",
                    "provider": self._config.llm_provider,
                    "model": self._config.llm_model,
                    "error": f"{exc.__class__.__name__}: {exc}",
                },
            )
            return []

    def _extract_response_style_preference(self, message: str) -> ChatMemoryCandidate | None:
        lowered = message.lower()
        fact_key = ""
        if any(token in message for token in _TABLE_HINTS) or "table" in lowered:
            fact_key = "preference.response_style.table"
        elif any(token in message for token in _STEP_BY_STEP_HINTS) or any(
            token in lowered for token in ("step by step", "step-by-step")
        ):
            fact_key = "preference.response_style.step_by_step"
        elif any(token in message for token in _CONCISE_HINTS) or any(
            token in lowered for token in ("concise", "brief")
        ):
            fact_key = "preference.response_style.concise"

        if not fact_key:
            return None

        return ChatMemoryCandidate(
            content=_preference_content_for(fact_key),
            memory_type="preference",
            scope_type="user",
            fact_key=fact_key,
            origin="rule",
        )

    def _extract_structured_candidates(self, message: str) -> list[ChatMemoryCandidate]:
        candidates: list[ChatMemoryCandidate] = []
        for match in _STRUCTURED_PAIR_PATTERN.finditer(message):
            normalized_key = _normalize_fact_key(match.group("key"))
            normalized_value = str(match.group("value") or "").strip()
            if not normalized_key or not normalized_value:
                continue

            if normalized_key.startswith("preference.response_style."):
                candidates.append(
                    ChatMemoryCandidate(
                        content=_preference_content_for(normalized_key),
                        memory_type="preference",
                        scope_type="user",
                        fact_key=normalized_key,
                        origin="rule",
                    )
                )
                continue

            memory_type: MemoryFactType = "fact"
            scope_type: ScopeType = "project"
            lowered_key = normalized_key.lower()
            if lowered_key.startswith("preference."):
                memory_type = "preference"
                scope_type = "user"
            elif lowered_key.startswith("decision.") or any(
                token in lowered_key for token in ("strategy", "route", "policy")
            ):
                memory_type = "decision"

            candidates.append(
                ChatMemoryCandidate(
                    content=f"{normalized_key}: {normalized_value}",
                    memory_type=memory_type,
                    scope_type=scope_type,
                    fact_key=normalized_key,
                    origin="rule",
                )
            )
        return candidates

    def _extract_remembered_statement(self, message: str) -> str:
        match = _REMEMBER_PATTERN.search(message)
        if match is None:
            return ""

        statement = str(match.group("statement") or "").strip()
        if not statement:
            return ""

        for delimiter in ("。", "！", "？", "!", "?", "\n"):
            if delimiter in statement:
                statement = statement.split(delimiter, 1)[0].strip()
                break

        for boundary in (" 另外", " 现在", " 然后", " and ", " then "):
            if boundary in statement:
                statement = statement.split(boundary, 1)[0].strip()
                break

        return statement.strip(" ,:：")

    def _candidate_from_statement(self, statement: str, *, scene: str | None) -> ChatMemoryCandidate:
        preference_candidate = self._extract_response_style_preference(statement)
        if preference_candidate is not None:
            return preference_candidate

        lowered = statement.lower()
        if scene == "troubleshooting" and any(token in lowered for token in _ISSUE_HINTS):
            return ChatMemoryCandidate(
                content=statement,
                memory_type="pending_issue",
                scope_type="session",
                origin="rule",
            )

        if any(token in lowered for token in _DECISION_HINTS):
            return ChatMemoryCandidate(
                content=statement,
                memory_type="decision",
                scope_type="project",
                origin="rule",
            )

        return ChatMemoryCandidate(
            content=statement,
            memory_type="fact",
            scope_type="project",
            origin="rule",
        )

    def _merge_candidates(
        self,
        primary_candidates: list[ChatMemoryCandidate],
        secondary_candidates: list[ChatMemoryCandidate],
    ) -> list[ChatMemoryCandidate]:
        merged: list[ChatMemoryCandidate] = []
        index_by_key: dict[tuple[str, str, str], int] = {}
        for candidate in [*primary_candidates, *secondary_candidates]:
            dedupe_key = self._candidate_dedupe_key(candidate)
            existing_index = index_by_key.get(dedupe_key)
            if existing_index is None:
                index_by_key[dedupe_key] = len(merged)
                merged.append(candidate)
                continue
            if self._should_replace_candidate(merged[existing_index], candidate):
                merged[existing_index] = candidate
        return merged

    @staticmethod
    def _candidate_dedupe_key(candidate: ChatMemoryCandidate) -> tuple[str, str, str]:
        identity = (candidate.fact_key or "").strip().lower()
        if not identity:
            identity = _structured_fact_key_from_content(candidate.content)
        if not identity:
            identity = " ".join(candidate.content.strip().lower().split())
        return (candidate.memory_type, candidate.scope_type, identity)

    @staticmethod
    def _should_replace_candidate(existing: ChatMemoryCandidate, candidate: ChatMemoryCandidate) -> bool:
        return ChatMemoryService._candidate_priority(candidate) > ChatMemoryService._candidate_priority(existing)

    @staticmethod
    def _candidate_priority(candidate: ChatMemoryCandidate) -> tuple[int, int, int, int, float]:
        source_priority = {
            "user_confirmed": 3,
            "imported": 2,
            "system_generated": 1,
            "model_inferred": 0,
        }
        return (
            1 if candidate.confirmed else 0,
            1 if candidate.reviewed_by_human is True else 0,
            source_priority.get(candidate.source_type, 0),
            1 if candidate.fact_key else 0,
            float(candidate.source_confidence or 0.0),
        )


def _normalize_fact_key(raw_key: str) -> str:
    tokens = [token for token in _KEY_TOKEN_PATTERN.split(str(raw_key or "").strip().lower()) if token]
    return ".".join(tokens)


def _structured_fact_key_from_content(content: str) -> str:
    match = _STRUCTURED_PAIR_PATTERN.match(content.strip())
    if match is None:
        return ""
    return _normalize_fact_key(match.group("key"))


def _preference_content_for(fact_key: str) -> str:
    if fact_key == "preference.response_style.table":
        return "Prefer table answers"
    if fact_key == "preference.response_style.step_by_step":
        return "Prefer step by step answers"
    if fact_key == "preference.response_style.concise":
        return "Prefer concise answers"
    return f"Prefer {fact_key}"
