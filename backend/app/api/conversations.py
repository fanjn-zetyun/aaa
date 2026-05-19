"""V2 conversation endpoints."""

from __future__ import annotations

import json

from starlette.websockets import WebSocketState
from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect, status
from sqlalchemy import func, select

from app.api.deps import CurrentUser, DbSession
from app.api.logs_ws import _authenticate_ws
from app.models import Conversation, ConversationMessage, UsageRecord
from app.models.conversation import ConversationStatus, ConversationTaskType, MessageRole
from app.schemas.conversation import (
    ConversationCreateRequest,
    ConversationDetailResponse,
    ConversationResponse,
    MessageCreateRequest,
)
from app.services.agent_loop import get_agent_manager
from app.services.conversation_store import conversation_log_path
from app.services.tools import infer_task_type

router = APIRouter(prefix="/api/conversations", tags=["conversations"])


@router.post("", response_model=ConversationResponse, status_code=status.HTTP_201_CREATED)
async def create_conversation(
    payload: ConversationCreateRequest,
    user: CurrentUser,
    session: DbSession,
) -> ConversationResponse:
    await _ensure_quota_available(user.id, user.gpu_quota_hours + user.cpu_quota_hours, session)

    seed = " ".join(
        part
        for part in (
            str(payload.github_url) if payload.github_url else "",
            str(payload.paper_url) if payload.paper_url else "",
            payload.user_prompt or "",
        )
        if part
    )
    task_type = ConversationTaskType(infer_task_type(seed, payload.task_type.value))
    title = payload.title or _build_title(task_type, payload.github_url, payload.user_prompt)
    metadata = {
        "task_type": task_type.value,
        "github_url": str(payload.github_url) if payload.github_url else None,
        "paper_url": str(payload.paper_url) if payload.paper_url else None,
        "intent_hint": task_type.value,
    }
    conv = Conversation(
        user_id=user.id,
        task_type=task_type,
        title=title,
        status=ConversationStatus.ACTIVE,
        metadata_=metadata,
    )
    session.add(conv)
    await session.commit()
    await session.refresh(conv)

    conv.log_file_path = str(conversation_log_path(conv.id))
    if seed:
        session.add(
            ConversationMessage(
                conversation_id=conv.id,
                role=MessageRole.USER,
                content=seed,
                message_metadata={
                    "github_url": metadata["github_url"],
                    "paper_url": metadata["paper_url"],
                },
            )
        )
    await session.commit()
    await session.refresh(conv)
    if seed:
        get_agent_manager().start(conv.id)
    return ConversationResponse.model_validate(conv)


@router.get("", response_model=list[ConversationResponse])
async def list_conversations(user: CurrentUser, session: DbSession) -> list[ConversationResponse]:
    result = await session.execute(
        select(Conversation)
        .where(Conversation.user_id == user.id)
        .order_by(Conversation.updated_at.desc())
    )
    return [ConversationResponse.model_validate(item) for item in result.scalars().all()]


@router.get("/{conversation_id}", response_model=ConversationDetailResponse)
async def get_conversation(
    conversation_id: int, user: CurrentUser, session: DbSession
) -> ConversationDetailResponse:
    conv = await _get_owned_conversation(conversation_id, user.id, session)
    messages = (
        await session.execute(
            select(ConversationMessage)
            .where(ConversationMessage.conversation_id == conversation_id)
            .order_by(ConversationMessage.created_at.asc())
        )
    ).scalars().all()
    return ConversationDetailResponse(
        **ConversationResponse.model_validate(conv).model_dump(),
        messages=[
            {
                "id": msg.id,
                "conversation_id": msg.conversation_id,
                "role": msg.role,
                "content": msg.content,
                "message_metadata": msg.message_metadata,
                "created_at": msg.created_at,
            }
            for msg in messages
        ],
    )


@router.post("/{conversation_id}/messages", response_model=ConversationDetailResponse)
async def send_message(
    conversation_id: int,
    payload: MessageCreateRequest,
    user: CurrentUser,
    session: DbSession,
) -> ConversationDetailResponse:
    conv = await _get_owned_conversation(conversation_id, user.id, session)
    if conv.status == ConversationStatus.RUNNING:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="当前对话正在执行")
    session.add(
        ConversationMessage(
            conversation_id=conversation_id,
            role=MessageRole.USER,
            content=payload.content,
        )
    )
    conv.status = ConversationStatus.ACTIVE
    await session.commit()
    get_agent_manager().start(conversation_id)
    return await get_conversation(conversation_id, user, session)


@router.post("/{conversation_id}/stop", response_model=ConversationResponse)
async def stop_conversation(
    conversation_id: int, user: CurrentUser, session: DbSession
) -> Conversation:
    conv = await _get_owned_conversation(conversation_id, user.id, session)
    await get_agent_manager().stop(conversation_id)
    await session.refresh(conv)
    return conv


@router.websocket("/{conversation_id}/stream")
async def ws_conversation_stream(websocket: WebSocket, conversation_id: int) -> None:
    user = await _authenticate_ws(websocket)
    if user is None:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason="unauthorized")
        return
    from app.core.database import SessionLocal

    async with SessionLocal() as session:
        conv = await session.get(Conversation, conversation_id)
        if conv is None or conv.user_id != user.id:
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason="not found")
            return

    await websocket.accept()
    q = get_agent_manager().subscribe(conversation_id)
    try:
        while True:
            event = await q.get()
            if event is None:
                break
            await websocket.send_text(json.dumps(event, ensure_ascii=False))
    except WebSocketDisconnect:
        pass
    finally:
        if websocket.client_state == WebSocketState.CONNECTED:
            await websocket.close()


async def _get_owned_conversation(conversation_id: int, user_id: int, session) -> Conversation:
    conv = await session.get(Conversation, conversation_id)
    if conv is None or conv.user_id != user_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="对话不存在")
    return conv


async def _ensure_quota_available(user_id: int, total_quota: float, session) -> None:
    result = await session.execute(
        select(func.sum(UsageRecord.duration_seconds)).where(UsageRecord.user_id == user_id)
    )
    used_hours = (result.scalar() or 0.0) / 3600
    if total_quota > 0 and used_hours >= total_quota:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="算力配额已用尽")


def _build_title(
    task_type: ConversationTaskType, github_url: object | None, user_prompt: str | None
) -> str:
    if github_url:
        return str(github_url).rstrip("/").split("/")[-1][:80] or task_type.value
    if user_prompt:
        return user_prompt[:80]
    return task_type.value
