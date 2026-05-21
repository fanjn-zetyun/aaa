from __future__ import annotations

import asyncio

import pytest

from app.services.agent_loop import AgentLoopManager
from app.services.llm_client import LLMRuntimeConfig, LLMToolResponse, LLMToolUse
from app.services.tools import ToolResult


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


async def test_invoke_tool_with_policy_scopes_confirmation_to_tool_call_id(
    test_user,
    db_session,
):
    from app.models import Conversation
    from app.models.conversation import ConversationStatus, ConversationTaskType

    manager = AgentLoopManager()
    conversation = Conversation(
        user_id=test_user.id,
        task_type=ConversationTaskType.GENERAL,
        title="tool confirm test",
        status=ConversationStatus.RUNNING,
        metadata_={},
    )
    db_session.add(conversation)
    await db_session.commit()
    await db_session.refresh(conversation)

    _, metadata, paused = await manager._invoke_tool_with_policy(
        conversation.id,
        {"workflow_run_id": "run-1"},
        "file_write",
        {
            "path": "/tmp/result.md",
            "content": "ok",
            "workflow_step_id": "step_8_generate_report",
            "tool_call_id": "toolu-file",
        },
    )

    assert paused is True
    pending = metadata["pending_user_input"]
    assert pending["tool_call_id"] == "toolu-file"
    assert pending["workflow_step_id"] == "step_8_generate_report"
    assert pending["run_id"] == "run-1"
    ask_event = [
        event for event in manager._streams[conversation.id].history if event["type"] == "ask_user"
    ][0]
    assert ask_event["tool_call_id"] == "toolu-file"
    assert ask_event["risk_level"] == "high"


async def test_lab4ai_missing_credentials_pauses_for_admin_intervention(
    monkeypatch,
    test_user,
    db_session,
):
    from app.models import Conversation
    from app.models.conversation import ConversationStatus, ConversationTaskType
    from app.services.conversation_memory import (
        mark_running,
        mark_waiting_for_user,
        resolve_pending_user_input,
    )

    async def fake_credentials(session):
        return None

    monkeypatch.setattr("app.services.tools.load_lab4ai_credentials", fake_credentials)
    manager = AgentLoopManager()
    conversation = Conversation(
        user_id=test_user.id,
        task_type=ConversationTaskType.REPRODUCE,
        title="missing credential test",
        status=ConversationStatus.RUNNING,
        metadata_={},
    )
    db_session.add(conversation)
    await db_session.commit()
    await db_session.refresh(conversation)
    metadata = mark_running({"task_type": "reproduce"})
    tool_input = {
        "resource_kind": "CPU",
        "workflow_step_id": "step_3_deploy_cpu",
        "tool_call_id": "toolu-lab4ai",
        "workflow_run_id": metadata["workflow_run_id"],
    }
    confirmation = manager._tools.confirmation_for("lab4ai_create_instance", tool_input)
    assert confirmation is not None
    metadata = mark_waiting_for_user(
        metadata,
        question=confirmation.question,
        options=list(confirmation.options),
        step=confirmation.step,
        tool_name="lab4ai_create_instance",
        tool_input=tool_input,
        tool_call_id=confirmation.tool_call_id,
        workflow_step_id=confirmation.workflow_step_id,
    )
    metadata = resolve_pending_user_input(metadata, answer="继续执行")

    result, metadata, paused = await manager._invoke_tool_with_policy(
        conversation.id,
        metadata,
        "lab4ai_create_instance",
        tool_input,
    )

    assert result is None
    assert paused is True
    pending = metadata["pending_user_input"]
    assert pending["intervention"]["type"] == "lab4ai_credentials_required"
    assert pending["tool_call_id"] == "toolu-lab4ai"
    assert pending["workflow_step_id"] == "step_3_deploy_cpu"
    event_types = [event["type"] for event in manager._streams[conversation.id].history]
    assert event_types == ["tool_started", "tool_completed", "ask_user", "status"]
    ask_event = next(
        event for event in manager._streams[conversation.id].history if event["type"] == "ask_user"
    )
    assert ask_event["intervention"]["type"] == "lab4ai_credentials_required"

    resumed = resolve_pending_user_input(metadata, answer="已完成配置，继续执行")
    assert resumed["memory"]["decisions"][-1]["outcome"] == "approved"


