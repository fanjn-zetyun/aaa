from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.services.tools import ToolDefinition, ToolResult


@dataclass(slots=True)
class ValidationResult:
    ok: bool
    error: str = ""


def validate_tool_input(schema: dict[str, Any], value: dict[str, Any]) -> ValidationResult:
    if schema.get("type") not in (None, "object"):
        return ValidationResult(False, "工具 input_schema 必须是 object。")
    required = schema.get("required") or []
    for key in required:
        if key not in value:
            return ValidationResult(False, f"缺少必填参数：{key}")
    properties = schema.get("properties") or {}
    for key, raw_schema in properties.items():
        if key not in value or not isinstance(raw_schema, dict):
            continue
        expected = raw_schema.get("type")
        actual = value[key]
        if expected == "string" and not isinstance(actual, str):
            return ValidationResult(False, f"参数 `{key}` 必须是 string。")
        if expected == "number" and not isinstance(actual, (int, float)):
            return ValidationResult(False, f"参数 `{key}` 必须是 number。")
        if expected == "integer" and not isinstance(actual, int):
            return ValidationResult(False, f"参数 `{key}` 必须是 integer。")
        if expected == "boolean" and not isinstance(actual, bool):
            return ValidationResult(False, f"参数 `{key}` 必须是 boolean。")
        if expected == "array" and not isinstance(actual, list):
            return ValidationResult(False, f"参数 `{key}` 必须是 array。")
        if expected == "object" and not isinstance(actual, dict):
            return ValidationResult(False, f"参数 `{key}` 必须是 object。")
    return ValidationResult(True)


class RegistryToolAdapter:
    def __init__(self, definition: ToolDefinition) -> None:
        self.definition = definition
        self.name = definition.name

    def anthropic_schema(self) -> dict[str, Any]:
        return self.definition.anthropic_schema()

    def validate_input(self, input_value: dict[str, Any]) -> ValidationResult:
        return validate_tool_input(self.definition.input_schema, input_value)

    def to_tool_result_block(self, result: ToolResult, *, tool_call_id: str) -> dict[str, Any]:
        return {
            "type": "tool_result",
            "tool_use_id": tool_call_id,
            "content": result.content,
            "is_error": not result.ok,
        }
