"""ClawInstance 模型：本地 openclaw 进程。"""

from __future__ import annotations

import enum
from datetime import UTC, datetime

from sqlalchemy import JSON, DateTime, Enum, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class ClawInstanceStatus(str, enum.Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    STOPPED = "stopped"
    FAILED = "failed"


class ClawInstance(Base):
    __tablename__ = "claw_instances"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True, nullable=False)

    pid: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[ClawInstanceStatus] = mapped_column(
        Enum(ClawInstanceStatus), default=ClawInstanceStatus.PENDING, nullable=False
    )

    workspace_path: Mapped[str | None] = mapped_column(String(512), nullable=True)
    task_config: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)

    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
