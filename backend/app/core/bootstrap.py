"""启动时自检：创建默认 admin（如果不存在）。"""

from __future__ import annotations

import logging

from sqlalchemy import select

from app.core.config import get_settings
from app.core.database import SessionLocal
from app.core.security import hash_password
from app.models import User, UserRole

logger = logging.getLogger(__name__)


async def ensure_default_admin() -> None:
    settings = get_settings()
    async with SessionLocal() as session:
        existing_admin = await session.scalar(
            select(User).where(User.role == UserRole.ADMIN).limit(1)
        )
        if existing_admin is not None:
            return

        same_name = await session.scalar(
            select(User).where(User.username == settings.default_admin_username)
        )
        if same_name is not None:
            logger.warning(
                "默认 admin 用户名 %r 已被占用但角色不是 admin，跳过自动创建",
                settings.default_admin_username,
            )
            return

        admin = User(
            username=settings.default_admin_username,
            password_hash=hash_password(settings.default_admin_password),
            role=UserRole.ADMIN,
        )
        session.add(admin)
        await session.commit()
        logger.warning(
            "已创建默认 admin: username=%s （请尽快登录后修改密码）",
            settings.default_admin_username,
        )
