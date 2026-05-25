from __future__ import annotations

import asyncio

import pytest

from app.services.agent_loop import (
    AgentLoopManager,
    _apply_model_tool_result_to_workflow,
    _assistant_tool_message,
    _prepare_model_tool_input,
    _safe_skill_selection_evidence,
    _should_use_static_workflow_completion_reply,
)
from app.services.conversation_memory import (
    mark_running,
    mark_waiting_for_user,
    resolve_pending_user_input,
)
from app.services.llm_client import LLMRuntimeConfig, LLMToolResponse, LLMToolUse
from app.services.skill_selector import SkillSelectionResult
from app.services.skills import SkillDefinition
from app.services.tools import ToolResult
from app.services.workflow import (
    WorkflowStep,
    add_workflow_tool_call,
    ensure_workflow_metadata_for_step,
    workflow_step_state,
)


pytestmark = pytest.mark.asyncio


async def test_agent_loop_selects_skill_and_records_metadata():
    class FakeSelector:
        async def select(self, *, config, skills, metadata, latest_user):
            assert config.model == "model"
            assert "lab4ai-auto-reproduct" in skills
            assert metadata["task_type"] == "reproduce"
            assert latest_user == "Please reproduce this repo"
            return SkillSelectionResult(
                skill_name="lab4ai-auto-reproduct",
                reason="Model selected registered skill `lab4ai-auto-reproduct`.",
                confidence=None,
                source="model",
                model_choice="lab4ai-auto-reproduct",
                fallback_choice="general-chat",
                error=None,
            )

    manager = AgentLoopManager()
    manager._skill_selector = FakeSelector()
    manager._skills = {
        "lab4ai-auto-reproduct": SkillDefinition(
            name="lab4ai-auto-reproduct",
            workflow_context="steps: []",
        )
    }
    config = LLMRuntimeConfig(
        provider="anthropic",
        base_url="https://api.anthropic.com",
        api_key="key",
        model="model",
        max_tokens=4096,
    )
    metadata = {"task_type": "reproduce"}

    skill, skill_name, updated_metadata = await manager._select_skill_for_run(
        config,
        metadata,
        "Please reproduce this repo",
    )

    assert skill is manager._skills["lab4ai-auto-reproduct"]
    assert skill_name == "lab4ai-auto-reproduct"
    assert updated_metadata is not metadata
    assert updated_metadata["skill_selection"] == {
        "selected_skill": "lab4ai-auto-reproduct",
        "source": "model",
        "model_choice": "lab4ai-auto-reproduct",
        "fallback_choice": "general-chat",
        "reason": "Model selected registered skill `lab4ai-auto-reproduct`.",
        "confidence": None,
        "error": None,
    }


async def test_agent_loop_reuses_existing_skill_selection_on_resume():
    class FakeSelector:
        async def select(self, *, config, skills, metadata, latest_user):
            raise AssertionError("selector should not run while resuming a workflow")

    manager = AgentLoopManager()
    manager._skill_selector = FakeSelector()
    manager._skills = {
        "lab4ai-auto-reproduct": SkillDefinition(
            name="lab4ai-auto-reproduct",
            workflow_context="steps: []",
        )
    }
    config = LLMRuntimeConfig(
        provider="anthropic",
        base_url="https://api.anthropic.com",
        api_key="key",
        model="model",
        max_tokens=4096,
    )
    metadata = {
        "workflow_name": "Lab4AI_Auto_Reproduction_Pipeline",
        "skill_selection": {
            "selected_skill": "lab4ai-auto-reproduct",
            "source": "model",
            "model_choice": "lab4ai-auto-reproduct",
            "fallback_choice": None,
            "reason": "Original model choice.",
            "confidence": 0.91,
            "error": None,
        },
    }

    skill, skill_name, updated_metadata = await manager._select_skill_for_run(
        config,
        metadata,
        "继续执行",
        reuse_existing=True,
    )

    assert skill is manager._skills["lab4ai-auto-reproduct"]
    assert skill_name == "lab4ai-auto-reproduct"
    assert updated_metadata["skill_selection"] == metadata["skill_selection"]
    assert updated_metadata["skill_selection"]["source"] == "model"


