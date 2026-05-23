import pytest

from app.agent_runtime.events import ListEventSink
from app.agent_runtime.llm import ModelResponse
from app.agent_runtime.runtime import AgentRuntime
from app.models import Conversation, ConversationStatus, ConversationTaskType
from app.services.llm_client import LLMToolUse


class FakeLLM:
    def __init__(self):
        self.calls = 0

    async def complete(self, request):
        self.calls += 1
        if self.calls == 1:
            return ModelResponse(
                text="需要询问用户。",
                tool_calls=[LLMToolUse(id="toolu_1", name="ask_user", input={"question": "继续吗？"})],
                stop_reason="tool_use",
                usage={},
                raw={},
            )
        return ModelResponse(
            text="完成。",
            tool_calls=[],
            stop_reason="end_turn",
            usage={},
            raw={},
        )


@pytest.mark.asyncio
async def test_agent_runtime_runs_tool_loop_until_final_answer(db_session, test_user):
    conversation = Conversation(
        user_id=test_user.id,
        task_type=ConversationTaskType.GENERAL,
        title="runtime",
        status=ConversationStatus.RUNNING,
        metadata_={},
    )
    db_session.add(conversation)
    await db_session.commit()
    await db_session.refresh(conversation)

    events = ListEventSink()
    runtime = AgentRuntime.for_test(session=db_session, llm=FakeLLM(), event_sink=events)

    result = await runtime.run_conversation(conversation.id, model="claude-test")

    assert result.status == "completed"
    assert result.final_text == "完成。"
    assert [event["type"] for event in events.events if event["type"].startswith("runtime_")] == [
        "runtime_started",
        "runtime_completed",
    ]
