from __future__ import annotations

from app.agent_runtime.instructions import compile_step_instruction


def test_compile_step_instruction_extracts_required_actions():
    plan = compile_step_instruction(
        step_id="step_7_gpu_execution",
        step_name="GPU execution",
        instruction="""
        Task 0.5: Import precheck. Run python -c "import torch" first.
        Task 2: Entrypoint detection. Inspect scripts, examples, demo and README.
        Task 4: Environment patch record. Save env_patches.md.
        """,
        expected_output="Model runs on GPU and captures loss plus resource metrics.",
        allowed_tools=["ssh_execute", "file_system_read", "file_system_list"],
    )

    assert plan.step_id == "step_7_gpu_execution"
    assert [item.id for item in plan.items] == [
        "import_precheck",
        "entrypoint_detection",
        "env_patch_record",
        "expected_output_validation",
    ]
    assert plan.items[0].required is True
    assert "ssh_execute" in plan.recommended_tools


def test_compile_step_instruction_keeps_unknown_text_as_general_item():
    plan = compile_step_instruction(
        step_id="custom_step",
        step_name="Custom",
        instruction="Read the project notes and understand how to run it.",
        expected_output="Project understanding is complete.",
        allowed_tools=["file_system_read"],
    )

    assert len(plan.items) == 1
    assert plan.items[0].id == "general_instruction_1"
    assert plan.items[0].status == "pending"
