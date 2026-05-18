"""WebSocket 实时日志流端点。

客户端连接 ws://host/api/claw-instances/{id}/logs?token=<jwt>
服务端从 OpenclawManager 的 log_queue 读取行并推送。
"""

from __future__ import annotations

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, status
from sqlalchemy import select

from app.core.database import SessionLocal
from app.core.security import decode_access_token
from app.models import ClawInstance, ClawInstanceStatus, User
from app.services.openclaw import get_manager

router = APIRouter(tags=["logs"])


async def _authenticate_ws(websocket: WebSocket) -> User | None:
    """从 query string 中的 token 参数验证用户身份。"""
    token = websocket.query_params.get("token")
    if not token:
        return None
    try:
        payload = decode_access_token(token)
    except ValueError:
        return None
    user_id = payload.get("sub")
    if user_id is None:
        return None
    async with SessionLocal() as session:
        user = await session.get(User, int(user_id))
        if user and user.is_active:
            return user
    return None


@router.websocket("/api/claw-instances/{instance_id}/logs")
async def ws_logs(websocket: WebSocket, instance_id: int) -> None:
    user = await _authenticate_ws(websocket)
    if user is None:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason="认证失败")
        return

    async with SessionLocal() as session:
        instance = await session.get(ClawInstance, instance_id)
        if instance is None or instance.user_id != user.id:
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason="实例不存在")
            return

    await websocket.accept()

    manager = get_manager()
    handle = manager.get_handle(instance_id)

    if handle is None:
        await websocket.send_text("[系统] 该任务进程已结束，无实时日志可推送。")
        await websocket.close()
        return

    q = handle.subscribe()
    try:
        while True:
            line = await q.get()
            if line is None:
                await websocket.send_text("[系统] 进程已退出。")
                break
            await websocket.send_text(line)
    except WebSocketDisconnect:
        pass
    finally:
        await websocket.close()
