from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    CloudInstance,
    CloudInstanceStatus,
    CloudInstanceType,
    Conversation,
    ConversationStatus,
    ConversationTaskType,
    User,
)
from app.services.lab4ai.credentials import save_lab4ai_credentials
from tests.conftest import auth_headers


pytestmark = pytest.mark.asyncio


async def test_runtime_credentials_returns_owned_instance_ssh_secret(
    client: AsyncClient,
    test_user: User,
    db_session: AsyncSession,
):
    conv = Conversation(
        user_id=test_user.id,
        task_type=ConversationTaskType.REPRODUCE,
        title="runtime credentials",
        status=ConversationStatus.ACTIVE,
        metadata_={},
    )
    db_session.add(conv)
    await db_session.commit()
    await db_session.refresh(conv)

    instance = CloudInstance(
        user_id=test_user.id,
        conversation_id=conv.id,
        server_id="srv-123",
        instance_id="inst-123",
        instance_type=CloudInstanceType.CPU,
        gpu_count=0,
        ssh_host="10.0.0.8",
        ssh_port=2222,
        ssh_user="root",
        ssh_pass="secret-pass",
        status=CloudInstanceStatus.RUNNING,
        raw_payload={},
    )
    db_session.add(instance)
    await db_session.commit()

    await save_lab4ai_credentials(db_session, "13812348000", "lab4ai-secret")

    response = await client.get(
        f"/api/conversations/{conv.id}/runtime-credentials",
        headers=auth_headers(test_user),
    )

    assert response.status_code == 200
    data = response.json()
    assert data["lab4ai_credentials"] == {
        "configured": True,
        "phone_masked": "138****8000",
    }
    assert "lab4ai-secret" not in response.text
    assert len(data["instances"]) == 1
    item = data["instances"][0]
    assert item["id"] == instance.id
    assert item["server_id"] == "srv-123"
    assert item["instance_id"] == "inst-123"
    assert item["instance_type"] == "CPU"
    assert item["status"] == "running"
    assert item["username"] == "root"
    assert item["password"] == "secret-pass"
    assert item["ssh_host"] == "10.0.0.8"
    assert item["ssh_port"] == 2222
    assert item["ssh_command"] == "ssh -p 2222 root@10.0.0.8"
    assert item["started_at"]
    assert item["stopped_at"] is None


async def test_runtime_credentials_reports_missing_lab4ai_login(
    client: AsyncClient,
    test_user: User,
    db_session: AsyncSession,
):
    conv = Conversation(
        user_id=test_user.id,
        task_type=ConversationTaskType.REPRODUCE,
        title="missing lab4ai login",
        status=ConversationStatus.ACTIVE,
        metadata_={},
    )
    db_session.add(conv)
    await db_session.commit()
    await db_session.refresh(conv)

    response = await client.get(
        f"/api/conversations/{conv.id}/runtime-credentials",
        headers=auth_headers(test_user),
    )

    assert response.status_code == 200
    assert response.json()["lab4ai_credentials"] == {
        "configured": False,
        "phone_masked": "",
    }


async def test_runtime_credentials_keeps_user_isolation(
    client: AsyncClient,
    test_user: User,
    admin_user: User,
    db_session: AsyncSession,
):
    conv = Conversation(
        user_id=admin_user.id,
        task_type=ConversationTaskType.REPRODUCE,
        title="other user runtime credentials",
        status=ConversationStatus.ACTIVE,
        metadata_={},
    )
    db_session.add(conv)
    await db_session.commit()
    await db_session.refresh(conv)

    response = await client.get(
        f"/api/conversations/{conv.id}/runtime-credentials",
        headers=auth_headers(test_user),
    )

    assert response.status_code == 404
