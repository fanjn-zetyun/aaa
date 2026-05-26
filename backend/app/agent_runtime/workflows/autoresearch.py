from __future__ import annotations

import re
from typing import Any

import yaml

from app.agent_runtime.state import RuntimeState


AUTORESEARCH_KIND = "autoresearch_pipeline"


def is_autoresearch_workflow(raw_workflow: str) -> bool:
    return "WORKFLOW_KIND: autoresearch_pipeline" in raw_workflow


def activate_autoresearch_workflow(raw_workflow: str, *, state: RuntimeState) -> RuntimeState:
    pipeline = _extract_pipeline(raw_workflow)
    stages = [stage for stage in pipeline.get("stages") or [] if isinstance(stage, dict)]
    steps = {_stage_id(stage): _stage_state(stage) for stage in stages if _stage_id(stage)}
    current_step_id = _first_stage_id(stages)
    if current_step_id and current_step_id in steps:
        steps[current_step_id]["status"] = "waiting_for_user"

    workflow = {
        "kind": AUTORESEARCH_KIND,
        "name": str(pipeline.get("name") or AUTORESEARCH_KIND),
        "version": str(pipeline.get("version") or ""),
        "current_step_id": current_step_id,
        "step_order": [_stage_id(stage) for stage in stages if _stage_id(stage)],
        "steps": steps,
        "gate_log": _initial_gate_log(),
        "completion_criteria": [
            str(item) for item in pipeline.get("completion_criteria") or [] if str(item).strip()
        ],
        "resources": {},
        "results": {},
        "status": "waiting_for_user",
    }

    updated = state.mark_waiting_for_user(
        pending_tool_call={
            "tool_call_id": "autoresearch:lab_instance_flow",
            "tool_name": "ask_user",
            "workflow_step_id": current_step_id,
        },
        pending_user_input={
            "question": "是否创建实验室实例（Lab instance flow）？",
            "options": ["yes", "no"],
            "workflow_step_id": current_step_id,
            "gate": "lab_instance_flow",
            "command_preview": ["lab4ai_create_instance"],
            "resume_action": "创建实例后进入 policies 阶段",
        },
    )
    updated.active_workflow = workflow
    updated.allowed_tools = ["ask_user", "skill.invoke"]
    return updated


def apply_autoresearch_user_reply(state: RuntimeState, answer: str) -> RuntimeState:
    workflow = dict(state.active_workflow or {})
    if workflow.get("kind") != AUTORESEARCH_KIND:
        return state
    pending = state.pending_user_input or {}
    if pending.get("gate") != "lab_instance_flow":
        return state

    normalized = _normalize_yes_no(answer)
    if normalized == "no":
        return _apply_lab_no(state, workflow)
    if normalized == "yes":
        return _apply_lab_yes(state, workflow)
    return state


def _extract_pipeline(raw_workflow: str) -> dict[str, Any]:
    match = re.search(r"## pipeline\.yml\s*```yaml\s*(.*?)\s*```", raw_workflow, re.DOTALL)
    if match:
        raw_pipeline = match.group(1)
    else:
        raw_pipeline = raw_workflow
    parsed = yaml.safe_load(raw_pipeline)
    return parsed if isinstance(parsed, dict) else {}


def _stage_id(stage: dict[str, Any]) -> str:
    return str(stage.get("id") or "").strip()


def _first_stage_id(stages: list[dict[str, Any]]) -> str:
    for stage in stages:
        stage_id = _stage_id(stage)
        if stage_id:
            return stage_id
    return ""


def _stage_state(stage: dict[str, Any]) -> dict[str, Any]:
    stage_id = _stage_id(stage)
    return {
        "id": stage_id,
        "name": str(stage.get("title") or stage_id),
        "status": "pending",
        "instruction": str(stage.get("description") or stage.get("title") or stage_id),
        "expected_output": "",
        "skill_file": str(stage.get("skill_file") or ""),
        "confirm_required": bool(stage.get("confirm_required") or False),
        "gates": [str(item) for item in stage.get("gates") or []],
        "tasks": [dict(item) for item in stage.get("tasks") or [] if isinstance(item, dict)],
        "command_templates": dict(stage.get("command_templates") or {}),
        "allowed_tools": _allowed_tools_for_stage(stage_id),
        "required_tools": [],
        "required_effects": [],
        "required_evidence": [],
        "tool_calls": [],
        "evidence": {},
        "artifacts": [],
    }


def _initial_gate_log() -> dict[str, Any]:
    return {
        "lab_instance_flow": {
            "value": "unresolved",
            "status": "blocked",
            "evidence": "用户尚未明确答复",
        },
        "step_1_project_setup": {"value": "no", "status": "blocked", "evidence": ""},
        "step_2_lab_instance": {"value": "no", "status": "blocked", "evidence": ""},
        "step_2_5_environment": {"value": "no", "status": "blocked", "evidence": ""},
        "step_5_pre_loop": {"value": "no", "status": "blocked", "evidence": ""},
        "step_5_loop": {"value": "not_started", "status": "pending", "evidence": ""},
        "step_6_final_report": {"value": "no", "status": "pending", "evidence": ""},
        "step_7_stop_instance": {"value": "no", "status": "pending", "evidence": ""},
        "next_action": "先确认是否创建实验室实例（Lab instance flow）。",
    }


