"""V2 Agent Loop with real LLM calls and streaming tool events."""

from __future__ import annotations

import asyncio
from collections import defaultdict
from dataclasses import dataclass, field, replace

from sqlalchemy import select

from app.core.database import SessionLocal
from app.models import Conversation, ConversationMessage, LLMConfig
from app.models.conversation import ConversationStatus, MessageRole
from app.core.config import get_settings
from app.services.conversation_store import append_conversation_event
from app.services.llm_client import LLMRuntimeConfig, call_anthropic_compatible
from app.services.skills import SkillDefinition, SkillLoader, select_skill
from app.services.tools import ToolRegistry


@dataclass
class ConversationStream:
    history: list[dict] = field(default_factory=list)
    subscribers: list[asyncio.Queue[dict | None]] = field(default_factory=list)
    finished: bool = False

    def subscribe(self) -> asyncio.Queue[dict | None]:
        q: asyncio.Queue[dict | None] = asyncio.Queue()
        for event in self.history:
            q.put_nowait(event)
        if self.finished:
            q.put_nowait(None)
        else:
            self.subscribers.append(q)
        return q

    def publish(self, event: dict) -> None:
        self.history.append(event)
        for q in self.subscribers:
            q.put_nowait(event)

    def close(self) -> None:
        self.finished = True
        for q in self.subscribers:
            q.put_nowait(None)
        self.subscribers.clear()


