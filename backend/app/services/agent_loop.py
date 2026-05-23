"""V2 Agent Loop with real LLM calls and streaming tool events."""

from __future__ import annotations

import asyncio
from collections import defaultdict
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
import math
import re
from uuid import uuid4

from sqlalchemy import select

from app.agent_runtime.events import CallbackEventSink
from app.agent_runtime.llm import LLMAdapter
from app.agent_runtime.runtime import AgentRuntime
from app.agent_runtime.skills import SkillInvokeTool
from app.agent_runtime.tool_executor import ToolExecutor
from app.core.database import SessionLocal
from app.models import Conversation, ConversationMessage, LLMConfig
from app.models.conversation import ConversationStatus, MessageRole
from app.core.config import get_settings
from app.services.conversation_store import append_conversation_event
from app.services.conversation_memory import (
    DECISION_APPROVED,
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
from app.services.skill_selector import SkillSelector
from app.services.skills import SkillDefinition, SkillLoader
from app.services.tools import ToolExecutionContext, ToolRegistry, ToolResult
from app.services.workflow import (
    SkillWorkflowRunner,
    WorkflowStep,
    add_workflow_step_artifact,
    add_workflow_tool_call,
    cleanup_workflow_resources,
    parse_workflow,
    set_workflow_resource,
    set_workflow_step_evidence,
    update_workflow_tool_call,
    workflow_step_state,
)

AGENT_PLAN_MAX_TOKENS = 2048
AGENT_REPLY_MAX_TOKENS = 8192
AGENT_REPLY_FALLBACK_MAX_TOKENS = 4096
AGENT_TOOL_USE_MAX_ITERATIONS = 8
LAB4AI_CREDENTIAL_ERROR_PREFIX = "Lab4AI 凭证未配置"
SSH_TOOL_ALIASES = {
    "claw-shell": "ssh_execute",
    "claw_shell_run": "ssh_execute",
    "ssh_essentials_execute": "ssh_execute",
}
FILE_TOOL_ALIASES = {
    "file-system": "file_system_read",
    "file_system_read": "file_system_read",
    "file_system_list": "file_system_list",
    "file_system_write": "file_write",
}


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
    failed: bool = False


class AgentLoopManager:
    def __init__(self) -> None:
        self._streams: defaultdict[int, ConversationStream] = defaultdict(ConversationStream)
        self._tasks: dict[int, asyncio.Task] = {}
        self._active_runs: dict[int, str] = {}
        self._pending_starts: set[int] = set()
        self._tools = ToolRegistry()
        self._skills = SkillLoader(get_settings().skills_dir_path).load_all()
        self._skill_selector = SkillSelector()

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

    async def _run_with_agent_runtime_v3(
        self,
        *,
        conversation_id: int,
        config: LLMRuntimeConfig,
    ) -> bool:
        settings = get_settings()
        if not settings.agent_runtime_v3_enabled:
            return False
        if not config.configured:
            return False
        async with SessionLocal() as session:
            event_sink = CallbackEventSink(lambda event: self._publish(conversation_id, event))
            runtime = AgentRuntime(
                session=session,
                llm=LLMAdapter(config),
                tool_executor=ToolExecutor(
                    registry=self._tools,
                    event_sink=event_sink,
                    runtime_tools={"skill.invoke": SkillInvokeTool(self._skills)},
                ),
                event_sink=event_sink,
            )
            await runtime.run_conversation(conversation_id, model=config.model)
        return True

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

    async def _select_skill_for_run(
        self,
        config: LLMRuntimeConfig,
        metadata: dict,
        latest_user: str,
        reuse_existing: bool = False,
    ) -> tuple[SkillDefinition | None, str, dict]:
        updated_metadata = dict(metadata)
        if reuse_existing:
            current_selection = metadata.get("skill_selection")
            existing_name = ""
            if isinstance(current_selection, dict):
                existing_name = str(current_selection.get("selected_skill") or "").strip()
            if not existing_name:
                existing_name = str(metadata.get("selected_skill") or "").strip()
            if not existing_name:
                workflow_name = str(metadata.get("workflow_name") or "").strip()
                if workflow_name in self._skills:
                    existing_name = workflow_name
            if existing_name:
                if "skill_selection" not in updated_metadata:
                    updated_metadata["skill_selection"] = {
                        "selected_skill": existing_name,
                        "source": "fallback",
                        "model_choice": None,
                        "fallback_choice": existing_name,
                        "reason": "复用当前 workflow 已选 skill。",
                        "confidence": None,
                        "error": None,
                    }
                return self._skills.get(existing_name), existing_name, updated_metadata

        selection = await self._skill_selector.select(
            config=config,
            skills=self._skills,
            metadata=metadata,
            latest_user=latest_user,
        )
        updated_metadata["skill_selection"] = selection.to_metadata()
        return self._skills.get(selection.skill_name), selection.skill_name, updated_metadata

    async def _run(self, conversation_id: int) -> None:
        metadata: dict = {}
        try:
            await self._set_status(conversation_id, ConversationStatus.RUNNING)
            self._publish(conversation_id, {"type": "status", "status": "running"})

            stop_after_user_reply = False
            decision_outcome: str | None = None
            pending_input: dict | None = None
            memory_compacted = False
            resuming_workflow = False
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
                resuming_workflow = metadata.get("workflow_state") == WORKFLOW_WAITING_FOR_USER
                if resuming_workflow:
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
            if await self._run_with_agent_runtime_v3(
                conversation_id=conversation_id,
                config=llm_config,
            ):
                return
            skill, skill_name, metadata = await self._select_skill_for_run(
                llm_config,
                metadata,
                latest_user,
                reuse_existing=resuming_workflow,
            )
            await self._set_metadata(conversation_id, metadata)
            if _requires_workflow_task(metadata) and not (skill and skill.workflow_context):
                await self._fail_missing_workflow_skill(conversation_id, metadata)
                return
            system_prompt = _build_system_prompt(metadata, skill_name, skill, self._tools)
            initial_messages = _build_llm_messages(db_messages, metadata)
            long_term_context = await self._long_term_memory_context(user_id, latest_user)
            if long_term_context:
                system_prompt = f"{system_prompt}\n\n{long_term_context}"
            selection_source = metadata["skill_selection"].get("source")

            await self._progress(
                conversation_id,
                (
                    f"已选择 skill：{skill_name}（来源：{selection_source}）。"
                    "当前 Lab4AI Tool 会直接调用真实平台 API；"
                    "SSH、文件写入、仓库/论文分析和报告生成均通过后端 ToolRegistry 执行。"
                ),
                stage="skill_selection",
                extra={
                    "skill_selection_source": selection_source,
                    "skill_selection": _safe_skill_selection_evidence(
                        metadata.get("skill_selection")
                    ),
                    "workflow_path": _workflow_display_path_for_skill(skill),
                },
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
            if skill and skill.workflow_context:
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
        parts = ["本轮执行完成。"]
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

    async def _progress(
        self,
        conversation_id: int,
        content: str,
        *,
        stage: str,
        extra: dict | None = None,
    ) -> None:
        event = dict(extra or {})
        event.update(
            {
                "type": "progress",
                "stage": stage,
                "content": content,
            }
        )
        self._publish(conversation_id, event)

    async def _fail_missing_workflow_skill(self, conversation_id: int, metadata: dict) -> None:
        message = "未找到可执行的复现 workflow skill，无法继续。"
        failed_metadata = mark_failed(metadata)
        await self._assistant(conversation_id, message)
        await self._set_status_and_metadata(
            conversation_id, ConversationStatus.FAILED, failed_metadata
        )
        self._publish(conversation_id, {"type": "status", "status": "failed"})

    async def _run_model_tool_use_or_fallback(
        self,
        conversation_id: int,
        metadata: dict,
        config: LLMRuntimeConfig,
        *,
        system: str,
        messages: list[dict],
        allowed_tools: list[str] | None,
        workflow_step_id: str | None = None,
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
            prepared_tool_calls: list[tuple[object, dict[str, object]]] = []
            available_tool_names = {item["name"] for item in available_tools}
            for tool_call in response.tool_calls:
                canonical_tool_name = _canonical_tool_name(tool_call.name)
                if (
                    tool_call.name not in available_tool_names
                    and canonical_tool_name not in available_tool_names
                ):
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
                tool_input = _prepare_model_tool_input(
                    canonical_tool_name,
                    tool_input,
                    metadata,
                    workflow_step_id,
                )
                adapter_error = str(tool_input.pop("_adapter_error", "") or "")
                if adapter_error:
                    tool_outputs.append(
                        f"{tool_call.name}: {adapter_error}，已拒绝执行。"
                    )
                    return ModelToolRunResult(
                        metadata=metadata,
                        tool_outputs=tool_outputs,
                        used_model_tools=True,
                        failed=True,
                    )
                if _contains_unrendered_template(tool_input):
                    tool_outputs.append(
                        (
                            f"{tool_call.name}: 工具参数中仍包含未渲染模板变量 `{{{{...}}}}`，"
                            "已回退到后端固定执行链路。"
                        )
                    )
                    return ModelToolRunResult(
                        metadata=metadata,
                        tool_outputs=tool_outputs,
                        used_model_tools=True,
                        failed=True,
                    )
                prepared_tool_calls.append((tool_call, {"_tool_name": canonical_tool_name, **tool_input}))
            for tool_call, tool_input in prepared_tool_calls:
                canonical_tool_name = str(tool_input.pop("_tool_name"))
                if workflow_step_id:
                    metadata = _record_model_tool_call_started(
                        metadata,
                        workflow_step_id,
                        canonical_tool_name,
                        str(tool_input["tool_call_id"]),
                    )
                result, metadata, paused = await self._invoke_tool_with_policy(
                    conversation_id,
                    metadata,
                    canonical_tool_name,
                    tool_input,
                )
                if paused:
                    if workflow_step_id:
                        metadata = update_workflow_tool_call(
                            metadata,
                            workflow_step_id,
                            str(tool_input["tool_call_id"]),
                            status="waiting_for_user",
                        )
                    return ModelToolRunResult(
                        metadata=metadata,
                        tool_outputs=tool_outputs,
                        paused=True,
                        used_model_tools=True,
                    )
                if result:
                    if workflow_step_id:
                        metadata = _record_model_tool_call_completed(
                            metadata,
                            workflow_step_id,
                            canonical_tool_name,
                            str(tool_input["tool_call_id"]),
                            tool_input,
                            result,
                        )
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
            message = f"模型 tool-use 调用失败，当前 workflow step 已停止。错误：{_format_exception(last_error)}"
            await self._progress(
                conversation_id,
                message,
                stage="tool_use_failed",
            )
            return ModelToolRunResult(
                metadata=metadata,
                tool_outputs=[message],
                failed=True,
            )
        if not used_model_tools:
            message = "模型未调用当前 step 允许的任何 Tool，已停止该 workflow step，避免回退到固定执行链路。"
            return ModelToolRunResult(
                metadata=metadata,
                tool_outputs=[message],
                failed=True,
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
    ) -> tuple[dict, list[str], bool, bool, bool]:
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
            return metadata, [], False, False, False

        approved_waiting_tool = _approved_waiting_step_tool(metadata, step.id, allowed_tools)
        if approved_waiting_tool:
            tool_name, tool_input = approved_waiting_tool
            tool_call_id = str(tool_input["tool_call_id"])
            metadata = _record_model_tool_call_started(
                metadata,
                step.id,
                tool_name,
                tool_call_id,
            )
            result, metadata, paused = await self._invoke_tool_with_policy(
                conversation_id,
                metadata,
                tool_name,
                tool_input,
            )
            if paused:
                metadata = update_workflow_tool_call(
                    metadata,
                    step.id,
                    tool_call_id,
                    status="waiting_for_user",
                )
                return metadata, [], True, True, False
            if result is None:
                return metadata, [], False, True, True
            metadata = _record_model_tool_call_completed(
                metadata,
                step.id,
                tool_name,
                tool_call_id,
                tool_input,
                result,
            )
            return (
                metadata,
                [f"{result.name}: {result.content}"],
                False,
                True,
                result.ok is False,
            )

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
                        f"{_step_tool_use_guidance(metadata, step.id)}\n"
                        "你只能调用当前 step allowlist 中的 Tool；不要越过 Workflow 顺序。"
                    ),
                },
            ],
            allowed_tools=allowed_tools,
            workflow_step_id=step.id,
        )
        return (
            result.metadata,
            result.tool_outputs,
            result.paused,
            result.used_model_tools,
            result.failed,
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


def _requires_workflow_task(metadata: dict) -> bool:
    return metadata.get("task_type") == "reproduce" or bool(metadata.get("github_url"))


def _workflow_display_path_for_skill(skill: SkillDefinition | None) -> str | None:
    if not skill or not skill.workflow_context:
        return None
    if skill.name == "lab4ai-auto-reproduct":
        return f"skills/{skill.name}/project_reproduce.yaml"
    return f"skills/{skill.name}/workflow.yaml"


_SAFE_SKILL_SELECTION_KEYS = {
    "selected_skill",
    "source",
    "model_choice",
    "fallback_choice",
    "reason",
    "confidence",
    "error",
}
_SAFE_SKILL_SELECTION_STRING_MAX_LENGTH = 500
_MODEL_CALL_FAILED_SAFE_REASON = "Model skill selection failed; selected fallback."


def _safe_skill_selection_evidence(selection: object) -> dict[str, object | None] | None:
    if not isinstance(selection, dict):
        return None
    evidence: dict[str, object | None] = {}
    for key in _SAFE_SKILL_SELECTION_KEYS:
        if key not in selection:
            continue
        value = selection.get(key)
        if isinstance(value, float) and not math.isfinite(value):
            continue
        if isinstance(value, str):
            if key == "reason" and selection.get("error") == "model_call_failed":
                evidence[key] = _MODEL_CALL_FAILED_SAFE_REASON
            else:
                evidence[key] = value[:_SAFE_SKILL_SELECTION_STRING_MAX_LENGTH]
        elif value is None or isinstance(value, (int, bool)):
            evidence[key] = value
        elif isinstance(value, float):
            evidence[key] = value
    return evidence


def _canonical_tool_name(name: str) -> str:
    if name in SSH_TOOL_ALIASES:
        return SSH_TOOL_ALIASES[name]
    if name in FILE_TOOL_ALIASES:
        return FILE_TOOL_ALIASES[name]
    return name


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


def _step_tool_use_guidance(metadata: dict, step_id: str) -> str:
    if step_id == "step_7_gpu_execution":
        server_id = _workflow_resource_server_id(metadata, "gpu")
        return (
            f"当前 GPU 实例 server_id：{server_id or '未记录'}。\n"
            "Step 7 必须按 skill instruction 的语义执行：先等待 SSH 就绪，再在同一段远程 Bash 中激活 "
            "Conda、注入 CUDA/Hopper 编译环境、执行 import 预检、动态 smoke test 并写入 env_patches.md。"
            "`claw_shell_run` 会由后端映射到受控 `ssh_execute`；如果你输出旧式 sshpass wrapper，"
            "后端只会提取远程 Bash 并使用当前 GPU 实例的受控连接参数执行。不要留下 `{{...}}` 模板变量。"
        )
    if step_id == "step_4_cpu_env_setup":
        server_id = _workflow_resource_server_id(metadata, "cpu")
        return (
            f"当前 CPU 实例 server_id：{server_id or '未记录'}。\n"
            "`ssh_execute.command` 只填写远程实例内执行的 Bash；"
            "`claw_shell_run` 只是兼容别名，底层仍会转成 `ssh_execute`；"
            "不要在 command 中再次写 sshpass/ssh root@...，也不要输出 `{{...}}` 模板变量。"
        )
    if step_id == "step_7_gpu_execution":
        server_id = _workflow_resource_server_id(metadata, "gpu")
        return (
            f"当前 GPU 实例 server_id：{server_id or '未记录'}。\n"
            "`ssh_execute.command` 只填写远程实例内执行的 Bash；"
            "`claw_shell_run` 只是兼容别名，底层仍会转成 `ssh_execute`；"
            "不要在 command 中再次写 sshpass/ssh root@...，也不要输出 `{{...}}` 模板变量。"
        )
    return "不要输出 `{{...}}` 模板变量。"


def _record_model_tool_call_started(
    metadata: dict,
    workflow_step_id: str,
    tool_name: str,
    tool_call_id: str,
) -> dict:
    step = _workflow_step_ref(metadata, workflow_step_id)
    existing = workflow_step_state(metadata, workflow_step_id).get("tool_calls") or []
    if any(isinstance(item, dict) and item.get("tool_call_id") == tool_call_id for item in existing):
        return update_workflow_tool_call(
            metadata,
            workflow_step_id,
            tool_call_id,
            status="running",
        )
    return add_workflow_tool_call(
        metadata,
        step,
        tool_call_id=tool_call_id,
        tool_name=tool_name,
        status="running",
    )


def _approved_waiting_step_tool(
    metadata: dict,
    workflow_step_id: str,
    allowed_tools: list[str],
) -> tuple[str, dict[str, object]] | None:
    step = workflow_step_state(metadata, workflow_step_id)
    waiting_calls = {
        str(item.get("tool_call_id")): str(item.get("name") or "")
        for item in reversed(step.get("tool_calls") or [])
        if (
            isinstance(item, dict)
            and item.get("status") == "waiting_for_user"
            and item.get("tool_call_id")
            and str(item.get("name") or "") in allowed_tools
        )
    }
    if not waiting_calls:
        return None

    run_id = str(metadata.get("workflow_run_id") or "")
    decisions = (ensure_memory(metadata).get("memory") or {}).get("decisions") or []
    for decision in reversed(decisions):
        if not isinstance(decision, dict):
            continue
        tool_call_id = str(decision.get("tool_call_id") or "")
        tool_name = str(decision.get("tool_name") or waiting_calls.get(tool_call_id) or "")
        if (
            decision.get("outcome") != DECISION_APPROVED
            or decision.get("workflow_step_id") != workflow_step_id
            or tool_call_id not in waiting_calls
            or tool_name not in allowed_tools
            or (run_id and decision.get("run_id") != run_id)
            or (waiting_calls.get(tool_call_id) and waiting_calls[tool_call_id] != tool_name)
        ):
            continue

        tool_input = dict(decision.get("tool_input") or {})
        tool_input["tool_call_id"] = tool_call_id
        tool_input["workflow_step_id"] = workflow_step_id
        if run_id:
            tool_input["workflow_run_id"] = run_id
        return tool_name, tool_input
    return None


def _record_model_tool_call_completed(
    metadata: dict,
    workflow_step_id: str,
    tool_name: str,
    tool_call_id: str,
    tool_input: dict[str, object],
    result: ToolResult,
) -> dict:
    metadata = update_workflow_tool_call(
        metadata,
        workflow_step_id,
        tool_call_id,
        status="completed" if result.ok else "failed",
        ok=result.ok,
        error=None if result.ok else result.content,
        result_metadata=result.metadata,
    )
    if result.ok:
        metadata = _apply_model_tool_result_to_workflow(
            metadata,
            workflow_step_id,
            tool_name,
            tool_input,
            result,
        )
    return metadata


def _apply_model_tool_result_to_workflow(
    metadata: dict,
    workflow_step_id: str,
    tool_name: str,
    tool_input: dict[str, object],
    result: ToolResult,
) -> dict:
    step = _workflow_step_ref(metadata, workflow_step_id)
    result_metadata = result.metadata or {}

    if tool_name == "analyze_repo":
        metadata = ensure_memory(metadata)
        workflow_results = dict(metadata.get("workflow_results") or {})
        workflow_results.update(
            {
                "repo_name": _repo_name_from_url(str(metadata.get("github_url") or "project")),
                "repo_score": result_metadata.get("score", workflow_results.get("repo_score")),
                "score": result_metadata.get("score", workflow_results.get("score")),
                "audit_report_path": str(result_metadata.get("report_path") or ""),
            }
        )
        metadata["workflow_results"] = workflow_results
        if result_metadata.get("report_path"):
            metadata = add_workflow_step_artifact(metadata, step, str(result_metadata["report_path"]))

    if tool_name == "analyze_paper":
        metadata = ensure_memory(metadata)
        workflow_results = dict(metadata.get("workflow_results") or {})
        workflow_results.update(
            {
                "paper_score": result_metadata.get("score", workflow_results.get("paper_score")),
                "paper_report_path": str(result_metadata.get("report_path") or ""),
                "baseline_metrics": result_metadata.get("metrics") or workflow_results.get("baseline_metrics") or {},
                "hyperparams": result_metadata.get("hyperparams") or workflow_results.get("hyperparams") or {},
                "datasets": result_metadata.get("datasets") or workflow_results.get("datasets") or [],
            }
        )
        if result_metadata.get("score") is not None:
            workflow_results["score"] = max(
                int(workflow_results.get("score") or 0),
                int(result_metadata.get("score") or 0),
            )
        metadata["workflow_results"] = workflow_results
        if result_metadata.get("report_path"):
            metadata = add_workflow_step_artifact(metadata, step, str(result_metadata["report_path"]))

    if tool_name == "lab4ai_create_instance":
        kind = _resource_kind_for_tool(workflow_step_id, tool_input)
        server_id = str(result_metadata.get("server_id") or "")
        if kind and server_id:
            resource_key = kind.lower()
            metadata = set_workflow_resource(
                metadata,
                resource_key,
                server_id=server_id,
                released=False,
                raw=result_metadata,
            )
            metadata = add_workflow_step_artifact(
                metadata,
                step,
                f"lab4ai:{resource_key}:{server_id}",
            )
            metadata = set_workflow_step_evidence(
                metadata,
                step,
                **{
                    f"{resource_key}_instance_created": True,
                    "server_id": server_id,
                    "completion_source": "model_tool_use",
                },
            )
            metadata = remember_artifact(metadata, f"{kind} 实例：{server_id}")

    if tool_name == "lab4ai_stop_instance":
        kind = _resource_kind_for_tool(workflow_step_id, tool_input)
        resource_key = (kind or "").lower()
        server_id = str(tool_input.get("server_id") or result_metadata.get("server_id") or "")
        if resource_key:
            metadata = set_workflow_resource(metadata, resource_key, released=True)
            metadata = set_workflow_step_evidence(
                metadata,
                step,
                **{
                    f"{resource_key}_instance_released": bool(server_id),
                    "server_id": server_id,
                    "completion_source": "model_tool_use",
                },
            )

    if workflow_step_id == "step_4_cpu_env_setup":
        if tool_name in {"ssh_execute", "claw_shell_run"}:
            metadata = set_workflow_step_evidence(
                metadata,
                step,
                clone_completed=True,
                remote_workspace_verified=True,
                git_repo_verified=True,
                completion_source="model_tool_use",
            )
        if tool_name == "remote_project_prep":
            metadata = set_workflow_step_evidence(
                metadata,
                step,
                dependency_install_attempted=True,
                project_prep_completed=True,
                completion_source="model_tool_use",
            )

    if workflow_step_id == "step_7_gpu_execution" and tool_name in {"ssh_execute", "claw_shell_run"}:
        metadata = ensure_memory(metadata)
        workflow_results = dict(metadata.get("workflow_results") or {})
        workflow_results["smoke_test_metrics"] = {
            "status": "passed",
            "exit_code": result_metadata.get("exit_code"),
            "stdout_tail": str(result_metadata.get("stdout") or "")[-2000:],
            "stderr_tail": str(result_metadata.get("stderr") or "")[-2000:],
        }
        metadata["workflow_results"] = workflow_results
        metadata = set_workflow_step_evidence(
            metadata,
            step,
            gpu_ssh_probe_completed=True,
            gpu_workspace_verified=True,
            gpu_runtime_env_configured=True,
            smoke_test_executed=True,
            env_patches_recorded=True,
            completion_source="model_tool_use",
        )

    if tool_name == "repro_report":
        report_path = str(result_metadata.get("report_path") or "")
        metadata = ensure_memory(metadata)
        workflow_results = dict(metadata.get("workflow_results") or {})
        workflow_results["word_report_path"] = report_path
        metadata["workflow_results"] = workflow_results
        metadata = set_workflow_step_evidence(
            metadata,
            step,
            report_generated=bool(report_path),
            report_path=report_path,
            completion_source="model_tool_use",
        )
        if report_path:
            metadata = add_workflow_step_artifact(metadata, step, report_path)
            metadata = remember_artifact(metadata, f"复现报告：{report_path}")

    return metadata


def _workflow_step_ref(metadata: dict, workflow_step_id: str) -> WorkflowStep:
    state = workflow_step_state(metadata, workflow_step_id)
    depends_on = state.get("depends_on") if isinstance(state.get("depends_on"), list) else []
    return WorkflowStep(
        id=workflow_step_id,
        name=str(state.get("name") or workflow_step_id),
        depends_on=[str(item) for item in depends_on],
        expected_output=str(state.get("expected_output") or ""),
    )


def _resource_kind_for_tool(workflow_step_id: str, tool_input: dict[str, object]) -> str | None:
    explicit = str(tool_input.get("resource_kind") or "").upper()
    if explicit in {"CPU", "GPU"}:
        return explicit
    if workflow_step_id in {"step_3_deploy_cpu", "step_5_release_cpu"}:
        return "CPU"
    if workflow_step_id in {"step_6_deploy_gpu", "step_9_release_gpu"}:
        return "GPU"
    return None


def _prepare_model_tool_input(
    tool_name: str,
    tool_input: dict[str, object],
    metadata: dict,
    workflow_step_id: str | None,
) -> dict[str, object]:
    tool_name = _canonical_tool_name(tool_name)
    payload = dict(tool_input)
    if tool_name in {"ssh_execute", "remote_project_prep"}:
        payload = _strip_sensitive_skill_connection_fields(payload)
    if not workflow_step_id:
        return _render_templates(payload, metadata)

    _set_if_missing_or_template(payload, "workflow_step_id", workflow_step_id)
    if tool_name not in {
        "ssh_execute",
        "remote_project_prep",
        "file_write",
        "file_system_read",
        "file_system_list",
    }:
        return _render_templates(payload, metadata)

    if workflow_step_id == "step_4_cpu_env_setup":
        _set_if_missing_or_template(payload, "resource_kind", "CPU")
        server_id = _workflow_resource_server_id(metadata, "cpu")
        if server_id:
            _set_if_missing_or_template(payload, "server_id", server_id)
        if tool_name == "ssh_execute":
            payload = _compile_skill_ssh_payload(payload)
    elif workflow_step_id == "step_7_gpu_execution":
        _set_if_missing_or_template(payload, "resource_kind", "GPU")
        server_id = _workflow_resource_server_id(metadata, "gpu")
        if server_id:
            _set_if_missing_or_template(payload, "server_id", server_id)
        if tool_name == "ssh_execute":
            payload = _compile_skill_ssh_payload(payload)
    return _render_templates(payload, metadata)


def _strip_sensitive_skill_connection_fields(payload: dict[str, object]) -> dict[str, object]:
    result = dict(payload)
    for key in ("ssh_pass", "ssh_password", "password"):
        result.pop(key, None)
    return result


def _compile_skill_ssh_payload(payload: dict[str, object]) -> dict[str, object]:
    command = str(payload.get("command") or "")
    compiled = _remote_command_from_skill_ssh_wrapper(command)
    if compiled is None and not _looks_like_ssh_wrapper(command):
        return payload
    result = dict(payload)
    if compiled is None:
        if _contains_unrendered_template(command):
            return payload
        result["_adapter_error"] = (
            "检测到 SSH/sshpass wrapper，但没有可安全提取的远程命令"
        )
        return result
    result["command"] = compiled
    result.setdefault("connect_retries", 30)
    result.setdefault("connect_retry_interval", 10)
    return result


def _remote_command_from_skill_ssh_wrapper(command: str) -> str | None:
    if not _looks_like_ssh_wrapper(command):
        return None
    remote_commands = _extract_remote_ssh_commands(command)
    if not remote_commands:
        return None
    meaningful = [
        item
        for item in remote_commands
        if not re.fullmatch(r"\s*echo\b.*", item, flags=re.IGNORECASE | re.DOTALL)
    ]
    return (meaningful or remote_commands)[-1].strip()


def _looks_like_ssh_wrapper(command: str) -> bool:
    return bool(re.search(r"\bsshpass\b|\bssh\b[^\n;|&]*@", command))


def _extract_remote_ssh_commands(command: str) -> list[str]:
    results: list[str] = []
    pattern = re.compile(r"\bssh\b")
    position = 0
    while True:
        match = pattern.search(command, position)
        if match is None:
            break
        at_index = command.find("@", match.end())
        if at_index == -1:
            break
        quote_start = _find_remote_command_quote(command, at_index)
        if quote_start is None:
            position = match.end()
            continue
        quote = command[quote_start]
        quote_end = _find_unescaped_quote(command, quote_start + 1, quote)
        if quote_end is None:
            break
        results.append(command[quote_start + 1 : quote_end])
        position = quote_end + 1
    return results


def _find_remote_command_quote(command: str, start: int) -> int | None:
    position = start
    while position < len(command):
        char = command[position]
        if char in {'"', "'"}:
            return position
        if char in ";&|\n":
            return None
        position += 1
    return None


def _find_unescaped_quote(command: str, start: int, quote: str) -> int | None:
    escaped = False
    for index in range(start, len(command)):
        char = command[index]
        if escaped:
            escaped = False
            continue
        if char == "\\":
            escaped = True
            continue
        if char == quote:
            return index
    return None


def _render_templates(value: object, metadata: dict) -> object:
    context = _template_context(metadata)
    if isinstance(value, str):
        return _render_template_string(value, context)
    if isinstance(value, dict):
        return {key: _render_templates(item, metadata) for key, item in value.items()}
    if isinstance(value, list):
        return [_render_templates(item, metadata) for item in value]
    if isinstance(value, tuple):
        return tuple(_render_templates(item, metadata) for item in value)
    return value


def _render_template_string(value: str, context: dict[str, object]) -> str:
    def replace(match: re.Match[str]) -> str:
        key = match.group(1).strip()
        if key not in context:
            return match.group(0)
        return str(context[key])

    return re.sub(r"\{\{\s*([^}]+?)\s*\}\}", replace, value)


def _template_context(metadata: dict) -> dict[str, object]:
    github_url = str(metadata.get("github_url") or "")
    paper_url = str(metadata.get("paper_url") or "")
    repo_name = _repo_name_from_url(github_url or "project")
    context: dict[str, object] = {
        "github_url": github_url,
        "paper_url": paper_url,
        "parameters.github_url": github_url,
        "parameters.paper_url": paper_url,
        "repo_name": repo_name,
        "repo_name_underscore": re.sub(r"\W+", "_", repo_name).strip("_") or "project",
    }
    _add_step_resource_context(context, "step_3", metadata, "cpu")
    _add_step_resource_context(context, "step_3_deploy_cpu", metadata, "cpu")
    _add_step_resource_context(context, "step_6", metadata, "gpu")
    _add_step_resource_context(context, "step_6_deploy_gpu", metadata, "gpu")
    return context


def _add_step_resource_context(
    context: dict[str, object],
    prefix: str,
    metadata: dict,
    kind: str,
) -> None:
    resources = metadata.get("workflow_resources")
    resource = (resources or {}).get(kind) if isinstance(resources, dict) else None
    if not isinstance(resource, dict):
        return
    raw = resource.get("raw") if isinstance(resource.get("raw"), dict) else {}
    values = {
        "server_id": resource.get("server_id") or raw.get("server_id"),
        "serverId": resource.get("server_id") or raw.get("server_id"),
        "ssh_host": raw.get("ssh_host"),
        "ssh_port": raw.get("ssh_port"),
        "ssh_user": raw.get("ssh_user") or "root",
    }
    for key, value in values.items():
        if value not in (None, ""):
            context[f"{prefix}.{key}"] = value


def _repo_name_from_url(url: str) -> str:
    value = url.rstrip("/").split("/")[-1]
    if value.endswith(".git"):
        value = value[:-4]
    return re.sub(r"[^A-Za-z0-9_.-]+", "-", value).strip("-") or "project"


def _set_if_missing_or_template(
    payload: dict[str, object],
    key: str,
    value: object | None,
) -> None:
    if value is None:
        return
    current = payload.get(key)
    if current is None or str(current).strip() == "" or _contains_unrendered_template(current):
        payload[key] = value


def _workflow_resource_server_id(metadata: dict, kind: str) -> str | None:
    resources = metadata.get("workflow_resources")
    resource = (resources or {}).get(kind) if isinstance(resources, dict) else None
    if not isinstance(resource, dict):
        return None
    server_id = resource.get("server_id")
    return str(server_id) if server_id else None


def _contains_unrendered_template(value: object) -> bool:
    if isinstance(value, str):
        return bool(re.search(r"\{\{\s*[^}]+\s*\}\}", value))
    if isinstance(value, dict):
        return any(_contains_unrendered_template(item) for item in value.values())
    if isinstance(value, (list, tuple, set)):
        return any(_contains_unrendered_template(item) for item in value)
    return False


def _assistant_tool_message(response: LLMToolResponse) -> dict:
    raw_content = _raw_assistant_content(response.raw)
    if raw_content:
        return {"role": "assistant", "content": raw_content}

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


def _raw_assistant_content(raw: dict[str, object]) -> list[dict] | None:
    content = raw.get("content") if isinstance(raw, dict) else None
    if not isinstance(content, list):
        return None
    blocks = [dict(item) for item in content if isinstance(item, dict)]
    if not blocks:
        return None
    return blocks


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
