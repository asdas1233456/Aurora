"""LLM providers with an offline fallback mode."""

from __future__ import annotations

from collections.abc import Iterable
import re
from typing import Protocol

from openai import OpenAI

from app.config import AppConfig, is_openai_compatible_provider, is_openai_provider
from app.schemas import RetrievedChunk
from app.services.retrieval_service import _tokenize as _tokenize_for_match


HEADING_PATTERN = re.compile(r"^(#{1,6})\s+(.+?)\s*$")
INLINE_CODE_PATTERN = re.compile(r"`([^`\n]+)`")
COMMAND_PREFIXES = (
    "adb",
    "cd",
    "chmod",
    "curl",
    "df",
    "du",
    "findstr",
    "free",
    "git",
    "grep",
    "head",
    "htop",
    "kill",
    "less",
    "ls",
    "lsof",
    "mkdir",
    "more",
    "nc",
    "netstat",
    "npm",
    "ping",
    "ps",
    "pytest",
    "python",
    "rm",
    "scp",
    "ss",
    "su",
    "sudo",
    "tail",
    "tar",
    "telnet",
    "top",
    "unzip",
    "vmstat",
    "zip",
)


class BaseLLMProvider(Protocol):
    def generate_answer(
        self,
        question: str,
        chat_history: list[dict[str, object]],
        retrieved_chunks: list[RetrievedChunk],
        config: AppConfig,
    ) -> str:
        """Generate a full answer."""

    def stream_answer(
        self,
        question: str,
        chat_history: list[dict[str, object]],
        retrieved_chunks: list[RetrievedChunk],
        config: AppConfig,
    ) -> Iterable[str]:
        """Generate an answer stream."""


class LocalExtractiveChatProvider:
    """Offline fallback provider for demo and local acceptance flows."""

    def generate_answer(
        self,
        question: str,
        chat_history: list[dict[str, object]],
        retrieved_chunks: list[RetrievedChunk],
        config: AppConfig,
    ) -> str:
        del chat_history, config
        return _build_local_answer(question, retrieved_chunks)

    def stream_answer(
        self,
        question: str,
        chat_history: list[dict[str, object]],
        retrieved_chunks: list[RetrievedChunk],
        config: AppConfig,
    ) -> Iterable[str]:
        text = self.generate_answer(question, chat_history, retrieved_chunks, config)
        for start in range(0, len(text), 48):
            yield text[start : start + 48]


class OpenAICompatibleChatProvider:
    """OpenAI-style chat provider."""

    def __init__(self, config: AppConfig) -> None:
        if not config.llm_api_ready:
            raise ValueError(
                "LLM API configuration is incomplete. Please check provider, key, base URL, and model."
            )

        client_kwargs = {
            "api_key": config.llm_api_key_for_client,
            "timeout": config.llm_timeout,
        }
        if config.llm_api_base:
            client_kwargs["base_url"] = config.llm_api_base

        self.client = OpenAI(**client_kwargs)
        self.model = config.llm_model
        self.temperature = config.llm_temperature
        self.max_tokens = config.llm_max_tokens

    def generate_answer(
        self,
        question: str,
        chat_history: list[dict[str, object]],
        retrieved_chunks: list[RetrievedChunk],
        config: AppConfig,
    ) -> str:
        system_prompt, user_prompt = _build_prompts(
            question=question,
            chat_history=chat_history,
            retrieved_chunks=retrieved_chunks,
            config=config,
        )

        try:
            response = self.client.chat.completions.create(
                model=self.model,
                temperature=self.temperature,
                max_tokens=self.max_tokens,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
            )
        except Exception as exc:
            raise RuntimeError(f"调用模型 API 生成回答失败：{exc}") from exc

        if not response.choices:
            return "模型返回了空结果，请稍后重试。"

        answer = response.choices[0].message.content or ""
        if isinstance(answer, list):
            answer = "\n".join(
                str(getattr(item, "text", item))
                for item in answer
                if getattr(item, "text", item)
            )

        answer_text = str(answer).strip()
        return answer_text or "模型返回了空结果，请稍后重试。"

    def stream_answer(
        self,
        question: str,
        chat_history: list[dict[str, object]],
        retrieved_chunks: list[RetrievedChunk],
        config: AppConfig,
    ) -> Iterable[str]:
        system_prompt, user_prompt = _build_prompts(
            question=question,
            chat_history=chat_history,
            retrieved_chunks=retrieved_chunks,
            config=config,
        )

        try:
            stream = self.client.chat.completions.create(
                model=self.model,
                temperature=self.temperature,
                max_tokens=self.max_tokens,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                stream=True,
            )
        except Exception as exc:
            raise RuntimeError(f"调用模型 API 流式生成回答失败：{exc}") from exc

        for chunk in stream:
            try:
                delta = chunk.choices[0].delta.content
            except Exception:
                delta = ""

            if isinstance(delta, list):
                text = "".join(
                    str(getattr(item, "text", item))
                    for item in delta
                    if getattr(item, "text", item)
                )
            else:
                text = str(delta or "")

            if text:
                yield text