class AgentLoopManager:
    def __init__(self) -> None:
        self._streams: defaultdict[int, ConversationStream] = defaultdict(ConversationStream)
        self._tasks: dict[int, asyncio.Task] = {}
        self._tools = ToolRegistry()
        self._skills = SkillLoader(get_settings().skills_dir_path).load_all()

    def subscribe(self, conversation_id: int) -> asyncio.Queue[dict | None]:
        return self._streams[conversation_id].subscribe()

    def start(self, conversation_id: int) -> None:
        if conversation_id in self._tasks and not self._tasks[conversation_id].done():
            return
        self._tasks[conversation_id] = asyncio.create_task(self._run(conversation_id))

    async def stop(self, conversation_id: int) -> None:
        task = self._tasks.get(conversation_id)
        if task and not task.done():
            task.cancel()
        async with SessionLocal() as session:
            conv = await session.get(Conversation, conversation_id)
            if conv:
                conv.status = ConversationStatus.STOPPED
                session.add(
                    ConversationMessage(
                        conversation_id=conversation_id,
                        role=MessageRole.SYSTEM,
                        content="执行已被用户中断。",
                    )
                )
                await session.commit()
        self._publish(conversation_id, {"type": "status", "status": "stopped"})
        self._streams[conversation_id].close()

    async def _run(self, conversation_id: int) -> None:
        try:
            await self._set_status(conversation_id, ConversationStatus.RUNNING)
            self._publish(conversation_id, {"type": "status", "status": "running"})

            async with SessionLocal() as session:
                conv = await session.get(Conversation, conversation_id)
                if conv is None:
                    return
                user_id = conv.user_id
                metadata = conv.metadata_ or {}
                db_messages = (
                    await session.execute(
                        select(ConversationMessage)
                        .where(ConversationMessage.conversation_id == conversation_id)
                        .order_by(ConversationMessage.created_at.asc())
                    )
                ).scalars().all()
                latest_user = next(
                    (m.content for m in reversed(db_messages) if m.role == MessageRole.USER),
                    "",
                )

            llm_config = await _load_llm_config(user_id)
            skill = select_skill(self._skills, metadata)
            skill_name = skill.name if skill else _select_skill(metadata)
            system_prompt = _build_system_prompt(metadata, skill_name, skill)
            initial_messages = _build_llm_messages(db_messages, metadata)

            await self._tool(
                conversation_id,
                "skill_selection",
                (
                    f"已选择 skill：{skill_name}。"
                    "当前后端仍处于 MVP 工具层模式，Lab4AI/SSH 执行为模拟工具事件；"
                    "接入真实 OpenClaw 后会由 skill workflow 驱动真实执行。"
                ),
            )

            plan = await self._model_or_fallback(
                llm_config,
                system=system_prompt,
                messages=initial_messages,
                fallback="我会按 V2 Agent Loop 执行：先分析任务，再调用工具，最后给出下一步结果。",
            )
            await self._assistant(conversation_id, plan)

            tool_outputs: list[str] = []
            result = await self._tools.analyze_repo(metadata.get("github_url"))
            tool_outputs.append(f"{result.name}: {result.content}")
            await self._tool(conversation_id, result.name, result.content)

            if metadata.get("task_type") == "reproduce" or metadata.get("github_url"):
                result = await self._tools.lab4ai_create_instance()
                tool_outputs.append(f"{result.name}: {result.content}")
                await self._tool(conversation_id, result.name, result.content)

                result = await self._tools.ssh_execute(
                    "git clone && inspect README/requirements"
                )
                tool_outputs.append(f"{result.name}: {result.content}")
                await self._tool(conversation_id, result.name, result.content)

                result = await self._tools.lab4ai_stop_instance()
                tool_outputs.append(f"{result.name}: {result.content}")
                await self._tool(conversation_id, result.name, result.content)

            reply = await self._model_or_fallback(
                llm_config,
                system=system_prompt,
                messages=[
                    *initial_messages,
                    {"role": "assistant", "content": plan},
                    {
                        "role": "user",
                        "content": (
                            "工具执行结果如下，请给用户一个真实场景运行总结，"
                            "明确哪些步骤已经完成、哪些步骤还需要真实 Lab4AI/SSH 接入。\n"
                            + "\n".join(tool_outputs)
                            + f"\n用户最新需求：{latest_user}"
                        ),
                    },
                ],
                fallback=self._build_reply(metadata, latest_user),
            )
            await self._assistant(conversation_id, reply)
            await self._set_status(conversation_id, ConversationStatus.COMPLETED)
            self._publish(conversation_id, {"type": "status", "status": "completed"})
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            await self._assistant(conversation_id, f"执行失败：{_format_exception(exc)}")
            await self._set_status(conversation_id, ConversationStatus.FAILED)
            self._publish(conversation_id, {"type": "status", "status": "failed"})
        finally:
            self._streams[conversation_id].close()

    def _build_reply(self, metadata: dict, latest_user: str) -> str:
        parts = ["MVP 执行完成。"]
        if github_url := metadata.get("github_url"):
            parts.append(f"仓库：{github_url}")
        if paper_url := metadata.get("paper_url"):
            parts.append(f"论文：{paper_url}")
        if latest_user:
            parts.append(f"已记录你的要求：{latest_user}")
        parts.append("当前版本已经具备对话历史、工具事件、WebSocket 流式推送和配额检查骨架。")
        return "\n".join(parts)

    async def _assistant(self, conversation_id: int, content: str) -> None:
        async with SessionLocal() as session:
            msg = ConversationMessage(
                conversation_id=conversation_id,
                role=MessageRole.ASSISTANT,
                content=content,
            )
            session.add(msg)
            await session.commit()
            await session.refresh(msg)
            self._publish(conversation_id, {"type": "message", "message": _message_event(msg)})

    async def _tool(self, conversation_id: int, name: str, content: str) -> None:
        async with SessionLocal() as session:
            msg = ConversationMessage(
                conversation_id=conversation_id,
                role=MessageRole.TOOL,
                content=content,
                message_metadata={"tool_name": name},
            )
            session.add(msg)
            await session.commit()
            await session.refresh(msg)
            self._publish(
                conversation_id,
                {"type": "tool", "tool_name": name, "message": _message_event(msg)},
            )

    async def _set_status(self, conversation_id: int, status: ConversationStatus) -> None:
        async with SessionLocal() as session:
            conv = await session.get(Conversation, conversation_id)
            if conv:
                conv.status = status
                await session.commit()

    async def _model_or_fallback(
        self,
        config: LLMRuntimeConfig,
        *,
        system: str,
        messages: list[dict[str, str]],
        fallback: str,
    ) -> str:
        if not config.configured:
            return fallback
        try:
            runtime_config = replace(config, max_tokens=min(config.max_tokens, 1024))
            return await call_anthropic_compatible(runtime_config, system=system, messages=messages)
        except Exception as exc:
            return f"真实模型调用失败，已保留本地执行结果。错误：{_format_exception(exc)}"

    def _publish(self, conversation_id: int, event: dict) -> None:
        append_conversation_event(conversation_id, event)
        self._streams[conversation_id].publish(event)


