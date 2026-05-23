from app.agent_runtime.state import RuntimeState
from app.agent_runtime.workflows.contract import WorkflowContractRuntime
from app.services.tools import ToolResult


def test_workflow_contract_stays_on_step_when_required_tool_missing():
    state = RuntimeState.new(conversation_id=1, model="claude-test")
    state.active_workflow = {
        "current_step_id": "step_1",
        "steps": {
            "step_1": {
                "allowed_tools": ["analyze_repo"],
                "required_tools": ["analyze_repo"],
                "required_evidence": ["repo_audit"],
                "tool_calls": [],
                "evidence": {},
            }
        },
    }

    updated = WorkflowContractRuntime().validate_after_tool_results(state, [])

    assert updated.active_workflow["current_step_id"] == "step_1"
    assert updated.active_workflow["steps"]["step_1"]["status"] == "recovery"
    assert updated.active_workflow["steps"]["step_1"]["validation_failures"] == [
        "missing required tool(s): analyze_repo",
        "missing required evidence: repo_audit",
    ]


def test_workflow_contract_records_successful_tool_call_as_evidence():
    state = RuntimeState.new(conversation_id=1, model="claude-test")
    state.active_workflow = {
        "current_step_id": "step_1",
        "steps": {
            "step_1": {
                "allowed_tools": ["analyze_repo"],
                "required_tools": ["analyze_repo"],
                "required_evidence": ["repo_audit"],
                "tool_calls": [],
                "evidence": {},
            }
        },
    }
    result = ToolResult("analyze_repo", "ok", ok=True, metadata={"evidence": {"repo_audit": True}})

    updated = WorkflowContractRuntime().validate_after_tool_results(state, [result])

    assert updated.active_workflow["steps"]["step_1"]["status"] == "completed"
