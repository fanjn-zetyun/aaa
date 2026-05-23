import pytest

from app.agent_runtime.messages import MessageStore
from app.models import (
    Conversation,
    ConversationMessage,
    ConversationStatus,
    ConversationTaskType,
    MessageRole,
)


@pytest.mark.asyncio
async def test_message_store_appends_assistant_and_tool_result(db_session, test_user):
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

    store = MessageStore(db_session)
    await store.append_assistant(
        conversation.id,
        "我将调用工具。",
        metadata={"run_id": "run-1", "tool_calls": [{"id": "toolu_1", "name": "ask_user"}]},
    )
    await store.append_tool_result(
        conversation.id,
        tool_name="ask_user",
        content="已向用户提问。",
        metadata={"run_id": "run-1", "tool_call_id": "toolu_1", "ok": True},
    )

    rows = await store.list_messages(conversation.id)

    assert [row.role for row in rows] == [MessageRole.ASSISTANT, MessageRole.TOOL]
    assert rows[1].message_metadata["tool_call_id"] == "toolu_1"


@pytest.mark.asyncio
async def test_message_store_builds_model_messages(db_session, test_user):
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
    db_session.add(
        ConversationMessage(
            conversation_id=conversation.id,
            role=MessageRole.USER,
            content="你好",
            message_metadata={},
        )
    )
    await db_session.commit()

    store = MessageStore(db_session)

    assert await store.build_model_messages(conversation.id) == [{"role": "user", "content": "你好"}]
