"""V2 Agent Loop with real LLM calls and streaming tool events."""

from __future__ import annotations

import asyncio
from collections import defaultdict
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from uuid import uuid4

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
from app.services.llm_client import (
    LLMToolResponse,
    LLMRuntimeConfig,
    call_anthropic_compatible,
    call_anthropic_compatible_tool_use,
    stream_anthropic_compatible,
)
from app.services.long_term_memory import (
    format_long_term_memory_context,
    search_user_memories,
    store_user_memory,
)
from app.services.skills import SkillDefinition, SkillLoader, select_skill
from app.services.tools import ToolExecutionContext, ToolRegistry, ToolResult
from app.services.workflow import (
    SkillWorkflowRunner,
    cleanup_workflow_resources,
    parse_workflow,
)

AGENT_PLAN_MAX_TOKENS = 2048
AGENT_REPLY_MAX_TOKENS = 8192
AGENT_REPLY_FALLBACK_MAX_TOKENS = 4096
AGENT_TOOL_USE_MAX_ITERATIONS = 8
LAB4AI_CREDENTIAL_ERROR_PREFIX = "Lab4AI 凭证未配置"


@dataclass
class ConversationStream:
    history: list[dict] = field(default_factory=list)
    subscribers: list[asyncio.Queue[dict | None]] = field(default_factory=list)
    finished: bool = False
    next_seq: int = 1

    def subscribe(self) -> asyncio.Queue[dict | None]:
        q: asyncio.Queue[dict | None] = asyncio.Queue()
        for event in self.history:
            q.put_nowait(event)
        if self.finished:
            q.put_nowait(None)
        else:
            self.subscribers.append(q)
        return q

    def publish(self, event: dict) -> dict:
        payload = dict(event)
        payload.setdefault("seq", self.next_seq)
        self.next_seq += 1
        self.history.append(payload)
        for q in self.subscribers:
            q.put_nowait(payload)
        return payload

    def close(self) -> None:
        self.finished = True
        for q in self.subscribers:
            q.put_nowait(None)
        self.subscribers.clear()


@dataclass(slots=True)
class ModelToolRunResult:
    metadata: dict
    tool_outputs: list[str]
    paused: bool = False
    used_model_tools: bool = False


