"""V2 conversation API schemas."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, HttpUrl

from app.models.conversation import ConversationStatus, ConversationTaskType, MessageRole


class LLMConfigResponse(BaseModel):
    provider: str
    base_url: str
    model: str
    max_tokens: int
    api_key_configured: bool
    updated_at: datetime | None = None


class LLMConfigUpdateRequest(BaseModel):
    provider: str = "anthropic"
    base_url: str = "https://api.anthropic.com"
    api_key: str | None = Field(default=None, min_length=1)
    model: str = "claude-sonnet-4-6"
    max_tokens: int = Field(default=4096, ge=256, le=65536)


class LLMConfigTestResponse(BaseModel):
    ok: bool
    message: str


class ConversationCreateRequest(BaseModel):
    task_type: ConversationTaskType = ConversationTaskType.REPRODUCE
    title: str | None = Field(default=None, max_length=200)
    github_url: HttpUrl | None = None
    paper_url: HttpUrl | None = None
    user_prompt: str | None = Field(default=None, max_length=4000)


class MessageCreateRequest(BaseModel):
    content: str = Field(min_length=1, max_length=8000)


class ConversationMessageResponse(BaseModel):
    id: int
    conversation_id: int
    role: MessageRole
    content: str
    message_metadata: dict
    created_at: datetime

    model_config = {"from_attributes": True}


class ConversationResponse(BaseModel):
    id: int
    user_id: int
    task_type: ConversationTaskType
    title: str
    status: ConversationStatus
    metadata_: dict = Field(serialization_alias="metadata")
    log_file_path: str | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True, "populate_by_name": True}


class ConversationDetailResponse(ConversationResponse):
    messages: list[ConversationMessageResponse] = Field(default_factory=list)


class WorkspaceFileResponse(BaseModel):
    path: str
    name: str
    kind: Literal["file", "directory", "symlink"]
    size: int | None = None
    modified_at: datetime | None = None
    depth: int = 0


class WorkspaceFileListResponse(BaseModel):
    exists: bool
    root: str
    files: list[WorkspaceFileResponse] = Field(default_factory=list)
