"""项目内部通用数据结构。"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class RetrievedChunk:
    """统一封装检索到的文本片段。"""

    file_name: str
    source_path: str
    text: str
    score: float | None
    vector_score: float | None = None
    lexical_score: float = 0.0
    theme: str = ""
    tags: list[str] = field(default_factory=list)


@dataclass(slots=True)
class Citation:
    """回答引用来源。"""

    file_name: str
    source_path: str
    snippet: str
    full_text: str
    score: float | None
    vector_score: float | None = None
    lexical_score: float = 0.0
    theme: str = ""
    tags: list[str] = field(default_factory=list)


@dataclass(slots=True)
class ChatResult:
    """一次问答的完整结果。"""

    answer: str
    citations: list[Citation]
    retrieved_count: int
    retrieval_ms: float = 0.0
    generation_ms: float = 0.0
    total_ms: float = 0.0
    rewritten_question: str = ""
    retrieval_query: str = ""
    confidence: float = 0.0


@dataclass(slots=True)
class KnowledgeBaseStats:
    """知识库构建结果统计。"""

    document_count: int
    chunk_count: int
    indexed_count: int = 0
    changed_count: int = 0
    pending_count: int = 0
    failed_count: int = 0
    removed_count: int = 0
    skipped_count: int = 0
    job_id: str = ""


@dataclass(slots=True)
class KnowledgeBaseJob:
    """知识库任务状态。"""

    job_id: str
    status: str
    stage: str
    progress: float
    message: str
    total_documents: int = 0
    processed_documents: int = 0
    total_chunks: int = 0
    processed_chunks: int = 0
    started_at: str = ""
    finished_at: str = ""
    error: str = ""
    cancel_requested: bool = False
    stats: KnowledgeBaseStats | None = None


@dataclass(slots=True)
class DocumentSummary:
    """文档展示摘要。"""

    name: str
    path: str
    relative_path: str
    extension: str
    size_bytes: int
    updated_at: str
    status: str
    theme: str
    tags: list[str]
    content_hash: str = ""
    indexed_hash: str = ""
    chunk_count: int = 0
    citation_count: int = 0
    last_indexed_at: str = ""
    last_error: str = ""


@dataclass(slots=True)
class DocumentDeleteResult:
    """文档删除结果。"""

    deleted_paths: list[str]
    missing_paths: list[str]


@dataclass(slots=True)
class DocumentRenameResult:
    """文档重命名结果。"""

    old_path: str
    new_path: str
    new_name: str


@dataclass(slots=True)
class KnowledgeGraphNode:
    """知识图谱节点。"""

    id: str
    label: str
    node_type: str
    size: int
    meta: dict[str, object]


@dataclass(slots=True)
class KnowledgeGraphEdge:
    """知识图谱边。"""

    source: str
    target: str
    label: str
    weight: int


@dataclass(slots=True)
class KnowledgeGraph:
    """知识图谱视图。"""

    nodes: list[KnowledgeGraphNode]
    edges: list[KnowledgeGraphEdge]
    summary: dict[str, object]


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
    indexed_file_count: int = 0
    changed_file_count: int = 0
    pending_file_count: int = 0
    failed_file_count: int = 0
    active_job_status: str = ""
    active_job_progress: float = 0.0


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
    no_answer_min_score: float
    collection_name: str
    log_level: str
    api_host: str
    api_port: int
    cors_origins: str


@dataclass(slots=True)
class ConnectionCheckResult:
    """单个配置连通性测试结果。"""

    ok: bool
    latency_ms: float
    message: str


@dataclass(slots=True)
class SettingsConnectionReport:
    """配置连通性测试报告。"""

    llm: ConnectionCheckResult
    embedding: ConnectionCheckResult
    checked_at: str
