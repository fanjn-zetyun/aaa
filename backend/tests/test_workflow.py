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
    assert audit["allowed_tools"] == ["analyze_repo", "analyze_paper"]
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
        return ToolResult(tool_name, "ok", metadata={"score": 80}), metadata, False

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
        metadata_payload = {"server_id": "server-1"} if tool_name == "lab4ai_create_instance" else {"score": 80}
        return ToolResult(tool_name, "ok", metadata=metadata_payload), metadata, False

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
async def test_workflow_runner_runs_fixed_executor_after_step_model_tool_hook():
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
    tool_calls: list[tuple[str, dict]] = []

    async def invoke(metadata, tool_name, tool_input):
        tool_calls.append((tool_name, tool_input))
        return ToolResult(tool_name, "fixed ssh ok", metadata={"exit_code": 0}), metadata, False

    async def write(metadata):
        return None

    async def step_hook(metadata, step):
        hook_calls.append(step.id)
        return metadata, ["file_system_read: ok"], False, True

    runner = SkillWorkflowRunner(
        workflow,
        skill_name="lab4ai-auto-reproduct",
        invoke_tool=invoke,
        write_metadata=write,
        publish=events.append,
        run_step_model_tools=step_hook,
    )

    result = await runner.run(
        mark_running(
            {
                "task_type": "reproduce",
                "github_url": "https://github.com/example/demo",
                "workflow_resources": {"cpu": {"server_id": "cpu-1"}},
            }
        )
    )

    assert result.paused is False
    assert result.tool_outputs == [
        "file_system_read: ok",
        "claw_shell_run: fixed ssh ok",
        "remote_project_prep: fixed ssh ok",
        "ssh_execute: fixed ssh ok",
    ]
    assert hook_calls == ["step_4_cpu_env_setup"]
    assert tool_calls[0][0] == "claw_shell_run"
    assert tool_calls[0][1]["server_id"] == "cpu-1"
    assert "git clone --recursive" in tool_calls[0][1]["command"]
    assert "pip install" not in tool_calls[0][1]["command"]
    assert tool_calls[1][0] == "remote_project_prep"
    assert tool_calls[1][1]["server_id"] == "cpu-1"
    assert tool_calls[1][1]["repo_name"] == "demo"
    assert tool_calls[1][1]["dependency_cmds"][0].startswith("pip install torch")
    assert "requirements.txt" in tool_calls[1][1]["dependency_cmds"][1]
    assert tool_calls[2][0] == "ssh_execute"
    assert "git rev-parse --is-inside-work-tree" in tool_calls[2][1]["command"]
    step = workflow_step_state(result.metadata, "step_4_cpu_env_setup")
    assert step["status"] == "completed"
    assert step["evidence"]["clone_completed"] is True
    assert step["evidence"]["remote_workspace_verified"] is True
    assert step["evidence"]["git_repo_verified"] is True
    assert step["evidence"]["dependency_install_attempted"] is True
    assert step["evidence"]["project_prep_completed"] is True
    assert step["output"] == "CPU 环境准备命令已真实执行完成。"


@pytest.mark.asyncio
async def test_workflow_runner_gpu_execution_uses_claw_shell_retry_and_conda():
    workflow = parse_workflow(
        """
version: demo/v1
name: demo
tasks:
  - id: step_7_gpu_execution
    name: GPU smoke
"""
    )
    events: list[dict] = []
    tool_calls: list[tuple[str, dict]] = []

    async def invoke(metadata, tool_name, tool_input):
        tool_calls.append((tool_name, tool_input))
        return (
            ToolResult(
                tool_name,
                "gpu ssh ok",
                metadata={"exit_code": 0, "stdout": "ok", "stderr": ""},
            ),
            metadata,
            False,
        )

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
                "github_url": "https://github.com/example/demo",
                "workflow_resources": {"gpu": {"server_id": "gpu-1"}},
            }
        )
    )

    assert result.paused is False
    assert tool_calls[0][0] == "claw_shell_run"
    assert tool_calls[0][1]["server_id"] == "gpu-1"
    assert tool_calls[0][1]["connect_retries"] == 30
    assert tool_calls[0][1]["connect_retry_interval"] == 10
    assert "source /opt/conda/bin/activate" in tool_calls[0][1]["command"]
    assert "TORCH_CUDA_ARCH_LIST=\"9.0\"" in tool_calls[0][1]["command"]
    assert "repro_run.log" in tool_calls[0][1]["command"]
    assert "env_patches.md" in tool_calls[0][1]["command"]
    assert "command -v python3 || command -v python" not in tool_calls[0][1]["command"]
    assert tool_calls[1][0] == "ssh_execute"
    assert "git rev-parse --is-inside-work-tree" in tool_calls[1][1]["command"]
    step = workflow_step_state(result.metadata, "step_7_gpu_execution")
    assert step["status"] == "completed"
    assert step["evidence"]["gpu_ssh_probe_completed"] is True
    assert step["evidence"]["gpu_workspace_verified"] is True
    assert step["evidence"]["gpu_runtime_env_configured"] is True
    assert step["evidence"]["smoke_test_executed"] is True
    assert step["evidence"]["env_patches_recorded"] is True


