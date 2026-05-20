from __future__ import annotations

import pytest

from app.models import LLMConfig, User
from app.models.user import UserRole
from app.core.security import create_access_token, hash_password


def auth_headers(user: User) -> dict[str, str]:
    token = create_access_token(user.id, extra={"role": user.role.value})
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.asyncio
async def test_llm_config_connection_test_uses_saved_key(client, db_session, monkeypatch):
    user = User(
        username="llmuser",
        password_hash=hash_password("password123"),
        role=UserRole.USER,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)

    db_session.add(
        LLMConfig(
            user_id=user.id,
            provider="anthropic",
            base_url="https://api.anthropic.com",
            api_key_encrypted="saved-key",
            model="claude-sonnet-4-6",
        )
    )
    await db_session.commit()

    async def fake_call(config, *, system, messages):
        assert config.api_key == "saved-key"
        assert config.max_tokens == 32
        assert messages == [{"role": "user", "content": "请回复 OK"}]
        return "OK"

    monkeypatch.setattr("app.api.llm_config.call_anthropic_compatible", fake_call)

    response = await client.post(
        "/api/llm-config/test",
        json={
            "provider": "anthropic",
            "base_url": "https://api.anthropic.com",
            "api_key": None,
            "model": "claude-sonnet-4-6",
        },
        headers=auth_headers(user),
    )

    assert response.status_code == 200
    assert response.json() == {"ok": True, "message": "OK"}


@pytest.mark.asyncio
async def test_llm_config_response_hides_max_tokens(client, test_user):
    response = await client.get("/api/llm-config", headers=auth_headers(test_user))

    assert response.status_code == 200
    assert "max_tokens" not in response.json()
