"""Request payload models for FastAPI routes."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class ChatMessageModel(BaseModel):
    role: str = Field(..., description="Message role, for example user / assistant")
    content: str = Field(..., description="Message content")


class ChatRequestModel(BaseModel):
    scene: Literal["qa_query", "troubleshooting", "onboarding", "command_lookup"] | None = Field(
        default=None
    )
    question: str = Field(..., description="User question")
    top_k: int | None = Field(default=None, ge=1, le=20)
    chat_history: list[ChatMessageModel] = Field(default_factory=list)
    tenant_id: str | None = Field(default=None, min_length=1)
    user_id: str | None = Field(default=None, min_length=1)
    project_id: str | None = Field(default=None, min_length=1)
    session_id: str | None = Field(default=None, min_length=1)
    session_title: str | None = Field(default=None)
    request_id: str | None = Field(default=None, min_length=1)


class MemoryManualWriteModel(BaseModel):
    content: str = Field(..., min_length=1)
    type: str = Field(..., pattern="^(fact|preference|decision|pending_issue)$")
    scope_type: str | None = Field(default=None, pattern="^(session|user|project|team|global)$")
    scope_id: str | None = Field(default=None, min_length=1)
    tenant_id: str | None = Field(default=None, min_length=1)
    user_id: str | None = Field(default=None, min_length=1)
    project_id: str | None = Field(default=None, min_length=1)
    session_id: str | None = Field(default=None, min_length=1)
    session_title: str | None = Field(default=None)
    request_id: str | None = Field(default=None, min_length=1)
    team_id: str | None = Field(default=None, min_length=1)
    global_scope_id: str | None = Field(default=None, min_length=1)
    confirmed: bool = Field(default=False)
    source_kind: str = Field(default="chat", min_length=1)
    subject_key: str | None = Field(default=None, min_length=1)
    fact_key: str | None = Field(default=None, min_length=1)
    correction_of: str | None = Field(default=None, min_length=1)
    source_type: str | None = Field(
        default=None,
        pattern="^(user_confirmed|model_inferred|imported|system_generated)$",
    )
    source_confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    reviewed_by_human: bool | None = Field(default=None)
    consistency_group_id: str | None = Field(default=None, min_length=1)


class MemoryStatusUpdateModel(BaseModel):
    status: str = Field(..., pattern="^(active|stale|superseded|deleted|conflict_pending_review)$")
    tenant_id: str | None = Field(default=None, min_length=1)
    user_id: str | None = Field(default=None, min_length=1)
    project_id: str | None = Field(default=None, min_length=1)
    session_id: str | None = Field(default=None, min_length=1)
    request_id: str | None = Field(default=None, min_length=1)
    team_id: str | None = Field(default=None, min_length=1)
    global_scope_id: str | None = Field(default=None, min_length=1)


class MemoryRetrievalPreviewModel(BaseModel):
    scene: Literal["qa_query", "troubleshooting", "onboarding", "command_lookup"] | None = Field(
        default=None
    )
    question: str = Field(..., min_length=1)
    top_k: int | None = Field(default=None, ge=1, le=10)
    retrieval_mode: Literal["exact_scope_only", "ranked", "ranked_with_fallback"] | None = Field(
        default=None
    )
    tenant_id: str | None = Field(default=None, min_length=1)
    user_id: str | None = Field(default=None, min_length=1)
    project_id: str | None = Field(default=None, min_length=1)
    session_id: str | None = Field(default=None, min_length=1)
    request_id: str | None = Field(default=None, min_length=1)
    team_id: str | None = Field(default=None, min_length=1)
    global_scope_id: str | None = Field(default=None, min_length=1)


class MemoryLifecycleMaintenanceModel(BaseModel):
    tenant_id: str | None = Field(default=None, min_length=1)
    request_id: str | None = Field(default=None, min_length=1)
    limit: int = Field(default=100, ge=1, le=500)
    dry_run: bool = Field(default=False)


class ProviderResolveModel(BaseModel):
    provider: str | None = Field(default=None, min_length=1)
    model: str | None = Field(default=None, min_length=1)


class ProviderDryRunModel(BaseModel):
    provider: str | None = Field(default=None, min_length=1)
    model: str | None = Field(default=None, min_length=1)
    scene: Literal["qa_query", "troubleshooting", "onboarding", "command_lookup"] | None = Field(
        default=None
    )
    question: str = Field(..., min_length=1)
    top_k: int | None = Field(default=None, ge=1, le=20)
    chat_history: list[ChatMessageModel] = Field(default_factory=list)
    tenant_id: str | None = Field(default=None, min_length=1)
    user_id: str | None = Field(default=None, min_length=1)
    project_id: str | None = Field(default=None, min_length=1)
    session_id: str | None = Field(default=None, min_length=1)
    session_title: str | None = Field(default=None)
    request_id: str | None = Field(default=None, min_length=1)
    team_id: str | None = Field(default=None, min_length=1)
    global_scope_id: str | None = Field(default=None, min_length=1)
    include_raw_response: bool = Field(default=False)


class SettingsUpdateModel(BaseModel):
    values: dict[str, Any]


class DocumentsDeleteModel(BaseModel):
    document_ids: list[str] = Field(default_factory=list, min_length=1)


class DocumentRenameModel(BaseModel):
    document_id: str = Field(..., min_length=1)
    new_name: str = Field(..., min_length=1)


class DocumentMetadataUpdateModel(BaseModel):
    document_ids: list[str] = Field(default_factory=list, min_length=1)
    theme: str | None = None
    tags: list[str] | None = None


class KnowledgeBaseRunModel(BaseModel):
    mode: str = Field(default="sync", pattern="^(sync|scan|reset)$")
