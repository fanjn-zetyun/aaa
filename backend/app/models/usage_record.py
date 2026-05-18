"""UsageRecord 模型：算力用量统计。"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import DateTime, Enum, Float, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.cloud_instance import CloudInstanceType


class UsageRecord(Base):
    __tablename__ = "usage_records"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True, nullable=False)
    cloud_instance_id: Mapped[int] = mapped_column(
        ForeignKey("cloud_instances.id"), index=True, nullable=False
    )
    instance_type: Mapped[CloudInstanceType] = mapped_column(
        Enum(CloudInstanceType), nullable=False
    )
    duration_seconds: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    billing_month: Mapped[str] = mapped_column(String(7), index=True, nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )
