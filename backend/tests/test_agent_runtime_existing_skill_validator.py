from pathlib import Path

from app.agent_runtime.state import RuntimeState
from app.agent_runtime.workflows.contract import WorkflowContractRuntime
from app.agent_runtime.workflows.validator import validate_workflow_contract


def test_existing_lab4ai_reproduce_skill_normalizes_to_contract_without_fatal_errors():
    raw = Path("skills/lab4ai-auto-reproduct/project_reproduce.yaml").read_text(encoding="utf-8")
    state = RuntimeState.new(conversation_id=1, model="claude-test")
    state = WorkflowContractRuntime().activate(raw, state=state)

    report = validate_workflow_contract(state.active_workflow)

    assert report.ok is True
    assert report.fatal_errors == []
    assert report.step_count >= 9
    assert "step_1_audit" in report.step_ids
    assert "step_9_release_gpu" in report.step_ids
    assert "legacy_compatibility_mode" in report.warnings
