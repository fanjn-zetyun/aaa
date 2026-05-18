"""管理员路由：用户管理、Lab4AI 凭证配置、全局实例查看。"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select

from app.api.deps import AdminUser, DbSession
from app.models import ClawInstance, CloudInstance, User
from app.schemas.auth import UserResponse
from app.schemas.claw_instance import ClawInstanceResponse
from app.services.lab4ai.credentials import load_lab4ai_credentials, save_lab4ai_credentials

router = APIRouter(prefix="/api/admin", tags=["admin"])


# --- 用户管理 ---


class QuotaUpdateRequest(BaseModel):
    gpu_quota_hours: float | None = None
    cpu_quota_hours: float | None = None


@router.get("/users", response_model=list[UserResponse])
async def list_users(_admin: AdminUser, session: DbSession) -> list[User]:
    result = await session.execute(select(User).order_by(User.created_at.desc()))
    return list(result.scalars().all())


@router.put("/users/{user_id}/quota", response_model=UserResponse)
async def update_user_quota(
    user_id: int, payload: QuotaUpdateRequest, _admin: AdminUser, session: DbSession
) -> User:
    user = await session.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="用户不存在")
    if payload.gpu_quota_hours is not None:
        user.gpu_quota_hours = payload.gpu_quota_hours
    if payload.cpu_quota_hours is not None:
        user.cpu_quota_hours = payload.cpu_quota_hours
    await session.commit()
    await session.refresh(user)
    return user


# --- Lab4AI 凭证 ---


class Lab4AICredentialRequest(BaseModel):
    phone: str
    password: str


class Lab4AICredentialResponse(BaseModel):
    phone_masked: str
    configured: bool


@router.get("/settings/lab4ai", response_model=Lab4AICredentialResponse)
async def get_lab4ai_settings(_admin: AdminUser, session: DbSession) -> dict:
    creds = await load_lab4ai_credentials(session)
    if creds is None:
        return {"phone_masked": "", "configured": False}
    masked = creds.phone[:3] + "****" + creds.phone[-4:] if len(creds.phone) >= 7 else "***"
    return {"phone_masked": masked, "configured": True}


@router.put("/settings/lab4ai", response_model=Lab4AICredentialResponse)
async def set_lab4ai_settings(
    payload: Lab4AICredentialRequest, _admin: AdminUser, session: DbSession
) -> dict:
    creds = await save_lab4ai_credentials(session, payload.phone, payload.password)
    masked = creds.phone[:3] + "****" + creds.phone[-4:] if len(creds.phone) >= 7 else "***"
    return {"phone_masked": masked, "configured": True}


# --- 全局实例查看 ---


@router.get("/claw-instances", response_model=list[ClawInstanceResponse])
async def list_all_claw_instances(_admin: AdminUser, session: DbSession) -> list[ClawInstance]:
    result = await session.execute(
        select(ClawInstance).order_by(ClawInstance.created_at.desc())
    )
    return list(result.scalars().all())


@router.get("/cloud-instances")
async def list_all_cloud_instances(_admin: AdminUser, session: DbSession) -> list[dict]:
    result = await session.execute(
        select(CloudInstance).order_by(CloudInstance.started_at.desc())
    )
    instances = result.scalars().all()
    return [
        {
            "id": i.id,
            "user_id": i.user_id,
            "server_id": i.server_id,
            "instance_type": i.instance_type.value,
            "gpu_count": i.gpu_count,
            "status": i.status.value,
            "started_at": i.started_at.isoformat() if i.started_at else None,
            "stopped_at": i.stopped_at.isoformat() if i.stopped_at else None,
        }
        for i in instances
    ]