async def test_agent_loop_reuses_top_level_selected_skill_on_resume():
    class FakeSelector:
        async def select(self, *, config, skills, metadata, latest_user):
            raise AssertionError("selector should not run while resuming a workflow")

    manager = AgentLoopManager()
    manager._skill_selector = FakeSelector()
    manager._skills = {
        "lab4ai-auto-reproduct": SkillDefinition(
            name="lab4ai-auto-reproduct",
            workflow_context="steps: []",
        )
    }
    config = LLMRuntimeConfig(
        provider="anthropic",
        base_url="https://api.anthropic.com",
        api_key="key",
        model="model",
        max_tokens=4096,
    )
    metadata = {
        "selected_skill": "lab4ai-auto-reproduct",
        "workflow_name": "Lab4AI_Auto_Reproduction_Pipeline",
    }

    skill, skill_name, updated_metadata = await manager._select_skill_for_run(
        config,
        metadata,
        "继续执行",
        reuse_existing=True,
    )

    assert skill is manager._skills["lab4ai-auto-reproduct"]
    assert skill_name == "lab4ai-auto-reproduct"
    assert updated_metadata["skill_selection"]["selected_skill"] == "lab4ai-auto-reproduct"
    assert updated_metadata["skill_selection"]["source"] == "fallback"
    assert updated_metadata["skill_selection"]["fallback_choice"] == "lab4ai-auto-reproduct"


async def test_agent_loop_fails_reproduce_without_workflow_skill(
    monkeypatch,
):
    from app.models.conversation import ConversationStatus

    async def fail_invoke(*args, **kwargs):
        raise AssertionError("legacy fixed tool chain should not run without workflow skill")

    assistant_messages: list[str] = []
    status_updates: list[tuple[ConversationStatus, dict]] = []

    async def fake_assistant(conversation_id, content):
        assistant_messages.append(content)

    async def fake_set_status_and_metadata(conversation_id, status, metadata):
        status_updates.append((status, metadata))

    manager = AgentLoopManager()
    monkeypatch.setattr(manager, "_invoke_tool_with_policy", fail_invoke)
    monkeypatch.setattr(manager, "_assistant", fake_assistant)
    monkeypatch.setattr(manager, "_set_status_and_metadata", fake_set_status_and_metadata)
    metadata = {
        "task_type": "reproduce",
        "github_url": "https://github.com/example/repo",
        "skill_selection": {
            "selected_skill": "",
            "source": "fallback",
            "fallback_choice": "lab4ai-auto-reproduct",
        },
    }

    await manager._fail_missing_workflow_skill(123, metadata)

    assert assistant_messages == ["未找到可执行的复现 workflow skill，无法继续。"]
    assert status_updates[0][0] == ConversationStatus.FAILED
    assert status_updates[0][1]["workflow_state"] == "failed"
    assert status_updates[0][1]["skill_selection"]["selected_skill"] == ""
    assert manager._streams[123].history[-1]["status"] == "failed"


async def test_progress_event_includes_extra_payload():
    manager = AgentLoopManager()
    content = "已选择 skill：lab4ai-auto-reproduct（来源：model）。"

    await manager._progress(
        42,
        content,
        stage="skill_selection",
        extra={
            "type": "x",
            "stage": "x",
            "content": "bad",
            "skill_selection_source": "model",
        },
    )

    event = manager._streams[42].history[-1]
    assert event["type"] == "progress"
    assert event["stage"] == "skill_selection"
    assert event["content"] == content
    assert event["skill_selection_source"] == "model"


async def test_skill_selection_progress_exposes_structured_evidence():
    manager = AgentLoopManager()
    conversation_id = 123
    manager._active_runs[conversation_id] = "run-skill"

    metadata = {
        "skill_selection": {
            "selected_skill": "lab4ai-auto-reproduct",
            "source": "model",
            "model_choice": "lab4ai-auto-reproduct",
            "fallback_choice": None,
            "reason": "Model selected registered skill `lab4ai-auto-reproduct`.",
            "confidence": None,
            "error": None,
        }
    }

    await manager._progress(
        conversation_id,
        "已选择 skill：lab4ai-auto-reproduct（来源：model）。",
        stage="skill_selection",
        extra={
            "skill_selection": metadata["skill_selection"],
            "workflow_path": "skills/lab4ai-auto-reproduct/project_reproduce.yaml",
        },
    )

    event = manager._streams[conversation_id].history[-1]
    assert event["type"] == "progress"
    assert event["stage"] == "skill_selection"
    assert event["skill_selection"]["source"] == "model"
    assert event["skill_selection"]["model_choice"] == "lab4ai-auto-reproduct"
    assert event["workflow_path"] == "skills/lab4ai-auto-reproduct/project_reproduce.yaml"
    assert "workflow_context" not in event["skill_selection"]
    assert "body" not in event["skill_selection"]


