"""Retrieval services for vector and local demo modes."""

from __future__ import annotations

import logging
from pathlib import Path
import re
from typing import Any

from app.config import AppConfig
from app.schemas import RetrievedChunk
from app.services.knowledge_access_policy import (
    KnowledgeAccessFilter,
    build_chroma_where,
    can_access_metadata,
)
from app.services.knowledge_base_service import (
    build_embedding_model,
    get_chroma_collection,
    get_vector_collection_count,
)
from app.services.local_index_service import load_local_index_chunks, search_local_index_chunks


logger = logging.getLogger(__name__)

FOLLOW_UP_MARKERS = (
    "这个",
    "这个问题",
    "这个场景",
    "它",
    "这个流程",
    "那",
    "那如果",
    "继续",
    "然后",
    "接着",
    "进一步",
)
HEADING_PATTERN = re.compile(r"^(#{1,6})\s+(.+?)\s*$")
ASCII_TOKEN_PATTERN = re.compile(r"[a-z0-9_]+")
CHINESE_SEGMENT_PATTERN = re.compile(r"[\u4e00-\u9fff]{2,}")
CHINESE_STOP_TOKENS = {
    "一个",
    "一些",
    "一种",
    "什么",
    "哪些",
    "如何",
    "怎么",
    "问题",
    "场景",
    "时候",
    "是否",
    "这个",
    "那个",
    "当前",
    "已经",
    "需要",
    "应该",
    "可以",
    "进行",
    "有关",
    "相关",
    "其中",
    "因为",
    "如果",
    "然后",
    "继续",
    "接着",
}


def retrieve_chunks(
    question: str,
    config: AppConfig,
    top_k: int | None = None,
    chat_history: list[dict[str, object]] | None = None,
    access_filter: KnowledgeAccessFilter | None = None,
) -> tuple[list[RetrievedChunk], str, str]:
    """Retrieve chunks through a metadata-filtered hybrid pipeline.

    Dense recall and sparse recall are kept separate on purpose:
    dense uses Chroma's native metadata filter before similarity search, while
    sparse uses SQLite predicates before lexical candidate generation. The
    reranker then operates on one merged pool instead of two divergent paths.
    """

    target_top_k = top_k or config.default_top_k
    retrieval_query = rewrite_question(question, chat_history or [])
    resolved_access_filter = access_filter or KnowledgeAccessFilter()
    dense_chunks = _retrieve_dense_chunks(
        query=retrieval_query,
        config=config,
        candidate_limit=min(max(target_top_k * 3, target_top_k), 20),
        access_filter=resolved_access_filter,
    )
    sparse_chunks = _retrieve_local_chunks(
        question=question,
        retrieval_query=retrieval_query,
        config=config,
        candidate_limit=min(max(target_top_k * 4, target_top_k), 40),
        access_filter=resolved_access_filter,
    )
    normalized_chunks = _merge_hybrid_candidates(
        dense_chunks=dense_chunks,
        sparse_chunks=sparse_chunks,
        candidate_limit=min(max(target_top_k * 6, target_top_k), 60),
    )

    reranked_chunks = rerank_chunks(
        normalized_chunks,
        question=question,
        retrieval_query=retrieval_query,
        top_k=target_top_k,
    )
    rewritten_question = retrieval_query if retrieval_query != question else ""
    return reranked_chunks, retrieval_query, rewritten_question


def rewrite_question(question: str, chat_history: list[dict[str, object]]) -> str:
    normalized_question = " ".join(str(question or "").split()).strip()
    if not normalized_question:
        return normalized_question

    recent_user_messages = [
        str(item.get("content", "")).strip()
        for item in chat_history
        if item.get("role") == "user" and str(item.get("content", "")).strip()
    ]
    if not recent_user_messages:
        return normalized_question

    previous_question = recent_user_messages[-1]
    looks_like_follow_up = (
        len(normalized_question) <= 18
        or any(marker in normalized_question for marker in FOLLOW_UP_MARKERS)
        or normalized_question.endswith(("吗？", "吗", "呢？", "呢"))
    )

    if not looks_like_follow_up or previous_question == normalized_question:
        return normalized_question

    return f"{previous_question} | 追问：{normalized_question}"