async def test_step_model_tool_use_executes_allowed_tool(monkeypatch):
    manager = AgentLoopManager()
    seen_tools: list[list[dict]] = []
    invoked: list[tuple[str, dict]] = []
    call_count = 0

    async def fake_tool_use(config, *, system, messages, tools):
        nonlocal call_count
        call_count += 1
        seen_tools.append(tools)
        if call_count > 1:
            return LLMToolResponse(
                text="分析完成。",
                tool_calls=[],
                stop_reason="end_turn",
                raw={},
            )
        return LLMToolResponse(
            text="需要先分析仓库。",
            tool_calls=[
                LLMToolUse(
                    id="toolu-1",
                    name="analyze_repo",
                    input={"github_url": "https://github.com/example/demo"},
                )
            ],
            stop_reason="tool_use",
            raw={},
        )

    async def fake_invoke(conversation_id, metadata, tool_name, tool_input):
        invoked.append((tool_name, tool_input))
        return ToolResult(tool_name, "repo ok"), metadata, False

    monkeypatch.setattr("app.services.agent_loop.call_anthropic_compatible_tool_use", fake_tool_use)
    monkeypatch.setattr(manager, "_invoke_tool_with_policy", fake_invoke)
    config = LLMRuntimeConfig(
        provider="anthropic",
        base_url="https://api.anthropic.com",
        api_key="key",
        model="model",
        max_tokens=4096,
    )
    step = type(
        "Step",
        (),
        {
            "id": "step_4_cpu_env_setup",
            "name": "CPU setup",
            "instruction": "inspect repo",
            "expected_output": "env ready",
        },
    )()

    metadata, outputs, paused, handled, failed = await manager._run_step_model_tool_use(
        1,
        {
            "workflow_run_id": "run-1",
            "workflow_steps": [
                {
                    "id": "step_4_cpu_env_setup",
                    "allowed_tools": ["analyze_repo"],
                }
            ],
        },
        step,
        config,
        system="system",
        messages=[{"role": "user", "content": "hello"}],
    )

    assert metadata["workflow_run_id"] == "run-1"
    assert paused is False
    assert handled is True
    assert failed is False
    assert outputs == ["analyze_repo: repo ok"]
    assert invoked == [
        (
            "analyze_repo",
            {
                "github_url": "https://github.com/example/demo",
                "tool_call_id": "toolu-1",
                "workflow_step_id": "step_4_cpu_env_setup",
            },
        )
    ]
    assert [tool["name"] for tool in seen_tools[0]] == ["analyze_repo"]


async def test_step_model_tool_use_fills_workflow_resource_context(monkeypatch):
    manager = AgentLoopManager()
    invoked: list[tuple[str, dict]] = []
    call_count = 0

    async def fake_tool_use(config, *, system, messages, tools):
        nonlocal call_count
        call_count += 1
        if call_count > 1:
            return LLMToolResponse(
                text="执行完成。",
                tool_calls=[],
                stop_reason="end_turn",
                raw={},
            )
        return LLMToolResponse(
            text="执行远程命令。",
            tool_calls=[
                LLMToolUse(
                    id="toolu-ssh",
                    name="ssh_execute",
                    input={"command": "echo ok"},
                )
            ],
            stop_reason="tool_use",
            raw={},
        )

    async def fake_invoke(conversation_id, metadata, tool_name, tool_input):
        invoked.append((tool_name, tool_input))
        return ToolResult(tool_name, "ssh ok"), metadata, False

    monkeypatch.setattr("app.services.agent_loop.call_anthropic_compatible_tool_use", fake_tool_use)
    monkeypatch.setattr(manager, "_invoke_tool_with_policy", fake_invoke)
    config = LLMRuntimeConfig(
        provider="anthropic",
        base_url="https://api.anthropic.com",
        api_key="key",
        model="model",
        max_tokens=4096,
    )
    step = type(
        "Step",
        (),
        {
            "id": "step_4_cpu_env_setup",
            "name": "CPU setup",
            "instruction": "run ssh",
            "expected_output": "env ready",
        },
    )()

    metadata, outputs, paused, handled, failed = await manager._run_step_model_tool_use(
        1,
        {
            "workflow_run_id": "run-1",
            "workflow_resources": {"cpu": {"server_id": "cpu-1"}},
            "workflow_steps": [
                {
                    "id": "step_4_cpu_env_setup",
                    "allowed_tools": ["ssh_execute"],
                }
            ],
        },
        step,
        config,
        system="system",
        messages=[{"role": "user", "content": "hello"}],
    )

    assert paused is False
    assert handled is True
    assert failed is False
    assert outputs == ["ssh_execute: ssh ok"]
    assert invoked == [
        (
            "ssh_execute",
            {
                "command": "echo ok",
                "tool_call_id": "toolu-ssh",
                "workflow_step_id": "step_4_cpu_env_setup",
                "resource_kind": "CPU",
                "server_id": "cpu-1",
            },
        )
    ]
    assert metadata["workflow_run_id"] == "run-1"