def _allowed_tools_for_stage(stage_id: str) -> list[str]:
    if stage_id in {"instance_provision", "instance_teardown"}:
        return ["ask_user", "lab4ai_create_instance", "lab4ai_stop_instance"]
    if stage_id in {"setup", "environments", "experimentation", "output_and_logging", "experiment_loop"}:
        return ["ask_user", "ssh_execute", "file_system_read", "file_system_list", "file_write"]
    if stage_id == "final_report":
        return ["ask_user", "file_write"]
    return ["ask_user"]


def _apply_lab_no(state: RuntimeState, workflow: dict[str, Any]) -> RuntimeState:
    steps = dict(workflow.get("steps") or {})
    current_step_id = str(workflow.get("current_step_id") or "")
    current = dict(steps.get(current_step_id) or {})
    if current:
        current["status"] = "skipped"
        current["evidence"] = {
            **dict(current.get("evidence") or {}),
            "lab_instance_flow": "no",
        }
        steps[current_step_id] = current

    next_step_id = _next_step_id(workflow, current_step_id)
    if next_step_id:
        next_step = dict(steps.get(next_step_id) or {})
        next_step["status"] = "running"
        steps[next_step_id] = next_step
        workflow["current_step_id"] = next_step_id

    gate_log = dict(workflow.get("gate_log") or {})
    gate_log["lab_instance_flow"] = {
        "value": "no",
        "status": "completed",
        "evidence": "用户明确选择不创建实验室实例",
    }
    gate_log["step_2_lab_instance"] = {
        "value": "skipped",
        "status": "completed",
        "evidence": "Lab instance flow = no",
    }
    gate_log["step_7_stop_instance"] = {
        "value": "not_applicable",
        "status": "completed",
        "evidence": "未创建实验室实例",
    }
    gate_log["next_action"] = "进入 policies 阶段并输出 Gate log。"
    workflow["gate_log"] = gate_log
    workflow["steps"] = steps
    workflow["status"] = "running"

    updated = state.next_turn()
    updated.status = "running"
    updated.pending_tool_call = None
    updated.pending_user_input = None
    updated.active_workflow = workflow
    updated.allowed_tools = list(dict.fromkeys([*_current_allowed_tools(workflow), "skill.invoke", "ask_user"]))
    return updated


def _apply_lab_yes(state: RuntimeState, workflow: dict[str, Any]) -> RuntimeState:
    steps = dict(workflow.get("steps") or {})
    current_step_id = str(workflow.get("current_step_id") or "")
    current = dict(steps.get(current_step_id) or {})
    if current:
        current["status"] = "running"
        current["evidence"] = {
            **dict(current.get("evidence") or {}),
            "lab_instance_flow": "yes",
        }
        steps[current_step_id] = current

    gate_log = dict(workflow.get("gate_log") or {})
    gate_log["lab_instance_flow"] = {
        "value": "yes",
        "status": "completed",
        "evidence": "用户明确选择创建实验室实例",
    }
    gate_log["step_2_lab_instance"] = {
        "value": "no",
        "status": "running",
        "evidence": "等待 lab4ai_create_instance 返回 serverId 与 SSH 信息",
    }
    gate_log["next_action"] = "通过受控 Tool 创建 Lab4AI 实验室实例。"
    workflow["gate_log"] = gate_log
    workflow["steps"] = steps
    workflow["status"] = "running"

    updated = state.next_turn()
    updated.status = "running"
    updated.pending_tool_call = None
    updated.pending_user_input = None
    updated.active_workflow = workflow
    updated.allowed_tools = list(dict.fromkeys([*_current_allowed_tools(workflow), "skill.invoke", "ask_user"]))
    return updated


def _normalize_yes_no(answer: str) -> str:
    text = answer.strip().lower()
    if text in {"yes", "y", "是", "创建", "创建实例", "需要", "继续", "同意"}:
        return "yes"
    if text in {"no", "n", "否", "不", "不创建", "不需要", "跳过"}:
        return "no"
    return ""


def _next_step_id(workflow: dict[str, Any], current_step_id: str) -> str:
    order = [str(item) for item in workflow.get("step_order") or []]
    try:
        index = order.index(current_step_id)
    except ValueError:
        return ""
    for step_id in order[index + 1 :]:
        if step_id:
            return step_id
    return ""


def _current_allowed_tools(workflow: dict[str, Any]) -> list[str]:
    current_step_id = str(workflow.get("current_step_id") or "")
    steps = workflow.get("steps") if isinstance(workflow.get("steps"), dict) else {}
    current = steps.get(current_step_id) if isinstance(steps, dict) else None
    if not isinstance(current, dict):
        return []
    return [str(item) for item in current.get("allowed_tools") or []]
