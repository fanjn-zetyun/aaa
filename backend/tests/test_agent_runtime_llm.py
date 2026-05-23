import pytest

from app.agent_runtime.llm import LLMAdapter, ModelRequest
from app.services.llm_client import LLMRuntimeConfig, LLMToolResponse, LLMToolUse


@pytest.mark.asyncio
async def test_llm_adapter_normalizes_tool_response(monkeypatch):
    async def fake_call(config, *, system, messages, tools):
        return LLMToolResponse(
            text="我需要调用工具。",
            tool_calls=[LLMToolUse(id="toolu_1", name="ask_user", input={"question": "继续吗？"})],
            stop_reason="tool_use",
            raw={"usage": {"input_tokens": 10, "output_tokens": 5}},
        )

    monkeypatch.setattr("app.agent_runtime.llm.call_anthropic_compatible_tool_use", fake_call)
    adapter = LLMAdapter(
        LLMRuntimeConfig(
            provider="anthropic",
            base_url="https://example.com",
            api_key="key",
            model="claude-test",
            max_tokens=4096,
        )
    )

    response = await adapter.complete(
        ModelRequest(
            system="system",
            messages=[{"role": "user", "content": "hi"}],
            tools=[{"name": "ask_user", "description": "ask", "input_schema": {"type": "object"}}],
            max_tokens=2048,
        )
    )

    assert response.text == "我需要调用工具。"
    assert response.tool_calls[0].name == "ask_user"
    assert response.usage == {"input_tokens": 10, "output_tokens": 5}
