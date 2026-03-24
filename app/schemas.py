"""项目内部通用数据结构。"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class RetrievedChunk:
    """统一封装检索到的文本片段。"""

    file_name: str
    source_path: str
    text: str
    score: float | None


@dataclass(slots=True)
class Citation:
    """回答引用来源。"""

    file_name: str
    source_path: str
    snippet: str
    score: float | None


@dataclass(slots=True)
class ChatResult:
    """一次问答的完整结果。"""

    answer: str
    citations: list[Citation]
    retrieved_count: int


@dataclass(slots=True)
class KnowledgeBaseStats:
    """知识库重建结果统计。"""

    document_count: int
    chunk_count: int


@dataclass(slots=True)
class DocumentSummary:
    """文档展示摘要。"""

    name: str
    path: str
    extension: str
    size_bytes: int
    updated_at: str


@dataclass(slots=True)
class SystemOverview:
    """系统总览信息。"""

    app_name: str
    app_version: str
    data_dir: str
    db_dir: str
    logs_dir: str
    llm_provider: str
    embedding_provider: str
    llm_api_ready: bool
    embedding_api_ready: bool
    knowledge_base_ready: bool
    source_file_count: int
    chunk_count: int


@dataclass(slots=True)
class AppSettings:
    """可编辑的应用配置。"""

    llm_provider: str
    embedding_provider: str
    llm_api_key: str
    llm_api_base: str
    llm_model: str
    llm_temperature: float
    llm_timeout: float
    llm_max_tokens: int
    embedding_api_key: str
    embedding_api_base: str
    embedding_model: str
    chunk_size: int
    chunk_overlap: int
    top_k: int
    max_history_turns: int
    collection_name: str
    log_level: str
    api_host: str
    api_port: int
    cors_origins: str
