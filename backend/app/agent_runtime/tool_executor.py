from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.agent_runtime.events import EventSink
from app.agent_runtime.state import RuntimeState
from app.agent_runtime.tool_protocol import RegistryToolAdapter
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
            result, updated_state = await runtime_tool.call(tool_call.input, state=state)
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

        adapter = RegistryToolAdapter(definition)
        validation = adapter.validate_input(tool_call.input)
        if not validation.ok:
            result = ToolResult(
                tool_call.name,
                validation.error,
                ok=False,
                metadata={"error_code": "invalid_tool_input", "retryable": True},
            )
            return self._as_executed(tool_call, result)

        tool_input = {
            **tool_call.input,
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

    def _definition_or_none(self, name: str) -> Any | None:
        try:
            return self.registry.definition(name)
        except Exception:
            return None


def _workflow_step_id(state: RuntimeState) -> str | None:
    workflow = state.active_workflow or {}
    current = workflow.get("current_step_id")
    return str(current) if current else None