def _message_event(msg: ConversationMessage) -> dict:
    return {
        "id": msg.id,
        "conversation_id": msg.conversation_id,
        "role": msg.role.value,
        "content": msg.content,
        "message_metadata": msg.message_metadata,
        "created_at": msg.created_at.isoformat(),
    }


async def _load_llm_config(user_id: int) -> LLMRuntimeConfig:
    async with SessionLocal() as session:
        config = await session.scalar(select(LLMConfig).where(LLMConfig.user_id == user_id))
        if config is None:
            return LLMRuntimeConfig(
                provider="anthropic",
                base_url="https://api.anthropic.com",
                api_key=None,
                model="claude-sonnet-4-6",
                max_tokens=4096,
            )
        return LLMRuntimeConfig(
            provider=config.provider,
            base_url=config.base_url,
            api_key=config.api_key_encrypted,
            model=config.model,
            max_tokens=config.max_tokens,
        )


def _build_legacy_system_prompt(metadata: dict) -> str:
    return "\n".join(
        [
            "你是 LOBSTER 科研复现 Agent。",
            "你需要基于用户输入制定真实科研复现计划，并在工具执行后总结结果。",
            "当前后端负责调度、工具执行和日志转发；涉及算力实例、SSH、仓库分析时应说明具体下一步。",
            f"任务类型：{metadata.get('task_type') or 'general'}",
            f"GitHub：{metadata.get('github_url') or '未提供'}",
            f"论文：{metadata.get('paper_url') or '未提供'}",
        ]
    )


def _select_skill(metadata: dict) -> str:
    if metadata.get("task_type") == "reproduce" or metadata.get("github_url"):
        return "lab4ai-auto-reproduct"
    return "general-chat"


def _format_exception(exc: Exception) -> str:
    message = str(exc).strip()
    if message:
        return f"{type(exc).__name__}: {message}"
    return type(exc).__name__


def _build_system_prompt(
    metadata: dict, skill_name: str, skill: SkillDefinition | None = None
) -> str:
    parts = [
        "你是 LOBSTER 科研复现 Agent。",
        "你需要基于用户输入制定真实科研复现计划，并在工具执行后总结结果。",
        "当前后端负责任务调度、工具执行和日志转发。",
        f"已选择 skill：{skill_name}",
        "当前真实 Lab4AI/SSH 尚未接入时，工具事件代表 MVP 模拟执行结果，不代表真实云实例已经创建。",
        f"任务类型：{metadata.get('task_type') or 'general'}",
        f"GitHub：{metadata.get('github_url') or '未提供'}",
        f"论文：{metadata.get('paper_url') or '未提供'}",
    ]
    if skill:
        parts.extend(
            [
                "",
                "以下是已选 skill 上下文。它只用于指导工作流；任何会产生副作用的动作仍必须通过后端 Tool 执行。",
                skill.prompt_context,
            ]
        )
    return "\n".join(parts)


def _build_llm_messages(
    messages: list[ConversationMessage], metadata: dict
) -> list[dict[str, str]]:
    result: list[dict[str, str]] = []
    if metadata:
        result.append({"role": "user", "content": f"任务元数据：{metadata}"})
    for msg in messages[-12:]:
        if msg.role == MessageRole.USER:
            result.append({"role": "user", "content": msg.content})
        elif msg.role == MessageRole.ASSISTANT:
            result.append({"role": "assistant", "content": msg.content})
        elif msg.role == MessageRole.TOOL:
            result.append(
                {
                    "role": "user",
                    "content": (
                        f"工具结果 {msg.message_metadata.get('tool_name', 'tool')}："
                        f"{msg.content}"
                    ),
                }
            )
    if not result:
        result.append({"role": "user", "content": "请开始执行任务。"})
    return result


_manager: AgentLoopManager | None = None


def get_agent_manager() -> AgentLoopManager:
    global _manager
    if _manager is None:
        _manager = AgentLoopManager()
    return _manager
