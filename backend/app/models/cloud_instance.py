"""CloudInstance 模型：Lab4AI 远程云实例。"""

from __future__ import annotations

import enum
from datetime import UTC, datetime

from sqlalchemy import JSON, DateTime, Enum, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class CloudInstanceType(str, enum.Enum):
    CPU = "CPU"
    GPU = "GPU"


class CloudInstanceStatus(str, enum.Enum):
    RUNNING = "running"
    STOPPED = "stopped"


class CloudInstance(Base):
    __tablename__ = "cloud_instances"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True, nullable=False)
    conversation_id: Mapped[int | None] = mapped_column(
        ForeignKey("conversations.id"), index=True, nullable=True
    )

    server_id: Mapped[str] = mapped_column(String(128), unique=True, index=True, nullable=False)
    instance_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    instance_type: Mapped[CloudInstanceType] = mapped_column(
        Enum(CloudInstanceType), nullable=False
    )
    gpu_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    ssh_host: Mapped[str | None] = mapped_column(String(128), nullable=True)
    ssh_port: Mapped[int | None] = mapped_column(Integer, nullable=True)
    ssh_user: Mapped[str | None] = mapped_column(String(64), nullable=True)
    ssh_pass: Mapped[str | None] = mapped_column(String(256), nullable=True)

    status: Mapped[CloudInstanceStatus] = mapped_column(
        Enum(CloudInstanceStatus), default=CloudInstanceStatus.RUNNING, nullable=False
    )
    raw_payload: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)

    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )
    stopped_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
