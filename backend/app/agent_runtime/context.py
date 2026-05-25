from __future__ import annotations

from typing import Any

from app.agent_runtime.state import RuntimeState


class ContextBuilder:
    def build_system_prompt(self, state: RuntimeState) -> str:
        parts = [
            "你是 LOBSTER Agent Runtime。",
            "所有会产生副作用、费用、远程执行或文件写入的动作都必须通过后端 Tool。",
            "不要要求用户提供 Lab4AI 密码、SSH 密码或 API Key；这些由后端凭证服务读取。",
            "Only call tools from the current allowed tool list.",
            f"当前 run_id：{state.run_id}",
        ]
        if state.active_skill:
            parts.extend(
                [
                    "",
                    f"已激活 skill：{state.active_skill.get('name')}",
                    str(state.active_skill.get("body") or ""),
                ]
            )

        workflow = state.active_workflow or {}
        current_step_id = workflow.get("current_step_id")
        steps = workflow.get("steps") if isinstance(workflow.get("steps"), dict) else {}
        current_step = steps.get(current_step_id) if current_step_id else None
        if isinstance(current_step, dict):
            parts.extend(
                [
                    "",
                    f"当前 workflow step：{current_step_id}",
                    f"instruction：{current_step.get('instruction') or ''}",
                    f"expected_output：{current_step.get('expected_output') or ''}",
                    "只能调用当前 runtime allowed_tools 中的工具。",
                    f"Allowed tools: {', '.join(state.allowed_tools)}",
                ]
            )
            parts.extend(_format_required_evidence(current_step))
            parts.extend(_format_instruction_plan(state, current_step_id))
        return "\n".join(part for part in parts if part is not None)


def _format_required_evidence(current_step: dict[str, Any]) -> list[str]:
    required_evidence = current_step.get("required_evidence") or []
    if not required_evidence:
        return []
    return ["Required evidence: " + ", ".join(str(item) for item in required_evidence)]


def _format_instruction_plan(state: RuntimeState, current_step_id: object) -> list[str]:
    plan = state.instruction_plans.get(str(current_step_id))
    if not isinstance(plan, dict):
        return []
    items = plan.get("items") if isinstance(plan.get("items"), list) else []
    if not items:
        return []

    lines = ["Instruction checklist:"]
    for item in items:
        if not isinstance(item, dict):
            continue
        status = str(item.get("status") or "pending")
        item_id = str(item.get("id") or "instruction")
        text = str(item.get("text") or "")
        lines.append(f"- [{status}] {item_id}: {text}")
    return lines