async def test_safe_skill_selection_evidence_removes_private_fields():
    evidence = _safe_skill_selection_evidence(
        {
            "selected_skill": "lab4ai-auto-reproduct",
            "source": "model",
            "model_choice": "lab4ai-auto-reproduct",
            "fallback_choice": None,
            "reason": "Model selected registered skill `lab4ai-auto-reproduct`.",
            "confidence": None,
            "error": None,
            "workflow_context": "secret yaml",
            "body": "secret body",
            "prompt_context": "secret prompt",
        }
    )

    assert evidence == {
        "selected_skill": "lab4ai-auto-reproduct",
        "source": "model",
        "model_choice": "lab4ai-auto-reproduct",
        "fallback_choice": None,
        "reason": "Model selected registered skill `lab4ai-auto-reproduct`.",
        "confidence": None,
        "error": None,
    }


async def test_safe_skill_selection_evidence_drops_nested_values():
    evidence = _safe_skill_selection_evidence(
        {
            "selected_skill": "lab4ai-auto-reproduct",
            "source": "model",
            "reason": {"body": "secret body"},
            "error": ["secret error"],
            "confidence": 0.8,
        }
    )

    assert evidence == {
        "selected_skill": "lab4ai-auto-reproduct",
        "source": "model",
        "confidence": 0.8,
    }


async def test_safe_skill_selection_evidence_redacts_model_call_failure_reason():
    evidence = _safe_skill_selection_evidence(
        {
            "selected_skill": "lab4ai-auto-reproduct",
            "source": "fallback",
            "error": "model_call_failed",
            "reason": (
                "Model skill selection failed; selected fallback. Error: "
                "RuntimeError: https://secret.example/token abc123"
            ),
        }
    )

    assert evidence == {
        "selected_skill": "lab4ai-auto-reproduct",
        "source": "fallback",
        "error": "model_call_failed",
        "reason": "Model skill selection failed; selected fallback.",
    }


async def test_safe_skill_selection_evidence_drops_non_finite_float_and_caps_strings():
    evidence = _safe_skill_selection_evidence(
        {
            "selected_skill": "x" * 600,
            "source": "model",
            "confidence": float("nan"),
        }
    )

    assert evidence == {
        "selected_skill": "x" * 500,
        "source": "model",
    }


async def test_assistant_tool_message_preserves_raw_thinking_blocks():
    response = LLMToolResponse(
        text="I will inspect.",
        tool_calls=[
            LLMToolUse(
                id="call_01_test",
                name="analyze_repo",
                input={"github_url": "https://github.com/example/repo"},
            )
        ],
        stop_reason="tool_use",
        raw={
            "content": [
                {"type": "thinking", "thinking": "Need repository audit.", "signature": "sig"},
                {"type": "text", "text": "I will inspect."},
                {
                    "type": "tool_use",
                    "id": "call_01_test",
                    "name": "analyze_repo",
                    "input": {"github_url": "https://github.com/example/repo"},
                },
            ]
        },
    )

    message = _assistant_tool_message(response)

    assert message["content"][0] == {
        "type": "thinking",
        "thinking": "Need repository audit.",
        "signature": "sig",
    }
    assert message["content"][2]["type"] == "tool_use"


async def test_prepare_model_tool_input_drops_remote_output_dir_for_local_analysis():
    payload = _prepare_model_tool_input(
        "analyze_paper",
        {
            "paper_url": "https://arxiv.org/pdf/2502.14397",
            "github_url": "https://github.com/showlab/PhotoDoodle",
            "output_dir": "/root/.openclaw/workspace/PhotoDoodle",
        },
        {"github_url": "https://github.com/showlab/PhotoDoodle"},
        "step_1_audit",
    )

    assert "output_dir" not in payload


async def test_prepare_model_tool_input_defaults_gpu_creation_from_workflow_step():
    payload = _prepare_model_tool_input(
        "lab4ai_create_instance",
        {},
        {},
        "step_6_deploy_gpu",
    )

    assert payload["workflow_step_id"] == "step_6_deploy_gpu"
    assert payload["resource_kind"] == "GPU"
    assert payload["gpu_count"] == 1


