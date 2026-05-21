from __future__ import annotations

import pytest
from pathlib import Path

from app.services.conversation_memory import mark_running, resolve_pending_user_input
from app.services.tools import ToolResult
from app.services.workflow import (
    SkillWorkflowRunner,
    cleanup_workflow_resources,
    ensure_workflow_metadata,
    parse_workflow,
    set_workflow_resource,
    workflow_step_state,
)


def test_parse_project_reproduce_workflow():
    root = Path(__file__).resolve().parents[2]
    raw = (root / "skills/lab4ai-auto-reproduct/project_reproduce.yaml").read_text(
        encoding="utf-8"
    )

    workflow = parse_workflow(raw)

    assert workflow.name == "Lab4AI_Auto_Reproduction_Pipeline"
    assert workflow.version == "lab4ai-workflow/v2.1"
    assert [step.id for step in workflow.steps[:3]] == [
        "step_1_audit",
        "step_2_condition_check",
        "step_3_deploy_cpu",
    ]
    assert workflow.steps[1].depends_on == ["step_1_audit"]
    assert "代码审计" in workflow.steps[0].instruction


def test_ensure_workflow_metadata_initializes_step_runtime_fields():
    workflow = parse_workflow(
        """
version: demo/v1
name: demo
tasks:
  - id: step_1_audit
    name: Audit
  - id: step_3_deploy_cpu
    name: CPU
"""
    )

    metadata = ensure_workflow_metadata({}, workflow, skill_name="lab4ai-auto-reproduct")

    audit = workflow_step_state(metadata, "step_1_audit")
    cpu = workflow_step_state(metadata, "step_3_deploy_cpu")
    assert audit["attempts"] == 0
    assert audit["allowed_tools"] == ["analyze_repo"]
    assert audit["tool_calls"] == []
    assert audit["artifacts"] == []
    assert audit["progress"] == []
    assert audit["error"] is None
    assert cpu["allowed_tools"] == ["lab4ai_create_instance"]


@pytest.mark.asyncio
async def test_workflow_runner_pauses_for_resource_confirmation():
    workflow = parse_workflow(
        """
version: demo/v1
name: demo
tasks:
  - id: step_1_audit
    name: Audit
    instruction: |
      audit
  - id: step_2_condition_check
    name: Check
    depends_on:[step_1_audit]
  - id: step_3_deploy_cpu
    name: CPU
    depends_on:[step_2_condition_check]
"""
    )
    stored: list[dict] = []
    events: list[dict] = []

    async def invoke(metadata, tool_name, tool_input):
        if tool_name == "lab4ai_create_instance":
            return None, metadata, True
        return ToolResult(tool_name, "ok"), metadata, False

    async def write(metadata):
        stored.append(metadata)

    runner = SkillWorkflowRunner(
        workflow,
        skill_name="lab4ai-auto-reproduct",
        invoke_tool=invoke,
        write_metadata=write,
        publish=events.append,
    )

    result = await runner.run(mark_running({"task_type": "reproduce"}))

    assert result.paused is True
    assert workflow_step_state(result.metadata, "step_3_deploy_cpu")["status"] == "waiting_for_user"
    assert any(event["type"] == "workflow_step_waiting" for event in events)
    assert stored


