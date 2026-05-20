"""Per-user LLM configuration endpoints."""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException
from sqlalchemy import select

from app.api.deps import CurrentUser, DbSession
from app.models import LLMConfig
from app.schemas.conversation import (
    LLMConfigResponse,
    LLMConfigTestResponse,
    LLMConfigUpdateRequest,
)
from app.services.llm_client import LLMRuntimeConfig, call_anthropic_compatible

router = APIRouter(prefix="/api/llm-config", tags=["llm-config"])


@router.get("", response_model=LLMConfigResponse)
async def get_llm_config(user: CurrentUser, session: DbSession) -> LLMConfigResponse:
    config = await session.scalar(select(LLMConfig).where(LLMConfig.user_id == user.id))
    if config is None:
        return LLMConfigResponse(
            provider="anthropic",
            base_url="https://api.anthropic.com",
            model="claude-sonnet-4-6",
            api_key_configured=False,
            updated_at=None,
        )
    return _to_response(config)


@router.put("", response_model=LLMConfigResponse)
async def update_llm_config(
    payload: LLMConfigUpdateRequest, user: CurrentUser, session: DbSession
) -> LLMConfigResponse:
    config = await session.scalar(select(LLMConfig).where(LLMConfig.user_id == user.id))
    if config is None:
        config = LLMConfig(user_id=user.id)
        session.add(config)

    config.provider = payload.provider
    config.base_url = payload.base_url.rstrip("/")
    config.model = payload.model
    if payload.api_key:
        # MVP: do not return the key to clients. A later migration can replace this with
        # project-wide encryption once key management is finalized.
        config.api_key_encrypted = payload.api_key
    config.updated_at = datetime.now(UTC)
    await session.commit()
    await session.refresh(config)
    return _to_response(config)


def _to_response(config: LLMConfig) -> LLMConfigResponse:
    return LLMConfigResponse(
        provider=config.provider,
        base_url=config.base_url,
        model=config.model,
        api_key_configured=bool(config.api_key_encrypted),
        updated_at=config.updated_at,
    )


@router.post("/test", response_model=LLMConfigTestResponse)
async def test_llm_config(
    payload: LLMConfigUpdateRequest, user: CurrentUser, session: DbSession
) -> LLMConfigTestResponse:
    config = await session.scalar(select(LLMConfig).where(LLMConfig.user_id == user.id))
    api_key = payload.api_key or (config.api_key_encrypted if config else None)
    runtime_config = LLMRuntimeConfig(
        provider=payload.provider,
        base_url=payload.base_url.rstrip("/"),
        api_key=api_key,
        model=payload.model,
        max_tokens=32,
    )

    try:
        reply = await call_anthropic_compatible(
            runtime_config,
            system="你是一个连通性测试助手，只需返回一个简短确认。",
            messages=[{"role": "user", "content": "请回复 OK"}],
        )
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=f"模型连通性测试失败：{exc}") from exc

    return LLMConfigTestResponse(ok=True, message=reply.strip() or "连通性测试成功")