def rerank_chunks(
    chunks: list[RetrievedChunk],
    *,
    question: str,
    retrieval_query: str,
    top_k: int,
) -> list[RetrievedChunk]:
    if not chunks:
        return []

    vector_scores = [float(chunk.vector_score or 0.0) for chunk in chunks]
    min_score = min(vector_scores)
    max_score = max(vector_scores)
    denominator = max(max_score - min_score, 1e-6)

    reranked: list[RetrievedChunk] = []
    for chunk in chunks:
        lexical_score = max(
            float(chunk.lexical_score or 0.0),
            _lexical_overlap_score(
                question=question,
                retrieval_query=retrieval_query,
                chunk_text=f"{chunk.file_name}\n{chunk.theme}\n{' '.join(chunk.tags)}\n{chunk.text}",
            ),
        )
        heading_text = _extract_primary_heading_text(chunk.text)
        heading_score = (
            _lexical_overlap_score(
                question=question,
                retrieval_query=retrieval_query,
                chunk_text=heading_text,
            )
            if heading_text
            else 0.0
        )
        normalized_vector = (float(chunk.vector_score or 0.0) - min_score) / denominator
        lexical_boost = 0.1 if lexical_score >= 0.28 else 0.0
        exact_match_bonus = _exact_match_bonus(question, retrieval_query, f"{heading_text}\n{chunk.text}")
        focus_bonus = _focus_bonus(chunk.text)
        hybrid_bonus = 0.08 if (float(chunk.vector_score or 0.0) > 0 and lexical_score > 0) else 0.0
        blended_score = round(
            min(
                1.0,
                normalized_vector * 0.2
                + lexical_score * 0.48
                + heading_score * 0.16
                + lexical_boost
                + exact_match_bonus
                + focus_bonus
                + hybrid_bonus,
            ),
            6,
        )
        reranked.append(
            RetrievedChunk(
                document_id=chunk.document_id,
                file_name=chunk.file_name,
                source_path=chunk.source_path,
                relative_path=chunk.relative_path,
                text=chunk.text,
                score=blended_score,
                vector_score=chunk.vector_score,
                lexical_score=lexical_score,
                theme=chunk.theme,
                tags=chunk.tags,
                chunk_id=chunk.chunk_id,
                page_number=chunk.page_number,
                source_type=chunk.source_type,
                tenant_id=chunk.tenant_id,
                owner_user_id=chunk.owner_user_id,
                department_id=chunk.department_id,
                is_public=chunk.is_public,
            )
        )

    reranked.sort(key=lambda item: (float(item.score or 0.0), float(item.vector_score or 0.0)), reverse=True)
    return reranked[:top_k]