@pytest.mark.asyncio
async def test_workflow_runner_resumes_and_completes_after_confirmation():
    workflow = parse_workflow(
        """
version: demo/v1
name: demo
tasks:
  - id: step_1_audit
    name: Audit
  - id: step_2_condition_check
    name: Check
    depends_on:[step_1_audit]
  - id: step_3_deploy_cpu
    name: CPU
    depends_on:[step_2_condition_check]
  - id: step_5_release_cpu
    name: Release CPU
    depends_on:[step_3_deploy_cpu]
"""
    )
    events: list[dict] = []
    paused_once = False
    create_call_ids: list[str] = []

    async def invoke(metadata, tool_name, tool_input):
        nonlocal paused_once
        if tool_name == "lab4ai_create_instance" and not paused_once:
            paused_once = True
            create_call_ids.append(str(tool_input["tool_call_id"]))
            return None, metadata, True
        if tool_name == "lab4ai_create_instance":
            create_call_ids.append(str(tool_input["tool_call_id"]))
        return ToolResult(tool_name, "ok", metadata={"server_id": "server-1"}), metadata, False

    async def write(metadata):
        return None

    runner = SkillWorkflowRunner(
        workflow,
        skill_name="lab4ai-auto-reproduct",
        invoke_tool=invoke,
        write_metadata=write,
        publish=events.append,
    )
    metadata = mark_running({"task_type": "reproduce"})
    first = await runner.run(metadata)
    resumed_metadata = resolve_pending_user_input(first.metadata, answer="继续执行")

    second = await runner.run(resumed_metadata)

    assert second.paused is False
    assert workflow_step_state(second.metadata, "step_3_deploy_cpu")["status"] == "completed"
    assert workflow_step_state(second.metadata, "step_5_release_cpu")["status"] == "completed"
    assert second.metadata["workflow_resources"]["cpu"]["released"] is True
    assert len(create_call_ids) == 2
    assert create_call_ids[0] == create_call_ids[1]


@pytest.mark.asyncio
async def test_workflow_runner_allows_step_model_tool_hook():
    workflow = parse_workflow(
        """
version: demo/v1
name: demo
tasks:
  - id: step_4_cpu_env_setup
    name: CPU setup
"""
    )
    events: list[dict] = []
    hook_calls: list[str] = []

    async def invoke(metadata, tool_name, tool_input):
        raise AssertionError("fixed executor should not run when hook handles the step")

    async def write(metadata):
        return None

    async def step_hook(metadata, step):
        hook_calls.append(step.id)
        return metadata, ["ssh_execute: ok"], False, True

    runner = SkillWorkflowRunner(
        workflow,
        skill_name="lab4ai-auto-reproduct",
        invoke_tool=invoke,
        write_metadata=write,
        publish=events.append,
        run_step_model_tools=step_hook,
    )

    result = await runner.run(mark_running({"task_type": "reproduce"}))

    assert result.paused is False
    assert result.tool_outputs == ["ssh_execute: ok"]
    assert hook_calls == ["step_4_cpu_env_setup"]
    assert workflow_step_state(result.metadata, "step_4_cpu_env_setup")["status"] == "completed"


@pytest.mark.asyncio
async def test_workflow_runner_records_tool_calls_and_progress():
    workflow = parse_workflow(
        """
version: demo/v1
name: demo
tasks:
  - id: step_1_audit
    name: Audit
"""
    )
    events: list[dict] = []
    calls: list[tuple[str, dict]] = []

    async def invoke(metadata, tool_name, tool_input):
        calls.append((tool_name, tool_input))
        return ToolResult(tool_name, "ok", metadata={"repo": "showlab/PhotoDoodle"}), metadata, False

    async def write(metadata):
        return None

    runner = SkillWorkflowRunner(
        workflow,
        skill_name="lab4ai-auto-reproduct",
        invoke_tool=invoke,
        write_metadata=write,
        publish=events.append,
    )

    result = await runner.run(
        mark_running(
            {
                "task_type": "reproduce",
                "github_url": "https://github.com/showlab/PhotoDoodle",
            }
        )
    )

    step = workflow_step_state(result.metadata, "step_1_audit")
    assert step["status"] == "completed"
    assert step["attempts"] == 1
    assert step["error"] is None
    assert step["progress"] == [
        "Start step: Audit",
        "Invoking tool: analyze_repo",
        "Tool completed: analyze_repo",
    ]
    assert len(step["tool_calls"]) == 1
    tool_call = step["tool_calls"][0]
    assert tool_call["tool_call_id"].startswith("toolu_")
    assert tool_call["name"] == "analyze_repo"
    assert tool_call["status"] == "completed"
    assert tool_call["ok"] is True
    assert tool_call["completed_at"]
    assert tool_call["audit_category"] == "general"
    assert tool_call["risk_level"] == "low"
    assert calls[0][1]["workflow_step_id"] == "step_1_audit"
    assert calls[0][1]["tool_call_id"] == tool_call["tool_call_id"]
    assert [event["type"] for event in events].count("workflow_step_progress") == 3