def get_llm_provider(config: AppConfig) -> BaseLLMProvider:
    if not config.llm_api_ready:
        return LocalExtractiveChatProvider()

    if is_openai_provider(config.llm_provider) or is_openai_compatible_provider(config.llm_provider):
        return OpenAICompatibleChatProvider(config)

    raise NotImplementedError(f"llm_provider={config.llm_provider} is not supported yet.")


def _build_prompts(
    question: str,
    chat_history: list[dict[str, object]],
    retrieved_chunks: list[RetrievedChunk],
    config: AppConfig,
) -> tuple[str, str]:
    system_prompt = (
        "你是 Aurora 软件测试知识助手。"
        "请严格基于提供的知识库片段回答，不要编造。"
        "如果片段信息不足，请明确说明当前知识库中没有足够信息。"
        "回答使用简洁、清晰、适合一线工程师阅读的中文。"
    )

    history_text = _format_history(chat_history, config.max_history_turns)
    context_text = _format_context(retrieved_chunks)

    user_prompt = f"""
请根据下面的信息回答用户问题。

【对话历史】
{history_text}

【知识库片段】
{context_text}

【当前问题】
{question}

要求：
1. 只根据“知识库片段”回答。
2. 如果片段不足，请直接说明信息不足。
3. 不要在正文中伪造引用编号。
4. 尽量分点说明，但不要过度展开。
""".strip()
    return system_prompt, user_prompt


def _format_history(chat_history: list[dict[str, object]], max_turns: int) -> str:
    if not chat_history:
        return "无"

    recent_messages = chat_history[-max_turns * 2 :]
    lines: list[str] = []
    for message in recent_messages:
        role = "用户" if message.get("role") == "user" else "助手"
        content = str(message.get("content", "")).strip()
        if content:
            lines.append(f"{role}: {content}")
    return "\n".join(lines) if lines else "无"


def _format_context(retrieved_chunks: list[RetrievedChunk]) -> str:
    if not retrieved_chunks:
        return "未检索到任何知识库片段。"

    blocks: list[str] = []
    for index, chunk in enumerate(retrieved_chunks, start=1):
        blocks.append(
            f"[片段 {index}] 文件：{chunk.file_name}\n"
            f"来源：{chunk.source_path}\n"
            f"内容：\n{chunk.text}"
        )
    return "\n\n".join(blocks)


