"""Anthropic-compatible LLM client used by the V2 agent loop."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, AsyncIterator

import httpx


@dataclass(slots=True)
class LLMRuntimeConfig:
    provider: str
    base_url: str
    api_key: str | None
    model: str
    max_tokens: int

    @property
    def configured(self) -> bool:
        return bool(self.api_key and self.model and self.base_url)


@dataclass(slots=True)
class LLMToolUse:
    id: str
    name: str
    input: dict[str, Any]


@dataclass(slots=True)
class LLMToolResponse:
    text: str
    tool_calls: list[LLMToolUse]
    stop_reason: str | None
    raw: dict[str, Any]


async def call_anthropic_compatible(
    config: LLMRuntimeConfig,
    *,
    system: str,
    messages: list[dict[str, str]],
) -> str:
    """Call Anthropic Messages API or an Anthropic-compatible endpoint."""
    if not config.configured:
        raise RuntimeError("LLM config is not complete")

    endpoint = _messages_endpoint(config.base_url)
    headers = {
        "content-type": "application/json",
        "anthropic-version": "2023-06-01",
        "x-api-key": config.api_key or "",
    }
    payload = {
        "model": config.model,
        "max_tokens": config.max_tokens,
        "system": system,
        "messages": messages,
    }
    async with httpx.AsyncClient(timeout=120) as client:
        response = await client.post(endpoint, headers=headers, json=payload)
        _raise_for_status_with_body(response)
        data = response.json()
    return _extract_text(data)


async def call_anthropic_compatible_tool_use(
    config: LLMRuntimeConfig,
    *,
    system: str,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]] | None = None,
) -> LLMToolResponse:
    """Call Anthropic Messages API and preserve text/tool_use content blocks."""
    if not config.configured:
        raise RuntimeError("LLM config is not complete")

    endpoint = _messages_endpoint(config.base_url)
    headers = {
        "content-type": "application/json",
        "anthropic-version": "2023-06-01",
        "x-api-key": config.api_key or "",
    }
    payload: dict[str, Any] = {
        "model": config.model,
        "max_tokens": config.max_tokens,
        "system": system,
        "messages": messages,
    }
    if tools is not None:
        payload["tools"] = tools

    async with httpx.AsyncClient(timeout=120) as client:
        response = await client.post(endpoint, headers=headers, json=payload)
        _raise_for_status_with_body(response)
        data = response.json()
    return _extract_tool_response(data)


async def stream_anthropic_compatible(
    config: LLMRuntimeConfig,
    *,
    system: str,
    messages: list[dict[str, str]],
) -> AsyncIterator[str]:
    """Stream text deltas from Anthropic Messages API compatible endpoints."""
    if not config.configured:
        raise RuntimeError("LLM config is not complete")

    endpoint = _messages_endpoint(config.base_url)
    headers = {
        "content-type": "application/json",
        "anthropic-version": "2023-06-01",
        "x-api-key": config.api_key or "",
    }
    payload = {
        "model": config.model,
        "max_tokens": config.max_tokens,
        "system": system,
        "messages": messages,
        "stream": True,
    }
    async with httpx.AsyncClient(timeout=120) as client:
        async with client.stream("POST", endpoint, headers=headers, json=payload) as response:
            response.raise_for_status()
            async for line in response.aiter_lines():
                if not line or line.startswith(":") or not line.startswith("data:"):
                    continue
                raw = line.removeprefix("data:").strip()
                if raw == "[DONE]":
                    break
                try:
                    data = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                text = _extract_stream_text(data)
                if text:
                    yield text


def _messages_endpoint(base_url: str) -> str:
    root = base_url.rstrip("/")
    if root.endswith("/v1"):
        return f"{root}/messages"
    if root.endswith("/v1/messages"):
        return root
    return f"{root}/v1/messages"


def _raise_for_status_with_body(response: httpx.Response) -> None:
    try:
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        body = response.text.strip()
        detail = f"{exc}"
        if body:
            detail = f"{detail}; response body: {body[:2000]}"
        raise RuntimeError(detail) from exc


def _extract_text(data: dict) -> str:
    content = data.get("content")
    if isinstance(content, list):
        parts = [
            block.get("text", "")
            for block in content
            if isinstance(block, dict) and block.get("type") == "text"
        ]
        text = "\n".join(part for part in parts if part).strip()
        if text:
            return text
    if isinstance(content, str):
        return content
    return str(data)


def _extract_tool_response(data: dict[str, Any]) -> LLMToolResponse:
    content = data.get("content")
    text_parts: list[str] = []
    tool_calls: list[LLMToolUse] = []

    if isinstance(content, list):
        for block in content:
            if not isinstance(block, dict):
                continue
            block_type = block.get("type")
            if block_type == "text":
                text = block.get("text")
                if text:
                    text_parts.append(str(text))
            elif block_type == "tool_use":
                tool_input = block.get("input")
                tool_calls.append(
                    LLMToolUse(
                        id=str(block.get("id") or ""),
                        name=str(block.get("name") or ""),
                        input=tool_input if isinstance(tool_input, dict) else {},
                    )
                )
    elif isinstance(content, str):
        text_parts.append(content)

    return LLMToolResponse(
        text="\n".join(part for part in text_parts if part).strip(),
        tool_calls=tool_calls,
        stop_reason=data.get("stop_reason") if isinstance(data.get("stop_reason"), str) else None,
        raw=data,
    )


def _extract_stream_text(data: dict) -> str:
    if data.get("type") == "content_block_delta":
        delta = data.get("delta")
        if isinstance(delta, dict) and delta.get("type") == "text_delta":
            return str(delta.get("text") or "")
    if data.get("type") == "content_block_start":
        block = data.get("content_block")
        if isinstance(block, dict) and block.get("type") == "text":
            return str(block.get("text") or "")

    # Some Anthropic-compatible gateways expose OpenAI-style SSE chunks.
    choices = data.get("choices")
    if isinstance(choices, list) and choices:
        first = choices[0]
        if isinstance(first, dict):
            delta = first.get("delta")
            if isinstance(delta, dict):
                return str(delta.get("content") or "")
    return ""
