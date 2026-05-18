"""云实例路由：查看当前用户的 Lab4AI 云实例 + 手动关停。"""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select

from app.api.deps import CurrentUser, DbSession
from app.models import CloudInstance, CloudInstanceStatus
from app.services.lab4ai.client import list_instances, stop_instance
from app.services.lab4ai.credentials import load_lab4ai_credentials

router = APIRouter(prefix="/api/cloud-instances", tags=["cloud-instances"])


class CloudInstanceResponse(BaseModel):
    id: int
    server_id: str
    instance_type: str
    gpu_count: int
    ssh_host: str | None
    ssh_port: int | None
    status: str
    started_at: datetime
    stopped_at: datetime | None

    model_config = {"from_attributes": True}


@router.get("", response_model=list[CloudInstanceResponse])
async def list_cloud_instances(user: CurrentUser, session: DbSession) -> list[CloudInstance]:
    """获取当前用户的云实例列表（从数据库记录中过滤）。"""
    result = await session.execute(
        select(CloudInstance)
        .where(CloudInstance.user_id == user.id)
        .order_by(CloudInstance.started_at.desc())
    )
    return list(result.scalars().all())


@router.post("/refresh", response_model=list[CloudInstanceResponse])
async def refresh_cloud_instances(user: CurrentUser, session: DbSession) -> list[CloudInstance]:
    """从 Lab4AI API 拉取全量列表，与数据库对比，更新当前用户的记录。"""
    creds = await load_lab4ai_credentials(session)
    if creds is None:
        raise HTTPException(
            status_code=status.HTTP_424_FAILED_DEPENDENCY,
            detail="Lab4AI 凭证未配置，请联系管理员",
        )

    remote_instances = await list_instances(creds.phone, creds.password)
    remote_ids = {inst.server_id for inst in remote_instances}

    # 查出该用户在数据库中记录的 running 实例
    result = await session.execute(
        select(CloudInstance).where(
            CloudInstance.user_id == user.id,
            CloudInstance.status == CloudInstanceStatus.RUNNING,
        )
    )
    db_instances = list(result.scalars().all())

    # 如果数据库中记录的实例已不在远程列表中，标记为 stopped
    for db_inst in db_instances:
        if db_inst.server_id not in remote_ids:
            db_inst.status = CloudInstanceStatus.STOPPED
            db_inst.stopped_at = datetime.now(UTC)

    await session.commit()

    # 返回该用户所有记录
    result = await session.execute(
        select(CloudInstance)
        .where(CloudInstance.user_id == user.id)
        .order_by(CloudInstance.started_at.desc())
    )
    return list(result.scalars().all())


@router.post("/{instance_id}/stop")
async def stop_cloud_instance(
    instance_id: int, user: CurrentUser, session: DbSession
) -> CloudInstanceResponse:
    """手动关停一个云实例（校验归属）。"""
    instance = await session.get(CloudInstance, instance_id)
    if instance is None or instance.user_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="实例不存在")
    if instance.status == CloudInstanceStatus.STOPPED:
        return instance  # type: ignore[return-value]

    creds = await load_lab4ai_credentials(session)
    if creds is None:
        raise HTTPException(
            status_code=status.HTTP_424_FAILED_DEPENDENCY,
            detail="Lab4AI 凭证未配置",
        )

    success = await stop_instance(creds.phone, creds.password, instance.server_id)
    if not success:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Lab4AI 关停 API 调用失败",
        )

    instance.status = CloudInstanceStatus.STOPPED
    instance.stopped_at = datetime.now(UTC)
    await session.commit()
    await session.refresh(instance)
    return instance  # type: ignore[return-value]
