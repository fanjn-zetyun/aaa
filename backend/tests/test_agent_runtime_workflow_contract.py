from pathlib import Path

from app.services.tools import ToolResult
from app.agent_runtime.state import RuntimeState
from app.agent_runtime.workflows.autoresearch import apply_autoresearch_user_reply
from app.agent_runtime.workflows.zero_code_reproduction import apply_zero_code_user_reply
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


def test_workflow_contract_activates_autoresearch_pipeline_and_blocks_on_lab_choice():
    raw = """
WORKFLOW_KIND: autoresearch_pipeline

## pipeline.yml
```yaml
name: autoresearch_pipeline
version: "2.0"
global_policies:
  policies_skill: scripts/skill_02policies.md
stages:
  - id: instance_provision
    title: "Step 1: Provision compute instance"
    skill_file: scripts/skill_01lab_instance.md
    confirm_required: true
    gates:
      - lab_instance_flow_choice_confirmed_before_create
    tasks:
      - id: ask_user_whether_create_instance
        confirm_required: true
    command_templates:
      ssh_interactive:
        - ssh -p "<sshPort>" "<sshUser>@<sshHost>"
  - id: policies
    title: "Step 2: Policies"
    skill_file: scripts/skill_02policies.md
    gates:
      - gate_log_output_per_skill_02policies
completion_criteria:
  - all required confirmations collected at gates
```

## scripts/skill_02policies.md
Gate protocol.
"""
    state = RuntimeState.new(conversation_id=1, model="claude-test")

    updated = WorkflowContractRuntime().activate(raw, state=state)

    workflow = updated.active_workflow
    assert workflow["kind"] == "autoresearch_pipeline"
    assert workflow["name"] == "autoresearch_pipeline"
    assert workflow["current_step_id"] == "instance_provision"
    assert workflow["gate_log"]["lab_instance_flow"]["value"] == "unresolved"
    assert workflow["gate_log"]["next_action"] == "先确认是否创建实验室实例（Lab instance flow）。"
    assert workflow["steps"]["instance_provision"]["status"] == "waiting_for_user"
    assert workflow["steps"]["instance_provision"]["gates"] == [
        "lab_instance_flow_choice_confirmed_before_create"
    ]
    assert workflow["steps"]["instance_provision"]["command_templates"]["ssh_interactive"] == [
        'ssh -p "<sshPort>" "<sshUser>@<sshHost>"'
    ]
    assert updated.status == "waiting_for_user"
    assert updated.pending_user_input["question"] == "是否创建实验室实例（Lab instance flow）？"
    assert updated.pending_user_input["options"] == ["yes", "no"]
    assert updated.pending_user_input["gate"] == "lab_instance_flow"
    assert updated.pending_user_input["command_preview"] == ["lab4ai_create_instance"]
    assert updated.pending_user_input["resume_action"] == "创建实例后进入 policies 阶段"
    assert updated.allowed_tools == ["ask_user", "skill.invoke"]


def test_autoresearch_lab_no_skips_instance_stage_and_advances_to_policies():
    state = WorkflowContractRuntime().activate(
        """
WORKFLOW_KIND: autoresearch_pipeline

## pipeline.yml
```yaml
name: autoresearch_pipeline
stages:
  - id: instance_provision
    title: Provision
    skill_file: scripts/skill_01lab_instance.md
  - id: policies
    title: Policies
    skill_file: scripts/skill_02policies.md
```
""",
        state=RuntimeState.new(conversation_id=1, model="claude-test"),
    )

    updated = apply_autoresearch_user_reply(state, "no")

    workflow = updated.active_workflow
    assert updated.status == "running"
    assert updated.pending_user_input is None
    assert workflow["gate_log"]["lab_instance_flow"]["value"] == "no"
    assert workflow["gate_log"]["step_2_lab_instance"]["value"] == "skipped"
    assert workflow["current_step_id"] == "policies"
    assert workflow["steps"]["instance_provision"]["status"] == "skipped"
    assert workflow["steps"]["policies"]["status"] == "running"
    assert updated.allowed_tools == ["ask_user", "skill.invoke"]


