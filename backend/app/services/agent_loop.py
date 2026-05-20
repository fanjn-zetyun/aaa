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
from app.services.conversation_memory import (
    DECISION_NEEDS_REVISION,
    DECISION_REJECTED,
    DECISION_STOPPED,
    WORKFLOW_WAITING_FOR_USER,
    build_memory_context,
    compact_memory_from_messages,
    ensure_memory,
    get_latest_decision_outcome,
    has_approved_decision,
    mark_idle,
    mark_completed,
    mark_failed,
    mark_running,
    mark_stopped,
    mark_waiting_for_user,
    remember_artifact,
    remember_fact,
    resolve_pending_user_input,
)
from app.services.llm_client import LLMRuntimeConfig, call_anthropic_compatible
from app.services.skills import SkillDefinition, SkillLoader, select_skill
from app.services.tools import ToolRegistry, ToolResult

AGENT_PLAN_MAX_TOKENS = 2048
AGENT_REPLY_MAX_TOKENS = 8192
AGENT_REPLY_FALLBACK_MAX_TOKENS = 4096


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
                conv.metadata_ = mark_stopped(conv.metadata_ or {})
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
        metadata: dict = {}
        try:
            await self._set_status(conversation_id, ConversationStatus.RUNNING)
            self._publish(conversation_id, {"type": "status", "status": "running"})

            stop_after_user_reply = False
            decision_outcome: str | None = None
            pending_input: dict | None = None
            memory_compacted = False
            async with SessionLocal() as session:
                conv = await session.get(Conversation, conversation_id)
                if conv is None:
                    return
                user_id = conv.user_id
                metadata = ensure_memory(conv.metadata_ or {})
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
                if metadata.get("workflow_state") == WORKFLOW_WAITING_FOR_USER:
                    pending_input = dict(metadata.get("pending_user_input") or {})
                    pending_step = pending_input.get("step")
                    metadata = resolve_pending_user_input(metadata, answer=latest_user)
                    if pending_step:
                        decision_outcome = get_latest_decision_outcome(metadata, str(pending_step))
                    stop_after_user_reply = decision_outcome == DECISION_STOPPED or _is_stop_request(
                        latest_user
                    )
                else:
                    metadata = mark_running(metadata)
                metadata, memory_compacted = compact_memory_from_messages(metadata, db_messages)
                conv.metadata_ = metadata
                await session.commit()

            if memory_compacted:
                self._publish(
                    conversation_id,
                    {
                        "type": "memory_compacted",
                        "compacted_through_message_id": metadata["memory"].get(
                            "compacted_through_message_id"
                        ),
                        "compaction_count": metadata["memory"].get("compaction_count"),
                    },
                )

            if stop_after_user_reply:
                metadata = mark_stopped(metadata)
                await self._system(conversation_id, "已根据你的回复停止当前任务。")
                await self._set_status_and_metadata(
                    conversation_id, ConversationStatus.STOPPED, metadata
                )
                self._publish(conversation_id, {"type": "status", "status": "stopped"})
                return

            if decision_outcome in (DECISION_NEEDS_REVISION, DECISION_REJECTED):
                tool_name = pending_input.get("tool_name") if pending_input else None
                blocked_step = f" `{tool_name}`" if tool_name else "需要确认的步骤"
                metadata = mark_idle(metadata)
                await self._assistant(
                    conversation_id,
                    (
                        f"我已记录你的回复，当前不会继续执行{blocked_step}。"
                        "请直接补充你希望修改的方案或新的执行约束。"
                    ),
                )
                await self._set_status_and_metadata(
                    conversation_id, ConversationStatus.ACTIVE, metadata
                )
                self._publish(conversation_id, {"type": "status", "status": "active"})
                return

            llm_config = await _load_llm_config(user_id)
            skill = select_skill(self._skills, metadata)
            skill_name = skill.name if skill else _select_skill(metadata)
            system_prompt = _build_system_prompt(metadata, skill_name, skill, self._tools)
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
                max_tokens=AGENT_PLAN_MAX_TOKENS,
                fallback="我会按 V2 Agent Loop 执行：先分析任务，再调用工具，最后给出下一步结果。",
            )
            await self._assistant(conversation_id, plan)

            tool_outputs: list[str] = []
            result, metadata, paused = await self._invoke_tool_with_policy(
                conversation_id,
                metadata,
                "analyze_repo",
                {"github_url": metadata.get("github_url")},
            )
            if paused:
                return
            if result:
                tool_outputs.append(f"{result.name}: {result.content}")
            if metadata.get("github_url"):
                metadata = remember_fact(metadata, f"目标仓库：{metadata['github_url']}")
                await self._set_metadata(conversation_id, metadata)

            if metadata.get("task_type") == "reproduce" or metadata.get("github_url"):
                result, metadata, paused = await self._invoke_tool_with_policy(
                    conversation_id,
                    metadata,
                    "lab4ai_create_instance",
                    {},
                )
                if paused:
                    return
                if result:
                    tool_outputs.append(f"{result.name}: {result.content}")
                    metadata = remember_artifact(metadata, result.content)
                    await self._set_metadata(conversation_id, metadata)

                result, metadata, paused = await self._invoke_tool_with_policy(
                    conversation_id,
                    metadata,
                    "ssh_execute",
                    {"command": "git clone && inspect README/requirements"},
                )
                if paused:
                    return
                if result:
                    tool_outputs.append(f"{result.name}: {result.content}")

                result, metadata, paused = await self._invoke_tool_with_policy(
                    conversation_id,
                    metadata,
                    "lab4ai_stop_instance",
                    {},
                )
                if paused:
                    return
                if result:
                    tool_outputs.append(f"{result.name}: {result.content}")

            metadata = _refresh_summary(metadata, latest_user, tool_outputs)
            await self._set_metadata(conversation_id, metadata)
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
                max_tokens=AGENT_REPLY_MAX_TOKENS,
                fallback=self._build_reply(metadata, latest_user),
            )
            await self._assistant(conversation_id, reply)
            metadata = mark_completed(metadata)
            await self._set_status_and_metadata(
                conversation_id, ConversationStatus.COMPLETED, metadata
            )
            self._publish(conversation_id, {"type": "status", "status": "completed"})
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            await self._assistant(conversation_id, f"执行失败：{_format_exception(exc)}")
            await self._set_status_and_metadata(
                conversation_id, ConversationStatus.FAILED, mark_failed(metadata)
            )
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

    async def _tool(
        self,
        conversation_id: int,
        name: str,
        content: str,
        message_metadata: dict | None = None,
    ) -> None:
        async with SessionLocal() as session:
            msg = ConversationMessage(
                conversation_id=conversation_id,
                role=MessageRole.TOOL,
                content=content,
                message_metadata={"tool_name": name, **(message_metadata or {})},
            )
            session.add(msg)
            await session.commit()
            await session.refresh(msg)
            self._publish(
                conversation_id,
                {"type": "tool", "tool_name": name, "message": _message_event(msg)},
            )

    async def _system(self, conversation_id: int, content: str) -> None:
        async with SessionLocal() as session:
            msg = ConversationMessage(
                conversation_id=conversation_id,
                role=MessageRole.SYSTEM,
                content=content,
            )
            session.add(msg)
            await session.commit()
            await session.refresh(msg)
            self._publish(conversation_id, {"type": "message", "message": _message_event(msg)})

    async def _invoke_tool_with_policy(
        self,
        conversation_id: int,
        metadata: dict,
        tool_name: str,
        tool_input: dict[str, object] | None = None,
    ) -> tuple[ToolResult | None, dict, bool]:
        tool_input = dict(tool_input or {})
        confirmation = self._tools.confirmation_for(tool_name, tool_input)
        if confirmation and not has_approved_decision(metadata, confirmation.step):
            metadata = await self._ask_user(
                conversation_id,
                metadata=metadata,
                question=confirmation.question,
                options=list(confirmation.options),
                step=confirmation.step,
                tool_name=tool_name,
                tool_input=tool_input,
            )
            return None, metadata, True

        result = await self._tools.invoke(tool_name, tool_input)
        await self._tool(
            conversation_id,
            result.name,
            result.content,
            {
                "tool_input": tool_input,
                "ok": result.ok,
                **(result.metadata or {}),
            },
        )
        return result, metadata, False

    async def _ask_user(
        self,
        conversation_id: int,
        *,
        metadata: dict,
        question: str,
        options: list[str],
        step: str,
        tool_name: str | None = None,
        tool_input: dict[str, object] | None = None,
    ) -> dict:
        result = await self._tools.ask_user(question)
        metadata = mark_waiting_for_user(
            metadata,
            question=question,
            options=options,
            step=step,
            tool_name=tool_name,
            tool_input=tool_input,
        )
        await self._set_status_and_metadata(conversation_id, ConversationStatus.ACTIVE, metadata)
        await self._tool(
            conversation_id,
            result.name,
            result.content,
            {"step": step, "options": options, "tool_name": tool_name},
        )
        await self._system(
            conversation_id,
            "需要你确认后再继续执行：\n"
            f"{question}\n\n"
            "可回复：继续执行 / 先修改方案 / 停止任务，或直接输入你的具体要求。",
        )
        self._publish(
            conversation_id,
            {
                "type": "ask_user",
                "question": question,
                "options": options,
                "step": step,
                "tool_name": tool_name,
            },
        )
        self._publish(conversation_id, {"type": "status", "status": WORKFLOW_WAITING_FOR_USER})
        return metadata

    async def _set_status(self, conversation_id: int, status: ConversationStatus) -> None:
        async with SessionLocal() as session:
            conv = await session.get(Conversation, conversation_id)
            if conv:
                conv.status = status
                await session.commit()

    async def _set_metadata(self, conversation_id: int, metadata: dict) -> None:
        async with SessionLocal() as session:
            conv = await session.get(Conversation, conversation_id)
            if conv:
                conv.metadata_ = metadata
                await session.commit()

    async def _set_status_and_metadata(
        self, conversation_id: int, status: ConversationStatus, metadata: dict
    ) -> None:
        async with SessionLocal() as session:
            conv = await session.get(Conversation, conversation_id)
            if conv:
                conv.status = status
                conv.metadata_ = metadata
                await session.commit()

    async def _model_or_fallback(
        self,
        config: LLMRuntimeConfig,
        *,
        system: str,
        messages: list[dict[str, str]],
        max_tokens: int,
        fallback: str,
    ) -> str:
        if not config.configured:
            return fallback
        token_budgets = [max_tokens]
        if max_tokens > AGENT_REPLY_FALLBACK_MAX_TOKENS:
            token_budgets.append(AGENT_REPLY_FALLBACK_MAX_TOKENS)

        last_error: Exception | None = None
        for token_budget in token_budgets:
            try:
                runtime_config = replace(config, max_tokens=token_budget)
                return await call_anthropic_compatible(
                    runtime_config,
                    system=system,
                    messages=messages,
                )
            except Exception as exc:
                last_error = exc

        error = _format_exception(last_error) if last_error else "未知错误"
        return f"真实模型调用失败，已保留本地执行结果。错误：{error}"

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


