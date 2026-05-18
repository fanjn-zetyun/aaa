"""Lab4AI 凭证读写：从 admin_settings 表加载 / 保存（加密）。"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import decrypt_credential, encrypt_credential
from app.models import AdminSetting

KEY_PHONE = "lab4ai.phone"
KEY_PASSWORD = "lab4ai.password"


@dataclass(slots=True)
class Lab4AICredentials:
    phone: str
    password: str


async def _get_setting(session: AsyncSession, key: str) -> str | None:
    setting = await session.get(AdminSetting, key)
    return setting.value if setting else None


async def _set_setting(session: AsyncSession, key: str, value: str) -> None:
    setting = await session.get(AdminSetting, key)
    if setting is None:
        session.add(AdminSetting(key=key, value=value))
    else:
        setting.value = value


async def load_lab4ai_credentials(session: AsyncSession) -> Lab4AICredentials | None:
    phone_enc = await _get_setting(session, KEY_PHONE)
    password_enc = await _get_setting(session, KEY_PASSWORD)
    if not phone_enc or not password_enc:
        return None
    try:
        return Lab4AICredentials(
            phone=decrypt_credential(phone_enc),
            password=decrypt_credential(password_enc),
        )
    except ValueError:
        return None


async def save_lab4ai_credentials(
    session: AsyncSession, phone: str, password: str
) -> Lab4AICredentials:
    await _set_setting(session, KEY_PHONE, encrypt_credential(phone))
    await _set_setting(session, KEY_PASSWORD, encrypt_credential(password))
    await session.commit()
    return Lab4AICredentials(phone=phone, password=password)
