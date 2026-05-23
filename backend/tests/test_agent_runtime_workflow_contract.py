from pathlib import Path

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
