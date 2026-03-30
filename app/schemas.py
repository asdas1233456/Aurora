"""项目内部通用数据结构。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal


ScopeType = Literal["session", "user", "project", "team", "global"]
MemoryFactType = Literal["fact", "preference", "decision", "pending_issue"]
MemoryFactStatus = Literal["active", "stale", "superseded", "deleted", "conflict_pending_review"]
MemorySourceType = Literal["user_confirmed", "model_inferred", "imported", "system_generated"]
ConsistencyOperation = Literal["insert", "update", "correction", "conflict", "coexist", "noop"]
MemoryAuditAction = Literal[
    "create",
    "read",
    "retrieve",
    "inject",
    "update",
    "correct",
    "deprecate",
    "archive",
    "redact",
    "delete",
]
RetentionLevel = Literal["critical", "high", "normal", "low", "temporary"]
RetrievalVisibility = Literal["normal", "deprioritized", "hidden_from_default", "archive_only"]
ForgettingStatus = Literal["none", "cooling", "expired", "archived"]
PolicyDecisionState = Literal["allow", "deny", "redact", "review", "fallback", "throttle", "observe"]
SecurityEventType = Literal[
    "sensitive_memory_detected",
    "unauthorized_scope_write_attempt",
    "suspicious_prompt_injection",
    "abnormal_retrieval_volume",
    "policy_blocked_write",
    "provider_failure_fallback",
    "rate_limit_triggered",
]
SecuritySeverity = Literal["low", "medium", "high", "critical"]
SecurityEventStatus = Literal["open", "acknowledged", "resolved", "ignored"]
ContentSafetyAction = Literal["allow", "block", "redact", "review"]
RetentionAuditAction = Literal[
    "initialized",
    "evaluated",
    "deprioritized",
    "hidden_from_default",
    "expired",
    "archived",
    "restored",
    "accessed",
    "successful_use",
]
ChatMessageRole = Literal["user", "assistant", "system", "tool"]
BusinessScene = Literal["qa_query", "troubleshooting", "onboarding", "command_lookup"]
OutputStyle = Literal["structured", "concise", "step_by_step"]
FallbackBehavior = Literal["say_insufficient_context", "best_effort", "ask_for_more_context"]


@dataclass(slots=True)
class RetrievedChunk:
    """统一封装检索到的文本片段。"""

    document_id: str
    file_name: str
    source_path: str
    relative_path: str
    text: str
    score: float | None
    vector_score: float | None = None
    lexical_score: float = 0.0
    theme: str = ""
    tags: list[str] = field(default_factory=list)


@dataclass(slots=True)
class Citation:
    """回答引用来源。"""

    knowledge_id: str
    document_id: str
    file_name: str
    source_path: str
    relative_path: str
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
    memory_count: int = 0
    retrieval_ms: float = 0.0
    generation_ms: float = 0.0
    total_ms: float = 0.0
    rewritten_question: str = ""
    retrieval_query: str = ""
    confidence: float = 0.0
    summary: str = ""
    steps: list[str] = field(default_factory=list)
    used_memory_ids: list[str] = field(default_factory=list)
    used_knowledge_ids: list[str] = field(default_factory=list)
    provider: str = ""
    model: str = ""
    raw_response: dict[str, object] | None = None
    error_info: "BusinessErrorInfo | None" = None


@dataclass(slots=True)
class ConversationTurn:
    """Provider-independent conversation turn."""

    role: str
    content: str


@dataclass(slots=True)
class MemoryContextItem:
    """Memory context passed into the business request."""

    memory_id: str
    scope_type: ScopeType
    scope_id: str
    memory_type: MemoryFactType
    content: str
    subject_key: str = ""
    fact_key: str = ""
    version: int = 1
    source_type: MemorySourceType = "system_generated"
    retrieval_score: float = 0.0
    matched_reason: str = ""


@dataclass(slots=True)
class KnowledgeContextItem:
    """Knowledge evidence passed into the business request."""

    knowledge_id: str
    document_id: str
    file_name: str
    source_path: str
    relative_path: str
    content: str
    score: float | None
    theme: str = ""
    tags: list[str] = field(default_factory=list)


@dataclass(slots=True)
class OutputContract:
    """Business-level output contract for providers."""

    must_include_answer: bool = True
    must_include_citations: bool = True
    preferred_style: OutputStyle = "structured"
    fallback_behavior: FallbackBehavior = "say_insufficient_context"
    required_sections: list[str] = field(default_factory=list)
    scene_specific_rules: list[str] = field(default_factory=list)
    refusal_behavior: str = "acknowledge_limits_without_fabrication"


@dataclass(slots=True)
class GenerationConfig:
    """Generation settings passed through the business contract."""

    temperature: float = 0.2
    max_tokens: int = 2048
    timeout_seconds: float = 60.0
    stream: bool = False
    provider_session_id: str = ""


@dataclass(slots=True)
class BusinessRequest:
    """Aurora business-layer request contract."""

    scene: BusinessScene
    user_query: str
    system_instruction: str
    conversation_context: list[ConversationTurn]
    memory_context: list[MemoryContextItem]
    knowledge_context: list[KnowledgeContextItem]
    output_contract: OutputContract
    safety_rules: list[str]
    generation_config: GenerationConfig
    request_metadata: dict[str, object] = field(default_factory=dict)


@dataclass(slots=True)
class BusinessErrorInfo:
    """Sanitized business-layer error details."""

    code: str
    message: str
    retryable: bool = False
    details: dict[str, object] = field(default_factory=dict)


@dataclass(slots=True)
class BusinessResponse:
    """Aurora business-layer response contract."""

    answer: str
    citations: list[Citation]
    confidence: float
    used_memory_ids: list[str]
    used_knowledge_ids: list[str]
    provider: str
    model: str
    summary: str = ""
    steps: list[str] = field(default_factory=list)
    raw_response: dict[str, object] | None = None
    error_info: BusinessErrorInfo | None = None


@dataclass(slots=True)
class KnowledgeBaseStats:
    """知识库构建结果统计。"""

    document_count: int
    chunk_count: int
    mode: str = "sync"
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
    mode: str
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

    document_id: str
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

    deleted_ids: list[str]
    deleted_paths: list[str]
    missing_ids: list[str]
    missing_paths: list[str]


@dataclass(slots=True)
class DocumentRenameResult:
    """文档重命名结果。"""

    document_id: str
    old_path: str
    new_path: str
    old_relative_path: str
    new_relative_path: str
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


@dataclass(slots=True)
class ScopeRef:
    """A resolved memory scope that a request can access."""

    scope_type: ScopeType
    scope_id: str


@dataclass(slots=True)
class MemoryRequestContext:
    """Normalized request context used by memory isolation services."""

    request_id: str
    tenant_id: str
    user_id: str
    project_id: str
    session_id: str
    team_id: str = "team_default"
    global_scope_id: str = "global_default"
    actor_role: str = "conversation"
    allow_shared_scope_write: bool = False
    allow_global_write: bool = False


@dataclass(slots=True)
class ResolvedScopeContext:
    """Request context plus the scopes that were resolved for it."""

    request_context: MemoryRequestContext
    allowed_scopes: tuple[ScopeRef, ...]


@dataclass(slots=True)
class ChatSessionRecord:
    """Session shell record used for memory isolation and auditing."""

    id: str
    tenant_id: str
    user_id: str
    project_id: str
    title: str
    status: str
    created_at: str
    last_active_at: str


@dataclass(slots=True)
class ChatMessageRecord:
    """Raw persisted chat message used for recovery and audit."""

    id: str
    tenant_id: str
    session_id: str
    user_id: str
    role: ChatMessageRole
    content: str
    provider: str
    model: str
    citations_json: str
    metadata_json: str
    created_at: str


@dataclass(slots=True)
class ChatMessageCreate:
    """Validated input for writing a raw chat message."""

    tenant_id: str
    session_id: str
    user_id: str
    role: ChatMessageRole
    content: str
    provider: str = ""
    model: str = ""
    citations_json: str = "[]"
    metadata_json: str = "{}"


@dataclass(slots=True)
class SessionRecoverySnapshot:
    """Recovered session shell plus the recent persisted message window."""

    session: ChatSessionRecord | None
    messages: list[ChatMessageRecord]
    restored_from_persistence: bool


@dataclass(slots=True)
class MemoryFact:
    """A distilled memory fact, separate from raw chat messages and KB docs."""

    id: str
    tenant_id: str
    owner_user_id: str
    project_id: str
    scope_type: ScopeType
    scope_id: str
    type: MemoryFactType
    content: str
    status: MemoryFactStatus
    source_session_id: str
    created_at: str
    updated_at: str
    subject_key: str = ""
    fact_key: str = ""
    version: int = 1
    superseded_by: str | None = None
    supersedes: str | None = None
    correction_of: str | None = None
    source_type: MemorySourceType = "system_generated"
    source_confidence: float = 0.0
    reviewed_by_human: bool | None = None
    consistency_group_id: str | None = None
    value_score: float = 0.0
    retention_level: RetentionLevel = "normal"
    ttl_seconds: int | None = None
    expires_at: str | None = None
    last_accessed_at: str | None = None
    access_count: int = 0
    successful_use_count: int = 0
    decay_factor: float = 1.0
    archived_at: str | None = None
    retrieval_visibility: RetrievalVisibility = "normal"
    forgetting_status: ForgettingStatus = "none"
    next_evaluation_at: str | None = None
    retention_policy_id: str | None = None
    archive_bucket: str | None = None


@dataclass(slots=True)
class MemoryFactCreate:
    """Validated input for creating a memory fact."""

    tenant_id: str
    owner_user_id: str
    project_id: str
    scope_type: ScopeType
    scope_id: str
    type: MemoryFactType
    content: str
    source_session_id: str
    status: MemoryFactStatus = "active"
    source_kind: str = "chat"
    confirmed: bool = False
    subject_key: str | None = None
    fact_key: str | None = None
    version: int | None = None
    superseded_by: str | None = None
    supersedes: str | None = None
    correction_of: str | None = None
    source_type: MemorySourceType | None = None
    source_confidence: float = 0.0
    reviewed_by_human: bool | None = None
    consistency_group_id: str | None = None
    value_score: float | None = None
    retention_level: RetentionLevel | None = None
    ttl_seconds: int | None = None
    expires_at: str | None = None
    last_accessed_at: str | None = None
    access_count: int = 0
    successful_use_count: int = 0
    decay_factor: float | None = None
    archived_at: str | None = None
    retrieval_visibility: RetrievalVisibility | None = None
    forgetting_status: ForgettingStatus | None = None
    next_evaluation_at: str | None = None
    retention_policy_id: str | None = None
    archive_bucket: str | None = None


@dataclass(slots=True)
class ResolvedMemoryFactIdentity:
    """Resolved identity fields that make a free-form memory governable."""

    subject_key: str
    fact_key: str
    consistency_group_id: str
    source_type: MemorySourceType
    source_confidence: float
    reviewed_by_human: bool | None = None
    allows_coexistence: bool = False
    fact_family: str = ""


@dataclass(slots=True)
class ConsistencyCheckResult:
    """Consistency classification for an incoming memory write."""

    operation: ConsistencyOperation
    subject_key: str
    fact_key: str
    consistency_group_id: str
    status: MemoryFactStatus
    reason: str
    current_fact: MemoryFact | None = None
    correction_target: MemoryFact | None = None
    related_active_facts: list[MemoryFact] = field(default_factory=list)


@dataclass(slots=True)
class MemoryWriteResult:
    """Structured result returned by the consistency-aware write pipeline."""

    memory_fact: MemoryFact
    operation: ConsistencyOperation
    reason: str
    subject_key: str
    fact_key: str
    consistency_group_id: str
    superseded_fact_ids: list[str] = field(default_factory=list)
    hidden_by_scope_fact_ids: list[str] = field(default_factory=list)


@dataclass(slots=True)
class RetentionPolicySnapshot:
    """Resolved retention policy for a memory fact."""

    policy_id: str
    ttl_seconds: int | None
    decay_factor: float
    retention_level: RetentionLevel
    retrieval_visibility: RetrievalVisibility = "normal"
    archive_after_seconds: int | None = None
    cooling_after_seconds: int | None = None
    expires_after_seconds: int | None = None
    archive_bucket: str | None = None


@dataclass(slots=True)
class MemoryValueAssessment:
    """Transparent rule-based value evaluation result."""

    value_score: float
    scope_value: float
    type_value: float
    recency_value: float
    usage_value: float
    source_value: float
    correction_penalty: float
    expiration_penalty: float
    retention_level: RetentionLevel
    ttl_seconds: int | None
    expires_at: str | None
    decay_factor: float
    next_evaluation_at: str | None
    retention_policy_id: str | None = None
    archive_bucket: str | None = None
    reasons: tuple[str, ...] = ()


@dataclass(slots=True)
class ForgettingDecision:
    """Planner output describing how a memory should leave or stay in the hot path."""

    retrieval_visibility: RetrievalVisibility
    forgetting_status: ForgettingStatus
    archived_at: str | None
    next_evaluation_at: str | None
    action: str
    reason: str
    reasons: tuple[str, ...] = ()
    archive_bucket: str | None = None


@dataclass(slots=True)
class LifecycleMaintenanceReport:
    """Summary returned by lifecycle maintenance runs."""

    evaluated_count: int
    updated_count: int
    unchanged_count: int
    deprioritized_count: int
    hidden_count: int
    expired_count: int
    archived_count: int
    dry_run: bool = False
    touched_memory_ids: list[str] = field(default_factory=list)


@dataclass(slots=True)
class MemoryAccessAuditRecord:
    """Audit record for memory read/write activity."""

    id: str
    tenant_id: str
    request_id: str
    memory_fact_id: str
    action: MemoryAuditAction
    actor_user_id: str
    session_id: str
    created_at: str
    scope_type: str = ""
    retrieval_stage: str = ""
    decision_reason: str = ""


@dataclass(slots=True)
class MemoryRetentionAuditRecord:
    """Audit record for retention and forgetting decisions."""

    id: str
    tenant_id: str
    memory_fact_id: str
    action: RetentionAuditAction
    reason: str
    value_score: float
    retention_level: RetentionLevel
    retrieval_visibility: RetrievalVisibility
    forgetting_status: ForgettingStatus
    policy_id: str
    details_json: str
    created_at: str


@dataclass(slots=True)
class PolicyDecisionRecord:
    """Persisted policy decision used for governance explainability."""

    id: str
    request_id: str
    policy_name: str
    decision: PolicyDecisionState
    reason: str
    target_type: str
    target_id: str
    payload_json: str
    created_at: str


@dataclass(slots=True)
class SecurityEventRecord:
    """Persisted security governance event."""

    id: str
    tenant_id: str
    event_type: SecurityEventType
    severity: SecuritySeverity
    actor_user_id: str
    session_id: str
    target_memory_fact_id: str | None
    request_id: str
    event_payload_json: str
    status: SecurityEventStatus
    created_at: str
    resolved_at: str | None = None


@dataclass(slots=True)
class SystemMetricSnapshotRecord:
    """Persisted metric sample that future admin tooling can aggregate."""

    id: str
    metric_name: str
    metric_value: float
    dimensions_json: str
    captured_at: str


@dataclass(slots=True)
class PolicyEvaluation:
    """In-process policy result returned by governance components."""

    policy_name: str
    decision: PolicyDecisionState
    reason: str
    allowed: bool
    severity: SecuritySeverity = "low"
    payload: dict[str, object] = field(default_factory=dict)


@dataclass(slots=True)
class ContentSafetyFinding:
    """Single sensitive-content match returned by the guard."""

    rule_id: str
    category: str
    action: ContentSafetyAction
    match_text: str
    redacted_text: str = ""


@dataclass(slots=True)
class ContentSafetyDecision:
    """Guard result used before memory enters long-term storage."""

    action: ContentSafetyAction
    reason: str
    sanitized_content: str
    findings: list[ContentSafetyFinding] = field(default_factory=list)
    severity: SecuritySeverity = "low"
    requires_review: bool = False


@dataclass(slots=True)
class RateLimitDecision:
    """Operational protection decision for high-cost memory actions."""

    action_name: str
    allowed: bool
    reason: str
    limited_scope: str = ""
    retry_after_seconds: int = 0
    limit: int = 0
    window_seconds: int = 0


@dataclass(slots=True)
class StorageInspectionReport:
    """Basic persistence health snapshot for local inspection."""

    table_status: dict[str, bool]
    session_count: int
    message_count: int
    memory_count: int
    memory_count_by_scope: dict[str, int]
