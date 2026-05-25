from __future__ import annotations

from app.agent_runtime.instruction_evaluator import evaluate_instruction_plan
from app.agent_runtime.instructions import compile_step_instruction
from app.services.tools import ToolResult


def test_instruction_evaluator_marks_items_from_tool_result_evidence():
    plan = compile_step_instruction(
        step_id="step_7_gpu_execution",
        step_name="GPU",
        instruction="""
        Task 0.5: Import precheck. Run python -c "import torch" first.
        Task 2: Entrypoint detection. Inspect scripts, examples, demo and README.
        Task 4: Environment patch record. Save env_patches.md.
        """,
        expected_output="Model runs on GPU and captures loss plus resource metrics.",
        allowed_tools=["ssh_execute"],
    ).to_metadata()
    results = [
        ToolResult(
            "ssh_execute",
            "torch=2.8 CUDA=True\nREADME and demo.py inspected\nenv_patches.md saved\nloss=0.1 VRAM=2GB",
            ok=True,
            metadata={"evidence": {"inline_cuda_smoke": True}},
        )
    ]

    evaluation = evaluate_instruction_plan(plan, results)

    statuses = {item["id"]: item["status"] for item in evaluation.plan["items"]}
    assert statuses == {
        "import_precheck": "completed",
        "entrypoint_detection": "completed",
        "env_patch_record": "completed",
        "expected_output_validation": "completed",
    }
    assert evaluation.missing_required == []


def test_instruction_evaluator_reports_missing_required_items():
    plan = compile_step_instruction(
        step_id="step_7_gpu_execution",
        step_name="GPU",
        instruction='Task 0.5: Import precheck. Run python -c "import torch" first.',
        expected_output="Model runs on GPU and captures loss plus resource metrics.",
        allowed_tools=["ssh_execute"],
    ).to_metadata()

    evaluation = evaluate_instruction_plan(
        plan,
        [ToolResult("ssh_execute", "command failed", ok=False, metadata={})],
    )

    assert evaluation.missing_required == ["import_precheck", "expected_output_validation"]
    assert evaluation.plan["items"][0]["missing_reason"]