def _retrieve_local_chunks(
    *,
    question: str,
    retrieval_query: str,
    config: AppConfig,
    candidate_limit: int,
    access_filter: KnowledgeAccessFilter,
) -> list[RetrievedChunk]:
    ranked_chunks: list[RetrievedChunk] = []
    seen_candidates: set[tuple[str, int | None, str]] = set()
    candidate_items = search_local_index_chunks(
        config,
        f"{question}\n{retrieval_query}".strip(),
        limit=max(candidate_limit * 3, candidate_limit),
        access_filter=access_filter,
    )
    if not candidate_items:
        candidate_items = load_local_index_chunks(config, access_filter=access_filter)

    for item in candidate_items:
        for candidate in _iter_local_candidates(item):
            text = str(candidate.get("text", "") or "").strip()
            if not text:
                continue

            file_name = str(candidate.get("file_name", "") or "未知文件")
            theme = str(candidate.get("theme", "") or "")
            tags = [str(tag) for tag in candidate.get("tags", []) or []]
            source_path = str(candidate.get("source_path", "") or file_name)
            lexical_score = _score_local_candidate(
                question=question,
                retrieval_query=retrieval_query,
                file_name=file_name,
                theme=theme,
                tags=tags,
                text=text,
            )
            if lexical_score <= 0:
                continue

            candidate_key = (
                str(candidate.get("chunk_id", "") or source_path),
                _coerce_page_number(candidate.get("page_number")),
                text,
            )
            if candidate_key in seen_candidates:
                continue
            seen_candidates.add(candidate_key)

            ranked_chunks.append(
                RetrievedChunk(
                    document_id=str(candidate.get("document_id", "") or ""),
                    file_name=file_name,
                    source_path=source_path,
                    relative_path=str(candidate.get("relative_path", "") or file_name),
                    text=text,
                    score=lexical_score,
                    vector_score=lexical_score,
                    lexical_score=lexical_score,
                    theme=theme,
                    tags=tags,
                    chunk_id=str(candidate.get("chunk_id", "") or ""),
                    page_number=_coerce_page_number(candidate.get("page_number")),
                    source_type=str(candidate.get("source_type", "") or ""),
                    tenant_id=str(candidate.get("tenant_id", "") or ""),
                    owner_user_id=str(candidate.get("owner_user_id", "") or ""),
                    department_id=str(candidate.get("department_id", "") or ""),
                    is_public=bool(candidate.get("is_public", True)),
                )
            )

    ranked_chunks.sort(
        key=lambda item: (
            float(item.score or 0.0),
            float(item.lexical_score or 0.0),
            -len(item.text),
        ),
        reverse=True,
    )
    return ranked_chunks[:candidate_limit]


def _retrieve_dense_chunks(
    *,
    query: str,
    config: AppConfig,
    candidate_limit: int,
    access_filter: KnowledgeAccessFilter,
) -> list[RetrievedChunk]:
    """Run dense recall against Chroma with native metadata filtering."""
    if not config.embedding_api_ready or get_vector_collection_count(config) <= 0:
        return []

    collection = get_chroma_collection(config, reset=False)
    embed_model = build_embedding_model(config)
    query_embedding = embed_model.get_query_embedding(query)
    where = build_chroma_where(access_filter)

    query_kwargs: dict[str, object] = {
        "query_embeddings": [query_embedding],
        "n_results": max(1, int(candidate_limit)),
        "include": ["documents", "metadatas", "distances"],
    }
    if where is not None:
        query_kwargs["where"] = where

    try:
        payload = collection.query(**query_kwargs)
    except Exception:
        logger.exception("Dense retrieval with metadata filter failed; retrying with post-filter fallback.")
        payload = collection.query(
            query_embeddings=[query_embedding],
            n_results=max(1, int(candidate_limit * 2)),
            include=["documents", "metadatas", "distances"],
        )

    return _normalize_dense_query_result(
        payload,
        access_filter=access_filter,
        candidate_limit=candidate_limit,
    )