@pytest.mark.asyncio
async def test_workflow_runner_does_not_fallback_after_model_tool_failure():
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

    async def invoke(metadata, tool_name, tool_input):
        raise AssertionError("fixed executor must not run after model tool failure")

    async def write(metadata):
        return None

    async def step_hook(metadata, step):
        return metadata, ["ssh_execute: 未渲染模板变量"], False, True, True

    runner = SkillWorkflowRunner(
        workflow,
        skill_name="lab4ai-auto-reproduct",
        invoke_tool=invoke,
        write_metadata=write,
        publish=events.append,
        run_step_model_tools=step_hook,
    )

    result = await runner.run(mark_running({"task_type": "reproduce"}))

    assert result.failed is True
    step = workflow_step_state(result.metadata, "step_4_cpu_env_setup")
    assert step["status"] == "failed"
    assert "未渲染模板变量" in step["error"]


@pytest.mark.asyncio
async def test_workflow_runner_rejects_completed_step_without_required_evidence():
    workflow = parse_workflow(
        """
version: demo/v1
name: demo
tasks:
  - id: step_8_generate_report
    name: Report
"""
    )
    events: list[dict] = []

    async def invoke(metadata, tool_name, tool_input):
        return ToolResult(tool_name, "report ok", metadata={}), metadata, False

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
                "github_url": "https://github.com/example/demo",
            }
        )
    )

    assert result.failed is True
    step = workflow_step_state(result.metadata, "step_8_generate_report")
    assert step["status"] == "failed"
    assert "missing evidence: report_generated" in step["error"]


@pytest.mark.asyncio
async def test_workflow_runner_rejects_previous_completion_without_contract_evidence():
    workflow = parse_workflow(
        """
version: demo/v1
name: demo
tasks:
  - id: step_8_generate_report
    name: Report
"""
    )
    events: list[dict] = []

    async def invoke(metadata, tool_name, tool_input):
        raise AssertionError("completed step with invalid contract must not be skipped or rerun")

    async def write(metadata):
        return None

    metadata = ensure_workflow_metadata(
        mark_running(
            {
                "task_type": "reproduce",
                "github_url": "https://github.com/example/demo",
            }
        ),
        workflow,
        skill_name="lab4ai-auto-reproduct",
    )
    step = workflow_step_state(metadata, "step_8_generate_report")
    step["status"] = "completed"
    step["tool_calls"] = [
        {
            "tool_call_id": "toolu_report",
            "name": "repro_report",
            "status": "completed",
            "ok": True,
        }
    ]

    runner = SkillWorkflowRunner(
        workflow,
        skill_name="lab4ai-auto-reproduct",
        invoke_tool=invoke,
        write_metadata=write,
        publish=events.append,
    )

    result = await runner.run(metadata)

    assert result.failed is True
    step = workflow_step_state(result.metadata, "step_8_generate_report")
    assert step["status"] == "failed"
    assert "missing evidence: report_generated" in step["error"]


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
        if tool_name == "analyze_repo":
            return (
                ToolResult(
                    tool_name,
                    "repo ok",
                    metadata={
                        "repo": "showlab/PhotoDoodle",
                        "score": 80,
                        "report_path": "runtime/workspaces/1/PhotoDoodle/repo_audit.md",
                        "artifact_paths": ["runtime/workspaces/1/PhotoDoodle/repo_audit.md"],
                    },
                ),
                metadata,
                False,
            )
        return (
            ToolResult(
                tool_name,
                "paper ok",
                metadata={
                    "score": 90,
                    "report_path": "runtime/workspaces/1/PhotoDoodle/paper_analysis.md",
                    "artifact_paths": ["runtime/workspaces/1/PhotoDoodle/paper_analysis.md"],
                },
            ),
            metadata,
            False,
        )

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
                "paper_url": "https://arxiv.org/pdf/2502.14397",
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
        "Invoking tool: analyze_paper",
        "Tool completed: analyze_paper",
    ]
    assert len(step["tool_calls"]) == 2
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
    assert calls[1][0] == "analyze_paper"
    assert result.metadata["workflow_results"]["score"] == 84
    assert [event["type"] for event in events].count("workflow_step_progress") == 5


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
