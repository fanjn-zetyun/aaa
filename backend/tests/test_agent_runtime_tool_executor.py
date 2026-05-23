import pytest

from app.agent_runtime.events import ListEventSink
from app.agent_runtime.skills import SkillInvokeTool
from app.agent_runtime.state import RuntimeState
from app.agent_runtime.tool_protocol import RegistryToolAdapter, validate_tool_input
from app.agent_runtime.tool_executor import ToolExecutor
from app.services.llm_client import LLMToolUse
from app.services.skills import SkillDefinition
from app.services.tools import ToolDefinition, ToolResult


def test_validate_tool_input_reports_missing_required_property():
    schema = {
        "type": "object",
        "required": ["question"],
        "properties": {"question": {"type": "string"}},
    }

    result = validate_tool_input(schema, {})

    assert result.ok is False
    assert result.error == "缺少必填参数：question"


def test_registry_tool_adapter_maps_result_to_tool_result_block():
    definition = ToolDefinition(
        name="ask_user",
        description="ask",
        input_schema={"type": "object", "properties": {"question": {"type": "string"}}},
        read_only=True,
    )
    adapter = RegistryToolAdapter(definition)

    block = adapter.to_tool_result_block(
        ToolResult("ask_user", "已提问", ok=True, metadata={"answer_required": True}),
        tool_call_id="toolu_1",
    )

    assert block == {
        "type": "tool_result",
        "tool_use_id": "toolu_1",
        "content": "已提问",
        "is_error": False,
    }


class FakeRegistry:
    def __init__(self):
        self.definitions = {
            "ask_user": ToolDefinition(
                name="ask_user",
                description="ask",
                input_schema={
                    "type": "object",
                    "required": ["question"],
                    "properties": {"question": {"type": "string"}},
                },
                read_only=True,
            )
        }

    def definition(self, name):
        return self.definitions[name]

    def list_definitions(self, allowed_tools=None):
        allowed = set(allowed_tools or [])
        return [item for item in self.definitions.values() if not allowed or item.name in allowed]

    def confirmation_for(self, name, tool_input):
        return None

    async def invoke(self, name, tool_input, context=None):
        return ToolResult(name, f"called {name}", ok=True, metadata={"echo": tool_input})


@pytest.mark.asyncio
async def test_tool_executor_rejects_tool_outside_allowlist():
    state = RuntimeState.new(conversation_id=1, model="claude-test")
    state.allowed_tools = ["skill.invoke"]
    events = ListEventSink()
    executor = ToolExecutor(registry=FakeRegistry(), event_sink=events)

    result = await executor.execute_one(
        LLMToolUse(id="toolu_1", name="ask_user", input={"question": "继续吗？"}),
        state=state,
    )

    assert result.paused is False
    assert result.tool_result.ok is False
    assert result.tool_result.metadata["error_code"] == "tool_not_allowed"
    assert result.tool_result_block["is_error"] is True


@pytest.mark.asyncio
async def test_tool_executor_returns_schema_error_as_tool_result():
    state = RuntimeState.new(conversation_id=1, model="claude-test")
    state.allowed_tools = ["ask_user"]
    executor = ToolExecutor(registry=FakeRegistry(), event_sink=ListEventSink())

    result = await executor.execute_one(
        LLMToolUse(id="toolu_1", name="ask_user", input={}),
        state=state,
    )

    assert result.paused is False
    assert result.tool_result.ok is False
    assert result.tool_result.metadata["error_code"] == "invalid_tool_input"
    assert "缺少必填参数" in result.tool_result.content


@pytest.mark.asyncio
async def test_tool_executor_executes_runtime_tool_before_registry_lookup(tmp_path):
    skill = SkillDefinition(
        name="demo-skill",
        allowed_tools=["ask_user"],
        body="执行 demo skill。",
        base_dir=tmp_path,
    )
    state = RuntimeState.new(conversation_id=1, model="claude-test")
    state.allowed_tools = ["skill.invoke"]
    executor = ToolExecutor(
        registry=FakeRegistry(),
        event_sink=ListEventSink(),
        runtime_tools={"skill.invoke": SkillInvokeTool({"demo-skill": skill})},
    )

    result = await executor.execute_one(
        LLMToolUse(id="toolu_1", name="skill.invoke", input={"skill": "demo-skill"}),
        state=state,
    )

    assert result.tool_result.ok is True
    assert result.updated_state.active_skill["name"] == "demo-skill"
    assert result.tool_result_block == {
        "type": "tool_result",
        "tool_use_id": "toolu_1",
        "content": "Launching skill: demo-skill",
        "is_error": False,
    }