async def test_step_model_tool_use_renders_skill_ssh_wrapper(monkeypatch):
    manager = AgentLoopManager()
    invoked: list[tuple[str, dict]] = []
    call_count = 0

    skill_command = (
        "RETRY=0; while ! sshpass -p '{{step_3.ssh_pass}}' ssh "
        "-o StrictHostKeyChecking=no -p {{step_3.ssh_port}} root@{{step_3.ssh_host}} "
        "\"echo ready\"; do sleep 10; done; "
        "sshpass -p '{{step_3.ssh_pass}}' ssh -o StrictHostKeyChecking=no "
        "-p {{step_3.ssh_port}} root@{{step_3.ssh_host}} "
        "\"mkdir -p /workspace/user-data/codelab/{{repo_name}}/code && "
        "cd /workspace/user-data/codelab/{{repo_name}}/code && "
        "git clone --recursive https://gh-proxy.org/{{parameters.github_url}} .\""
    )

    async def fake_tool_use(config, *, system, messages, tools):
        nonlocal call_count
        call_count += 1
        if call_count > 1:
            return LLMToolResponse(
                text="执行完成。",
                tool_calls=[],
                stop_reason="end_turn",
                raw={},
            )
        return LLMToolResponse(
            text="按 skill 执行 SSH 探活和克隆。",
            tool_calls=[
                LLMToolUse(
                    id="toolu-skill-ssh",
                    name="ssh_execute",
                    input={"command": skill_command},
                )
            ],
            stop_reason="tool_use",
            raw={},
        )

    async def fake_invoke(conversation_id, metadata, tool_name, tool_input):
        invoked.append((tool_name, tool_input))
        return ToolResult(tool_name, "ssh ok"), metadata, False

    monkeypatch.setattr("app.services.agent_loop.call_anthropic_compatible_tool_use", fake_tool_use)
    monkeypatch.setattr(manager, "_invoke_tool_with_policy", fake_invoke)
    config = LLMRuntimeConfig(
        provider="anthropic",
        base_url="https://api.anthropic.com",
        api_key="key",
        model="model",
        max_tokens=4096,
    )
    step = type(
        "Step",
        (),
        {
            "id": "step_4_cpu_env_setup",
            "name": "CPU setup",
            "instruction": "run skill ssh wrapper",
            "expected_output": "env ready",
        },
    )()

    _metadata, outputs, paused, handled, failed = await manager._run_step_model_tool_use(
        1,
        {
            "workflow_run_id": "run-1",
            "github_url": "https://github.com/example/demo",
            "workflow_resources": {
                "cpu": {
                    "server_id": "cpu-1",
                    "raw": {
                        "ssh_host": "10.0.0.1",
                        "ssh_port": "2222",
                        "ssh_user": "root",
                    },
                }
            },
            "workflow_steps": [
                {
                    "id": "step_4_cpu_env_setup",
                    "allowed_tools": ["ssh_execute"],
                }
            ],
        },
        step,
        config,
        system="system",
        messages=[{"role": "user", "content": "hello"}],
    )

    assert paused is False
    assert handled is True
    assert failed is False
    assert outputs == ["ssh_execute: ssh ok"]
    assert len(invoked) == 1
    tool_input = invoked[0][1]
    assert invoked[0][0] == "ssh_execute"
    assert tool_input["server_id"] == "cpu-1"
    assert tool_input["resource_kind"] == "CPU"
    assert tool_input["connect_retries"] == 30
    assert "sshpass" not in tool_input["command"]
    assert "{{" not in tool_input["command"]
    assert "/workspace/user-data/codelab/demo/code" in tool_input["command"]
    assert "https://gh-proxy.org/https://github.com/example/demo" in tool_input["command"]


