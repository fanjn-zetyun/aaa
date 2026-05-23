from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import ConversationMessage, MessageRole


class MessageStore:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list_messages(self, conversation_id: int) -> list[ConversationMessage]:
        result = await self.session.execute(
            select(ConversationMessage)
            .where(ConversationMessage.conversation_id == conversation_id)
            .order_by(ConversationMessage.created_at.asc(), ConversationMessage.id.asc())
        )
        return list(result.scalars().all())

    async def append_assistant(
        self,
        conversation_id: int,
        content: str,
        *,
        metadata: dict[str, Any],
    ) -> ConversationMessage:
        message = ConversationMessage(
            conversation_id=conversation_id,
            role=MessageRole.ASSISTANT,
            content=content,
            message_metadata=dict(metadata),
        )
        self.session.add(message)
        await self.session.commit()
        await self.session.refresh(message)
        return message

    async def append_tool_result(
        self,
        conversation_id: int,
        *,
        tool_name: str,
        content: str,
        metadata: dict[str, Any],
    ) -> ConversationMessage:
        message = ConversationMessage(
            conversation_id=conversation_id,
            role=MessageRole.TOOL,
            content=content,
            message_metadata={"tool_name": tool_name, **dict(metadata)},
        )
        self.session.add(message)
        await self.session.commit()
        await self.session.refresh(message)
        return message

    async def build_model_messages(self, conversation_id: int) -> list[dict[str, Any]]:
        messages: list[dict[str, Any]] = []
        for row in await self.list_messages(conversation_id):
            if row.role == MessageRole.USER:
                messages.append({"role": "user", "content": row.content})
            elif row.role == MessageRole.ASSISTANT:
                tool_calls = row.message_metadata.get("tool_calls")
                if tool_calls:
                    content: list[dict[str, Any]] = []
                    if row.content:
                        content.append({"type": "text", "text": row.content})
                    for call in tool_calls:
                        content.append(
                            {
                                "type": "tool_use",
                                "id": call["id"],
                                "name": call["name"],
                                "input": call.get("input") or {},
                            }
                        )
                    messages.append({"role": "assistant", "content": content})
                else:
                    messages.append({"role": "assistant", "content": row.content})
            elif row.role == MessageRole.TOOL:
                tool_call_id = str(row.message_metadata.get("tool_call_id") or "")
                messages.append(
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "tool_result",
                                "tool_use_id": tool_call_id,
                                "content": row.content,
                                "is_error": not bool(row.message_metadata.get("ok", True)),
                            }
                        ],
                    }
                )
        return messages
