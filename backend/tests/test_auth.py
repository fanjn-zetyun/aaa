"""Auth tests: register, login, and current user."""

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
            json={
                "phone": "13800138000",
                "institution": "Test University",
                "password": "secret123",
            },
        )
        assert r.status_code == 201
        data = r.json()
        assert data["username"] == "13800138000"
        assert data["institution"] == "Test University"
        assert data["role"] == "user"
        assert data["is_active"] is True

    async def test_register_accepts_e164_china_phone(self, client: AsyncClient):
        r = await client.post(
            "/api/auth/register",
            json={
                "phone": "+8613800138004",
                "institution": "Test University",
                "password": "secret123",
            },
        )
        assert r.status_code == 201
        assert r.json()["username"] == "13800138004"

    async def test_register_duplicate_phone(self, client: AsyncClient):
        payload = {
            "phone": "13900139000",
            "institution": "Test University",
            "password": "secret123",
        }
        first = await client.post("/api/auth/register", json=payload)
        assert first.status_code == 201

        second = await client.post("/api/auth/register", json=payload)
        assert second.status_code == 409
        assert second.json()["detail"] == "该手机号已注册，请直接登录"

    async def test_register_invalid_phone(self, client: AsyncClient):
        r = await client.post(
            "/api/auth/register",
            json={
                "phone": "not-phone",
                "institution": "Test University",
                "password": "secret123",
            },
        )
        assert r.status_code == 422

    async def test_register_invalid_mobile_prefix(self, client: AsyncClient):
        r = await client.post(
            "/api/auth/register",
            json={
                "phone": "12345678901",
                "institution": "Test University",
                "password": "secret123",
            },
        )
        assert r.status_code == 422

    async def test_register_missing_institution(self, client: AsyncClient):
        r = await client.post(
            "/api/auth/register",
            json={"phone": "13800138001", "password": "secret123"},
        )
        assert r.status_code == 422

    async def test_register_blank_institution(self, client: AsyncClient):
        r = await client.post(
            "/api/auth/register",
            json={
                "phone": "13800138002",
                "institution": "   ",
                "password": "secret123",
            },
        )
        assert r.status_code == 422

    async def test_register_short_password(self, client: AsyncClient):
        r = await client.post(
            "/api/auth/register",
            json={
                "phone": "13800138003",
                "institution": "Test University",
                "password": "12345",
            },
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

    async def test_login_accepts_e164_china_phone(self, client: AsyncClient):
        await client.post(
            "/api/auth/register",
            json={
                "phone": "13800138005",
                "institution": "Test University",
                "password": "secret123",
            },
        )
        r = await client.post(
            "/api/auth/login",
            data={"username": "+8613800138005", "password": "secret123"},
        )
        assert r.status_code == 200

    async def test_login_wrong_password(self, client: AsyncClient, test_user: User):
        r = await client.post(
            "/api/auth/login",
            data={"username": "testuser", "password": "wrongpass"},
        )
        assert r.status_code == 401

    async def test_login_nonexistent_user(self, client: AsyncClient):
        r = await client.post(
            "/api/auth/login",
            data={"username": "13800999000", "password": "whatever"},
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

    async def test_admin_backdoor_login_creates_admin(self, client: AsyncClient):
        r = await client.post(
            "/api/auth/login",
            data={"username": "admin", "password": "admin123"},
        )
        assert r.status_code == 200
        headers = {"Authorization": f"Bearer {r.json()['access_token']}"}

        me = await client.get("/api/auth/me", headers=headers)
        assert me.status_code == 200
        data = me.json()
        assert data["username"] == "admin"
        assert data["role"] == "admin"
        assert data["institution"] == "Platform Admin"

    async def test_admin_backdoor_rejects_admin124(self, client: AsyncClient):
        r = await client.post(
            "/api/auth/login",
            data={"username": "admin", "password": "admin124"},
        )
        assert r.status_code == 401


class TestMe:
    async def test_me_success(self, client: AsyncClient, test_user: User):
        r = await client.get("/api/auth/me", headers=auth_headers(test_user))
        assert r.status_code == 200
        data = r.json()
        assert data["username"] == "testuser"
        assert data["institution"] == ""
        assert data["gpu_quota_hours"] == 10.0

    async def test_me_no_token(self, client: AsyncClient):
        r = await client.get("/api/auth/me")
        assert r.status_code == 401

    async def test_me_invalid_token(self, client: AsyncClient):
        r = await client.get(
            "/api/auth/me", headers={"Authorization": "Bearer invalid.token.here"}
        )
        assert r.status_code == 401
