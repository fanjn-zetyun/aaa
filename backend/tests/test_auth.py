"""auth 模块单元测试：注册、登录、获取当前用户。"""

from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import User
from tests.conftest import auth_headers


pytestmark = pytest.mark.asyncio


class TestRegister:
    async def test_register_success(self, client: AsyncClient):
        r = await client.post(
            "/api/auth/register",
            json={"username": "newuser", "password": "secret123"},
        )
        assert r.status_code == 201
        data = r.json()
        assert data["username"] == "newuser"
        assert data["role"] == "user"
        assert data["is_active"] is True

    async def test_register_duplicate_username(self, client: AsyncClient, test_user: User):
        r = await client.post(
            "/api/auth/register",
            json={"username": "testuser", "password": "another123"},
        )
        assert r.status_code == 409
        assert "已被占用" in r.json()["detail"]

    async def test_register_short_username(self, client: AsyncClient):
        r = await client.post(
            "/api/auth/register",
            json={"username": "ab", "password": "secret123"},
        )
        assert r.status_code == 422

    async def test_register_short_password(self, client: AsyncClient):
        r = await client.post(
            "/api/auth/register",
            json={"username": "validname", "password": "12345"},
        )
        assert r.status_code == 422


class TestLogin:
    async def test_login_success(self, client: AsyncClient, test_user: User):
        r = await client.post(
            "/api/auth/login",
            data={"username": "testuser", "password": "password123"},
        )
        assert r.status_code == 200
        data = r.json()
        assert "access_token" in data
        assert data["token_type"] == "bearer"

    async def test_login_wrong_password(self, client: AsyncClient, test_user: User):
        r = await client.post(
            "/api/auth/login",
            data={"username": "testuser", "password": "wrongpass"},
        )
        assert r.status_code == 401

    async def test_login_nonexistent_user(self, client: AsyncClient):
        r = await client.post(
            "/api/auth/login",
            data={"username": "ghost", "password": "whatever"},
        )
        assert r.status_code == 401

    async def test_login_inactive_user(
        self, client: AsyncClient, db_session: AsyncSession, test_user: User
    ):
        test_user.is_active = False
        await db_session.commit()
        r = await client.post(
            "/api/auth/login",
            data={"username": "testuser", "password": "password123"},
        )
        assert r.status_code == 403


class TestMe:
    async def test_me_success(self, client: AsyncClient, test_user: User):
        r = await client.get("/api/auth/me", headers=auth_headers(test_user))
        assert r.status_code == 200
        data = r.json()
        assert data["username"] == "testuser"
        assert data["gpu_quota_hours"] == 10.0

    async def test_me_no_token(self, client: AsyncClient):
        r = await client.get("/api/auth/me")
        assert r.status_code == 401

    async def test_me_invalid_token(self, client: AsyncClient):
        r = await client.get(
            "/api/auth/me", headers={"Authorization": "Bearer invalid.token.here"}
        )
        assert r.status_code == 401