async def test_agent_loop_delegates_to_agent_runtime_v3_when_enabled(monkeypatch):
    class FakeSettings:
        agent_runtime_v3_enabled = True

    class FakeSessionContext:
        async def __aenter__(self):
            return "session"

        async def __aexit__(self, exc_type, exc, tb):
            return None

    calls: list[tuple[str, object]] = []

    class FakeAgentRuntime:
        def __init__(self, **kwargs):
            calls.append(("init", kwargs))

        async def run_conversation(self, conversation_id: int, *, model: str):
            calls.append(("run", {"conversation_id": conversation_id, "model": model}))

    manager = AgentLoopManager()
    config = LLMRuntimeConfig(
        provider="anthropic",
        base_url="https://api.anthropic.com",
        api_key="key",
        model="model",
        max_tokens=4096,
    )
    monkeypatch.setattr("app.services.agent_loop.get_settings", lambda: FakeSettings())
    monkeypatch.setattr("app.services.agent_loop.SessionLocal", lambda: FakeSessionContext())
    monkeypatch.setattr("app.services.agent_loop.AgentRuntime", FakeAgentRuntime)

    delegated = await manager._run_with_agent_runtime_v3(conversation_id=123, config=config)

    assert delegated is True
    assert calls[0][0] == "init"
    assert calls[0][1]["session"] == "session"
    assert "skill.invoke" in calls[0][1]["tool_executor"].runtime_tools
    assert calls[1] == ("run", {"conversation_id": 123, "model": "model"})


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


async def test_step_model_tool_use_resumes_approved_waiting_tool_without_new_model_call(
    monkeypatch,
    test_user,
    db_session,
):
    from app.models import Conversation
    from app.models.conversation import ConversationStatus, ConversationTaskType

    async def fail_model_call(*args, **kwargs):
        raise AssertionError("resumed approved tool should execute without a new model call")

    manager = AgentLoopManager()
    monkeypatch.setattr("app.services.agent_loop.call_anthropic_compatible_tool_use", fail_model_call)
    invoked: list[tuple[str, dict]] = []

    async def fake_invoke(name, tool_input, context=None):
        invoked.append((name, dict(tool_input or {})))
        return ToolResult(name, "created", metadata={"server_id": "cpu-resumed"})

    monkeypatch.setattr(manager._tools, "invoke", fake_invoke)
    conversation = Conversation(
        user_id=test_user.id,
        task_type=ConversationTaskType.REPRODUCE,
        title="resume approved model tool",
        status=ConversationStatus.RUNNING,
        metadata_={},
    )
    db_session.add(conversation)
    await db_session.commit()
    await db_session.refresh(conversation)

    step = WorkflowStep(id="step_3_deploy_cpu", name="CPU")
    metadata = ensure_workflow_metadata_for_step(mark_running({"task_type": "reproduce"}), step)
    tool_input = {
        "resource_kind": "CPU",
        "workflow_step_id": step.id,
        "tool_call_id": "call_waiting_cpu",
        "workflow_run_id": metadata["workflow_run_id"],
    }
    metadata = add_workflow_tool_call(
        metadata,
        step,
        tool_call_id="call_waiting_cpu",
        tool_name="lab4ai_create_instance",
        status="waiting_for_user",
    )
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
    metadata = resolve_pending_user_input(metadata, answer="yes")

    metadata, outputs, paused, handled, failed = await manager._run_step_model_tool_use(
        conversation.id,
        metadata,
        step,
        LLMRuntimeConfig(
            provider="anthropic",
            base_url="https://api.example.com",
            api_key="key",
            model="model",
            max_tokens=4096,
        ),
        system="system",
        messages=[],
    )

    assert paused is False
    assert handled is True
    assert failed is False
    assert outputs == ["lab4ai_create_instance: created"]
    assert invoked == [
        (
            "lab4ai_create_instance",
            {
                "resource_kind": "CPU",
                "workflow_step_id": "step_3_deploy_cpu",
                "tool_call_id": "call_waiting_cpu",
                "workflow_run_id": metadata["workflow_run_id"],
            },
        )
    ]
    assert metadata["workflow_resources"]["cpu"]["server_id"] == "cpu-resumed"
    step_state = workflow_step_state(metadata, "step_3_deploy_cpu")
    assert step_state["tool_calls"][-1]["status"] == "completed"


