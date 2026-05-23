from app.agent_runtime.workflows.postconditions import evaluate_step_postconditions


def test_step_3_requires_cpu_instance_resource():
    result = evaluate_step_postconditions(
        "step_3_deploy_cpu",
        workflow_state={"resources": {"cpu": {"server_id": "cpu-1"}}},
        step_state={"evidence": {"cpu_instance_created": True}},
    )

    assert result.ok is True


def test_step_7_inline_cuda_smoke_alone_is_not_reproduction_success():
    result = evaluate_step_postconditions(
        "step_7_gpu_execution",
        workflow_state={"resources": {"gpu": {"server_id": "gpu-1"}}},
        step_state={"evidence": {"inline_cuda_smoke": True}},
    )

    assert result.ok is False
    assert "project_reproduction_log" in result.missing_evidence


def test_step_8_requires_report_artifact_path():
    result = evaluate_step_postconditions(
        "step_8_generate_report",
        workflow_state={"results": {}},
        step_state={"evidence": {}},
    )

    assert result.ok is False
    assert "report_path" in result.missing_evidence