def _normalize_dense_query_result(
    payload: dict[str, object],
    *,
    access_filter: KnowledgeAccessFilter,
    candidate_limit: int,
) -> list[RetrievedChunk]:
    """Normalize Chroma query results into Aurora chunks."""
    ids = _first_result_list(payload.get("ids"))
    documents = _first_result_list(payload.get("documents"))
    metadatas = _first_result_list(payload.get("metadatas"))
    distances = _first_result_list(payload.get("distances"))

    normalized_chunks: list[RetrievedChunk] = []
    for index, chunk_id in enumerate(ids):
        metadata = metadatas[index] if index < len(metadatas) and isinstance(metadatas[index], dict) else {}
        text = str(documents[index] or "") if index < len(documents) else ""
        if not text.strip():
            continue
        if not can_access_metadata(
            access_filter,
            tenant_id=str(metadata.get("tenant_id", "") or ""),
            owner_user_id=str(metadata.get("owner_user_id") or metadata.get("user_id") or ""),
            department_id=str(metadata.get("department_id", "") or ""),
            is_public=bool(metadata.get("is_public", True)),
        ):
            continue

        source_path = str(
            metadata.get("source_path") or metadata.get("file_path") or metadata.get("file_name", "")
        )
        file_name = str(metadata.get("source_file") or Path(source_path).name or "未知文件")
        distance = float(distances[index]) if index < len(distances) and distances[index] is not None else 1.0
        vector_score = _distance_to_similarity(distance)
        normalized_chunks.append(
            RetrievedChunk(
                document_id=str(metadata.get("document_id", "") or ""),
                file_name=file_name,
                source_path=source_path or file_name,
                relative_path=str(metadata.get("relative_path", "") or file_name),
                text=text,
                score=vector_score,
                vector_score=vector_score,
                lexical_score=0.0,
                theme=str(metadata.get("theme", "") or ""),
                tags=[str(item) for item in metadata.get("tags", []) or []],
                chunk_id=str(chunk_id or ""),
                page_number=_coerce_page_number(metadata.get("page_number")),
                source_type=str(metadata.get("source_type", "") or ""),
                tenant_id=str(metadata.get("tenant_id", "") or ""),
                owner_user_id=str(metadata.get("owner_user_id") or metadata.get("user_id") or ""),
                department_id=str(metadata.get("department_id", "") or ""),
                is_public=bool(metadata.get("is_public", True)),
            )
        )

    return normalized_chunks[:candidate_limit]


def _merge_hybrid_candidates(
    *,
    dense_chunks: list[RetrievedChunk],
    sparse_chunks: list[RetrievedChunk],
    candidate_limit: int,
) -> list[RetrievedChunk]:
    """Merge dense and sparse candidates into one shared reranking pool."""
    merged: dict[tuple[str, int | None, str], RetrievedChunk] = {}

    for chunk in [*dense_chunks, *sparse_chunks]:
        candidate_key = (
            chunk.chunk_id or chunk.source_path,
            chunk.page_number,
            chunk.text,
        )
        existing = merged.get(candidate_key)
        if existing is None:
            merged[candidate_key] = chunk
            continue

        merged[candidate_key] = RetrievedChunk(
            document_id=existing.document_id or chunk.document_id,
            file_name=existing.file_name or chunk.file_name,
            source_path=existing.source_path or chunk.source_path,
            relative_path=existing.relative_path or chunk.relative_path,
            text=existing.text or chunk.text,
            score=max(float(existing.score or 0.0), float(chunk.score or 0.0)),
            vector_score=max(float(existing.vector_score or 0.0), float(chunk.vector_score or 0.0)),
            lexical_score=max(float(existing.lexical_score or 0.0), float(chunk.lexical_score or 0.0)),
            theme=existing.theme or chunk.theme,
            tags=list(dict.fromkeys([*existing.tags, *chunk.tags])),
            chunk_id=existing.chunk_id or chunk.chunk_id,
            page_number=existing.page_number if existing.page_number is not None else chunk.page_number,
            source_type=existing.source_type or chunk.source_type,
            tenant_id=existing.tenant_id or chunk.tenant_id,
            owner_user_id=existing.owner_user_id or chunk.owner_user_id,
            department_id=existing.department_id or chunk.department_id,
            is_public=existing.is_public or chunk.is_public,
        )

    merged_chunks = list(merged.values())
    merged_chunks.sort(
        key=lambda item: (
            max(float(item.vector_score or 0.0), float(item.lexical_score or 0.0)),
            float(item.lexical_score or 0.0),
            float(item.vector_score or 0.0),
        ),
        reverse=True,
    )
    return merged_chunks[:candidate_limit]


def _first_result_list(value: object) -> list[object]:
    if not isinstance(value, list) or not value:
        return []
    first_item = value[0]
    return list(first_item) if isinstance(first_item, list) else []


def _distance_to_similarity(distance: float) -> float:
    normalized_distance = max(float(distance), 0.0)
    return round(1.0 / (1.0 + normalized_distance), 6)


