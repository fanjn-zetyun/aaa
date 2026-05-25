from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.agent_runtime.events import EventSink
from app.agent_runtime.state import RuntimeState
from app.agent_runtime.tool_protocol import RegistryToolAdapter
from app.agent_runtime.workflows.rendering import render_runtime_templates
from app.services.llm_client import LLMToolUse
from app.services.tools import ToolExecutionContext, ToolResult


@dataclass(slots=True)
class ExecutedToolResult:
    tool_call_id: str
    tool_name: str
    tool_result: ToolResult
    tool_result_block: dict[str, Any]
    paused: bool = False
    updated_state: RuntimeState | None = None


class ToolExecutor:
    def __init__(
        self,
        *,
        registry: Any,
        event_sink: EventSink,
        runtime_tools: dict[str, object] | None = None,
    ) -> None:
        self.registry = registry
        self.event_sink = event_sink
        self.runtime_tools = dict(runtime_tools or {})

    async def execute_one(
        self,
        tool_call: LLMToolUse,
        *,
        state: RuntimeState,
        context: ToolExecutionContext | None = None,
    ) -> ExecutedToolResult:
        if tool_call.name not in set(state.allowed_tools):
            result = ToolResult(
                tool_call.name,
                f"工具 `{tool_call.name}` 不在当前 allowlist 中，已拒绝执行。",
                ok=False,
                metadata={"error_code": "tool_not_allowed", "retryable": False},
            )
            return self._as_executed(tool_call, result)

        runtime_tool = self.runtime_tools.get(tool_call.name)
        if runtime_tool is not None:
            await self.event_sink.publish(
                {
                    "type": "tool_started",
                    "tool_name": tool_call.name,
                    "tool_call_id": tool_call.id,
                    "workflow_step_id": _workflow_step_id(state),
                }
            )
            result, updated_state = await runtime_tool.call(tool_call.input, state=state)
            await self.event_sink.publish(
                {
                    "type": "tool_completed" if result.ok else "tool_error",
                    "tool_name": tool_call.name,
                    "tool_call_id": tool_call.id,
                    "workflow_step_id": _workflow_step_id(updated_state),
                    "ok": result.ok,
                }
            )
            executed = self._as_executed(tool_call, result)
            executed.updated_state = updated_state
            return executed

        definition = self._definition_or_none(tool_call.name)
        if definition is None:
            result = ToolResult(
                tool_call.name,
                f"未知工具：{tool_call.name}",
                ok=False,
                metadata={"error_code": "unknown_tool", "retryable": False},
            )
            return self._as_executed(tool_call, result)

        rendered = render_runtime_templates(tool_call.input, _template_context(state))
        if not rendered.ok:
            result = ToolResult(
                tool_call.name,
                f"工具参数存在未解析模板变量：{', '.join(rendered.unresolved_variables)}",
                ok=False,
                metadata={
                    "error_code": rendered.error_code,
                    "unresolved_variables": rendered.unresolved_variables,
                    "retryable": True,
                },
            )
            return self._as_executed(tool_call, result)
        tool_input = rendered.value

        adapter = RegistryToolAdapter(definition)
        validation = adapter.validate_input(tool_input)
        if not validation.ok:
            result = ToolResult(
                tool_call.name,
                validation.error,
                ok=False,
                metadata={"error_code": "invalid_tool_input", "retryable": True},
            )
            return self._as_executed(tool_call, result)

        tool_input = {
            **tool_input,
            "workflow_run_id": state.run_id,
            "tool_call_id": tool_call.id,
            "workflow_step_id": _workflow_step_id(state),
        }
        confirmation = self.registry.confirmation_for(tool_call.name, tool_input)
        if confirmation:
            pending = confirmation.as_pending_input()
            updated_state = state.mark_waiting_for_user(
                pending_tool_call={
                    "tool_call_id": tool_call.id,
                    "tool_name": tool_call.name,
                    "workflow_step_id": pending.get("workflow_step_id"),
                },
                pending_user_input=pending,
            )
            result = ToolResult(
                tool_call.name,
                confirmation.question,
                ok=False,
                metadata={"error_code": "waiting_for_user", "retryable": True},
            )
            executed = self._as_executed(tool_call, result)
            executed.paused = True
            executed.updated_state = updated_state
            await self.event_sink.publish({"type": "permission_requested", **pending})
            return executed

        await self.event_sink.publish(
            {
                "type": "tool_started",
                "tool_name": tool_call.name,
                "tool_call_id": tool_call.id,
                "workflow_step_id": _workflow_step_id(state),
            }
        )
        result = await self.registry.invoke(tool_call.name, tool_input, context=context)
        await self.event_sink.publish(
            {
                "type": "tool_completed" if result.ok else "tool_error",
                "tool_name": tool_call.name,
                "tool_call_id": tool_call.id,
                "workflow_step_id": _workflow_step_id(state),
                "ok": result.ok,
            }
        )
        return self._as_executed(tool_call, result)

    def _as_executed(self, tool_call: LLMToolUse, result: ToolResult) -> ExecutedToolResult:
        definition = self._definition_or_none(tool_call.name)
        block = {
            "type": "tool_result",
            "tool_use_id": tool_call.id,
            "content": result.content,
            "is_error": not result.ok,
        }
        if definition is not None:
            block = RegistryToolAdapter(definition).to_tool_result_block(
                result,
                tool_call_id=tool_call.id,
            )
        return ExecutedToolResult(
            tool_call_id=tool_call.id,
            tool_name=tool_call.name,
            tool_result=result,
            tool_result_block=block,
        )

    def list_anthropic_tools(self, allowed_tools: list[str] | None = None) -> list[dict[str, Any]]:
        schemas_by_name: dict[str, dict[str, Any]] = {}
        for schema in self.registry.list_anthropic_tools(allowed_tools):
            name = schema.get("name")
            if isinstance(name, str):
                schemas_by_name[name] = schema

        allowed = set(allowed_tools or [])
        for name, runtime_tool in self.runtime_tools.items():
            if allowed and name not in allowed:
                continue
            definition = getattr(runtime_tool, "definition", None)
            if definition is None:
                continue
            schema = definition.anthropic_schema()
            schemas_by_name[name] = schema
        return [schemas_by_name[name] for name in sorted(schemas_by_name)]

    def _definition_or_none(self, name: str) -> Any | None:
        try:
            return self.registry.definition(name)
        except Exception:
            return None


def _workflow_step_id(state: RuntimeState) -> str | None:
    workflow = state.active_workflow or {}
    current = workflow.get("current_step_id")
    return str(current) if current else None


def _template_context(state: RuntimeState) -> dict[str, Any]:
    return {
        "parameters": (state.active_skill or {}).get("args") or {},
        "workflow_resources": (state.active_workflow or {}).get("resources") or {},
        "workflow_results": (state.active_workflow or {}).get("results") or {},
    }
