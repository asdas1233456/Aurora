"""Rule-driven scanning before memory enters governed persistence."""

from __future__ import annotations

import re

from app.schemas import ContentSafetyDecision, ContentSafetyFinding


class SensitiveContentGuard:
    """Detect secrets, sensitive environment data, PII, and prompt-injection markers."""

    _BLOCK_RULES: tuple[tuple[str, str, re.Pattern[str]], ...] = (
        (
            "secret.bearer_token",
            "credential",
            re.compile(r"(?:authorization\s*:\s*bearer\s+|bearer\s+)[a-z0-9._\-]{12,}", re.IGNORECASE),
        ),
        (
            "secret.api_key",
            "credential",
            re.compile(r"\b(?:sk|rk)-[A-Za-z0-9]{12,}\b"),
        ),
        (
            "secret.assignment",
            "credential",
            re.compile(r"\b(?:api[_-]?key|secret|password|token)\b\s*[:=]\s*[^\s]{4,}", re.IGNORECASE),
        ),
        (
            "prompt.ignore_instructions",
            "prompt_injection",
            re.compile(
                r"(ignore\s+(all|previous|prior)\s+instructions|reveal\s+the\s+system\s+prompt|developer\s+message|jailbreak)",
                re.IGNORECASE,
            ),
        ),
    )

    _REDACT_RULES: tuple[tuple[str, str, re.Pattern[str], str], ...] = (
        (
            "pii.email",
            "pii",
            re.compile(r"\b[A-Z0-9._%+\-]+@[A-Z0-9.\-]+\.[A-Z]{2,}\b", re.IGNORECASE),
            "[REDACTED_EMAIL]",
        ),
        (
            "pii.phone",
            "pii",
            re.compile(r"\b(?:\+?\d{1,3}[-.\s]?)?(?:\d{3}[-.\s]?){2}\d{4}\b"),
            "[REDACTED_PHONE]",
        ),
        (
            "env.internal_ip",
            "sensitive_environment",
            re.compile(
                r"\b(?:10\.\d{1,3}\.\d{1,3}\.\d{1,3}|192\.168\.\d{1,3}\.\d{1,3}|172\.(?:1[6-9]|2\d|3[01])\.\d{1,3}\.\d{1,3})\b"
            ),
            "[REDACTED_INTERNAL_IP]",
        ),
    )

    def scan(self, content: str) -> ContentSafetyDecision:
        normalized_content = str(content or "").strip()
        findings: list[ContentSafetyFinding] = []
        redacted_content = normalized_content

        for rule_id, category, pattern in self._BLOCK_RULES:
            match = pattern.search(normalized_content)
            if match:
                findings.append(
                    ContentSafetyFinding(
                        rule_id=rule_id,
                        category=category,
                        action="block",
                        match_text=match.group(0),
                    )
                )

        if findings:
            severity = "critical" if any(item.category == "credential" for item in findings) else "high"
            reason = "credential or prompt-injection content cannot enter long-term memory directly"
            return ContentSafetyDecision(
                action="block",
                reason=reason,
                sanitized_content=normalized_content,
                findings=findings,
                severity=severity,
            )

        for rule_id, category, pattern, replacement in self._REDACT_RULES:
            for match in pattern.finditer(redacted_content):
                findings.append(
                    ContentSafetyFinding(
                        rule_id=rule_id,
                        category=category,
                        action="redact",
                        match_text=match.group(0),
                        redacted_text=replacement,
                    )
                )
            redacted_content = pattern.sub(replacement, redacted_content)

        if findings:
            return ContentSafetyDecision(
                action="redact",
                reason="sensitive personal or environment data was masked before persistence",
                sanitized_content=redacted_content,
                findings=findings,
                severity="medium",
            )

        return ContentSafetyDecision(
            action="allow",
            reason="content passed the first-version sensitive-content rules",
            sanitized_content=normalized_content,
            findings=[],
            severity="low",
        )
