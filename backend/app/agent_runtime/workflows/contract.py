from __future__ import annotations

from typing import Any

from app.agent_runtime.state import RuntimeState
from app.agent_runtime.workflows.postconditions import evaluate_step_postconditions
from app.agent_runtime.workflows.tool_mapping import normalize_allowed_tools
from app.services.workflow import STEP_ALLOWED_TOOLS, STEP_COMPLETION_CONTRACTS, parse_workflow
from app.services.tools import ToolResult


class WorkflowContractRuntime:
    def activate(self, raw_workflow: str, *, state: RuntimeState) -> RuntimeState:
        workflow = parse_workflow(raw_workflow)
        steps: dict[str, dict[str, Any]] = {}
        for step in workflow.steps:
            contract = STEP_COMPLETION_CONTRACTS.get(step.id)
            allowed_tools = normalize_allowed_tools(list(STEP_ALLOWED_TOOLS.get(step.id, [])))
            steps[step.id] = {
                "id": step.id,
                "name": step.name,
                "status": "pending",
                "instruction": step.instruction,
                "expected_output": step.expected_output,
                "depends_on": list(step.depends_on),
                "allowed_tools": allowed_tools,
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

    def validate_after_tool_results(
        self,
        state: RuntimeState,
        results: list[ToolResult],
    ) -> RuntimeState:
        workflow = dict(state.active_workflow or {})
        current_step_id = str(workflow.get("current_step_id") or "")
        steps = dict(workflow.get("steps") or {})
        step = dict(steps.get(current_step_id) or {})
        if not current_step_id or not step:
            return state

        step_tool_names = {
            str(name)
            for name in [
                *(step.get("allowed_tools") or []),
                *(step.get("required_tools") or []),
            ]
        }
        relevant_results = [
            result for result in results if not step_tool_names or result.name in step_tool_names
        ]
        if results and not relevant_results:
            return state

        tool_calls = list(step.get("tool_calls") or [])
        evidence = dict(step.get("evidence") or {})
        for result in relevant_results:
            tool_calls.append({"name": result.name, "ok": result.ok, "metadata": result.metadata})
            raw_evidence = (result.metadata or {}).get("evidence")
            if isinstance(raw_evidence, dict):
                evidence.update(raw_evidence)

        completed_tools = {str(item["name"]) for item in tool_calls if item.get("ok")}
        missing_tools = [
            str(name) for name in step.get("required_tools") or [] if str(name) not in completed_tools
        ]
        missing_evidence = [
            str(name) for name in step.get("required_evidence") or [] if not evidence.get(str(name))
        ]
        postcondition = evaluate_step_postconditions(
            current_step_id,
            workflow_state=workflow,
            step_state={**step, "evidence": evidence},
        )
        for item in postcondition.missing_evidence:
            if item not in missing_evidence:
                missing_evidence.append(item)
        failures = []
        if missing_tools:
            failures.append(f"missing required tool(s): {', '.join(missing_tools)}")
        if missing_evidence:
            failures.append(f"missing required evidence: {', '.join(missing_evidence)}")

        step["tool_calls"] = tool_calls
        step["evidence"] = evidence
        step["validation_failures"] = failures
        step["status"] = "recovery" if failures else "completed"
        steps[current_step_id] = step
        workflow["steps"] = steps

        updated = state.next_turn()
        updated.active_workflow = workflow
        return updated