def _build_local_answer(question: str, retrieved_chunks: list[RetrievedChunk]) -> str:
    if not retrieved_chunks:
        return "当前知识库中没有足够信息回答该问题。"

    answer_points = _build_local_answer_points(question, retrieved_chunks)
    if not answer_points:
        answer_points = _fallback_answer_points(retrieved_chunks)

    source_names: list[str] = []
    for chunk in retrieved_chunks[:3]:
        if chunk.file_name not in source_names:
            source_names.append(chunk.file_name)

    lines = ["当前为本地演示模式，以下内容基于命中的知识库片段整理："]
    is_step_question = _looks_like_step_question(question)
    max_points = 2 if is_step_question else 3
    lines.append("可以优先这样排查：" if is_step_question else "可以重点关注：")
    for index, point in enumerate(answer_points[:max_points], start=1):
        lines.append(f"{index}. {point}")
    lines.append(f"来源：{'、'.join(source_names) if source_names else '知识库片段'}")
    return "\n".join(lines)


def _build_local_answer_points(question: str, retrieved_chunks: list[RetrievedChunk]) -> list[str]:
    points: list[str] = []
    seen_points: set[str] = set()

    ranked_chunks = sorted(
        retrieved_chunks[:4],
        key=lambda chunk: _chunk_answer_priority(question, chunk),
        reverse=True,
    )

    for chunk in ranked_chunks:
        point = _build_chunk_answer_point(question, chunk.text)
        if not point or point in seen_points:
            continue
        seen_points.add(point)
        points.append(point)
        if len(points) >= 3:
            break

    return points


def _chunk_answer_priority(question: str, chunk: RetrievedChunk) -> float:
    title = _extract_primary_heading(chunk.text)
    title_score = _sentence_overlap_score(question, title) if title else 0.0
    command_bonus = 0.2 if _extract_commands(chunk.text) else 0.0
    text_length = len(chunk.text)
    focus_bonus = 0.15 if text_length <= 280 else 0.08 if text_length <= 520 else 0.02
    return float(chunk.score or 0.0) + title_score + command_bonus + focus_bonus


def _build_chunk_answer_point(question: str, text: str) -> str:
    title = _extract_primary_heading(text)
    commands = _extract_commands(text)
    supporting_sentences = _extract_supporting_sentences(question, text, limit=2)

    if title and commands:
        command_text = "、".join(f"`{command}`" for command in commands[:2])
        supporting_text = _merge_supporting_sentences(supporting_sentences)
        if supporting_text:
            return _ensure_sentence(f"{title}：优先执行 {command_text}。{supporting_text}")
        return f"{title}：优先执行 {command_text}"

    if title and supporting_sentences:
        supporting_text = _merge_supporting_sentences(supporting_sentences)
        if supporting_text:
            return _ensure_sentence(f"{title}：{supporting_text}")

    if commands:
        command_text = "、".join(f"`{command}`" for command in commands[:2])
        supporting_text = _merge_supporting_sentences(supporting_sentences)
        if supporting_text:
            return _ensure_sentence(f"可先执行 {command_text}。{supporting_text}")
        return f"可先执行 {command_text}"

    if supporting_sentences:
        return _ensure_sentence(_merge_supporting_sentences(supporting_sentences))

    return ""


def _extract_primary_heading(text: str) -> str:
    for line in str(text or "").splitlines():
        stripped = line.strip()
        match = HEADING_PATTERN.match(stripped)
        if not match:
            continue
        title = _normalize_heading_title(match.group(2).strip())
        if title and "所属章节" not in title:
            return title
    return ""


def _normalize_heading_title(title: str) -> str:
    normalized_title = re.sub(r"^\d+(?:\.\d+)*\.\s*", "", str(title or "").strip())
    return normalized_title.strip("：: ")


def _extract_commands(text: str) -> list[str]:
    commands: list[str] = []
    seen_commands: set[str] = set()
    in_code_block = False

    for line in str(text or "").splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("```"):
            in_code_block = not in_code_block
            continue

        candidates: list[str] = []
        if in_code_block:
            candidates.append(stripped)
        else:
            candidates.extend(match.strip() for match in INLINE_CODE_PATTERN.findall(stripped))
            if _looks_like_command(stripped):
                candidates.append(stripped)

        for candidate in candidates:
            normalized_candidate = candidate.strip()
            if not normalized_candidate or normalized_candidate in seen_commands:
                continue
            if not _looks_like_command(normalized_candidate):
                continue
            seen_commands.add(normalized_candidate)
            commands.append(normalized_candidate)
            if len(commands) >= 3:
                return commands

    return commands


