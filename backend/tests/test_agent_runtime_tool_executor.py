from app.agent_runtime.tool_protocol import RegistryToolAdapter, validate_tool_input
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
