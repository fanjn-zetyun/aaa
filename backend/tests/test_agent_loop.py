from __future__ import annotations

import asyncio

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


async def test_stream_model_or_fallback_publishes_deltas_and_persists_one_message(
    monkeypatch,
    test_user,
    db_session,
):
    from app.models import Conversation
    from app.models.conversation import ConversationStatus, ConversationTaskType

    async def fake_stream(config, *, system, messages):
        yield "Hello"
        yield " world"

    monkeypatch.setattr("app.services.agent_loop.stream_anthropic_compatible", fake_stream)
    manager = AgentLoopManager()
    conversation = Conversation(
        user_id=test_user.id,
        task_type=ConversationTaskType.GENERAL,
        title="stream test",
        status=ConversationStatus.RUNNING,
        metadata_={},
    )
    db_session.add(conversation)
    await db_session.commit()
    await db_session.refresh(conversation)
    manager._active_runs[conversation.id] = "run-1"

    config = LLMRuntimeConfig(
        provider="anthropic",
        base_url="https://api.anthropic.com",
        api_key="key",
        model="model",
        max_tokens=4096,
    )

    reply = await manager._stream_model_or_fallback(
        conversation.id,
        config,
        system="system",
        messages=[{"role": "user", "content": "hello"}],
        max_tokens=8192,
        fallback="fallback",
    )

    assert reply == "Hello world"
    event_types = [event["type"] for event in manager._streams[conversation.id].history]
    assert event_types == [
        "assistant_started",
        "assistant_delta",
        "assistant_delta",
        "assistant_completed",
    ]
    assert [event["seq"] for event in manager._streams[conversation.id].history] == [1, 2, 3, 4]
    assert all(event["run_id"] == "run-1" for event in manager._streams[conversation.id].history)

    completed = manager._streams[conversation.id].history[-1]
    assert completed["message"]["role"] == "assistant"
    assert completed["message"]["content"] == "Hello world"


async def test_invoke_tool_with_policy_publishes_start_and_completed(test_user, db_session):
    from app.models import Conversation
    from app.models.conversation import ConversationStatus, ConversationTaskType

    manager = AgentLoopManager()
    conversation = Conversation(
        user_id=test_user.id,
        task_type=ConversationTaskType.GENERAL,
        title="tool test",
        status=ConversationStatus.RUNNING,
        metadata_={},
    )
    db_session.add(conversation)
    await db_session.commit()
    await db_session.refresh(conversation)

    result, _, paused = await manager._invoke_tool_with_policy(
        conversation.id,
        {},
        "analyze_repo",
        {"github_url": "https://github.com/showlab/PhotoDoodle"},
    )

    assert paused is False
    assert result is not None
    events = manager._streams[conversation.id].history
    assert [event["type"] for event in events] == ["tool_started", "tool_completed"]
    assert events[0]["tool_name"] == "analyze_repo"
    assert events[1]["message"]["role"] == "tool"


async def test_start_queues_restart_when_existing_task_is_finishing(monkeypatch):
    manager = AgentLoopManager()
    calls: list[int] = []
    release = asyncio.Event()

    async def fake_run(conversation_id: int):
        calls.append(conversation_id)
        await release.wait()

    monkeypatch.setattr(manager, "_run", fake_run)

    manager.start(42)
    await asyncio.sleep(0)
    manager.start(42)

    assert manager._pending_starts == {42}
    release.set()
    for _ in range(10):
        if len(calls) == 2:
            break
        await asyncio.sleep(0)

    assert calls == [42, 42]
