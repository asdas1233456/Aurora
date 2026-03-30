"""Request payload models for FastAPI routes."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class ChatMessageModel(BaseModel):
    role: str = Field(..., description="消息角色，例如 user / assistant")
    content: str = Field(..., description="消息内容")


class ChatRequestModel(BaseModel):
    question: str = Field(..., description="用户问题")
    top_k: int | None = Field(default=None, ge=1, le=20)
    chat_history: list[ChatMessageModel] = Field(default_factory=list)


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