def _iter_local_candidates(item: dict[str, Any]) -> list[dict[str, Any]]:
    text = str(item.get("text", "") or "").strip()
    if not text:
        return []

    sections = _split_markdown_sections(text)
    if not sections:
        return [dict(item)]

    candidates: list[dict[str, Any]] = []
    for index, section in enumerate(sections, start=1):
        section_text = _render_local_section(section)
        if not section_text:
            continue
        candidate = dict(item)
        candidate["text"] = section_text
        candidate["position"] = f"{item.get('position', '')}-{index}"
        candidates.append(candidate)

    return candidates or [dict(item)]


def _coerce_page_number(value: object) -> int | None:
    try:
        if value is None or value == "":
            return None
        page_number = int(value)
    except (TypeError, ValueError):
        return None
    return page_number if page_number > 0 else None


def _split_markdown_sections(text: str) -> list[dict[str, Any]]:
    lines = str(text or "").splitlines()
    if not lines:
        return []

    sections: list[dict[str, Any]] = []
    open_sections: list[dict[str, Any]] = []
    heading_path: list[str] = []
    preamble_lines: list[str] = []

    for raw_line in lines:
        line = raw_line.rstrip()
        heading_match = HEADING_PATTERN.match(line.strip())
        if heading_match:
            level = len(heading_match.group(1))
            title = heading_match.group(2).strip()

            sections.extend(
                section
                for section in open_sections
                if int(section["level"]) >= level and _section_has_signal(section)
            )
            open_sections = [
                section for section in open_sections if int(section["level"]) < level
            ]
            for section in open_sections:
                section["body_lines"].append(line)

            heading_path = heading_path[: level - 1]
            heading_path.append(title)
            open_sections.append(
                {
                    "level": level,
                    "title": title,
                    "path": heading_path.copy(),
                    "body_lines": [],
                }
            )
            continue

        if open_sections:
            for section in open_sections:
                section["body_lines"].append(line)
        else:
            preamble_lines.append(line)

    sections.extend(section for section in open_sections if _section_has_signal(section))

    preamble_text = "\n".join(line for line in preamble_lines if line.strip()).strip()
    if preamble_text:
        sections.insert(
            0,
            {
                "level": 0,
                "title": "",
                "path": [],
                "body_lines": preamble_text.splitlines(),
            },
        )

    deduplicated_sections: list[dict[str, Any]] = []
    seen_rendered_texts: set[str] = set()
    for section in sections:
        rendered_text = _render_local_section(section)
        if not rendered_text or rendered_text in seen_rendered_texts:
            continue
        seen_rendered_texts.add(rendered_text)
        deduplicated_sections.append(section)

    return deduplicated_sections


def _section_has_signal(section: dict[str, Any]) -> bool:
    title = str(section.get("title", "") or "").strip()
    body_lines = [str(line).strip() for line in section.get("body_lines", [])]
    body_text = "\n".join(line for line in body_lines if line).strip()
    return bool(title or body_text)


def _render_local_section(section: dict[str, Any]) -> str:
    title = str(section.get("title", "") or "").strip()
    path = [str(item).strip() for item in section.get("path", []) if str(item).strip()]
    body_lines = [str(line).rstrip() for line in section.get("body_lines", [])]

    lines: list[str] = []
    if title:
        lines.append(f"### {title}")
    if len(path) > 1:
        lines.append(f"所属章节：{' / '.join(path[:-1])}")
    lines.extend(body_lines)

    text = "\n".join(lines).strip()
    text = re.sub(r"\n{3,}", "\n\n", text)
    if len(text) < 24 and not _contains_command_text(text):
        return ""
    return text


def _contains_command_text(text: str) -> bool:
    return bool(
        re.search(r"`[^`]+`", text)
        or re.search(r"(?m)^\s*[a-z][a-z0-9_-]*(?:\s+[^\s`]+)+\s*$", text.lower())
    )