def test_autoresearch_lab_yes_records_choice_and_allows_create_instance():
    state = WorkflowContractRuntime().activate(
        """
WORKFLOW_KIND: autoresearch_pipeline

## pipeline.yml
```yaml
name: autoresearch_pipeline
stages:
  - id: instance_provision
    title: Provision
    skill_file: scripts/skill_01lab_instance.md
  - id: policies
    title: Policies
    skill_file: scripts/skill_02policies.md
```
""",
        state=RuntimeState.new(conversation_id=1, model="claude-test"),
    )

    updated = apply_autoresearch_user_reply(state, "yes")

    workflow = updated.active_workflow
    assert updated.status == "running"
    assert updated.pending_user_input is None
    assert workflow["gate_log"]["lab_instance_flow"]["value"] == "yes"
    assert workflow["gate_log"]["step_2_lab_instance"]["value"] == "no"
    assert workflow["current_step_id"] == "instance_provision"
    assert workflow["steps"]["instance_provision"]["status"] == "running"
    assert "lab4ai_create_instance" in updated.allowed_tools


def test_workflow_contract_activates_zero_code_pipeline_and_blocks_on_step_zero():
    raw = """
WORKFLOW_KIND: zero_code_reproduction_pipeline

## zero-code-reproduction/SKILL.md
Step 0 must create a remote CPU instance before downloading the paper.

## zero-code-repro-csai/SKILL.md
CS/AI plugin.

## zero-code-repro-biodefense/SKILL.md
Biodefense plugin.
"""
    state = RuntimeState.new(conversation_id=1, model="claude-test")

    updated = WorkflowContractRuntime().activate(raw, state=state)

    workflow = updated.active_workflow
    assert workflow["kind"] == "zero_code_reproduction_pipeline"
    assert workflow["name"] == "zero_code_reproduction_pipeline"
    assert workflow["current_step_id"] == "step_0_remote_instance_init"
    assert workflow["steps"]["step_0_remote_instance_init"]["status"] == "waiting_for_user"
    assert workflow["steps"]["step_0_remote_instance_init"]["execution_location"] == "远程"
    assert workflow["steps"]["step_4_scaffold_generation"]["dynamic_output"] is True
    assert workflow["gate_log"]["step_0_cpu_instance"]["value"] == "unresolved"
    assert updated.status == "waiting_for_user"
    assert updated.pending_user_input["question"] == "是否创建远程 CPU 实例并开始零代码复现流水线？"
    assert updated.pending_user_input["options"] == ["yes", "no"]
    assert updated.pending_user_input["gate"] == "zero_code_step_0_cpu_instance"
    assert updated.allowed_tools == ["ask_user", "skill.invoke"]


def test_zero_code_step_zero_yes_allows_cpu_instance_creation():
    state = WorkflowContractRuntime().activate(
        "WORKFLOW_KIND: zero_code_reproduction_pipeline\n",
        state=RuntimeState.new(conversation_id=1, model="claude-test"),
    )

    updated = apply_zero_code_user_reply(state, "yes")

    workflow = updated.active_workflow
    assert updated.status == "running"
    assert updated.pending_user_input is None
    assert workflow["gate_log"]["step_0_cpu_instance"]["value"] == "yes"
    assert workflow["current_step_id"] == "step_0_remote_instance_init"
    assert workflow["steps"]["step_0_remote_instance_init"]["status"] == "running"
    assert "lab4ai_create_instance" in updated.allowed_tools


def test_zero_code_step_zero_no_stops_without_instance_tools():
    state = WorkflowContractRuntime().activate(
        "WORKFLOW_KIND: zero_code_reproduction_pipeline\n",
        state=RuntimeState.new(conversation_id=1, model="claude-test"),
    )

    updated = apply_zero_code_user_reply(state, "no")

    workflow = updated.active_workflow
    assert updated.status == "stopped"
    assert updated.pending_user_input is None
    assert workflow["gate_log"]["step_0_cpu_instance"]["value"] == "no"
    assert workflow["steps"]["step_0_remote_instance_init"]["status"] == "skipped"
    assert "lab4ai_create_instance" not in updated.allowed_tools
