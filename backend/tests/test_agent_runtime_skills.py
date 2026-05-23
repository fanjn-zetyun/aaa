from __future__ import annotations

import pytest

from app.agent_runtime.skills import SkillInvokeTool
from app.agent_runtime.state import RuntimeState
from app.services.skills import SkillDefinition
from app.services.tools import ToolResult


@pytest.mark.asyncio
async def test_skill_invoke_sets_active_skill_and_allowed_tools(tmp_path):
    skill = SkillDefinition(
        name="demo-skill",
        description="demo",
        triggers=["demo"],
        when_to_use="demo task",
        allowed_tools=["ask_user"],
        body="执行 demo skill。",
        base_dir=tmp_path,
        workflow_context="",
    )
    tool = SkillInvokeTool({"demo-skill": skill})
    state = RuntimeState.new(conversation_id=1, model="claude-test")

    result, updated = await tool.call({"skill": "demo-skill", "args": {}}, state=state)

    assert isinstance(result, ToolResult)
    assert result.ok is True
    assert updated.active_skill["name"] == "demo-skill"
    assert updated.allowed_tools == ["ask_user", "skill.invoke"]


@pytest.mark.asyncio
async def test_skill_invoke_keeps_ask_user_available(tmp_path):
    skill = SkillDefinition(
        name="demo-skill",
        allowed_tools=["analyze_repo"],
        base_dir=tmp_path,
    )
    tool = SkillInvokeTool({"demo-skill": skill})
    state = RuntimeState.new(conversation_id=1, model="claude-test")

    _result, updated = await tool.call({"skill": "demo-skill"}, state=state)

    assert updated.allowed_tools == ["analyze_repo", "skill.invoke", "ask_user"]


@pytest.mark.asyncio
async def test_skill_invoke_activates_workflow_contract(tmp_path):
    workflow = """
version: agent-workflow/v1
name: Demo
description: Demo workflow
tasks:
  - id: step_1_audit
    name: Audit
    instruction: |
      分析仓库。
    expected_output: |
      输出审计。
"""
    skill = SkillDefinition(
        name="workflow-skill",
        description="workflow",
        triggers=["workflow"],
        when_to_use="workflow task",
        allowed_tools=["analyze_repo"],
        body="执行 workflow skill。",
        base_dir=tmp_path,
        workflow_context=workflow,
    )
    tool = SkillInvokeTool({"workflow-skill": skill})
    state = RuntimeState.new(conversation_id=1, model="claude-test")

    result, updated = await tool.call({"skill": "workflow-skill", "args": {}}, state=state)

    assert result.ok is True
    assert updated.active_workflow["current_step_id"] == "step_1_audit"


def test_skill_invoke_schema_lists_available_skills_and_triggers(tmp_path):
    skill = SkillDefinition(
        name="lab4ai-auto-reproduct",
        description="Project reproduction",
        triggers=["reproduce", "github"],
        when_to_use="Use when the user asks to reproduce a GitHub project.",
        allowed_tools=["analyze_repo"],
        base_dir=tmp_path,
        workflow_context="version: agent-workflow/v1",
    )
    tool = SkillInvokeTool({"lab4ai-auto-reproduct": skill})

    schema = tool.definition.anthropic_schema()

    assert schema["input_schema"]["properties"]["skill"]["enum"] == ["lab4ai-auto-reproduct"]
    assert "Only call this tool when the user request matches an available skill" in schema["description"]
    assert "reproduce, github" in schema["description"]
