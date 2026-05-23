from __future__ import annotations

from typing import Any

from app.agent_runtime.state import RuntimeState
from app.services.skills import SkillDefinition
from app.services.tools import ToolDefinition, ToolResult


class SkillInvokeTool:
    name = "skill.invoke"

    def __init__(self, skills: dict[str, SkillDefinition]) -> None:
        self.skills = skills
        self.definition = ToolDefinition(
            name=self.name,
            description=(
                "加载一个 skill，并把 skill 指令、workflow contract 和 allowed tools "
                "注入当前 Agent Runtime。"
            ),
            input_schema={
                "type": "object",
                "required": ["skill"],
                "properties": {
                    "skill": {"type": "string"},
                    "args": {"type": "object"},
                },
            },
            read_only=True,
            confirmation_policy="never",
            risk_level="low",
            audit_category="skill",
        )

    async def call(
        self,
        input_value: dict[str, Any],
        *,
        state: RuntimeState,
    ) -> tuple[ToolResult, RuntimeState]:
        skill_name = str(input_value.get("skill") or "").strip()
        skill = self.skills.get(skill_name)
        if not skill:
            return (
                ToolResult(
                    self.name,
                    f"未知 skill：{skill_name}",
                    ok=False,
                    metadata={"error_code": "unknown_skill", "retryable": True},
                ),
                state,
            )

        updated = state.next_turn()
        updated.active_skill = {
            "name": skill.name,
            "description": skill.description,
            "body": skill.body,
            "workflow_context": skill.workflow_context,
            "args": input_value.get("args") or {},
        }
        updated.allowed_tools = list(dict.fromkeys([*skill.allowed_tools, "skill.invoke", "ask_user"]))
        return (
            ToolResult(
                self.name,
                f"Launching skill: {skill.name}",
                ok=True,
                metadata={
                    "skill": skill.name,
                    "allowed_tools": list(updated.allowed_tools),
                    "workflow_contract_loaded": bool(skill.workflow_context),
                },
            ),
            updated,
        )