def _looks_like_command(candidate: str) -> bool:
    normalized_candidate = candidate.strip().lower()
    if not normalized_candidate or normalized_candidate.startswith("所属章节："):
        return False
    if any(
        normalized_candidate == prefix or normalized_candidate.startswith(f"{prefix} ")
        for prefix in COMMAND_PREFIXES
    ):
        return True
    return bool(
        re.search(r"[|><=/-]", normalized_candidate)
        and re.search(r"[a-z]", normalized_candidate)
    )


def _extract_supporting_sentences(question: str, text: str, *, limit: int) -> list[str]:
    candidates: list[str] = []
    in_code_block = False

    for line in str(text or "").splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("```"):
            in_code_block = not in_code_block
            continue
        if in_code_block or stripped.startswith("所属章节："):
            continue
        if HEADING_PATTERN.match(stripped):
            continue

        cleaned = stripped.lstrip("-* ").strip()
        if len(cleaned) < 6 or _looks_like_command(cleaned):
            continue
        candidates.append(cleaned)

    deduplicated_candidates: list[str] = []
    seen_candidates: set[str] = set()
    for candidate in candidates:
        if candidate in seen_candidates:
            continue
        seen_candidates.add(candidate)
        deduplicated_candidates.append(candidate)

    scored_candidates = sorted(
        deduplicated_candidates,
        key=lambda item: (_sentence_overlap_score(question, item), -len(item)),
        reverse=True,
    )

    selected: list[str] = []
    for candidate in scored_candidates:
        if _sentence_overlap_score(question, candidate) <= 0 and selected:
            continue
        selected.append(candidate)
        if len(selected) >= limit:
            break

    return selected


def _merge_supporting_sentences(sentences: list[str]) -> str:
    if not sentences:
        return ""
    normalized_parts: list[str] = []
    for sentence in sentences:
        cleaned = sentence.strip().rstrip("。；;")
        if cleaned:
            normalized_parts.append(cleaned)
    return "；".join(normalized_parts)


def _fallback_answer_points(retrieved_chunks: list[RetrievedChunk]) -> list[str]:
    points: list[str] = []
    for chunk in retrieved_chunks[:3]:
        excerpt = chunk.text.strip().replace("\n", " ")
        if not excerpt:
            continue
        points.append(_ensure_sentence(excerpt[:120]))
    return points


def _looks_like_step_question(question: str) -> bool:
    normalized_question = str(question or "")
    return any(
        marker in normalized_question
        for marker in ("怎么", "如何", "步骤", "排查", "定位", "处理", "查看")
    )


def _ensure_sentence(text: str) -> str:
    cleaned = str(text or "").strip()
    if not cleaned:
        return ""
    if cleaned.endswith(("。", "！", "？")):
        return cleaned
    return f"{cleaned}。"


def _sentence_overlap_score(question: str, sentence: str) -> float:
    question_tokens = _tokenize(question)
    sentence_tokens = _tokenize(sentence)
    if not question_tokens or not sentence_tokens:
        return 0.0
    matched_tokens = question_tokens & sentence_tokens
    matched_weight = sum(_token_weight(token) for token in matched_tokens)
    total_weight = sum(_token_weight(token) for token in question_tokens)
    return matched_weight / max(1.0, total_weight)


def _tokenize(text: str) -> set[str]:
    return _tokenize_for_match(text)


def _token_weight(token: str) -> float:
    if re.fullmatch(r"[a-z0-9_]+", token):
        return 1.6 if len(token) <= 4 else 1.3
    if len(token) >= 4:
        return 2.2
    if len(token) == 3:
        return 1.7
    return 1.2
