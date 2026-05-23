from __future__ import annotations

from typing import Any

from app.agent_runtime.state import RuntimeState
from app.agent_runtime.workflows.contract import WorkflowContractRuntime
from app.services.skills import SkillDefinition
from app.services.tools import ToolDefinition, ToolResult


class SkillInvokeTool:
    name = "skill.invoke"

    def __init__(self, skills: dict[str, SkillDefinition]) -> None:
        self.skills = skills
        self.definition = ToolDefinition(
            name=self.name,
            description=_skill_catalog_description(skills),
            input_schema={
                "type": "object",
                "required": ["skill"],
                "properties": {
                    "skill": _skill_name_property(skills),
                    "args": {"type": "object"},
                },
            },
            read_only=True,
            confirmation_policy="never",
            risk_level="low",
            audit_category="skill",
        )
        self.workflow_runtime = WorkflowContractRuntime()

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
        if skill.workflow_context:
            updated = self.workflow_runtime.activate(skill.workflow_context, state=updated)
            allowed_tools = [*updated.allowed_tools, *skill.allowed_tools]
        else:
            allowed_tools = list(skill.allowed_tools)
        updated.allowed_tools = list(
            dict.fromkeys([*allowed_tools, "skill.invoke", "ask_user"])
        )
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


def _skill_name_property(skills: dict[str, SkillDefinition]) -> dict[str, Any]:
    property_schema: dict[str, Any] = {
        "type": "string",
        "description": "Exact name of the skill to load.",
    }
    names = sorted(skills)
    if names:
        property_schema["enum"] = names
    return property_schema


def _skill_catalog_description(skills: dict[str, SkillDefinition]) -> str:
    lines = [
        "Load one skill into the current Agent Runtime. Only call this tool when "
        "the user request matches an available skill; for normal conversation, "
        "answer directly without calling skill.invoke.",
        "Available skills:",
    ]
    if not skills:
        lines.append("- none")
        return "\n".join(lines)

    for skill in sorted(skills.values(), key=lambda item: item.name):
        parts = [skill.name]
        if skill.description:
            parts.append(f"description: {skill.description}")
        if skill.when_to_use:
            parts.append(f"when_to_use: {skill.when_to_use}")
        if skill.triggers:
            parts.append("triggers: " + ", ".join(skill.triggers[:20]))
        parts.append(f"has_workflow: {bool(skill.workflow_context)}")
        lines.append("- " + " | ".join(parts))
    return "\n".join(lines)
