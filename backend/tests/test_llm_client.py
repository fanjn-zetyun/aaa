from __future__ import annotations

from typing import Any

import httpx
import pytest

from app.services.llm_client import (
    LLMRuntimeConfig,
    call_anthropic_compatible_tool_use,
)


pytestmark = pytest.mark.asyncio


class FakeResponse:
    def __init__(self, data: dict[str, Any]) -> None:
        self._data = data

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, Any]:
        return self._data


def _config() -> LLMRuntimeConfig:
    return LLMRuntimeConfig(
        provider="anthropic",
        base_url="https://api.example.com",
        api_key="test-key",
        model="claude-compatible",
        max_tokens=1024,
    )


async def test_call_anthropic_compatible_tool_use_parses_text_response(monkeypatch):
    async def fake_post(self, url, *, headers, json):
        assert url == "https://api.example.com/v1/messages"
        assert headers["x-api-key"] == "test-key"
        assert json["messages"] == [{"role": "user", "content": "hello"}]
        return FakeResponse(
            {
                "content": [{"type": "text", "text": "Hello"}],
                "stop_reason": "end_turn",
            }
        )

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)

    response = await call_anthropic_compatible_tool_use(
        _config(),
        system="system",
        messages=[{"role": "user", "content": "hello"}],
    )

    assert response.text == "Hello"
    assert response.tool_calls == []
    assert response.stop_reason == "end_turn"
    assert response.raw["stop_reason"] == "end_turn"


async def test_call_anthropic_compatible_tool_use_parses_tool_use_response(monkeypatch):
    async def fake_post(self, url, *, headers, json):
        return FakeResponse(
            {
                "content": [
                    {"type": "text", "text": "I will inspect the repo."},
                    {
                        "type": "tool_use",
                        "id": "toolu_123",
                        "name": "analyze_repo",
                        "input": {"github_url": "https://github.com/example/repo"},
                    },
                ],
                "stop_reason": "tool_use",
            }
        )

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)

    response = await call_anthropic_compatible_tool_use(
        _config(),
        system="system",
        messages=[{"role": "user", "content": "analyze this"}],
    )

    assert response.text == "I will inspect the repo."
    assert response.stop_reason == "tool_use"
    assert len(response.tool_calls) == 1
    tool_call = response.tool_calls[0]
    assert tool_call.id == "toolu_123"
    assert tool_call.name == "analyze_repo"
    assert tool_call.input == {"github_url": "https://github.com/example/repo"}


async def test_call_anthropic_compatible_tool_use_sends_tools_payload(monkeypatch):
    captured_payload: dict[str, Any] = {}
    tools = [
        {
            "name": "analyze_repo",
            "description": "Analyze repository structure",
            "input_schema": {
                "type": "object",
                "properties": {"github_url": {"type": "string"}},
                "required": ["github_url"],
            },
        }
    ]

    async def fake_post(self, url, *, headers, json):
        captured_payload.update(json)
        return FakeResponse({"content": [{"type": "text", "text": "OK"}]})

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)

    await call_anthropic_compatible_tool_use(
        _config(),
        system="system",
        messages=[{"role": "user", "content": "use tools"}],
        tools=tools,
    )

    assert captured_payload["tools"] == tools


async def test_call_anthropic_compatible_tool_use_requires_complete_config():
    config = LLMRuntimeConfig(
        provider="anthropic",
        base_url="",
        api_key=None,
        model="",
        max_tokens=1024,
    )

    with pytest.raises(RuntimeError, match="LLM config is not complete"):
        await call_anthropic_compatible_tool_use(
            config,
            system="system",
            messages=[{"role": "user", "content": "hello"}],
        )
