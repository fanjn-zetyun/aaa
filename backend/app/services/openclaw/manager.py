"""OpenclawManager：协调任务的生命周期。

职责：
- 维护 task_id → ProcessHandle 的内存映射
- 启动任务（更新数据库 → 调 runner.start → 后台等待退出 → 更新数据库）
- 停止任务（runner.stop + 状态写回）
- 转发日志到队列（供 WebSocket 订阅，第二轮再补 fan-out）
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import SessionLocal
from app.models import ClawInstance, ClawInstanceStatus

from .mock import build_runner
from .runner import OpenclawRunner, ProcessHandle, TaskInput

logger = logging.getLogger(__name__)


class OpenclawManager:
    def __init__(self, runner: OpenclawRunner) -> None:
        self._runner = runner
        self._handles: dict[int, ProcessHandle] = {}
        self._lock = asyncio.Lock()

    @property
    def runner(self) -> OpenclawRunner:
        return self._runner

    def get_handle(self, task_id: int) -> ProcessHandle | None:
        return self._handles.get(task_id)

    async def start_task(self, task: TaskInput) -> ProcessHandle:
        async with self._lock:
            if task.task_id in self._handles:
                return self._handles[task.task_id]
            handle = await self._runner.start(task)
            self._handles[task.task_id] = handle
            await self._update_status(
                task.task_id,
                status=ClawInstanceStatus.RUNNING,
                pid=handle.pid,
                workspace_path=str(handle.workspace_path),
                started_at=datetime.now(UTC),
            )
            asyncio.create_task(self._supervise(handle))
            return handle

    async def stop_task(self, task_id: int, timeout: float = 30.0) -> int | None:
        handle = self._handles.get(task_id)
        if handle is None:
            return None
        rc = await self._runner.stop(handle, timeout=timeout)
        await self._update_status(
            task_id,
            status=ClawInstanceStatus.STOPPED,
            finished_at=datetime.now(UTC),
        )
        return rc

    async def _supervise(self, handle: ProcessHandle) -> None:
        try:
            rc = await self._runner.wait(handle)
        except Exception as exc:  # pragma: no cover - 防御性
            logger.exception("等待 openclaw 进程时异常: %s", exc)
            rc = -1

        # 已经被 stop_task 标记过的任务不要覆盖状态
        async with SessionLocal() as session:
            instance = await session.get(ClawInstance, handle.task_id)
            if instance is None:
                return
            if instance.status == ClawInstanceStatus.STOPPED:
                return
            instance.status = (
                ClawInstanceStatus.COMPLETED if rc == 0 else ClawInstanceStatus.FAILED
            )
            instance.finished_at = datetime.now(UTC)
            if rc != 0:
                instance.error_message = f"openclaw 进程异常退出，退出码={rc}"
            await session.commit()
        self._handles.pop(handle.task_id, None)

    async def _update_status(
        self,
        task_id: int,
        *,
        status: ClawInstanceStatus | None = None,
        pid: int | None = None,
        workspace_path: str | None = None,
        started_at: datetime | None = None,
        finished_at: datetime | None = None,
    ) -> None:
        async with SessionLocal() as session:
            await self._update_status_inner(
                session,
                task_id=task_id,
                status=status,
                pid=pid,
                workspace_path=workspace_path,
                started_at=started_at,
                finished_at=finished_at,
            )
            await session.commit()

    @staticmethod
    async def _update_status_inner(
        session: AsyncSession,
        *,
        task_id: int,
        status: ClawInstanceStatus | None,
        pid: int | None,
        workspace_path: str | None,
        started_at: datetime | None,
        finished_at: datetime | None,
    ) -> None:
        result = await session.execute(select(ClawInstance).where(ClawInstance.id == task_id))
        instance = result.scalar_one_or_none()
        if instance is None:
            return
        if status is not None:
            instance.status = status
        if pid is not None:
            instance.pid = pid
        if workspace_path is not None:
            instance.workspace_path = workspace_path
        if started_at is not None:
            instance.started_at = started_at
        if finished_at is not None:
            instance.finished_at = finished_at


_manager: OpenclawManager | None = None


def get_manager() -> OpenclawManager:
    global _manager
    if _manager is None:
        _manager = OpenclawManager(build_runner())
    return _manager