async def test_step_model_tool_use_defers_after_failed_resumed_remote_tool(
    monkeypatch,
    test_user,
    db_session,
):
    from app.models import Conversation
    from app.models.conversation import ConversationStatus, ConversationTaskType

    async def fail_model_call(*args, **kwargs):
        raise AssertionError("resumed approved tool should execute without a new model call")

    manager = AgentLoopManager()
    monkeypatch.setattr("app.services.agent_loop.call_anthropic_compatible_tool_use", fail_model_call)

    async def fake_invoke(name, tool_input, context=None):
        return ToolResult(
            name,
            "clone failed",
            ok=False,
            metadata={"error_code": "nonzero_exit", "exit_code": 128},
        )

    monkeypatch.setattr(manager._tools, "invoke", fake_invoke)
    conversation = Conversation(
        user_id=test_user.id,
        task_type=ConversationTaskType.REPRODUCE,
        title="resume failed remote tool",
        status=ConversationStatus.RUNNING,
        metadata_={},
    )
    db_session.add(conversation)
    await db_session.commit()
    await db_session.refresh(conversation)

    step = WorkflowStep(id="step_4_cpu_env_setup", name="CPU setup")
    metadata = ensure_workflow_metadata_for_step(
        mark_running(
            {
                "task_type": "reproduce",
                "workflow_resources": {"cpu": {"server_id": "cpu-1"}},
            }
        ),
        step,
    )
    tool_input = {
        "server_id": "cpu-1",
        "resource_kind": "CPU",
        "command": "git clone https://github.com/example/demo .",
        "workflow_step_id": step.id,
        "tool_call_id": "call_waiting_ssh",
        "workflow_run_id": metadata["workflow_run_id"],
    }
    metadata = add_workflow_tool_call(
        metadata,
        step,
        tool_call_id="call_waiting_ssh",
        tool_name="ssh_execute",
        status="waiting_for_user",
    )
    metadata = mark_waiting_for_user(
        metadata,
        question="continue?",
        options=["yes", "no"],
        step="tool_confirm:ssh_execute",
        tool_name="ssh_execute",
        tool_input=tool_input,
        tool_call_id="call_waiting_ssh",
        workflow_step_id=step.id,
    )
    metadata = resolve_pending_user_input(metadata, answer="yes")

    metadata, outputs, paused, handled, failed = await manager._run_step_model_tool_use(
        conversation.id,
        metadata,
        step,
        LLMRuntimeConfig(
            provider="anthropic",
            base_url="https://api.example.com",
            api_key="key",
            model="model",
            max_tokens=4096,
        ),
        system="system",
        messages=[],
    )

    assert paused is False
    assert handled is True
    assert failed is False
    assert outputs == ["ssh_execute: clone failed"]
    step_state = workflow_step_state(metadata, "step_4_cpu_env_setup")
    assert step_state["tool_calls"][-1]["status"] == "failed"


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
    step_state = workflow_step_state(metadata, "step_4_cpu_env_setup")
    assert step_state["tool_calls"][0]["name"] == "analyze_repo"
    assert step_state["tool_calls"][0]["status"] == "completed"
    assert step_state["tool_calls"][0]["ok"] is True


