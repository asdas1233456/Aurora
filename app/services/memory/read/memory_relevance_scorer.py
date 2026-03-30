"""Lightweight lexical relevance scoring for Aurora memory retrieval."""

from __future__ import annotations

import re
from typing import Protocol

from app.services.memory_retrieval_models import MemoryCandidate, MemoryQuery, MemoryRelevanceSignal


TOKEN_PATTERN = re.compile(r"[a-z0-9_./:-]+|[\u4e00-\u9fff]+", re.IGNORECASE)
STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "for",
    "how",
    "is",
    "of",
    "or",
    "the",
    "to",
    "what",
    "with",
    "为什么",
    "什么",
    "怎么",
    "如何",
    "请问",
    "一个",
    "这个",
    "那个",
    "我们",
}

CONTEXTUAL_MARKERS = (
    "current",
    "currently",
    "discuss",
    "discussion",
    "state",
    "status",
    "session",
    "our",
    "we",
    "context",
    "当前",
    "讨论",
    "状态",
    "会话",
    "上下文",
)


class MemoryRelevanceScorerPort(Protocol):
    """Stable scorer contract so lexical, semantic, and hybrid scorers share one boundary."""

    def score(self, query: MemoryQuery, candidate: MemoryCandidate) -> MemoryRelevanceSignal:
        """Return a normalized relevance signal in the range [0, 1]."""


class MemoryRelevanceScorer:
    """First-pass lexical scorer that can later be swapped for semantic scoring."""

    def score(self, query: MemoryQuery, candidate: MemoryCandidate) -> MemoryRelevanceSignal:
        query_terms = _tokenize(query.user_query)
        if not query_terms:
            return MemoryRelevanceSignal(score=0.0, matched_reason="empty_query")

        candidate_terms = _tokenize(
            " ".join(
                [
                    candidate.content,
                    candidate.fact_key,
                    candidate.subject_key,
                    candidate.scope_id,
                ]
            )
        )
        overlap_terms = sorted(query_terms & candidate_terms)
        overlap_score = len(overlap_terms) / max(len(query_terms), 1)

        normalized_query = " ".join(query.user_query.lower().split())
        normalized_content = " ".join(candidate.content.lower().split())
        exact_phrase_hit = bool(normalized_query) and normalized_query in normalized_content

        fact_key_hit = any(term in candidate.fact_key.lower() for term in query_terms)
        subject_key_hit = any(term in candidate.subject_key.lower() for term in query_terms)
        contextual_boost = _contextual_scope_boost(query.user_query, candidate.scope_type)

        score = 0.55 if exact_phrase_hit else 0.0
        score += min(0.35, overlap_score * 0.70)
        if fact_key_hit:
            score += 0.12
        if subject_key_hit:
            score += 0.08
        score += contextual_boost

        matched_reason_parts: list[str] = []
        if overlap_terms:
            matched_reason_parts.append(f"matched_terms={','.join(overlap_terms[:4])}")
        if exact_phrase_hit:
            matched_reason_parts.append("exact_phrase")
        if fact_key_hit:
            matched_reason_parts.append("fact_key_hit")
        if subject_key_hit:
            matched_reason_parts.append("subject_key_hit")
        if contextual_boost > 0:
            matched_reason_parts.append(f"contextual_scope_boost={candidate.scope_type}")

        return MemoryRelevanceSignal(
            score=max(0.0, min(1.0, score)),
            matched_reason="; ".join(matched_reason_parts) or "low_lexical_overlap",
            matched_terms=tuple(overlap_terms[:6]),
        )


class CompositeMemoryRelevanceScorer:
    """Combine multiple scorers so hybrid or learned relevance can be added incrementally."""

    def __init__(
        self,
        scorers: list[tuple[MemoryRelevanceScorerPort, float]],
    ) -> None:
        self._scorers = [
            (scorer, float(weight))
            for scorer, weight in scorers
            if scorer is not None and float(weight) > 0.0
        ]

    def score(self, query: MemoryQuery, candidate: MemoryCandidate) -> MemoryRelevanceSignal:
        if not self._scorers:
            return MemoryRelevanceSignal(score=0.0, matched_reason="no_active_relevance_scorer")

        total_weight = sum(weight for _, weight in self._scorers)
        weighted_score = 0.0
        matched_terms: list[str] = []
        matched_reasons: list[str] = []

        for scorer, weight in self._scorers:
            signal = scorer.score(query, candidate)
            weighted_score += signal.score * weight
            matched_terms.extend(signal.matched_terms)
            if signal.matched_reason:
                matched_reasons.append(signal.matched_reason)

        deduped_terms = tuple(dict.fromkeys(matched_terms))
        deduped_reasons = "; ".join(dict.fromkeys(matched_reasons))
        return MemoryRelevanceSignal(
            score=max(0.0, min(1.0, weighted_score / total_weight)),
            matched_reason=deduped_reasons or "combined_relevance_signal",
            matched_terms=deduped_terms[:6],
        )


def _tokenize(text: str) -> set[str]:
    tokens: set[str] = set()
    for raw_token in TOKEN_PATTERN.findall(str(text or "").lower()):
        token = raw_token.strip()
        if not token or token in STOPWORDS:
            continue
        if len(token) == 1 and not token.isdigit():
            continue
        tokens.add(token)

        # Chinese strings benefit from short shingles so partial intent still matches.
        if any("\u4e00" <= char <= "\u9fff" for char in token) and len(token) > 2:
            for index in range(len(token) - 1):
                shard = token[index : index + 2]
                if shard not in STOPWORDS:
                    tokens.add(shard)
    return tokens


def _contextual_scope_boost(user_query: str, scope_type: str) -> float:
    normalized = str(user_query or "").strip().lower()
    if not normalized:
        return 0.0
    if not any(marker in normalized for marker in CONTEXTUAL_MARKERS):
        return 0.0
    if scope_type == "session":
        return 0.26
    if scope_type == "project":
        return 0.12
    if scope_type == "user":
        return 0.10
    return 0.0
