"""Anthropic-compatible LLM client used by the V2 agent loop."""

from __future__ import annotations

from dataclasses import dataclass

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
        response.raise_for_status()
        data = response.json()
    return _extract_text(data)


def _messages_endpoint(base_url: str) -> str:
    root = base_url.rstrip("/")
    if root.endswith("/v1"):
        return f"{root}/messages"
    if root.endswith("/v1/messages"):
        return root
    return f"{root}/v1/messages"


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
