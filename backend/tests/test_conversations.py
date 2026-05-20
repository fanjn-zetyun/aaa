"""Conversation API tests."""

from __future__ import annotations

import pytest
from httpx import AsyncClient

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
