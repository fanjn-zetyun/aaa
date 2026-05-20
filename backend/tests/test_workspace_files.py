from __future__ import annotations

from types import SimpleNamespace

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Conversation, ConversationStatus, ConversationTaskType, User
from tests.conftest import auth_headers


pytestmark = pytest.mark.asyncio


async def test_workspace_files_lists_owned_workspace(
    client: AsyncClient,
    test_user: User,
    db_session: AsyncSession,
    tmp_path,
    monkeypatch,
):
    conv = Conversation(
        user_id=test_user.id,
        task_type=ConversationTaskType.REPRODUCE,
        title="workspace demo",
        status=ConversationStatus.ACTIVE,
        metadata_={},
    )
    db_session.add(conv)
    await db_session.commit()
    await db_session.refresh(conv)

    workspace_root = tmp_path / "runtime" / "workspaces"
    workspace = workspace_root / str(conv.id)
    (workspace / "reports").mkdir(parents=True)
    (workspace / "reports" / "result.md").write_text("# result", encoding="utf-8")
    (workspace / ".lobster").mkdir()
    (workspace / ".lobster" / ".env").write_text("SECRET=1", encoding="utf-8")
    (workspace / "node_modules").mkdir()
    (workspace / "node_modules" / "pkg.js").write_text("ignored", encoding="utf-8")

    monkeypatch.setattr(
        "app.api.conversations.get_settings",
        lambda: SimpleNamespace(project_root=tmp_path, workspace_root_path=workspace_root),
    )

    response = await client.get(
        f"/api/conversations/{conv.id}/workspace-files",
        headers=auth_headers(test_user),
    )

    assert response.status_code == 200
    data = response.json()
    assert data["exists"] is True
    assert data["root"] == f"runtime/workspaces/{conv.id}"

    paths = {item["path"] for item in data["files"]}
    assert "reports" in paths
    assert "reports/result.md" in paths
    assert ".lobster/.env" not in paths
    assert "node_modules/pkg.js" not in paths


async def test_workspace_files_keeps_user_isolation(
    client: AsyncClient,
    test_user: User,
    admin_user: User,
    db_session: AsyncSession,
):
    conv = Conversation(
        user_id=admin_user.id,
        task_type=ConversationTaskType.REPRODUCE,
        title="other user workspace",
        status=ConversationStatus.ACTIVE,
        metadata_={},
    )
    db_session.add(conv)
    await db_session.commit()
    await db_session.refresh(conv)

    response = await client.get(
        f"/api/conversations/{conv.id}/workspace-files",
        headers=auth_headers(test_user),
    )

    assert response.status_code == 404
