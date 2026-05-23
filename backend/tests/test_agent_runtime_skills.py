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
