from __future__ import annotations

import pytest
from pathlib import Path

from app.services.conversation_memory import mark_running, resolve_pending_user_input
from app.services.tools import ToolResult
from app.services.workflow import (
    SkillWorkflowRunner,
    cleanup_workflow_resources,
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
    assert workflow.version == "claw-workflow/v2.1"
    assert [step.id for step in workflow.steps[:3]] == [
        "step_1_audit",
        "step_2_condition_check",
        "step_3_deploy_cpu",
    ]
    assert workflow.steps[1].depends_on == ["step_1_audit"]
    assert "代码审计" in workflow.steps[0].instruction


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

    async def invoke(metadata, tool_name, tool_input):
        nonlocal paused_once
        if tool_name == "lab4ai_create_instance" and not paused_once:
            paused_once = True
            return None, metadata, True
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
    assert calls == [
        (
            "lab4ai_stop_instance",
            {
                "server_id": "cpu-1",
                "workflow_step_id": "step_5_release_cpu",
                "resource_kind": "CPU",
                "force_cleanup": True,
            },
        ),
        (
            "lab4ai_stop_instance",
            {
                "server_id": "gpu-1",
                "workflow_step_id": "step_9_release_gpu",
                "resource_kind": "GPU",
                "force_cleanup": True,
            },
        ),
    ]
    assert result["workflow_resources"]["cpu"]["released"] is True
    assert result["workflow_resources"]["gpu"]["released"] is True
    assert workflow_step_state(result, "step_5_release_cpu")["status"] == "completed"
    assert workflow_step_state(result, "step_9_release_gpu")["status"] == "completed"
    assert [event["type"] for event in events] == [
        "workflow_cleanup_started",
        "workflow_step_completed",
        "workflow_step_completed",
        "workflow_cleanup_completed",
    ]