async def test_step_model_tool_use_accepts_claw_shell_alias(monkeypatch):
    manager = AgentLoopManager()
    invoked: list[tuple[str, dict]] = []
    call_count = 0

    skill_command = (
        "RETRY=0; while ! sshpass -p '{{step_3.ssh_pass}}' ssh "
        "-p {{step_3.ssh_port}} root@{{step_3.ssh_host}} \"echo ready\"; "
        "do sleep 10; done; sshpass -p '{{step_3.ssh_pass}}' ssh "
        "-p {{step_3.ssh_port}} root@{{step_3.ssh_host}} \"echo cloned\""
    )

    async def fake_tool_use(config, *, system, messages, tools):
        nonlocal call_count
        call_count += 1
        if call_count > 1:
            return LLMToolResponse(
                text="执行完成。",
                tool_calls=[],
                stop_reason="end_turn",
                raw={},
            )
        return LLMToolResponse(
            text="调用 claw-shell 兼容入口。",
            tool_calls=[
                LLMToolUse(
                    id="toolu-claw",
                    name="claw_shell_run",
                    input={"command": skill_command},
                )
            ],
            stop_reason="tool_use",
            raw={},
        )

    async def fake_invoke(conversation_id, metadata, tool_name, tool_input):
        invoked.append((tool_name, tool_input))
        return ToolResult(tool_name, "ssh ok"), metadata, False

    monkeypatch.setattr("app.services.agent_loop.call_anthropic_compatible_tool_use", fake_tool_use)
    monkeypatch.setattr(manager, "_invoke_tool_with_policy", fake_invoke)
    config = LLMRuntimeConfig(
        provider="anthropic",
        base_url="https://api.anthropic.com",
        api_key="key",
        model="model",
        max_tokens=4096,
    )
    step = type(
        "Step",
        (),
        {
            "id": "step_4_cpu_env_setup",
            "name": "CPU setup",
            "instruction": "请调用 claw-shell 技能执行 SSH 探活。",
            "expected_output": "env ready",
        },
    )()

    metadata, outputs, paused, handled, failed = await manager._run_step_model_tool_use(
        1,
        {
            "workflow_run_id": "run-1",
            "workflow_resources": {"cpu": {"server_id": "cpu-1"}},
            "workflow_steps": [
                {
                    "id": "step_4_cpu_env_setup",
                    "allowed_tools": ["claw_shell_run"],
                }
            ],
        },
        step,
        config,
        system="system",
        messages=[{"role": "user", "content": "hello"}],
    )

    assert paused is False
    assert handled is True
    assert failed is False
    assert outputs == ["ssh_execute: ssh ok"]
    assert invoked[0][0] == "ssh_execute"
    assert invoked[0][1]["server_id"] == "cpu-1"
    assert invoked[0][1]["connect_retries"] == 30
    assert invoked[0][1]["command"] == "echo cloned"
    assert metadata["workflow_run_id"] == "run-1"


