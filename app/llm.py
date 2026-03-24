"""LLM Provider 封装。"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Protocol

from openai import OpenAI

from app.config import AppConfig
from app.schemas import RetrievedChunk


class BaseLLMProvider(Protocol):
    """统一的大模型接口协议。"""

    def generate_answer(
        self,
        question: str,
        chat_history: list[dict[str, object]],
        retrieved_chunks: list[RetrievedChunk],
        config: AppConfig,
    ) -> str:
        """根据问题、历史和检索结果生成最终答案。"""

    def stream_answer(
        self,
        question: str,
        chat_history: list[dict[str, object]],
        retrieved_chunks: list[RetrievedChunk],
        config: AppConfig,
    ) -> Iterable[str]:
        """流式生成回答内容。"""


class OpenAICompatibleChatProvider:
    """兼容 OpenAI 风格接口的聊天模型 Provider。"""

    def __init__(self, config: AppConfig) -> None:
        if not config.llm_api_ready:
            raise ValueError(
                "LLM API 配置不完整。请检查 LLM_PROVIDER、LLM_API_KEY、"
                "LLM_API_BASE、LLM_MODEL 等环境变量。"
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
    """根据配置选择当前的大模型提供方。"""
    if config.llm_provider in {"openai", "openai_compatible"}:
        return OpenAICompatibleChatProvider(config)

    raise NotImplementedError(
        f"暂未实现 llm_provider={config.llm_provider}。"
        "后续可在此接入 Ollama、Anthropic、Gemini 或其他模型接口。"
    )


def _build_prompts(
    question: str,
    chat_history: list[dict[str, object]],
    retrieved_chunks: list[RetrievedChunk],
    config: AppConfig,
) -> tuple[str, str]:
    """统一构造 system prompt 和 user prompt。"""
    system_prompt = (
        "你是“Aurora - 软件测试知识工作台”。"
        "请仅基于系统提供的知识库片段回答问题，不要凭空编造。"
        "如果知识库信息不足，请明确说明“当前知识库中没有足够信息回答该问题”。"
        "回答请使用简洁、清晰、适合初学者阅读的中文。"
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

回答要求：
1. 只根据“知识库片段”回答。
2. 如果片段不足，请直接说明信息不足。
3. 不要在正文中伪造引用编号，引用来源由系统单独展示。
4. 尽量分点说明，但不要过度展开。
""".strip()
    return system_prompt, user_prompt


def _format_history(chat_history: list[dict[str, object]], max_turns: int) -> str:
    """把历史对话转换成便于模型理解的纯文本。"""
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
    """把检索到的片段整理为模型上下文。"""
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
