from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.agent_runtime.context import ContextBuilder
from app.agent_runtime.events import EventSink, ListEventSink
from app.agent_runtime.llm import LLMAdapter, ModelRequest
from app.agent_runtime.messages import MessageStore
from app.agent_runtime.recovery import RecoveryPolicy
from app.agent_runtime.state import RuntimeState, save_runtime_state
from app.agent_runtime.tool_executor import ToolExecutor
from app.agent_runtime.workflows.contract import WorkflowContractRuntime
from app.models import Conversation, ConversationStatus
from app.services.tools import ToolRegistry, ToolResult


@dataclass(slots=True)
class RuntimeRunResult:
    status: str
    final_text: str
    metadata: dict[str, Any]


class AgentRuntime:
    def __init__(
        self,
        *,
        session: AsyncSession,
        llm: LLMAdapter,
        tool_executor: ToolExecutor,
        event_sink: EventSink,
    ) -> None:
        self.session = session
        self.llm = llm
        self.tool_executor = tool_executor
        self.event_sink = event_sink
        self.context_builder = ContextBuilder()
        self.workflow_runtime = WorkflowContractRuntime()
        self.recovery_policy = RecoveryPolicy(max_attempts=3)

    @classmethod
    def for_test(cls, *, session: AsyncSession, llm, event_sink: EventSink | None = None) -> AgentRuntime:
        sink = event_sink or ListEventSink()
        return cls(
            session=session,
            llm=llm,
            tool_executor=ToolExecutor(registry=ToolRegistry(), event_sink=sink),
            event_sink=sink,
        )

    async def run_conversation(self, conversation_id: int, *, model: str) -> RuntimeRunResult:
        conversation = await self.session.get(Conversation, conversation_id)
        if conversation is None:
            raise RuntimeError(f"Conversation not found: {conversation_id}")

        state = RuntimeState.new(conversation_id=conversation_id, model=model)
        conversation.metadata_ = save_runtime_state(conversation.metadata_ or {}, state)
        conversation.status = ConversationStatus.RUNNING
        await self.session.commit()
        await self.event_sink.publish({"type": "runtime_started", "run_id": state.run_id})

        store = MessageStore(self.session)
        final_text = ""
        while state.can_continue():
            messages = await store.build_model_messages(conversation_id)
            response = await self.llm.complete(
                ModelRequest(
                    system=self.context_builder.build_system_prompt(state),
                    messages=messages,
                    tools=[item for item in self._tool_schemas(state)],
                    max_tokens=state.token_budget["planning"],
                )
            )
            await store.append_assistant(
                conversation_id,
                response.text,
                metadata={
                    "run_id": state.run_id,
                    "tool_calls": [
                        {"id": call.id, "name": call.name, "input": call.input}
                        for call in response.tool_calls
                    ],
                    "raw_content": _raw_assistant_content(response.raw),
                    "usage": response.usage,
                },
            )
            if not response.tool_calls:
                final_text = response.text
                state.status = "completed"
                break

            turn_results: list[ToolResult] = []
            for tool_call in response.tool_calls:
                executed = await self.tool_executor.execute_one(tool_call, state=state)
                turn_results.append(executed.tool_result)
                await store.append_tool_result(
                    conversation_id,
                    tool_name=executed.tool_name,
                    content=executed.tool_result.content,
                    metadata={
                        "run_id": state.run_id,
                        "tool_call_id": executed.tool_call_id,
                        "ok": executed.tool_result.ok,
                        **(executed.tool_result.metadata or {}),
                    },
                )
                if executed.updated_state:
                    state = executed.updated_state
                if executed.paused:
                    break
            if state.active_workflow and turn_results:
                state = self.workflow_runtime.validate_after_tool_results(state, turn_results)
                if _current_workflow_step_status(state) == "recovery":
                    decision = self.recovery_policy.decide(state, retryable=True)
                    if decision.action == "hitl":
                        workflow_step_id = (state.active_workflow or {}).get("current_step_id")
                        state = state.mark_waiting_for_user(
                            pending_tool_call={
                                "tool_call_id": f"recovery:{workflow_step_id}",
                                "tool_name": "workflow_recovery",
                                "workflow_step_id": workflow_step_id,
                            },
                            pending_user_input={
                                "question": "当前 workflow step 自动恢复次数已耗尽，请补充处理方式。",
                                "options": ["继续重试", "停止任务"],
                            },
                        )
                        await self.event_sink.publish(
                            {
                                "type": "runtime_waiting_for_user",
                                "run_id": state.run_id,
                                "workflow_step_id": workflow_step_id,
                                "reason": decision.reason,
                            }
                        )
                    else:
                        state = _record_recovery_attempt(state, decision.next_attempt)
            if state.status == "waiting_for_user":
                break
            state = state.next_turn()

        conversation.metadata_ = save_runtime_state(conversation.metadata_ or {}, state)
        conversation.status = (
            ConversationStatus.COMPLETED if state.status == "completed" else ConversationStatus.ACTIVE
        )
        await self.session.commit()
        if state.status == "completed":
            await self.event_sink.publish({"type": "runtime_completed", "run_id": state.run_id})
        return RuntimeRunResult(
            status=state.status,
            final_text=final_text,
            metadata=conversation.metadata_,
        )

    def _tool_schemas(self, state: RuntimeState) -> list[dict[str, Any]]:
        return self.tool_executor.list_anthropic_tools(state.allowed_tools)


def _current_workflow_step_status(state: RuntimeState) -> str:
    workflow = state.active_workflow or {}
    step_id = str(workflow.get("current_step_id") or "")
    steps = workflow.get("steps") if isinstance(workflow.get("steps"), dict) else {}
    step = steps.get(step_id) if step_id else None
    if not isinstance(step, dict):
        return ""
    return str(step.get("status") or "")


def _record_recovery_attempt(state: RuntimeState, next_attempt: int) -> RuntimeState:
    workflow = dict(state.active_workflow or {})
    step_id = str(workflow.get("current_step_id") or "")
    attempts = dict(workflow.get("recovery_attempts") or {})
    attempts[step_id] = next_attempt
    workflow["recovery_attempts"] = attempts
    updated = state.next_turn()
    updated.active_workflow = workflow
    return updated


def _raw_assistant_content(raw: dict[str, Any]) -> list[dict[str, Any]] | None:
    content = raw.get("content") if isinstance(raw, dict) else None
    if not isinstance(content, list):
        return None
    blocks = [dict(item) for item in content if isinstance(item, dict)]
    return blocks or None
