"""V2 conversation endpoints."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Literal

from starlette.websockets import WebSocketState
from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect, status
from sqlalchemy import func, select

from app.api.deps import CurrentUser, DbSession
from app.api.ws_auth import authenticate_ws
from app.models import CloudInstance, Conversation, ConversationMessage, UsageRecord
from app.models.conversation import ConversationStatus, ConversationTaskType, MessageRole
from app.schemas.conversation import (
    ConversationCreateRequest,
    ConversationDetailResponse,
    ConversationResponse,
    MessageCreateRequest,
    RuntimeCredentialInstanceResponse,
    RuntimeLab4AICredentialsResponse,
    RuntimeCredentialsResponse,
    WorkspaceFileContentResponse,
    WorkspaceFileListResponse,
    WorkspaceFileResponse,
)
from app.core.config import get_settings
from app.services.agent_loop import get_agent_manager
from app.services.conversation_memory import ensure_memory
from app.services.conversation_store import conversation_log_path
from app.services.lab4ai.credentials import load_lab4ai_credentials, mask_lab4ai_phone
from app.services.tools import infer_task_type

router = APIRouter(prefix="/api/conversations", tags=["conversations"])


@router.post("", response_model=ConversationResponse, status_code=status.HTTP_201_CREATED)
async def create_conversation(
    payload: ConversationCreateRequest,
    user: CurrentUser,
    session: DbSession,
) -> ConversationResponse:
    await _ensure_quota_available(user.id, user.gpu_quota_hours + user.cpu_quota_hours, session)

    structured_seed = " ".join(
        part
        for part in (
            str(payload.github_url) if payload.github_url else "",
            str(payload.paper_url) if payload.paper_url else "",
            payload.user_prompt or "",
        )
        if part
    )
    display_seed = (payload.original_input or "").strip() or structured_seed
    task_type = ConversationTaskType(infer_task_type(structured_seed, payload.task_type.value))
    title = payload.title or _build_title(task_type, payload.github_url, payload.user_prompt)
    metadata = {
        "task_type": task_type.value,
        "github_url": str(payload.github_url) if payload.github_url else None,
        "paper_url": str(payload.paper_url) if payload.paper_url else None,
        "intent_hint": task_type.value,
    }
    metadata = ensure_memory(metadata)
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
    if display_seed:
        session.add(
            ConversationMessage(
                conversation_id=conv.id,
                role=MessageRole.USER,
                content=display_seed,
                message_metadata={
                    "github_url": metadata["github_url"],
                    "paper_url": metadata["paper_url"],
                    "structured_user_prompt": payload.user_prompt,
                },
            )
        )
    await session.commit()
    await session.refresh(conv)
    if display_seed:
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


@router.get("/{conversation_id}/runtime-credentials", response_model=RuntimeCredentialsResponse)
async def get_runtime_credentials(
    conversation_id: int, user: CurrentUser, session: DbSession
) -> RuntimeCredentialsResponse:
    await _get_owned_conversation(conversation_id, user.id, session)
    lab4ai_credentials = await load_lab4ai_credentials(session)
    instances = (
        await session.execute(
            select(CloudInstance)
            .where(
                CloudInstance.user_id == user.id,
                CloudInstance.conversation_id == conversation_id,
            )
            .order_by(CloudInstance.started_at.desc())
        )
    ).scalars().all()
    return RuntimeCredentialsResponse(
        lab4ai_credentials=RuntimeLab4AICredentialsResponse(
            configured=lab4ai_credentials is not None,
            phone_masked=mask_lab4ai_phone(lab4ai_credentials.phone)
            if lab4ai_credentials
            else "",
        ),
        instances=[
            RuntimeCredentialInstanceResponse(
                id=item.id,
                server_id=item.server_id,
                instance_id=item.instance_id,
                instance_type=item.instance_type.value,
                status=item.status.value,
                username=item.ssh_user,
                password=item.ssh_pass,
                ssh_host=item.ssh_host,
                ssh_port=item.ssh_port,
                ssh_command=_build_ssh_command(item.ssh_user, item.ssh_host, item.ssh_port),
                started_at=item.started_at,
                stopped_at=item.stopped_at,
            )
            for item in instances
        ]
    )


@router.get("/{conversation_id}/workspace-files", response_model=WorkspaceFileListResponse)
async def get_workspace_files(
    conversation_id: int, user: CurrentUser, session: DbSession
) -> WorkspaceFileListResponse:
    await _get_owned_conversation(conversation_id, user.id, session)
    settings = get_settings()
    root = settings.workspace_root_path / str(conversation_id)
    files = _list_workspace_files(root)
    return WorkspaceFileListResponse(
        exists=root.exists(),
        root=_display_workspace_root(root, settings.project_root),
        files=files,
    )


@router.get(
    "/{conversation_id}/workspace-files/content",
    response_model=WorkspaceFileContentResponse,
)
async def get_workspace_file_content(
    conversation_id: int, path: str, user: CurrentUser, session: DbSession
) -> WorkspaceFileContentResponse:
    await _get_owned_conversation(conversation_id, user.id, session)
    if not _is_markdown_path(path):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="仅支持预览 Markdown 文件")

    settings = get_settings()
    root = settings.workspace_root_path / str(conversation_id)
    target = _resolve_workspace_file(root, path)
    if target is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="文件路径不在工作区内")
    if not target.exists() or not target.is_file():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="文件不存在")

    max_bytes = 512 * 1024
    try:
        if target.stat().st_size > max_bytes:
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail="文件过大，无法预览",
            )
        content = target.read_text(encoding="utf-8", errors="replace")
    except HTTPException:
        raise
    except OSError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="文件读取失败"
        ) from exc

    normalized_path = str(target.relative_to(root.resolve())).replace("\\", "/")
    return WorkspaceFileContentResponse(
        path=normalized_path,
        name=target.name,
        kind="markdown",
        content=content,
    )


@router.websocket("/{conversation_id}/stream")
async def ws_conversation_stream(websocket: WebSocket, conversation_id: int) -> None:
    user = await authenticate_ws(websocket)
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


def _list_workspace_files(root: Path) -> list[WorkspaceFileResponse]:
    if not root.exists() or not root.is_dir():
        return []

    ignored_dirs = {
        ".git",
        ".lobster",
        "__pycache__",
        "node_modules",
        ".venv",
        "venv",
        "dist",
        "build",
    }
    ignored_files = {".DS_Store"}
    items: list[WorkspaceFileResponse] = []
    max_items = 200

    def walk(current: Path, depth: int) -> None:
        nonlocal items
        if len(items) >= max_items:
            return
        try:
            entries = sorted(current.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))
        except OSError:
            return

        for entry in entries:
            if len(items) >= max_items:
                break
            if entry.name in ignored_files:
                continue
            if entry.is_dir() and entry.name in ignored_dirs:
                continue

            try:
                stat = entry.stat(follow_symlinks=False)
            except OSError:
                stat = None

            kind: Literal["file", "directory", "symlink"]
            if entry.is_symlink():
                kind = "symlink"
            elif entry.is_dir():
                kind = "directory"
            else:
                kind = "file"

            rel_path = str(entry.relative_to(root)).replace("\\", "/")
            items.append(
                WorkspaceFileResponse(
                    path=rel_path,
                    name=entry.name,
                    kind=kind,
                    size=None if stat is None or entry.is_dir() else stat.st_size,
                    modified_at=None if stat is None else datetime.fromtimestamp(stat.st_mtime),
                    depth=depth,
                )
            )

            if entry.is_dir() and not entry.is_symlink() and depth < 3:
                walk(entry, depth + 1)

    walk(root, 0)
    return items


def _is_markdown_path(path: str) -> bool:
    suffix = Path(path).suffix.lower()
    return suffix in {".md", ".markdown"}


def _resolve_workspace_file(root: Path, path: str) -> Path | None:
    if Path(path).is_absolute():
        return None
    try:
        resolved_root = root.resolve()
        target = (resolved_root / path).resolve()
        target.relative_to(resolved_root)
        return target
    except (OSError, ValueError):
        return None


def _display_workspace_root(root: Path, project_root: Path) -> str:
    try:
        return root.relative_to(project_root).as_posix()
    except ValueError:
        return str(root).replace("\\", "/")


def _build_ssh_command(
    username: str | None, host: str | None, port: int | None
) -> str | None:
    if not host:
        return None
    user = username or "root"
    if port:
        return f"ssh -p {port} {user}@{host}"
    return f"ssh {user}@{host}"
