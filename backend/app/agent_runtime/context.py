from __future__ import annotations

from app.agent_runtime.state import RuntimeState


class ContextBuilder:
    def build_system_prompt(self, state: RuntimeState) -> str:
        parts = [
            "你是 LOBSTER Agent Runtime。",
            "所有会产生副作用、费用、远程执行或文件写入的动作都必须通过后端 Tool。",
            "不要要求用户提供 Lab4AI 密码、SSH 密码或 API Key；这些由后端凭证服务读取。",
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
                ]
            )
        return "\n".join(part for part in parts if part is not None)
