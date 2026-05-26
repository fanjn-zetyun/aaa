"""Conversation API tests."""

from __future__ import annotations

import pytest
from httpx import AsyncClient

from app.core.config import get_settings
from app.models import User
from tests.conftest import auth_headers


pytestmark = pytest.mark.asyncio


async def test_create_conversation_preserves_original_input(
    client: AsyncClient, test_user: User
):
    original_input = (
        "帮我复现这个项目：https://github.com/showlab/PhotoDoodle。"
        "论文链接：https://arxiv.org/pdf/2502.14397"
    )

    created = await client.post(
        "/api/conversations",
        headers=auth_headers(test_user),
        json={
            "task_type": "reproduce",
            "github_url": "https://github.com/showlab/PhotoDoodle",
            "paper_url": "https://arxiv.org/pdf/2502.14397",
            "user_prompt": "帮我复现这个项目",
            "original_input": original_input,
        },
    )
    assert created.status_code == 201

    detail = await client.get(
        f"/api/conversations/{created.json()['id']}",
        headers=auth_headers(test_user),
    )
    assert detail.status_code == 200
    data = detail.json()
    assert data["metadata"]["github_url"] == "https://github.com/showlab/PhotoDoodle"
    assert data["metadata"]["paper_url"] == "https://arxiv.org/pdf/2502.14397"
    assert data["messages"][0]["content"] == original_input
    assert data["messages"][0]["message_metadata"]["structured_user_prompt"] == "帮我复现这个项目"


async def test_create_auto_research_conversation_preserves_experiments_type(
    client: AsyncClient, test_user: User
):
    created = await client.post(
        "/api/conversations",
        headers=auth_headers(test_user),
        json={
            "task_type": "experiments",
            "github_url": "https://github.com/jingyaogong/minimind",
            "user_prompt": "帮我跑下的自动化训练实验",
            "original_input": "帮我跑下https://github.com/jingyaogong/minimind的自动化训练实验",
        },
    )
    assert created.status_code == 201

    data = created.json()
    assert data["task_type"] == "experiments"
    assert data["metadata"]["task_type"] == "experiments"
    assert data["metadata"]["intent_hint"] == "experiments"
    assert data["metadata"]["github_url"] == "https://github.com/jingyaogong/minimind"


async def test_download_workspace_file_allows_project_directory_files(
    client: AsyncClient, test_user: User, tmp_path, monkeypatch
):
    settings = get_settings()
    workspace_root = tmp_path / "workspaces"
    monkeypatch.setattr(settings, "workspace_root", str(workspace_root))

    created = await client.post(
        "/api/conversations",
        headers=auth_headers(test_user),
        json={
            "task_type": "reproduce",
            "github_url": "https://github.com/showlab/PhotoDoodle",
            "user_prompt": "帮我复现 PhotoDoodle",
        },
    )
    assert created.status_code == 201
    conversation_id = created.json()["id"]
    project_file = workspace_root / str(conversation_id) / "PhotoDoodle" / "notes.txt"
    project_file.parent.mkdir(parents=True)
    project_file.write_text("download me", encoding="utf-8")

    response = await client.get(
        f"/api/conversations/{conversation_id}/workspace-files/download?path=PhotoDoodle/notes.txt",
        headers=auth_headers(test_user),
    )

    assert response.status_code == 200
    assert response.content == b"download me"
    assert response.headers["content-disposition"].startswith('attachment; filename="notes.txt"')


async def test_download_workspace_file_rejects_files_outside_project_directory(
    client: AsyncClient, test_user: User, tmp_path, monkeypatch
):
    settings = get_settings()
    workspace_root = tmp_path / "workspaces"
    monkeypatch.setattr(settings, "workspace_root", str(workspace_root))

    created = await client.post(
        "/api/conversations",
        headers=auth_headers(test_user),
        json={
            "task_type": "reproduce",
            "github_url": "https://github.com/showlab/PhotoDoodle",
            "user_prompt": "帮我复现 PhotoDoodle",
        },
    )
    assert created.status_code == 201
    conversation_id = created.json()["id"]
    root_file = workspace_root / str(conversation_id) / "root-report.txt"
    root_file.parent.mkdir(parents=True)
    root_file.write_text("do not download", encoding="utf-8")

    response = await client.get(
        f"/api/conversations/{conversation_id}/workspace-files/download?path=root-report.txt",
        headers=auth_headers(test_user),
    )

    assert response.status_code == 400