async def test_step_model_tool_use_rejects_ssh_wrapper_without_remote_command(monkeypatch):
    manager = AgentLoopManager()
    invoked: list[tuple[str, dict]] = []

    async def fake_tool_use(config, *, system, messages, tools):
        return LLMToolResponse(
            text="误用了交互式 SSH wrapper。",
            tool_calls=[
                LLMToolUse(
                    id="toolu-wrapper",
                    name="claw_shell_run",
                    input={
                        "command": (
                            "export SSHPASS='secret'; "
                            "sshpass -e ssh -p 2222 root@10.0.0.1; unset SSHPASS"
                        )
                    },
                )
            ],
            stop_reason="tool_use",
            raw={},
        )

    async def fake_invoke(conversation_id, metadata, tool_name, tool_input):
        invoked.append((tool_name, tool_input))
        return ToolResult(tool_name, "should not run"), metadata, False

    monkeypatch.setattr("app.services.agent_loop.call_anthropic_compatible_tool_use", fake_tool_use)
    monkeypatch.setattr(manager, "_invoke_tool_with_policy", fake_invoke)
    config = LLMRuntimeConfig(
        provider="anthropic",
        base_url="https://api.anthropic.com",
        api_key="key",
        model="model",
        max_tokens=4096,
    )
    step = type(
        "Step",
        (),
        {
            "id": "step_4_cpu_env_setup",
            "name": "CPU setup",
            "instruction": "调用 claw-shell SSH 登录。",
            "expected_output": "env ready",
        },
    )()

    _metadata, outputs, paused, handled, failed = await manager._run_step_model_tool_use(
        1,
        {
            "workflow_run_id": "run-1",
            "workflow_resources": {"cpu": {"server_id": "cpu-1"}},
            "workflow_steps": [
                {
                    "id": "step_4_cpu_env_setup",
                    "allowed_tools": ["claw_shell_run"],
                }
            ],
        },
        step,
        config,
        system="system",
        messages=[{"role": "user", "content": "hello"}],
    )

    assert paused is False
    assert handled is True
    assert failed is True
    assert invoked == []
    assert "没有可安全提取的远程命令" in outputs[0]


async def test_step_model_tool_use_fails_on_unresolved_templates(monkeypatch):
    manager = AgentLoopManager()
    invoked: list[tuple[str, dict]] = []

    async def fake_tool_use(config, *, system, messages, tools):
        return LLMToolResponse(
            text="按 YAML 执行 SSH 探活。",
            tool_calls=[
                LLMToolUse(
                    id="toolu-template",
                    name="ssh_execute",
                    input={"command": "ssh root@{{step_3.ssh_host}} echo ok"},
                )
            ],
            stop_reason="tool_use",
            raw={},
        )

    async def fake_invoke(conversation_id, metadata, tool_name, tool_input):
        invoked.append((tool_name, tool_input))
        return ToolResult(tool_name, "should not run"), metadata, False

    monkeypatch.setattr("app.services.agent_loop.call_anthropic_compatible_tool_use", fake_tool_use)
    monkeypatch.setattr(manager, "_invoke_tool_with_policy", fake_invoke)
    config = LLMRuntimeConfig(
        provider="anthropic",
        base_url="https://api.anthropic.com",
        api_key="key",
        model="model",
        max_tokens=4096,
    )
    step = type(
        "Step",
        (),
        {
            "id": "step_4_cpu_env_setup",
            "name": "CPU setup",
            "instruction": "run ssh",
            "expected_output": "env ready",
        },
    )()

    metadata, outputs, paused, handled, failed = await manager._run_step_model_tool_use(
        1,
        {
            "workflow_run_id": "run-1",
            "workflow_resources": {"cpu": {"server_id": "cpu-1"}},
            "workflow_steps": [
                {
                    "id": "step_4_cpu_env_setup",
                    "allowed_tools": ["ssh_execute"],
                }
            ],
        },
        step,
        config,
        system="system",
        messages=[{"role": "user", "content": "hello"}],
    )

    assert metadata["workflow_run_id"] == "run-1"
    assert paused is False
    assert handled is True
    assert failed is True
    assert invoked == []
    assert "未渲染模板变量" in outputs[0]


async def test_long_term_memory_context_formats_search_results(monkeypatch):
    manager = AgentLoopManager()

    class Memory:
        kind = "project"
        content = "用户常用 PyTorch 环境"
        keywords = ["pytorch"]
        source_conversation_id = 1
        source_message_id = None
        created_at = None

    async def fake_search(session, user_id, query, limit):
        return [Memory()]

    monkeypatch.setattr("app.services.agent_loop.search_user_memories", fake_search)

    context = await manager._long_term_memory_context(123, "PyTorch 项目")

    assert "长期记忆上下文" in context
    assert "用户常用 PyTorch 环境" in context


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