class AgentLoopManager:
    def __init__(self) -> None:
        self._streams: defaultdict[int, ConversationStream] = defaultdict(ConversationStream)
        self._tasks: dict[int, asyncio.Task] = {}
        self._active_runs: dict[int, str] = {}
        self._pending_starts: set[int] = set()
        self._tools = ToolRegistry()
        self._skills = SkillLoader(get_settings().skills_dir_path).load_all()

    def subscribe(self, conversation_id: int) -> asyncio.Queue[dict | None]:
        return self._streams[conversation_id].subscribe()

    def start(self, conversation_id: int) -> None:
        if conversation_id in self._tasks and not self._tasks[conversation_id].done():
            self._pending_starts.add(conversation_id)
            return
        stream = self._streams[conversation_id]
        if stream.finished:
            self._streams[conversation_id] = ConversationStream(next_seq=stream.next_seq)
        task = asyncio.create_task(self._run(conversation_id))
        task.add_done_callback(lambda _task, cid=conversation_id: self._restart_if_pending(cid))
        self._tasks[conversation_id] = task

    def _restart_if_pending(self, conversation_id: int) -> None:
        if conversation_id not in self._pending_starts:
            return
        self._pending_starts.discard(conversation_id)
        self.start(conversation_id)

    async def stop(self, conversation_id: int) -> None:
        task = self._tasks.get(conversation_id)
        if task and not task.done():
            task.cancel()
        self._pending_starts.discard(conversation_id)
        metadata: dict = {}
        async with SessionLocal() as session:
            conv = await session.get(Conversation, conversation_id)
            if conv:
                metadata = ensure_memory(conv.metadata_ or {})
        if metadata:
            metadata = await self._cleanup_workflow_resources(conversation_id, metadata)
        async with SessionLocal() as session:
            conv = await session.get(Conversation, conversation_id)
            if conv:
                conv.status = ConversationStatus.STOPPED
                conv.metadata_ = mark_stopped(metadata or conv.metadata_ or {})
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
            run_id = str(metadata.get("workflow_run_id") or "")
            if run_id:
                self._active_runs[conversation_id] = run_id

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
                metadata = await self._cleanup_workflow_resources(conversation_id, metadata)
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
            long_term_context = await self._long_term_memory_context(user_id, latest_user)
            if long_term_context:
                system_prompt = f"{system_prompt}\n\n{long_term_context}"

            await self._progress(
                conversation_id,
                (
                    f"已选择 skill：{skill_name}。"
                    "当前 Lab4AI Tool 会直接调用真实平台 API；"
                    "SSH executor 仍需后续接入真实远程执行。"
                ),
                stage="skill_selection",
            )

            plan = await self._model_or_fallback(
                llm_config,
                system=system_prompt,
                messages=initial_messages,
                max_tokens=AGENT_PLAN_MAX_TOKENS,
                fallback="我会按 V2 Agent Loop 执行：先分析任务，再调用工具，最后给出下一步结果。",
            )
            await self._progress(conversation_id, plan, stage="plan")

            tool_outputs: list[str] = []
            if skill and skill.name == "lab4ai-auto-reproduct" and skill.workflow_context:
                workflow = parse_workflow(skill.workflow_context)
                runner = SkillWorkflowRunner(
                    workflow,
                    skill_name=skill.name,
                    invoke_tool=lambda current_metadata, tool_name, tool_input: (
                        self._invoke_tool_with_policy(
                            conversation_id,
                            current_metadata,
                            tool_name,
                            tool_input,
                        )
                    ),
                    write_metadata=lambda current_metadata: self._set_metadata(
                        conversation_id, current_metadata
                    ),
                    publish=lambda event: self._publish(conversation_id, event),
                    run_step_model_tools=lambda current_metadata, step: (
                        self._run_step_model_tool_use(
                            conversation_id,
                            current_metadata,
                            step,
                            llm_config,
                            system=system_prompt,
                            messages=[
                                *initial_messages,
                                {"role": "assistant", "content": plan},
                            ],
                        )
                    ),
                )
                workflow_result = await runner.run(metadata)
                metadata = workflow_result.metadata
                tool_outputs.extend(workflow_result.tool_outputs)
                if workflow_result.paused:
                    return
                if workflow_result.failed:
                    metadata = mark_failed(metadata)
                    await self._set_status_and_metadata(
                        conversation_id, ConversationStatus.FAILED, metadata
                    )
                    self._publish(conversation_id, {"type": "status", "status": "failed"})
                    return
            else:
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
            await self._stream_model_or_fallback(
                conversation_id,
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
            metadata = mark_completed(metadata)
            await self._set_status_and_metadata(
                conversation_id, ConversationStatus.COMPLETED, metadata
            )
            await self._store_completion_memory(conversation_id, user_id, metadata, latest_user)
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
            self._active_runs.pop(conversation_id, None)

    def _build_reply(self, metadata: dict, latest_user: str) -> str:
        parts = ["MVP 执行完成。"]
        if github_url := metadata.get("github_url"):
            parts.append(f"仓库：{github_url}")
        if paper_url := metadata.get("paper_url"):
            parts.append(f"论文：{paper_url}")
        if workflow_name := metadata.get("workflow_name"):
            parts.append(f"工作流：{workflow_name}")
            completed = [
                step
                for step in (metadata.get("workflow_steps") or [])
                if isinstance(step, dict) and step.get("status") == "completed"
            ]
            total = len(metadata.get("workflow_steps") or [])
            parts.append(f"步骤进度：{len(completed)}/{total} 已完成")
        if results := metadata.get("workflow_results"):
            if isinstance(results, dict) and results.get("word_report_path"):
                parts.append(f"报告路径：{results['word_report_path']}")
        if latest_user:
            parts.append(f"已记录你的要求：{latest_user}")
        parts.append("当前版本已经具备对话历史、工具事件、WebSocket 流式推送和配额检查骨架。")
        return "\n".join(parts)

    async def _assistant(self, conversation_id: int, content: str) -> None:
        msg = await self._persist_message(conversation_id, MessageRole.ASSISTANT, content)
        self._publish(
            conversation_id,
            {
                "type": "assistant_completed",
                "message": _message_event(msg),
            },
        )
        self._publish(conversation_id, {"type": "message", "message": _message_event(msg)})

    async def _progress(self, conversation_id: int, content: str, *, stage: str) -> None:
        self._publish(
            conversation_id,
            {
                "type": "progress",
                "stage": stage,
                "content": content,
            },
        )

    async def _run_model_tool_use_or_fallback(
        self,
        conversation_id: int,
        metadata: dict,
        config: LLMRuntimeConfig,
        *,
        system: str,
        messages: list[dict],
        allowed_tools: list[str] | None,
    ) -> ModelToolRunResult:
        if not config.configured:
            return ModelToolRunResult(metadata=metadata, tool_outputs=[])

        available_tools = self._tools.list_anthropic_tools(allowed_tools)
        if not available_tools:
            return ModelToolRunResult(metadata=metadata, tool_outputs=[])

        current_messages = list(messages)
        tool_outputs: list[str] = []
        used_model_tools = False
        last_error: Exception | None = None
        for iteration in range(AGENT_TOOL_USE_MAX_ITERATIONS):
            try:
                response = await call_anthropic_compatible_tool_use(
                    replace(config, max_tokens=AGENT_PLAN_MAX_TOKENS),
                    system=system,
                    messages=current_messages,
                    tools=available_tools,
                )
            except Exception as exc:
                last_error = exc
                break

            if response.text:
                await self._progress(
                    conversation_id,
                    response.text,
                    stage=f"tool_use_iteration_{iteration + 1}",
                )
            if not response.tool_calls:
                break

            used_model_tools = True
            current_messages.append(_assistant_tool_message(response))
            tool_result_blocks: list[dict] = []
            for tool_call in response.tool_calls:
                if tool_call.name not in {item["name"] for item in available_tools}:
                    tool_result_blocks.append(
                        _tool_result_block(
                            tool_call.id,
                            f"工具 `{tool_call.name}` 不在当前 allowlist 中，已拒绝执行。",
                            is_error=True,
                        )
                    )
                    continue

                tool_input = dict(tool_call.input or {})
                tool_input.setdefault("tool_call_id", tool_call.id or f"toolu_{uuid4().hex}")
                result, metadata, paused = await self._invoke_tool_with_policy(
                    conversation_id,
                    metadata,
                    tool_call.name,
                    tool_input,
                )
                if paused:
                    return ModelToolRunResult(
                        metadata=metadata,
                        tool_outputs=tool_outputs,
                        paused=True,
                        used_model_tools=True,
                    )
                if result:
                    output = f"{result.name}: {result.content}"
                    tool_outputs.append(output)
                    tool_result_blocks.append(
                        _tool_result_block(
                            str(tool_input["tool_call_id"]),
                            result.content,
                            is_error=not result.ok,
                        )
                    )
            if tool_result_blocks:
                current_messages.append({"role": "user", "content": tool_result_blocks})

        if last_error:
            await self._progress(
                conversation_id,
                f"模型 tool-use 调用失败，已回退到固定执行链路。错误：{_format_exception(last_error)}",
                stage="tool_use_fallback",
            )
        return ModelToolRunResult(
            metadata=metadata,
            tool_outputs=tool_outputs,
            used_model_tools=used_model_tools,
        )

    async def _run_step_model_tool_use(
        self,
        conversation_id: int,
        metadata: dict,
        step,
        config: LLMRuntimeConfig,
        *,
        system: str,
        messages: list[dict],
    ) -> tuple[dict, list[str], bool, bool]:
        step_state = next(
            (
                item
                for item in metadata.get("workflow_steps") or []
                if isinstance(item, dict) and item.get("id") == step.id
            ),
            {},
        )
        allowed_tools = [
            str(item)
            for item in (step_state.get("allowed_tools") or [])
            if isinstance(item, str) and item
        ]
        if not allowed_tools:
            return metadata, [], False, False

        result = await self._run_model_tool_use_or_fallback(
            conversation_id,
            metadata,
            config,
            system=system,
            messages=[
                *messages,
                {
                    "role": "user",
                    "content": (
                        f"当前 workflow step：{step.id} / {step.name}\n"
                        f"step 指令：{step.instruction or '未提供'}\n"
                        f"期望产出：{step.expected_output or '未提供'}\n"
                        "你只能调用当前 step allowlist 中的 Tool；不要越过 Workflow 顺序。"
                    ),
                },
            ],
            allowed_tools=allowed_tools,
        )
        return (
            result.metadata,
            result.tool_outputs,
            result.paused,
            result.used_model_tools,
        )

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
                {
                    "type": "tool_completed",
                    "tool_name": name,
                    "message": _message_event(msg),
                    "ok": msg.message_metadata.get("ok", True),
                    "tool_call_id": msg.message_metadata.get("tool_call_id"),
                    "workflow_step_id": msg.message_metadata.get("workflow_step_id"),
                },
            )

    async def _system(self, conversation_id: int, content: str) -> None:
        msg = await self._persist_message(conversation_id, MessageRole.SYSTEM, content)
        self._publish(conversation_id, {"type": "message", "message": _message_event(msg)})

    async def _invoke_tool_with_policy(
        self,
        conversation_id: int,
        metadata: dict,
        tool_name: str,
        tool_input: dict[str, object] | None = None,
    ) -> tuple[ToolResult | None, dict, bool]:
        tool_input = dict(tool_input or {})
        run_id = str(metadata.get("workflow_run_id") or "")
        if run_id:
            tool_input.setdefault("workflow_run_id", run_id)
        tool_input.setdefault("tool_call_id", _stable_tool_call_id(metadata, tool_name, tool_input))
        confirmation = self._tools.confirmation_for(tool_name, tool_input)
        approved = (
            has_approved_decision(
                metadata,
                confirmation.step,
                tool_call_id=confirmation.tool_call_id,
            )
            if confirmation
            else False
        )
        if confirmation and not approved:
            metadata = await self._ask_user(
                conversation_id,
                metadata=metadata,
                question=confirmation.question,
                options=list(confirmation.options),
                step=confirmation.step,
                tool_name=tool_name,
                tool_input=tool_input,
                risk_level=confirmation.risk_level,
                audit_category=confirmation.audit_category,
                tool_call_id=confirmation.tool_call_id,
                workflow_step_id=confirmation.workflow_step_id,
            )
            return None, metadata, True

        tool_definition = self._tools.definition(tool_name)
        self._publish(
            conversation_id,
            {
                "type": "tool_started",
                "tool_name": tool_name,
                "tool_input": tool_input,
                "tool_call_id": tool_input.get("tool_call_id"),
                "workflow_step_id": tool_input.get("workflow_step_id"),
                "risk_level": tool_definition.risk_level,
                "audit_category": tool_definition.audit_category,
            },
        )
        try:
            async with SessionLocal() as session:
                conv = await session.get(Conversation, conversation_id)
                context = (
                    ToolExecutionContext(
                        user_id=conv.user_id,
                        conversation_id=conversation_id,
                        session=session,
                    )
                    if conv
                    else None
                )
                result = await self._tools.invoke(tool_name, tool_input, context=context)
        except Exception as exc:
            if _is_lab4ai_credentials_missing(tool_name, exc):
                metadata = await self._ask_user(
                    conversation_id,
                    metadata=metadata,
                    question="Lab4AI 凭证未配置，请先由管理员配置平台账号。",
                    options=["已完成配置，继续执行", "停止任务"],
                    step=_admin_config_step(tool_name, tool_input),
                    tool_name=tool_name,
                    tool_input=tool_input,
                    risk_level=tool_definition.risk_level,
                    audit_category=tool_definition.audit_category,
                    tool_call_id=str(tool_input.get("tool_call_id") or ""),
                    workflow_step_id=str(tool_input.get("workflow_step_id") or ""),
                    intervention={
                        "type": "lab4ai_credentials_required",
                        "title": "需要配置 Lab4AI 平台账号",
                        "admin_endpoint": "/api/admin/settings/lab4ai",
                    },
                )
                return None, metadata, True
            self._publish(
                conversation_id,
                {
                    "type": "tool_error",
                    "tool_name": tool_name,
                    "tool_input": tool_input,
                    "tool_call_id": tool_input.get("tool_call_id"),
                    "workflow_step_id": tool_input.get("workflow_step_id"),
                    "error": _format_exception(exc),
                },
            )
            raise
        await self._tool(
            conversation_id,
            result.name,
            result.content,
            {
                "tool_input": tool_input,
                "ok": result.ok,
                "tool_call_id": tool_input.get("tool_call_id"),
                "workflow_step_id": tool_input.get("workflow_step_id"),
                "risk_level": tool_definition.risk_level,
                "audit_category": tool_definition.audit_category,
                "confirmation_required": confirmation is not None,
                "confirmed_by_user": confirmation is not None,
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
        risk_level: str | None = None,
        audit_category: str | None = None,
        tool_call_id: str | None = None,
        workflow_step_id: str | None = None,
        intervention: dict[str, object] | None = None,
    ) -> dict:
        result = await self._tools.ask_user(question)
        metadata = mark_waiting_for_user(
            metadata,
            question=question,
            options=options,
            step=step,
            tool_name=tool_name,
            tool_input=tool_input,
            tool_call_id=tool_call_id,
            workflow_step_id=workflow_step_id,
            intervention=intervention,
        )
        await self._set_status_and_metadata(conversation_id, ConversationStatus.ACTIVE, metadata)
        await self._tool(
            conversation_id,
            result.name,
            result.content,
            {
                "step": step,
                "options": options,
                "tool_name": tool_name,
                "tool_input": tool_input or {},
                "tool_call_id": tool_call_id,
                "workflow_step_id": workflow_step_id,
                "risk_level": risk_level,
                "audit_category": audit_category,
                "confirmation_required": True,
                "intervention": intervention,
            },
        )
        self._publish(
            conversation_id,
            {
                "type": "ask_user",
                "question": question,
                "options": options,
                "step": step,
                "tool_name": tool_name,
                "tool_call_id": tool_call_id,
                "workflow_step_id": workflow_step_id,
                "risk_level": risk_level,
                "audit_category": audit_category,
                "intervention": intervention,
            },
        )
        self._publish(conversation_id, {"type": "status", "status": WORKFLOW_WAITING_FOR_USER})
        return metadata

    async def _cleanup_workflow_resources(self, conversation_id: int, metadata: dict) -> dict:
        metadata, _outputs = await cleanup_workflow_resources(
            metadata,
            lambda current_metadata, tool_name, tool_input: self._invoke_tool_with_policy(
                conversation_id,
                current_metadata,
                tool_name,
                tool_input,
            ),
            lambda current_metadata: self._set_metadata(conversation_id, current_metadata),
            lambda event: self._publish(conversation_id, event),
        )
        return metadata

    async def _persist_message(
        self,
        conversation_id: int,
        role: MessageRole,
        content: str,
        message_metadata: dict | None = None,
    ) -> ConversationMessage:
        async with SessionLocal() as session:
            msg = ConversationMessage(
                conversation_id=conversation_id,
                role=role,
                content=content,
                message_metadata=message_metadata or {},
            )
            session.add(msg)
            await session.commit()
            await session.refresh(msg)
            return msg

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

    async def _long_term_memory_context(self, user_id: int, query: str) -> str:
        async with SessionLocal() as session:
            memories = await search_user_memories(session, user_id, query, limit=5)
        return format_long_term_memory_context(memories)

    async def _store_completion_memory(
        self,
        conversation_id: int,
        user_id: int,
        metadata: dict,
        latest_user: str,
    ) -> None:
        memory = ensure_memory(metadata).get("memory") or {}
        summary = str(memory.get("summary") or "").strip()
        artifacts = memory.get("artifacts") or []
        if not summary and not artifacts:
            return
        content_parts = []
        if latest_user:
            content_parts.append(f"用户需求：{latest_user}")
        if summary:
            content_parts.append(f"摘要：{summary}")
        if artifacts:
            content_parts.append("产物：" + "；".join(str(item) for item in artifacts[-5:]))
        async with SessionLocal() as session:
            await store_user_memory(
                session,
                user_id=user_id,
                kind="project",
                content="\n".join(content_parts),
                source_conversation_id=conversation_id,
            )

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

    async def _stream_model_or_fallback(
        self,
        conversation_id: int,
        config: LLMRuntimeConfig,
        *,
        system: str,
        messages: list[dict[str, str]],
        max_tokens: int,
        fallback: str,
    ) -> str:
        if not config.configured:
            return await self._stream_static_assistant(conversation_id, fallback)

        token_budgets = [max_tokens]
        if max_tokens > AGENT_REPLY_FALLBACK_MAX_TOKENS:
            token_budgets.append(AGENT_REPLY_FALLBACK_MAX_TOKENS)

        last_error: Exception | None = None
        for token_budget in token_budgets:
            content_parts: list[str] = []
            self._publish(conversation_id, {"type": "assistant_started"})
            try:
                runtime_config = replace(config, max_tokens=token_budget)
                async for delta in stream_anthropic_compatible(
                    runtime_config,
                    system=system,
                    messages=messages,
                ):
                    content_parts.append(delta)
                    self._publish(
                        conversation_id,
                        {
                            "type": "assistant_delta",
                            "delta": delta,
                        },
                    )
                content = "".join(content_parts).strip()
                if not content:
                    raise RuntimeError("模型流式响应为空")
                msg = await self._persist_message(conversation_id, MessageRole.ASSISTANT, content)
                self._publish(
                    conversation_id,
                    {
                        "type": "assistant_completed",
                        "message": _message_event(msg),
                    },
                )
                return content
            except Exception as exc:
                last_error = exc
                self._publish(
                    conversation_id,
                    {
                        "type": "assistant_error",
                        "error": _format_exception(exc),
                    },
                )

        error = _format_exception(last_error) if last_error else "未知错误"
        return await self._stream_static_assistant(
            conversation_id,
            f"真实模型调用失败，已保留本地执行结果。错误：{error}",
        )

    async def _stream_static_assistant(self, conversation_id: int, content: str) -> str:
        self._publish(conversation_id, {"type": "assistant_started"})
        if content:
            self._publish(conversation_id, {"type": "assistant_delta", "delta": content})
        msg = await self._persist_message(conversation_id, MessageRole.ASSISTANT, content)
        self._publish(
            conversation_id,
            {
                "type": "assistant_completed",
                "message": _message_event(msg),
            },
        )
        return content

    def _publish(self, conversation_id: int, event: dict) -> None:
        payload = dict(event)
        payload.setdefault("run_id", self._active_runs.get(conversation_id))
        payload.setdefault("timestamp", datetime.now(UTC).isoformat())
        stored = self._streams[conversation_id].publish(payload)
        append_conversation_event(conversation_id, stored)


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


def _is_lab4ai_credentials_missing(tool_name: str, exc: Exception) -> bool:
    return tool_name.startswith("lab4ai_") and str(exc).startswith(LAB4AI_CREDENTIAL_ERROR_PREFIX)


def _admin_config_step(tool_name: str, tool_input: dict[str, object]) -> str:
    parts = ["admin_config", "lab4ai", tool_name]
    for key in ("workflow_run_id", "tool_call_id", "workflow_step_id"):
        value = str(tool_input.get(key) or "").strip()
        if value:
            parts.append(value)
    return ":".join(parts)


def _assistant_tool_message(response: LLMToolResponse) -> dict:
    content: list[dict] = []
    if response.text:
        content.append({"type": "text", "text": response.text})
    for tool_call in response.tool_calls:
        content.append(
            {
                "type": "tool_use",
                "id": tool_call.id,
                "name": tool_call.name,
                "input": tool_call.input,
            }
        )
    return {"role": "assistant", "content": content}


def _tool_result_block(tool_use_id: str, content: str, *, is_error: bool = False) -> dict:
    return {
        "type": "tool_result",
        "tool_use_id": tool_use_id,
        "content": content,
        "is_error": is_error,
    }


def _stable_tool_call_id(metadata: dict, tool_name: str, tool_input: dict[str, object]) -> str:
    pending = metadata.get("pending_user_input")
    if (
        isinstance(pending, dict)
        and pending.get("tool_name") == tool_name
        and pending.get("tool_call_id")
    ):
        pending_input = pending.get("tool_input")
        pending_step = (pending_input or {}).get("workflow_step_id") if isinstance(pending_input, dict) else None
        current_step = tool_input.get("workflow_step_id")
        if not pending_step or not current_step or pending_step == current_step:
            return str(pending["tool_call_id"])
    return f"toolu_{uuid4().hex}"


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
        "Lab4AI 资源操作必须通过后端 Tool 调用真实平台 API 并写入归属记录。",
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
