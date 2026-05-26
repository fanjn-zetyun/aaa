from __future__ import annotations

from typing import Any

from app.agent_runtime.instruction_evaluator import evaluate_instruction_plan
from app.agent_runtime.instructions import compile_step_instruction
from app.agent_runtime.state import RuntimeState
from app.agent_runtime.workflows.autoresearch import (
    activate_autoresearch_workflow,
    is_autoresearch_workflow,
)
from app.agent_runtime.workflows.zero_code_reproduction import (
    activate_zero_code_workflow,
    is_zero_code_workflow,
)
from app.agent_runtime.workflows.postconditions import evaluate_step_postconditions
from app.agent_runtime.workflows.tool_mapping import normalize_allowed_tools, normalize_tool_name
from app.services.workflow import STEP_ALLOWED_TOOLS, STEP_COMPLETION_CONTRACTS, parse_workflow
from app.services.tools import ToolResult


class WorkflowContractRuntime:
    def activate(self, raw_workflow: str, *, state: RuntimeState) -> RuntimeState:
        if is_autoresearch_workflow(raw_workflow):
            return activate_autoresearch_workflow(raw_workflow, state=state)
        if is_zero_code_workflow(raw_workflow):
            return activate_zero_code_workflow(raw_workflow, state=state)

        workflow = parse_workflow(raw_workflow)
        steps: dict[str, dict[str, Any]] = {}
        instruction_plans: dict[str, dict[str, Any]] = {}
        for step in workflow.steps:
            contract = STEP_COMPLETION_CONTRACTS.get(step.id)
            allowed_tools = normalize_allowed_tools(list(STEP_ALLOWED_TOOLS.get(step.id, [])))
            instruction_plan = compile_step_instruction(
                step_id=step.id,
                step_name=step.name,
                instruction=step.instruction,
                expected_output=step.expected_output,
                allowed_tools=allowed_tools,
            )
            instruction_plans[step.id] = instruction_plan.to_metadata()
            steps[step.id] = {
                "id": step.id,
                "name": step.name,
                "status": "pending",
                "instruction": step.instruction,
                "expected_output": step.expected_output,
                "instruction_plan_id": step.id,
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
            "step_order": [step.id for step in workflow.steps],
            "steps": steps,
            "resources": {},
            "results": {},
            "compatibility_mode": True,
        }
        updated.instruction_plans = instruction_plans
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
            normalize_tool_name(str(name))
            for name in [
                *(step.get("allowed_tools") or []),
                *(step.get("required_tools") or []),
            ]
        }
        relevant_results = [
            result
            for result in results
            if not step_tool_names or normalize_tool_name(result.name) in step_tool_names
        ]
        if results and not relevant_results:
            return state

        tool_calls = list(step.get("tool_calls") or [])
        evidence = dict(step.get("evidence") or {})
        artifacts = list(step.get("artifacts") or [])
        workflow_results = dict(workflow.get("results") or {})
        resources = dict(workflow.get("resources") or {})
        for result in relevant_results:
            tool_name = normalize_tool_name(result.name)
            tool_call = {"name": tool_name, "ok": result.ok, "metadata": result.metadata}
            if tool_name != result.name:
                tool_call["raw_name"] = result.name
            tool_calls.append(tool_call)
            raw_evidence = (result.metadata or {}).get("evidence")
            if isinstance(raw_evidence, dict):
                evidence.update(raw_evidence)
            evidence.update(_inferred_evidence(current_step_id, tool_name, result))
            _record_workflow_outputs(
                current_step_id=current_step_id,
                tool_name=tool_name,
                result=result,
                workflow_results=workflow_results,
                resources=resources,
                artifacts=artifacts,
            )
        workflow["results"] = workflow_results
        workflow["resources"] = resources

        completed_tools = {normalize_tool_name(str(item["name"])) for item in tool_calls if item.get("ok")}
        missing_tools = [
            str(name)
            for name in step.get("required_tools") or []
            if normalize_tool_name(str(name)) not in completed_tools
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
        instruction_failures: list[str] = []
        instruction_plan = state.instruction_plans.get(current_step_id)
        instruction_plans = dict(state.instruction_plans)
        if isinstance(instruction_plan, dict):
            evaluation = evaluate_instruction_plan(instruction_plan, relevant_results)
            instruction_plans[current_step_id] = evaluation.plan
            instruction_failures = [
                f"missing instruction checklist item(s): {item}"
                for item in evaluation.missing_required
            ]
        failures = []
        if missing_tools:
            failures.append(f"missing required tool(s): {', '.join(missing_tools)}")
        if missing_evidence:
            failures.append(f"missing required evidence: {', '.join(missing_evidence)}")
        failures.extend(instruction_failures)

        step["tool_calls"] = tool_calls
        step["evidence"] = evidence
        step["artifacts"] = artifacts
        step["validation_failures"] = failures
        step["status"] = "recovery" if failures else "completed"
        steps[current_step_id] = step
        workflow["steps"] = steps
        next_step_id = ""
        if step["status"] == "completed":
            next_step_id = _next_ready_step_id(workflow, current_step_id)
            if next_step_id:
                next_step = dict(steps.get(next_step_id) or {})
                next_step["status"] = "running"
                steps[next_step_id] = next_step
                workflow["steps"] = steps
                workflow["current_step_id"] = next_step_id
            else:
                workflow["status"] = "completed"

        updated = state.next_turn()
        updated.active_workflow = workflow
        updated.instruction_plans = instruction_plans
        updated.instruction_failures = {
            **state.instruction_failures,
            current_step_id: instruction_failures,
        }
        updated.last_tool_results = [
            {
                "name": result.name,
                "ok": result.ok,
                "content": result.content,
                "metadata": result.metadata,
            }
            for result in relevant_results
        ]
        if next_step_id:
            current_tools = steps.get(next_step_id, {}).get("allowed_tools") or []
            updated.allowed_tools = list(dict.fromkeys([*current_tools, "skill.invoke", "ask_user"]))
        return updated


def _next_ready_step_id(workflow: dict[str, Any], current_step_id: str) -> str:
    steps = workflow.get("steps") if isinstance(workflow.get("steps"), dict) else {}
    order = [str(item) for item in workflow.get("step_order") or []]
    if not order:
        order = list(steps)
    try:
        start = order.index(current_step_id) + 1
    except ValueError:
        start = 0

    for step_id in order[start:]:
        step = steps.get(step_id) if isinstance(steps, dict) else None
        if not isinstance(step, dict) or step.get("status") == "completed":
            continue
        dependencies = [str(item) for item in step.get("depends_on") or []]
        if all((steps.get(dep) or {}).get("status") == "completed" for dep in dependencies):
            return step_id
    return ""


def _inferred_evidence(step_id: str, tool_name: str, result: ToolResult) -> dict[str, Any]:
    if not result.ok:
        return {}
    metadata = dict(result.metadata or {})
    evidence: dict[str, Any] = {}

    if tool_name == "lab4ai_create_instance":
        resource_key = _resource_key(step_id, metadata)
        if resource_key:
            evidence[f"{resource_key}_instance_created"] = True
        server_id = _metadata_text(metadata, "server_id")
        if server_id:
            evidence["server_id"] = server_id

    if tool_name == "lab4ai_stop_instance":
        resource_key = _resource_key(step_id, metadata)
        if resource_key:
            evidence[f"{resource_key}_instance_released"] = True
        server_id = _metadata_text(metadata, "server_id")
        if server_id:
            evidence["server_id"] = server_id

    if tool_name == "repro_report":
        local_report_path = _metadata_text(metadata, "local_report_path")
        markdown_report_path = _metadata_text(metadata, "markdown_report_path")
        remote_report_path = _metadata_text(metadata, "remote_report_path")
        report_path = _metadata_text(metadata, "report_path") or remote_report_path or local_report_path
        if report_path or ".docx" in str(result.content or "").lower():
            evidence["report_generated"] = True
            evidence["report_path"] = report_path or str(result.content or "").strip()
        if local_report_path:
            evidence["local_report_path"] = local_report_path
        if markdown_report_path:
            evidence["markdown_report_path"] = markdown_report_path
        if remote_report_path:
            evidence["remote_report_path"] = remote_report_path

    return evidence


def _record_workflow_outputs(
    *,
    current_step_id: str,
    tool_name: str,
    result: ToolResult,
    workflow_results: dict[str, Any],
    resources: dict[str, Any],
    artifacts: list[str],
) -> None:
    if not result.ok:
        return
    metadata = dict(result.metadata or {})

    if tool_name in {"lab4ai_create_instance", "lab4ai_stop_instance"}:
        resource_key = _resource_key(current_step_id, metadata)
        if resource_key:
            resource = dict(resources.get(resource_key) or {})
            server_id = _metadata_text(metadata, "server_id")
            if server_id:
                resource["server_id"] = server_id
            resource["resource_kind"] = resource_key.upper()
            if tool_name == "lab4ai_stop_instance":
                resource["released"] = True
            resources[resource_key] = resource

    if tool_name == "repro_report":
        local_report_path = _metadata_text(metadata, "local_report_path")
        markdown_report_path = _metadata_text(metadata, "markdown_report_path")
        remote_report_path = _metadata_text(metadata, "remote_report_path")
        report_path = _metadata_text(metadata, "report_path") or remote_report_path or local_report_path
        word_report_path = local_report_path or report_path or remote_report_path
        if word_report_path:
            workflow_results["word_report_path"] = word_report_path
        if report_path:
            workflow_results["report_path"] = report_path
        if local_report_path:
            workflow_results["local_report_path"] = local_report_path
        if markdown_report_path:
            workflow_results["markdown_report_path"] = markdown_report_path
        if remote_report_path:
            workflow_results["remote_report_path"] = remote_report_path
        for artifact in _artifact_paths(metadata, fallback=report_path or word_report_path):
            if artifact not in artifacts:
                artifacts.append(artifact)


def _resource_key(step_id: str, metadata: dict[str, Any]) -> str:
    raw_kind = str(
        metadata.get("resource_kind") or metadata.get("target_model") or metadata.get("instance_type") or ""
    ).strip().lower()
    if raw_kind in {"cpu", "gpu"}:
        return raw_kind
    if step_id in {"step_3_deploy_cpu", "step_5_release_cpu"}:
        return "cpu"
    if step_id in {"step_6_deploy_gpu", "step_9_release_gpu"}:
        return "gpu"
    return ""


def _artifact_paths(metadata: dict[str, Any], *, fallback: str = "") -> list[str]:
    raw_paths = metadata.get("artifact_paths")
    paths: list[str] = []
    if isinstance(raw_paths, list):
        paths.extend(str(item).strip() for item in raw_paths if str(item).strip())
    report_path = _metadata_text(metadata, "report_path")
    if report_path:
        paths.append(report_path)
    if fallback:
        paths.append(fallback)
    deduped: list[str] = []
    for path in paths:
        if path and path not in deduped:
            deduped.append(path)
    return deduped


def _metadata_text(metadata: dict[str, Any], key: str) -> str:
    return str(metadata.get(key) or "").strip()
