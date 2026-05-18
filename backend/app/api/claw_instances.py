"""ClawInstance 路由：创建任务、查询、停止。"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import func, select

from app.api.deps import CurrentUser, DbSession
from app.models import ClawInstance, ClawInstanceStatus, UsageRecord
from app.schemas.claw_instance import (
    ClawInstanceCreateRequest,
    ClawInstanceResponse,
    QuotaResponse,
)
from app.services.lab4ai.credentials import load_lab4ai_credentials
from app.services.openclaw import TaskInput, get_manager

router = APIRouter(prefix="/api/claw-instances", tags=["claw-instances"])


@router.get("/quota", response_model=QuotaResponse)
async def get_quota(user: CurrentUser, session: DbSession) -> dict:
    used = await _get_used_hours(user.id, session)
    return {
        "gpu_quota_hours": user.gpu_quota_hours,
        "cpu_quota_hours": user.cpu_quota_hours,
        "gpu_used_hours": used["gpu"],
        "cpu_used_hours": used["cpu"],
    }


async def _get_used_hours(user_id: int, session) -> dict[str, float]:
    from app.models.cloud_instance import CloudInstanceType

    result = await session.execute(
        select(
            UsageRecord.instance_type,
            func.sum(UsageRecord.duration_seconds),
        )
        .where(UsageRecord.user_id == user_id)
        .group_by(UsageRecord.instance_type)
    )
    gpu_seconds = 0.0
    cpu_seconds = 0.0
    for row in result.all():
        if row[0] == CloudInstanceType.GPU:
            gpu_seconds = row[1] or 0.0
        else:
            cpu_seconds = row[1] or 0.0
    return {"gpu": gpu_seconds / 3600, "cpu": cpu_seconds / 3600}


@router.post("", response_model=ClawInstanceResponse, status_code=status.HTTP_201_CREATED)
async def create_claw_instance(
    payload: ClawInstanceCreateRequest,
    user: CurrentUser,
    session: DbSession,
) -> ClawInstance:
    used = await _get_used_hours(user.id, session)
    total_quota = user.gpu_quota_hours + user.cpu_quota_hours
    total_used = used["gpu"] + used["cpu"]
    if total_quota > 0 and total_used >= total_quota:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="算力配额已用尽，请联系管理员增加配额",
        )
    task_config = {
        "github_url": str(payload.github_url),
        "paper_url": str(payload.paper_url) if payload.paper_url else None,
        "user_prompt": payload.user_prompt,
    }
    instance = ClawInstance(
        user_id=user.id,
        status=ClawInstanceStatus.PENDING,
        task_config=task_config,
    )
    session.add(instance)
    await session.commit()
    await session.refresh(instance)

    creds = await load_lab4ai_credentials(session)
    manager = get_manager()
    await manager.start_task(
        TaskInput(
            task_id=instance.id,
            github_url=task_config["github_url"],
            paper_url=task_config["paper_url"],
            user_prompt=task_config["user_prompt"],
            lab4ai_phone=creds.phone if creds else None,
            lab4ai_password=creds.password if creds else None,
        )
    )
    await session.refresh(instance)
    return instance


@router.get("", response_model=list[ClawInstanceResponse])
async def list_claw_instances(user: CurrentUser, session: DbSession) -> list[ClawInstance]:
    result = await session.execute(
        select(ClawInstance)
        .where(ClawInstance.user_id == user.id)
        .order_by(ClawInstance.created_at.desc())
    )
    return list(result.scalars().all())


@router.get("/{instance_id}", response_model=ClawInstanceResponse)
async def get_claw_instance(
    instance_id: int, user: CurrentUser, session: DbSession
) -> ClawInstance:
    instance = await session.get(ClawInstance, instance_id)
    if instance is None or instance.user_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="实例不存在")
    return instance


@router.post("/{instance_id}/stop", response_model=ClawInstanceResponse)
async def stop_claw_instance(
    instance_id: int, user: CurrentUser, session: DbSession
) -> ClawInstance:
    instance = await session.get(ClawInstance, instance_id)
    if instance is None or instance.user_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="实例不存在")
    if instance.status not in (ClawInstanceStatus.PENDING, ClawInstanceStatus.RUNNING):
        return instance
    manager = get_manager()
    await manager.stop_task(instance_id)
    await session.refresh(instance)
    return instance
