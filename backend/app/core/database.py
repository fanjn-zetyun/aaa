"""异步 SQLAlchemy 引擎与会话。"""

from __future__ import annotations

from collections.abc import AsyncIterator

from sqlalchemy import inspect, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from .config import get_settings


class Base(DeclarativeBase):
    pass


_settings = get_settings()

engine = create_async_engine(
    _settings.database_url,
    echo=_settings.app_debug,
    future=True,
)

SessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)


async def get_session() -> AsyncIterator[AsyncSession]:
    async with SessionLocal() as session:
        yield session


async def init_db() -> None:
    """开发模式下首次启动时建表（生产环境应使用 Alembic 迁移）。"""
    # 触发模型注册
    from app.models import (  # noqa: F401
        admin_settings,
        cloud_instance,
        conversation,
        usage_record,
        user,
        user_memory,
    )

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.run_sync(_ensure_compatible_schema)


def _ensure_compatible_schema(sync_conn) -> None:
    """Small development migration for SQLite databases created before Alembic."""
    inspector = inspect(sync_conn)
    if "users" not in inspector.get_table_names():
        return
    user_columns = {column["name"] for column in inspector.get_columns("users")}
    if "institution" not in user_columns:
        sync_conn.execute(
            text("ALTER TABLE users ADD COLUMN institution VARCHAR(128) NOT NULL DEFAULT ''")
        )
    if "cloud_instances" in inspector.get_table_names():
        cloud_columns = {column["name"] for column in inspector.get_columns("cloud_instances")}
        for column_name, definition in (
            ("conversation_id", "INTEGER"),
            ("instance_id", "VARCHAR(128)"),
            ("ssh_user", "VARCHAR(64)"),
            ("ssh_pass", "VARCHAR(256)"),
            ("raw_payload", "JSON NOT NULL DEFAULT '{}'"),
        ):
            if column_name not in cloud_columns:
                sync_conn.execute(
                    text(f"ALTER TABLE cloud_instances ADD COLUMN {column_name} {definition}")
                )
