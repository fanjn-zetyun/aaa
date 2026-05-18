"""ClawInstance 相关 schema。"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field, HttpUrl

from app.models.claw_instance import ClawInstanceStatus


class ClawInstanceCreateRequest(BaseModel):
    """用户在 Web 上提交任务时的输入。"""

    github_url: HttpUrl
    paper_url: HttpUrl | None = None
    user_prompt: str | None = Field(default=None, max_length=2000)


class ClawInstanceResponse(BaseModel):
    id: int
    user_id: int
    status: ClawInstanceStatus
    pid: int | None
    workspace_path: str | None
    task_config: dict
    error_message: str | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None

    model_config = {"from_attributes": True}
