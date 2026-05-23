from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.services.llm_client import (
    LLMRuntimeConfig,
    LLMToolUse,
    call_anthropic_compatible_tool_use,
)


@dataclass(slots=True)
class ModelRequest:
    system: str
    messages: list[dict[str, Any]]
    tools: list[dict[str, Any]]
    max_tokens: int
    tool_choice: dict[str, Any] | None = None
    temperature: float | None = None


@dataclass(slots=True)
class ModelResponse:
    text: str
    tool_calls: list[LLMToolUse]
    stop_reason: str | None
    usage: dict[str, Any]
    raw: dict[str, Any]


class LLMAdapter:
    def __init__(self, config: LLMRuntimeConfig) -> None:
        self.config = config

    async def complete(self, request: ModelRequest) -> ModelResponse:
        if not self.config.configured:
            raise RuntimeError("模型配置不完整，无法启动 Agent Runtime。")
        runtime_config = LLMRuntimeConfig(
            provider=self.config.provider,
            base_url=self.config.base_url,
            api_key=self.config.api_key,
            model=self.config.model,
            max_tokens=request.max_tokens,
        )
        response = await call_anthropic_compatible_tool_use(
            runtime_config,
            system=request.system,
            messages=request.messages,
            tools=request.tools,
        )
        raw = response.raw or {}
        usage = raw.get("usage") if isinstance(raw.get("usage"), dict) else {}
        return ModelResponse(
            text=response.text,
            tool_calls=list(response.tool_calls),
            stop_reason=response.stop_reason,
            usage=dict(usage),
            raw=raw,
        )
