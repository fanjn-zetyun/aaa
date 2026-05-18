"""claw-instances 模块单元测试：创建任务、列表、查询、停止。"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import ClawInstance, ClawInstanceStatus, User
from app.services.openclaw.runner import ProcessHandle
from tests.conftest import auth_headers


pytestmark = pytest.mark.asyncio


@pytest.fixture
def mock_manager():
    with patch("app.api.claw_instances.get_manager") as mock_get:
        manager = AsyncMock()
        mock_proc = MagicMock()
        mock_proc.pid = 12345
        handle = ProcessHandle(task_id=1, pid=12345, workspace_path="/tmp/ws/1", process=mock_proc)
        manager.start_task.return_value = handle
        manager.stop_task.return_value = 0
        mock_get.return_value = manager
        yield manager


@pytest.fixture
def mock_credentials():
    with patch("app.api.claw_instances.load_lab4ai_credentials") as mock_load:
        mock_load.return_value = None
        yield mock_load


class TestQuota:
    async def test_get_quota(self, client: AsyncClient, test_user: User):
        r = await client.get("/api/claw-instances/quota", headers=auth_headers(test_user))
        assert r.status_code == 200
        data = r.json()
        assert data["gpu_quota_hours"] == 10.0
        assert data["cpu_quota_hours"] == 20.0
        assert data["gpu_used_hours"] == 0.0
        assert data["cpu_used_hours"] == 0.0

    async def test_quota_unauthenticated(self, client: AsyncClient):
        r = await client.get("/api/claw-instances/quota")
        assert r.status_code == 401


class TestCreateClawInstance:
    async def test_create_success(
        self, client: AsyncClient, test_user: User, mock_manager, mock_credentials
    ):
        r = await client.post(
            "/api/claw-instances",
            json={
                "github_url": "https://github.com/example/repo",
                "user_prompt": "reproduce the paper",
            },
            headers=auth_headers(test_user),
        )
        assert r.status_code == 201
        data = r.json()
        assert data["user_id"] == test_user.id
        assert data["task_config"]["github_url"] == "https://github.com/example/repo"
        mock_manager.start_task.assert_called_once()

    async def test_create_with_paper_url(
        self, client: AsyncClient, test_user: User, mock_manager, mock_credentials
    ):
        r = await client.post(
            "/api/claw-instances",
            json={
                "github_url": "https://github.com/example/repo",
                "paper_url": "https://arxiv.org/abs/1234.5678",
                "user_prompt": "test",
            },
            headers=auth_headers(test_user),
        )
        assert r.status_code == 201
        assert r.json()["task_config"]["paper_url"] == "https://arxiv.org/abs/1234.5678"

    async def test_create_invalid_url(self, client: AsyncClient, test_user: User):
        r = await client.post(
            "/api/claw-instances",
            json={"github_url": "not-a-url"},
            headers=auth_headers(test_user),
        )
        assert r.status_code == 422

    async def test_create_unauthenticated(self, client: AsyncClient):
        r = await client.post(
            "/api/claw-instances",
            json={"github_url": "https://github.com/example/repo"},
        )
        assert r.status_code == 401


class TestListClawInstances:
    async def test_list_empty(self, client: AsyncClient, test_user: User):
        r = await client.get("/api/claw-instances", headers=auth_headers(test_user))
        assert r.status_code == 200
        assert r.json() == []

    async def test_list_own_instances(
        self, client: AsyncClient, test_user: User, db_session: AsyncSession
    ):
        inst = ClawInstance(
            user_id=test_user.id,
            status=ClawInstanceStatus.RUNNING,
            task_config={"github_url": "https://github.com/a/b"},
        )
        db_session.add(inst)
        await db_session.commit()

        r = await client.get("/api/claw-instances", headers=auth_headers(test_user))
        assert r.status_code == 200
        assert len(r.json()) == 1

    async def test_list_isolation(
        self, client: AsyncClient, test_user: User, admin_user: User, db_session: AsyncSession
    ):
        inst = ClawInstance(
            user_id=admin_user.id,
            status=ClawInstanceStatus.RUNNING,
            task_config={"github_url": "https://github.com/a/b"},
        )
        db_session.add(inst)
        await db_session.commit()

        r = await client.get("/api/claw-instances", headers=auth_headers(test_user))
        assert r.status_code == 200
        assert len(r.json()) == 0


class TestGetClawInstance:
    async def test_get_own_instance(
        self, client: AsyncClient, test_user: User, db_session: AsyncSession
    ):
        inst = ClawInstance(
            user_id=test_user.id,
            status=ClawInstanceStatus.COMPLETED,
            task_config={"github_url": "https://github.com/a/b"},
        )
        db_session.add(inst)
        await db_session.commit()
        await db_session.refresh(inst)

        r = await client.get(
            f"/api/claw-instances/{inst.id}", headers=auth_headers(test_user)
        )
        assert r.status_code == 200
        assert r.json()["status"] == "completed"

    async def test_get_other_user_instance(
        self, client: AsyncClient, test_user: User, admin_user: User, db_session: AsyncSession
    ):
        inst = ClawInstance(
            user_id=admin_user.id,
            status=ClawInstanceStatus.RUNNING,
            task_config={},
        )
        db_session.add(inst)
        await db_session.commit()
        await db_session.refresh(inst)

        r = await client.get(
            f"/api/claw-instances/{inst.id}", headers=auth_headers(test_user)
        )
        assert r.status_code == 404

    async def test_get_nonexistent(self, client: AsyncClient, test_user: User):
        r = await client.get("/api/claw-instances/9999", headers=auth_headers(test_user))
        assert r.status_code == 404


class TestStopClawInstance:
    async def test_stop_running_instance(
        self, client: AsyncClient, test_user: User, db_session: AsyncSession, mock_manager
    ):
        inst = ClawInstance(
            user_id=test_user.id,
            status=ClawInstanceStatus.RUNNING,
            task_config={},
        )
        db_session.add(inst)
        await db_session.commit()
        await db_session.refresh(inst)

        r = await client.post(
            f"/api/claw-instances/{inst.id}/stop", headers=auth_headers(test_user)
        )
        assert r.status_code == 200
        mock_manager.stop_task.assert_called_once_with(inst.id)

    async def test_stop_already_completed(
        self, client: AsyncClient, test_user: User, db_session: AsyncSession
    ):
        inst = ClawInstance(
            user_id=test_user.id,
            status=ClawInstanceStatus.COMPLETED,
            task_config={},
        )
        db_session.add(inst)
        await db_session.commit()
        await db_session.refresh(inst)

        r = await client.post(
            f"/api/claw-instances/{inst.id}/stop", headers=auth_headers(test_user)
        )
        assert r.status_code == 200
        assert r.json()["status"] == "completed"