def _refresh_summary(metadata: dict, latest_user: str, tool_outputs: list[str]) -> dict:
    metadata = ensure_memory(metadata)
    memory = metadata["memory"]
    parts: list[str] = []
    if metadata.get("github_url"):
        parts.append(f"仓库 {metadata['github_url']}")
    if latest_user:
        parts.append(f"用户需求 {latest_user}")
    if tool_outputs:
        parts.append(f"工具步骤 {len(tool_outputs)} 项")
    current_summary = "；".join(parts)
    previous_summary = str(memory.get("summary") or "").strip()
    if current_summary:
        marker = f"[当前轮次] {current_summary}"
        if marker not in previous_summary:
            memory["summary"] = f"{previous_summary}\n{marker}".strip()
    return metadata


def _is_stop_request(text: str) -> bool:
    lowered = text.lower()
    return any(key in lowered for key in ("停止", "中止", "取消", "stop", "cancel"))


def _format_exception(exc: Exception) -> str:
    message = str(exc).strip()
    if message:
        return f"{type(exc).__name__}: {message}"
    return type(exc).__name__


def _build_system_prompt(
    metadata: dict,
    skill_name: str,
    skill: SkillDefinition | None = None,
    tools: ToolRegistry | None = None,
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
    if tools:
        parts.extend(["", tools.prompt_context(skill.allowed_tools if skill else None)])
    if metadata.get("memory"):
        parts.extend(["", build_memory_context(metadata)])
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
        result.append({"role": "user", "content": build_memory_context(metadata)})
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
