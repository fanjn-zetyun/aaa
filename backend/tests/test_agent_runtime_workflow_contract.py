from pathlib import Path

from app.services.tools import ToolResult
from app.agent_runtime.state import RuntimeState
from app.agent_runtime.workflows.contract import WorkflowContractRuntime


def test_workflow_contract_loads_current_project_reproduce_without_modifying_skills():
    raw = Path("skills/lab4ai-auto-reproduct/project_reproduce.yaml").read_text(encoding="utf-8")
    state = RuntimeState.new(conversation_id=1, model="claude-test")

    updated = WorkflowContractRuntime().activate(raw, state=state)

    assert updated.active_workflow["name"]
    assert updated.active_workflow["current_step_id"] == "step_1_audit"
    assert "step_1_audit" in updated.active_workflow["steps"]
    assert updated.active_workflow["steps"]["step_1_audit"]["instruction"]
    assert updated.allowed_tools


def test_workflow_contract_compiles_instruction_plans_for_steps():
    raw = """
version: agent-workflow/v1
name: Demo
description: Demo workflow
tasks:
  - id: step_7_gpu_execution
    name: GPU
    instruction: |
      Task 0.5: Import precheck. Run python -c "import torch" first.
      Task 2: Entrypoint detection. Inspect scripts, examples, demo and README.
    expected_output: |
      Model runs on GPU and captures loss plus resource metrics.
"""
    state = RuntimeState.new(conversation_id=1, model="claude-test")

    updated = WorkflowContractRuntime().activate(raw, state=state)

    plan = updated.instruction_plans["step_7_gpu_execution"]
    assert [item["id"] for item in plan["items"]] == [
        "import_precheck",
        "entrypoint_detection",
        "expected_output_validation",
    ]
    assert updated.active_workflow["steps"]["step_7_gpu_execution"]["instruction_plan_id"] == (
        "step_7_gpu_execution"
    )


def test_workflow_contract_requires_instruction_checklist_for_completion():
    raw = """
version: agent-workflow/v1
name: Demo
description: Demo workflow
tasks:
  - id: step_7_gpu_execution
    name: GPU
    instruction: |
      Task 0.5: Import precheck. Run python -c "import torch" first.
    expected_output: |
      Model runs on GPU and captures loss plus resource metrics.
"""
    state = WorkflowContractRuntime().activate(
        raw,
        state=RuntimeState.new(conversation_id=1, model="claude-test"),
    )

    updated = WorkflowContractRuntime().validate_after_tool_results(
        state,
        [ToolResult("ssh_execute", "command completed without CUDA evidence", ok=True, metadata={})],
    )

    step = updated.active_workflow["steps"]["step_7_gpu_execution"]
    assert step["status"] == "recovery"
    assert "missing instruction checklist item(s): import_precheck" in step["validation_failures"]
    assert updated.instruction_failures["step_7_gpu_execution"] == [
        "missing instruction checklist item(s): import_precheck",
        "missing instruction checklist item(s): expected_output_validation",
    ]


def test_workflow_contract_completes_when_instruction_checklist_is_satisfied():
    raw = """
version: agent-workflow/v1
name: Demo
description: Demo workflow
tasks:
  - id: step_7_gpu_execution
    name: GPU
    instruction: |
      Task 0.5: Import precheck. Run python -c "import torch" first.
      Task 2: Entrypoint detection. Inspect scripts, examples, demo and README.
      Task 4: Environment patch record. Save env_patches.md.
    expected_output: |
      Model runs on GPU and captures loss plus resource metrics.
"""
    state = WorkflowContractRuntime().activate(
        raw,
        state=RuntimeState.new(conversation_id=1, model="claude-test"),
    )

    updated = WorkflowContractRuntime().validate_after_tool_results(
        state,
        [
            ToolResult(
                "ssh_execute",
                "torch=2.8 CUDA=True\nREADME scripts demo inspected\nenv_patches.md\nloss=0.1 VRAM=2GB",
                ok=True,
                metadata={
                    "evidence": {
                        "gpu_ssh_probe_completed": True,
                        "gpu_workspace_verified": True,
                        "gpu_runtime_env_configured": True,
                        "smoke_test_executed": True,
                        "env_patches_recorded": True,
                        "project_reproduction_log": True,
                        "gpu_execution_attempted": True,
                        "inline_cuda_smoke": True,
                    }
                },
            )
        ],
    )

    step = updated.active_workflow["steps"]["step_7_gpu_execution"]
    plan = updated.instruction_plans["step_7_gpu_execution"]
    assert step["status"] == "completed"
    assert {item["status"] for item in plan["items"]} == {"completed"}
    assert updated.instruction_failures["step_7_gpu_execution"] == []