def _score_local_candidate(
    *,
    question: str,
    retrieval_query: str,
    file_name: str,
    theme: str,
    tags: list[str],
    text: str,
) -> float:
    base_score = _lexical_overlap_score(
        question=question,
        retrieval_query=retrieval_query,
        chunk_text=f"{file_name}\n{theme}\n{' '.join(tags)}\n{text}",
    )
    if base_score <= 0:
        return 0.0

    focus_bonus = 0.0
    text_length = len(text)
    if text_length <= 260:
        focus_bonus = 0.08
    elif text_length <= 520:
        focus_bonus = 0.05
    elif text_length <= 900:
        focus_bonus = 0.02

    command_bonus = 0.04 if _looks_like_command_question(question) and "```" in text else 0.0

    exact_match_bonus = 0.0
    normalized_text = text.lower()
    for token in _salient_query_tokens(question, retrieval_query):
        if token in normalized_text:
            exact_match_bonus += 0.05 if len(token) >= 4 else 0.02
    exact_match_bonus = min(exact_match_bonus, 0.18)

    return round(min(1.0, base_score + focus_bonus + command_bonus + exact_match_bonus), 6)


def _looks_like_command_question(question: str) -> bool:
    normalized_question = str(question or "").lower()
    return any(
        marker in normalized_question
        for marker in ("命令", "查看", "怎么", "如何", "定位", "排查", "端口", "日志", "adb", "linux")
    )


def _salient_query_tokens(question: str, retrieval_query: str) -> set[str]:
    return {
        token
        for token in _tokenize(f"{question} {retrieval_query}")
        if len(token) >= 2 and token not in CHINESE_STOP_TOKENS
    }


def _extract_primary_heading_text(text: str) -> str:
    for line in str(text or "").splitlines():
        stripped = line.strip()
        match = HEADING_PATTERN.match(stripped)
        if not match:
            continue
        title = match.group(2).strip()
        if title:
            return title
    return ""


def _exact_match_bonus(question: str, retrieval_query: str, text: str) -> float:
    normalized_text = str(text or "").lower()
    bonus = 0.0
    for token in _salient_query_tokens(question, retrieval_query):
        if re.fullmatch(r"[a-z0-9_]+", token):
            if len(token) < 3:
                continue
        elif len(token) < 4:
            continue
        if token not in normalized_text:
            continue
        bonus += 0.06 if len(token) >= 4 else 0.04
    return min(bonus, 0.24)


def _focus_bonus(text: str) -> float:
    text_length = len(str(text or ""))
    if text_length <= 220:
        return 0.12
    if text_length <= 420:
        return 0.08
    if text_length <= 720:
        return 0.04
    return 0.0


def _lexical_overlap_score(*, question: str, retrieval_query: str, chunk_text: str) -> float:
    query_tokens = _tokenize(f"{question} {retrieval_query}")
    chunk_tokens = _tokenize(chunk_text)
    if not query_tokens or not chunk_tokens:
        return 0.0

    matched_weight = sum(_token_weight(token) for token in query_tokens if token in chunk_tokens)
    total_weight = sum(_token_weight(token) for token in query_tokens)
    coverage = matched_weight / max(total_weight, 1.0)
    return round(min(1.0, coverage), 6)


def _tokenize(text: str) -> set[str]:
    normalized = str(text or "").lower()
    tokens = {
        word.strip()
        for word in ASCII_TOKEN_PATTERN.findall(normalized)
        if len(word.strip()) >= 2
    }

    for segment in CHINESE_SEGMENT_PATTERN.findall(normalized):
        compact_segment = segment.strip()
        if len(compact_segment) < 2:
            continue
        if compact_segment not in CHINESE_STOP_TOKENS:
            tokens.add(compact_segment)

        max_ngram = min(4, len(compact_segment))
        for ngram_size in range(2, max_ngram + 1):
            for start in range(0, len(compact_segment) - ngram_size + 1):
                token = compact_segment[start : start + ngram_size]
                if token and token not in CHINESE_STOP_TOKENS:
                    tokens.add(token)

    return {token for token in tokens if token}


def _token_weight(token: str) -> float:
    if re.fullmatch(r"[a-z0-9_]+", token):
        return 1.6 if len(token) <= 4 else 1.3
    if len(token) >= 4:
        return 2.2
    if len(token) == 3:
        return 1.7
    return 1.2