@pytest.mark.asyncio
async def test_workflow_runner_records_error_on_tool_failure():
    workflow = parse_workflow(
        """
version: demo/v1
name: demo
tasks:
  - id: step_1_audit
    name: Audit
"""
    )
    events: list[dict] = []

    async def invoke(metadata, tool_name, tool_input):
        raise RuntimeError("boom")

    async def write(metadata):
        return None

    runner = SkillWorkflowRunner(
        workflow,
        skill_name="lab4ai-auto-reproduct",
        invoke_tool=invoke,
        write_metadata=write,
        publish=events.append,
    )

    with pytest.raises(RuntimeError, match="boom"):
        await runner.run(mark_running({"task_type": "reproduce"}))

    failed_event = [event for event in events if event["type"] == "workflow_step_failed"][-1]
    step = failed_event["step"]
    assert step["status"] == "failed"
    assert step["error"] == "RuntimeError: boom"
    assert step["tool_calls"][0]["status"] == "failed"
    assert step["tool_calls"][0]["ok"] is False
    assert step["tool_calls"][0]["error"] == "RuntimeError: boom"
    assert step["progress"][-1] == "Tool failed: analyze_repo"


@pytest.mark.asyncio
async def test_cleanup_workflow_resources_releases_unreleased_instances():
    metadata = set_workflow_resource({}, "cpu", server_id="cpu-1", released=False)
    metadata = set_workflow_resource(metadata, "gpu", server_id="gpu-1", released=False)
    calls: list[tuple[str, dict]] = []
    events: list[dict] = []

    async def invoke(metadata, tool_name, tool_input):
        calls.append((tool_name, tool_input))
        return ToolResult(tool_name, "released"), metadata, False

    async def write(metadata):
        return None

    result, outputs = await cleanup_workflow_resources(metadata, invoke, write, events.append)

    assert outputs == ["lab4ai_stop_instance: released", "lab4ai_stop_instance: released"]
    assert [name for name, _input in calls] == [
        "lab4ai_stop_instance",
        "lab4ai_stop_instance",
    ]
    assert calls[0][1]["server_id"] == "cpu-1"
    assert calls[0][1]["workflow_step_id"] == "step_5_release_cpu"
    assert calls[0][1]["tool_call_id"].startswith("toolu_")
    assert calls[0][1]["resource_kind"] == "CPU"
    assert calls[0][1]["force_cleanup"] is True
    assert calls[1][1]["server_id"] == "gpu-1"
    assert calls[1][1]["workflow_step_id"] == "step_9_release_gpu"
    assert calls[1][1]["tool_call_id"].startswith("toolu_")
    assert calls[1][1]["resource_kind"] == "GPU"
    assert calls[1][1]["force_cleanup"] is True
    assert result["workflow_resources"]["cpu"]["released"] is True
    assert result["workflow_resources"]["gpu"]["released"] is True
    cpu_step = workflow_step_state(result, "step_5_release_cpu")
    gpu_step = workflow_step_state(result, "step_9_release_gpu")
    assert cpu_step["status"] == "completed"
    assert cpu_step["attempts"] == 1
    assert cpu_step["tool_calls"][0]["tool_call_id"] == calls[0][1]["tool_call_id"]
    assert cpu_step["tool_calls"][0]["status"] == "completed"
    assert gpu_step["status"] == "completed"
    assert gpu_step["attempts"] == 1
    assert gpu_step["tool_calls"][0]["tool_call_id"] == calls[1][1]["tool_call_id"]
    assert gpu_step["tool_calls"][0]["status"] == "completed"
    assert [event["type"] for event in events] == [
        "workflow_cleanup_started",
        "workflow_step_progress",
        "workflow_step_completed",
        "workflow_step_progress",
        "workflow_step_completed",
        "workflow_cleanup_completed",
    ]
