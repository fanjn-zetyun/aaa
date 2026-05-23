from __future__ import annotations

from typing import Any

from app.agent_runtime.state import RuntimeState
from app.services.workflow import STEP_ALLOWED_TOOLS, STEP_COMPLETION_CONTRACTS, parse_workflow


class WorkflowContractRuntime:
    def activate(self, raw_workflow: str, *, state: RuntimeState) -> RuntimeState:
        workflow = parse_workflow(raw_workflow)
        steps: dict[str, dict[str, Any]] = {}
        for step in workflow.steps:
            contract = STEP_COMPLETION_CONTRACTS.get(step.id)
            steps[step.id] = {
                "id": step.id,
                "name": step.name,
                "status": "pending",
                "instruction": step.instruction,
                "expected_output": step.expected_output,
                "depends_on": list(step.depends_on),
                "allowed_tools": list(STEP_ALLOWED_TOOLS.get(step.id, [])),
                "required_tools": list(contract.required_tools if contract else ()),
                "required_effects": list(contract.required_effects if contract else ()),
                "required_evidence": list(contract.required_evidence if contract else ()),
                "tool_calls": [],
                "evidence": {},
                "artifacts": [],
            }

        current_step_id = workflow.steps[0].id if workflow.steps else ""
        updated = state.next_turn()
        updated.active_workflow = {
            "name": workflow.name,
            "version": workflow.version,
            "current_step_id": current_step_id,
            "steps": steps,
            "resources": {},
            "results": {},
            "compatibility_mode": True,
        }
        current_tools = steps.get(current_step_id, {}).get("allowed_tools") or []
        updated.allowed_tools = list(dict.fromkeys([*current_tools, "skill.invoke", "ask_user"]))
        return updated