async def test_step_model_tool_use_records_resource_evidence(monkeypatch):
    manager = AgentLoopManager()
    call_count = 0

    async def fake_tool_use(config, *, system, messages, tools):
        nonlocal call_count
        call_count += 1
        if call_count > 1:
            return LLMToolResponse(
                text="CPU 实例创建完成。",
                tool_calls=[],
                stop_reason="end_turn",
                raw={},
            )
        return LLMToolResponse(
            text="按 workflow instruction 创建 CPU 实例。",
            tool_calls=[
                LLMToolUse(
                    id="toolu-cpu",
                    name="lab4ai_create_instance",
                    input={"resource_kind": "CPU", "cpu_cores": 2},
                )
            ],
            stop_reason="tool_use",
            raw={},
        )

    async def fake_invoke(conversation_id, metadata, tool_name, tool_input):
        return (
            ToolResult(tool_name, "cpu ok", metadata={"server_id": "cpu-from-model"}),
            metadata,
            False,
        )

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
            "id": "step_3_deploy_cpu",
            "name": "CPU",
            "instruction": "调用 `lab4ai-instance-manage (创建)` 申请 1台 CPU 实例(2核)。",
            "expected_output": "成功获取 CPU 实例的 SSH 信息。",
        },
    )()

    metadata, outputs, paused, handled, failed = await manager._run_step_model_tool_use(
        1,
        {
            "workflow_run_id": "run-1",
            "workflow_steps": [
                {
                    "id": "step_3_deploy_cpu",
                    "allowed_tools": ["lab4ai_create_instance"],
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
    assert outputs == ["lab4ai_create_instance: cpu ok"]
    assert metadata["workflow_resources"]["cpu"]["server_id"] == "cpu-from-model"
    step_state = workflow_step_state(metadata, "step_3_deploy_cpu")
    assert step_state["tool_calls"][0]["name"] == "lab4ai_create_instance"
    assert step_state["tool_calls"][0]["status"] == "completed"
    assert step_state["evidence"]["cpu_instance_created"] is True
    assert step_state["evidence"]["completion_source"] == "model_tool_use"


async def test_step_model_tool_use_defers_when_model_omits_required_tool(monkeypatch):
    manager = AgentLoopManager()

    async def fake_tool_use(config, *, system, messages, tools):
        return LLMToolResponse(
            text="我将稍后创建实例。",
            tool_calls=[],
            stop_reason="end_turn",
            raw={},
        )

    monkeypatch.setattr("app.services.agent_loop.call_anthropic_compatible_tool_use", fake_tool_use)
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
            "id": "step_3_deploy_cpu",
            "name": "CPU",
            "instruction": "调用 `lab4ai-instance-manage (创建)` 申请 1台 CPU 实例(2核)。",
            "expected_output": "成功获取 CPU 实例的 SSH 信息。",
        },
    )()

    metadata, outputs, paused, handled, failed = await manager._run_step_model_tool_use(
        1,
        {
            "workflow_run_id": "run-1",
            "workflow_steps": [
                {
                    "id": "step_3_deploy_cpu",
                    "allowed_tools": ["lab4ai_create_instance"],
                }
            ],
        },
        step,
        config,
        system="system",
        messages=[{"role": "user", "content": "hello"}],
    )

    assert paused is False
    assert handled is False
    assert failed is False
    assert "未调用当前 step 允许的任何 Tool" in outputs[0]
    assert "workflow_resources" not in metadata


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


async def test_completed_workflow_uses_static_completion_reply_guard():
    metadata = {
        "workflow_state": "completed",
        "workflow_steps": [
            {"id": "step_1_audit", "status": "completed"},
            {"id": "step_2_condition_check", "status": "completed"},
        ],
    }

    assert _should_use_static_workflow_completion_reply(metadata) is True


async def test_incomplete_workflow_does_not_use_static_completion_reply_guard():
    metadata = {
        "workflow_state": "running",
        "workflow_steps": [
            {"id": "step_1_audit", "status": "completed"},
            {"id": "step_2_condition_check", "status": "running"},
        ],
    }

    assert _should_use_static_workflow_completion_reply(metadata) is False


async def test_model_repro_report_records_local_and_remote_artifacts():
    local_path = r"D:\codexP\aaa\runtime\workspaces\86\PhotoDoodle\PhotoDoodle_Final_Repro_Report.docx"
    markdown_path = r"D:\codexP\aaa\runtime\workspaces\86\PhotoDoodle\PhotoDoodle_Final_Repro_Report.md"
    remote_path = "/workspace/user-data/codelab/PhotoDoodle/PhotoDoodle_Final_Repro_Report.docx"
    metadata = {
        "workflow_results": {},
        "workflow_steps": [
            {
                "id": "step_8_generate_report",
                "name": "Report",
                "status": "running",
                "output": "",
                "depends_on": [],
                "expected_output": "",
                "evidence": {},
                "artifacts": [],
                "tool_calls": [],
                "progress": [],
            }
        ],
    }
    result = ToolResult(
        "repro_report",
        "ok",
        metadata={
            "report_path": remote_path,
            "local_report_path": local_path,
            "markdown_report_path": markdown_path,
            "remote_report_path": remote_path,
            "artifact_paths": [remote_path, local_path, markdown_path],
        },
    )

    updated = _apply_model_tool_result_to_workflow(
        metadata,
        "step_8_generate_report",
        "repro_report",
        {},
        result,
    )

    step_state = workflow_step_state(updated, "step_8_generate_report")
    assert updated["workflow_results"]["word_report_path"] == local_path
    assert step_state["evidence"]["report_path"] == local_path
    assert step_state["evidence"]["local_report_path"] == local_path
    assert step_state["evidence"]["markdown_report_path"] == markdown_path
    assert step_state["evidence"]["remote_report_path"] == remote_path
    assert updated["workflow_results"]["markdown_report_path"] == markdown_path
    assert remote_path in step_state["artifacts"]
    assert local_path in step_state["artifacts"]
    assert markdown_path in step_state["artifacts"]


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
