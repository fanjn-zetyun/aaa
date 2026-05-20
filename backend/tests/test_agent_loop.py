from __future__ import annotations

import pytest

from app.services.agent_loop import AgentLoopManager
from app.services.llm_client import LLMRuntimeConfig


pytestmark = pytest.mark.asyncio


async def test_model_or_fallback_retries_with_lower_token_budget(monkeypatch):
    seen_tokens: list[int] = []

    async def fake_call(config, *, system, messages):
        seen_tokens.append(config.max_tokens)
        if config.max_tokens == 8192:
            raise RuntimeError("max_tokens too high")
        return "OK"

    monkeypatch.setattr("app.services.agent_loop.call_anthropic_compatible", fake_call)
    manager = AgentLoopManager()
    config = LLMRuntimeConfig(
        provider="anthropic",
        base_url="https://api.anthropic.com",
        api_key="key",
        model="model",
        max_tokens=4096,
    )

    reply = await manager._model_or_fallback(
        config,
        system="system",
        messages=[{"role": "user", "content": "hello"}],
        max_tokens=8192,
        fallback="fallback",
    )

    assert reply == "OK"
    assert seen_tokens == [8192, 4096]