def test_workflow_contract_advances_to_next_step_after_completion():
    raw = """
version: agent-workflow/v1
name: Demo
description: Demo workflow
tasks:
  - id: step_3_deploy_cpu
    name: CPU
    instruction: |
      Create CPU instance.
    expected_output: |
      CPU instance created.
  - id: step_4_cpu_env_setup
    name: CPU env
    depends_on: [step_3_deploy_cpu]
    instruction: |
      Prepare CPU environment.
    expected_output: |
      CPU environment ready.
"""
    state = WorkflowContractRuntime().activate(
        raw,
        state=RuntimeState.new(conversation_id=1, model="claude-test"),
    )

    updated = WorkflowContractRuntime().validate_after_tool_results(
        state,
        [
            ToolResult(
                "lab4ai_create_instance",
                "CPU server created",
                ok=True,
                metadata={"evidence": {"cpu_instance_created": True}},
            )
        ],
    )

    assert updated.active_workflow["steps"]["step_3_deploy_cpu"]["status"] == "completed"
    assert updated.active_workflow["current_step_id"] == "step_4_cpu_env_setup"
    assert updated.active_workflow["steps"]["step_4_cpu_env_setup"]["status"] == "running"
    assert "remote_project_prep" in updated.allowed_tools


def test_workflow_contract_captures_report_artifact_and_release_evidence_from_tool_metadata():
    raw = """
version: agent-workflow/v1
name: Lab4AI_Auto_Reproduction_Pipeline
description: Demo workflow
tasks:
  - id: step_8_generate_report
    name: Generate report
    instruction: |
      Generate final Word report.
    expected_output: |
      Word file path.
  - id: step_9_release_gpu
    name: Release GPU
    depends_on: [step_8_generate_report]
    instruction: |
      Release GPU instance.
    expected_output: |
      GPU instance released.
"""
    state = WorkflowContractRuntime().activate(
        raw,
        state=RuntimeState.new(conversation_id=1, model="claude-test"),
    )

    after_report = WorkflowContractRuntime().validate_after_tool_results(
        state,
        [
            ToolResult(
                "repro_report",
                "report generated",
                ok=True,
                metadata={
                    "local_report_path": "runtime/workspaces/1/demo/report.docx",
                    "markdown_report_path": "runtime/workspaces/1/demo/report.md",
                    "remote_report_path": "/workspace/user-data/codelab/demo/report.docx",
                    "report_path": "/workspace/user-data/codelab/demo/report.docx",
                    "artifact_paths": [
                        "/workspace/user-data/codelab/demo/report.docx",
                        "runtime/workspaces/1/demo/report.docx",
                        "runtime/workspaces/1/demo/report.md",
                    ],
                },
            )
        ],
    )

    report_step = after_report.active_workflow["steps"]["step_8_generate_report"]
    assert report_step["status"] == "completed"
    assert report_step["evidence"]["report_generated"] is True
    assert report_step["evidence"]["report_path"] == "/workspace/user-data/codelab/demo/report.docx"
    assert report_step["evidence"]["markdown_report_path"] == "runtime/workspaces/1/demo/report.md"
    assert report_step["artifacts"] == [
        "/workspace/user-data/codelab/demo/report.docx",
        "runtime/workspaces/1/demo/report.docx",
        "runtime/workspaces/1/demo/report.md",
    ]
    assert after_report.active_workflow["results"]["word_report_path"] == (
        "runtime/workspaces/1/demo/report.docx"
    )
    assert after_report.active_workflow["results"]["markdown_report_path"] == (
        "runtime/workspaces/1/demo/report.md"
    )
    assert after_report.active_workflow["current_step_id"] == "step_9_release_gpu"

    completed = WorkflowContractRuntime().validate_after_tool_results(
        after_report,
        [
            ToolResult(
                "lab4ai_stop_instance",
                "GPU instance gpu-1 stopped.",
                ok=True,
                metadata={"server_id": "gpu-1", "resource_kind": "GPU"},
            )
        ],
    )

    release_step = completed.active_workflow["steps"]["step_9_release_gpu"]
    assert release_step["status"] == "completed"
    assert release_step["evidence"]["gpu_instance_released"] is True
    assert release_step["evidence"]["server_id"] == "gpu-1"
    assert completed.active_workflow["status"] == "completed"
