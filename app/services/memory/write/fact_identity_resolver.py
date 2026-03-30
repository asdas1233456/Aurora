"""Resolve governable memory identities from write payloads."""

from __future__ import annotations

import hashlib
import re

from app.schemas import MemoryFactCreate, ResolvedMemoryFactIdentity


_KEY_SPLIT_PATTERN = re.compile(r"[^a-z0-9_]+")


class FactIdentityResolver:
    """Lift free-form memory writes into stable subject/fact identities."""

    def resolve(self, payload: MemoryFactCreate) -> ResolvedMemoryFactIdentity:
        subject_key = self._resolve_subject_key(payload)
        fact_key, fact_family, allows_coexistence = self._resolve_fact_key(payload)
        consistency_group_id = (
            (payload.consistency_group_id or "").strip()
            or f"{subject_key}|{fact_family if allows_coexistence else fact_key}"
        )
        source_type = self._resolve_source_type(payload)
        reviewed_by_human = payload.reviewed_by_human
        if reviewed_by_human is None and source_type == "user_confirmed":
            reviewed_by_human = True

        return ResolvedMemoryFactIdentity(
            subject_key=subject_key,
            fact_key=fact_key,
            consistency_group_id=consistency_group_id,
            source_type=source_type,
            source_confidence=self._resolve_source_confidence(payload, source_type),
            reviewed_by_human=reviewed_by_human,
            allows_coexistence=allows_coexistence,
            fact_family=fact_family,
        )

    def _resolve_subject_key(self, payload: MemoryFactCreate) -> str:
        explicit_subject_key = self._normalize_subject_key(payload.subject_key or "")
        if explicit_subject_key:
            return explicit_subject_key

        if payload.scope_type == "project":
            return f"project:{self._normalize_subject_part(payload.project_id)}"
        if payload.scope_type == "user":
            return f"user:{self._normalize_subject_part(payload.owner_user_id or payload.scope_id)}"
        if payload.scope_type == "team":
            return f"team:{self._normalize_subject_part(payload.scope_id)}"
        if payload.scope_type == "global":
            return f"global:{self._normalize_subject_part(payload.scope_id)}"
        return f"session:{self._normalize_subject_part(payload.scope_id)}"

    def _resolve_fact_key(self, payload: MemoryFactCreate) -> tuple[str, str, bool]:
        explicit_fact_key = self._normalize_fact_key(payload.fact_key or "")
        if explicit_fact_key:
            return self._classify_fact_key(explicit_fact_key)

        normalized_content = " ".join(payload.content.split()).strip()
        lowered_content = normalized_content.lower()

        response_style_key = self._match_response_style_fact_key(lowered_content)
        if response_style_key:
            return response_style_key

        known_keyword_key = self._match_known_keyword_fact_key(lowered_content)
        if known_keyword_key:
            return known_keyword_key

        structured_key = self._match_structured_key(normalized_content)
        if structured_key:
            return self._classify_fact_key(structured_key)

        fallback_key = f"{payload.type}.entry.{self._fingerprint(normalized_content)}"
        return fallback_key, fallback_key, False

    def _resolve_source_type(self, payload: MemoryFactCreate) -> str:
        explicit_source_type = (payload.source_type or "").strip()
        if explicit_source_type:
            return explicit_source_type
        if payload.confirmed:
            return "user_confirmed"

        normalized_kind = str(payload.source_kind or "").strip().lower()
        if normalized_kind in {"import", "imported"}:
            return "imported"
        if normalized_kind in {"system", "system_generated", "summary_extraction", "memory_extraction"}:
            return "system_generated"
        return "model_inferred"

    def _resolve_source_confidence(self, payload: MemoryFactCreate, source_type: str) -> float:
        raw_confidence = float(payload.source_confidence or 0.0)
        if raw_confidence > 0:
            return max(0.0, min(1.0, raw_confidence))

        if source_type == "user_confirmed":
            return 1.0
        if source_type == "imported":
            return 0.85
        if source_type == "system_generated":
            return 0.75
        return 0.6

    def _match_response_style_fact_key(self, lowered_content: str) -> tuple[str, str, bool] | None:
        if "table" in lowered_content:
            return "preference.response_style.table", "preference.response_style", True
        if any(token in lowered_content for token in ("step by step", "step-by-step", "steps")):
            return "preference.response_style.step_by_step", "preference.response_style", True
        if any(token in lowered_content for token in ("concise", "brief")):
            return "preference.response_style.concise", "preference.response_style", True
        return None

    def _match_known_keyword_fact_key(self, lowered_content: str) -> tuple[str, str, bool] | None:
        if any(token in lowered_content for token in ("api base", "api_base", "base url")):
            return "env.api_base", "env.api_base", False
        if any(token in lowered_content for token in ("stack.framework", "framework", "fastapi", "flask")):
            return "stack.framework", "stack.framework", False
        if "memory strategy" in lowered_content:
            return "architecture.memory_strategy", "architecture.memory_strategy", False
        if any(token in lowered_content for token in ("main route", "primary route")):
            return "decision.main_route", "decision.main_route", False
        return None

    def _match_structured_key(self, content: str) -> str | None:
        # Structured writes like "stack.framework: FastAPI" are the fastest path into governed memory.
        for separator in (":", "="):
            if separator not in content:
                continue
            left, _right = content.split(separator, 1)
            normalized_left = self._normalize_fact_key(left)
            if normalized_left:
                return normalized_left
        return None

    def _classify_fact_key(self, fact_key: str) -> tuple[str, str, bool]:
        if fact_key.startswith("preference.response_style."):
            return fact_key, "preference.response_style", True
        return fact_key, fact_key, False

    @staticmethod
    def _normalize_subject_key(raw_key: str) -> str:
        if not raw_key:
            return ""
        left, separator, right = raw_key.partition(":")
        if separator:
            left = FactIdentityResolver._normalize_subject_part(left)
            right = FactIdentityResolver._normalize_subject_part(right)
            if left and right:
                return f"{left}:{right}"
        return ""

    @staticmethod
    def _normalize_subject_part(raw_text: str) -> str:
        tokens = [token for token in _KEY_SPLIT_PATTERN.split(str(raw_text or "").strip().lower()) if token]
        return "-".join(tokens)

    @staticmethod
    def _normalize_fact_key(raw_key: str) -> str:
        if not raw_key:
            return ""
        tokens = [token for token in _KEY_SPLIT_PATTERN.split(raw_key.strip().lower()) if token]
        return ".".join(tokens)

    @staticmethod
    def _fingerprint(text: str) -> str:
        return hashlib.sha1(text.encode("utf-8")).hexdigest()[:12]
