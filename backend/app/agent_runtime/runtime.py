from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.agent_runtime.events import EventSink, ListEventSink
from app.agent_runtime.llm import LLMAdapter, ModelRequest
from app.agent_runtime.messages import MessageStore
from app.agent_runtime.state import RuntimeState, save_runtime_state
from app.agent_runtime.tool_executor import ToolExecutor
from app.models import Conversation, ConversationStatus
from app.services.tools import ToolRegistry


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
                    system=_system_prompt(state),
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
                    "usage": response.usage,
                },
            )
            if not response.tool_calls:
                final_text = response.text
                state.status = "completed"
                break

            for tool_call in response.tool_calls:
                executed = await self.tool_executor.execute_one(tool_call, state=state)
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
                if executed.paused and executed.updated_state:
                    state = executed.updated_state
                    break
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
        return self.tool_executor.registry.list_anthropic_tools(state.allowed_tools)


def _system_prompt(state: RuntimeState) -> str:
    return (
        "你是 LOBSTER Agent Runtime。所有副作用必须通过后端 Tool 执行。"
        f"当前 run_id：{state.run_id}。"
    )
