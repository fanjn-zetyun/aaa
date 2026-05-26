from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.agent_runtime.context import ContextBuilder
from app.agent_runtime.events import EventSink, ListEventSink
from app.agent_runtime.llm import LLMAdapter, ModelRequest
from app.agent_runtime.messages import MessageStore
from app.agent_runtime.recovery import RecoveryPolicy
from app.agent_runtime.state import RuntimeState, load_runtime_state, save_runtime_state
from app.agent_runtime.tool_executor import ToolExecutor
from app.agent_runtime.workflows.autoresearch import apply_autoresearch_user_reply
from app.agent_runtime.workflows.zero_code_reproduction import apply_zero_code_user_reply
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

        state = load_runtime_state(conversation.metadata_ or {}, conversation_id=conversation_id)
        if not state.model:
            state.model = model
        if _should_resume_workflow_user_reply(state):
            latest_user = await _latest_user_message(MessageStore(self.session), conversation_id)
            resumed = apply_zero_code_user_reply(
                apply_autoresearch_user_reply(state, latest_user),
                latest_user,
            )
            if resumed is not state:
                state = resumed
                conversation.metadata_ = save_runtime_state(conversation.metadata_ or {}, state)
                conversation.status = ConversationStatus.ACTIVE
                await self.session.commit()
                await self.event_sink.publish(
                    {
                        "type": "workflow_step_updated",
                        "run_id": state.run_id,
                        "workflow_step_id": (state.active_workflow or {}).get("current_step_id"),
                        "workflow": _workflow_event_payload(state),
                    }
                )
                return RuntimeRunResult(
                    status=state.status,
                    final_text="",
                    metadata=conversation.metadata_,
                )
        else:
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
                if state.active_workflow and _current_workflow_step_status(state) != "completed":
                    state = _mark_workflow_text_only_completion_blocked(state)
                    decision = self.recovery_policy.decide(state, retryable=True)
                    if decision.action == "hitl":
                        state = _mark_workflow_recovery_waiting(state, decision.reason)
                        await self.event_sink.publish(
                            {
                                "type": "runtime_waiting_for_user",
                                "run_id": state.run_id,
                                "workflow_step_id": (state.active_workflow or {}).get("current_step_id"),
                                "reason": decision.reason,
                            }
                        )
                        break
                    state = _record_recovery_attempt(state, decision.next_attempt)
                    continue
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
                await self._publish_current_workflow_step(state)
                if _workflow_completed(state):
                    state.status = "completed"
                    final_text = _workflow_completion_report(state)
                    await store.append_assistant(
                        conversation_id,
                        final_text,
                        metadata={
                            "run_id": state.run_id,
                            "workflow_final_report": True,
                        },
                    )
                    break
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

    async def _publish_current_workflow_step(self, state: RuntimeState) -> None:
        workflow = state.active_workflow or {}
        step_id = str(workflow.get("current_step_id") or "")
        steps = workflow.get("steps") if isinstance(workflow.get("steps"), dict) else {}
        step = dict(steps.get(step_id) or {}) if step_id else {}
        if not step:
            return
        plan_id = str(step.get("instruction_plan_id") or step_id)
        instruction_plan = state.instruction_plans.get(plan_id)
        if instruction_plan:
            step["instruction_plan"] = instruction_plan
        await self.event_sink.publish(
            {
                "type": "workflow_step_updated",
                "run_id": state.run_id,
                "workflow_step_id": step_id,
                "step": step,
                "workflow": _workflow_event_payload(state),
            }
        )


def _current_workflow_step_status(state: RuntimeState) -> str:
    workflow = state.active_workflow or {}
    step_id = str(workflow.get("current_step_id") or "")
    steps = workflow.get("steps") if isinstance(workflow.get("steps"), dict) else {}
    step = steps.get(step_id) if step_id else None
    if not isinstance(step, dict):
        return ""
    return str(step.get("status") or "")


def _workflow_completed(state: RuntimeState) -> bool:
    workflow = state.active_workflow or {}
    return str(workflow.get("status") or "") == "completed"


def _workflow_completion_report(state: RuntimeState) -> str:
    workflow = state.active_workflow or {}
    steps = workflow.get("steps") if isinstance(workflow.get("steps"), dict) else {}
    results = workflow.get("results") if isinstance(workflow.get("results"), dict) else {}
    resources = workflow.get("resources") if isinstance(workflow.get("resources"), dict) else {}

    completed_count = sum(
        1 for step in steps.values() if isinstance(step, dict) and step.get("status") == "completed"
    )
    total_count = len(steps)
    lines = [
        "## 结项报告",
        "",
        f"复现 workflow 已按 project_reproduce.yaml 完成全部 {completed_count or total_count} 个步骤。",
    ]

    report_lines = _workflow_report_artifact_lines(results, steps)
    if report_lines:
        lines.extend(["", "交付物：", *report_lines])

    gpu_release = _resource_released(resources, "gpu") or _step_evidence_truthy(
        steps, "step_9_release_gpu", "gpu_instance_released"
    )
    if gpu_release:
        server_id = _resource_server_id(resources, "gpu") or _step_evidence_text(
            steps, "step_9_release_gpu", "server_id"
        )
        release_text = "GPU 实例已释放"
        if server_id:
            release_text += f"：{server_id}"
        lines.extend(["", "资源状态：", f"- {release_text}"])

    return "\n".join(lines)


def _workflow_report_artifact_lines(
    results: dict[str, Any],
    steps: dict[str, Any],
) -> list[str]:
    lines: list[str] = []
    word_report_path = _dict_text(results, "word_report_path")
    remote_report_path = _dict_text(results, "remote_report_path")
    local_report_path = _dict_text(results, "local_report_path")
    markdown_report_path = _dict_text(results, "markdown_report_path")
    report_path = _dict_text(results, "report_path")

    if not word_report_path:
        word_report_path = _step_evidence_text(steps, "step_8_generate_report", "local_report_path")
    if not remote_report_path:
        remote_report_path = _step_evidence_text(steps, "step_8_generate_report", "remote_report_path")
    if not report_path:
        report_path = _step_evidence_text(steps, "step_8_generate_report", "report_path")

    if word_report_path:
        lines.append(f"- Word 报告：{word_report_path}")
    if remote_report_path and remote_report_path not in {word_report_path, report_path}:
        lines.append(f"- 远程报告：{remote_report_path}")
    elif report_path and report_path != word_report_path:
        lines.append(f"- 报告路径：{report_path}")
    if local_report_path and local_report_path != word_report_path:
        lines.append(f"- 本地报告：{local_report_path}")
    if markdown_report_path:
        lines.append(f"- Markdown 预览报告：{markdown_report_path}")

    artifacts = _step_artifacts(steps, "step_8_generate_report")
    for artifact in artifacts:
        if artifact and all(artifact not in line for line in lines):
            lines.append(f"- 关联 artifact：{artifact}")
    return lines


def _resource_released(resources: dict[str, Any], key: str) -> bool:
    resource = resources.get(key)
    return isinstance(resource, dict) and bool(resource.get("released"))


def _resource_server_id(resources: dict[str, Any], key: str) -> str:
    resource = resources.get(key)
    if not isinstance(resource, dict):
        return ""
    return _dict_text(resource, "server_id")


def _step_evidence_truthy(steps: dict[str, Any], step_id: str, key: str) -> bool:
    step = steps.get(step_id)
    if not isinstance(step, dict):
        return False
    evidence = step.get("evidence")
    return isinstance(evidence, dict) and bool(evidence.get(key))


def _step_evidence_text(steps: dict[str, Any], step_id: str, key: str) -> str:
    step = steps.get(step_id)
    if not isinstance(step, dict):
        return ""
    evidence = step.get("evidence")
    if not isinstance(evidence, dict):
        return ""
    return _dict_text(evidence, key)


def _step_artifacts(steps: dict[str, Any], step_id: str) -> list[str]:
    step = steps.get(step_id)
    if not isinstance(step, dict):
        return []
    return [str(item).strip() for item in step.get("artifacts") or [] if str(item).strip()]


def _dict_text(value: dict[str, Any], key: str) -> str:
    return str(value.get(key) or "").strip()


def _record_recovery_attempt(state: RuntimeState, next_attempt: int) -> RuntimeState:
    workflow = dict(state.active_workflow or {})
    step_id = str(workflow.get("current_step_id") or "")
    attempts = dict(workflow.get("recovery_attempts") or {})
    attempts[step_id] = next_attempt
    workflow["recovery_attempts"] = attempts
    updated = state.next_turn()
    updated.active_workflow = workflow
    return updated


def _mark_workflow_text_only_completion_blocked(state: RuntimeState) -> RuntimeState:
    workflow = dict(state.active_workflow or {})
    step_id = str(workflow.get("current_step_id") or "")
    steps = dict(workflow.get("steps") or {})
    step = dict(steps.get(step_id) or {})
    if not step_id or not step:
        return state

    failures = list(step.get("validation_failures") or [])
    text_only_failure = "model text cannot complete workflow step without tool evidence"
    if text_only_failure not in failures:
        failures.append(text_only_failure)

    plan = state.instruction_plans.get(step_id)
    if isinstance(plan, dict):
        missing_items = [
            str(item.get("id"))
            for item in plan.get("items") or []
            if isinstance(item, dict) and item.get("required", True) and item.get("status") != "completed"
        ]
        for item_id in missing_items:
            failure = f"missing instruction checklist item(s): {item_id}"
            if failure not in failures:
                failures.append(failure)

    step["status"] = "recovery"
    step["validation_failures"] = failures
    steps[step_id] = step
    workflow["steps"] = steps

    updated = state.next_turn()
    updated.active_workflow = workflow
    updated.instruction_failures = {
        **state.instruction_failures,
        step_id: [failure for failure in failures if failure.startswith("missing instruction")],
    }
    return updated


def _workflow_event_payload(state: RuntimeState) -> dict[str, Any]:
    workflow = dict(state.active_workflow or {})
    steps = workflow.get("steps") if isinstance(workflow.get("steps"), dict) else {}
    event_steps: list[dict[str, Any]] = []
    for step_id, raw_step in steps.items():
        if not isinstance(raw_step, dict):
            continue
        step = dict(raw_step)
        plan_id = str(step.get("instruction_plan_id") or step_id)
        instruction_plan = state.instruction_plans.get(plan_id)
        if instruction_plan:
            step["instruction_plan"] = instruction_plan
        event_steps.append(step)

    return {
        "name": workflow.get("name"),
        "version": workflow.get("version"),
        "current_step_id": workflow.get("current_step_id"),
        "steps": event_steps,
        "resources": workflow.get("resources") or {},
        "results": workflow.get("results") or {},
    }


def _mark_workflow_recovery_waiting(state: RuntimeState, reason: str) -> RuntimeState:
    workflow_step_id = (state.active_workflow or {}).get("current_step_id")
    return state.mark_waiting_for_user(
        pending_tool_call={
            "tool_call_id": f"recovery:{workflow_step_id}",
            "tool_name": "workflow_recovery",
            "workflow_step_id": workflow_step_id,
        },
        pending_user_input={
            "question": "当前 workflow step 自动恢复次数已耗尽，请补充处理方式。",
            "options": ["继续重试", "停止任务"],
            "reason": reason,
        },
    )


def _should_resume_workflow_user_reply(state: RuntimeState) -> bool:
    workflow = state.active_workflow or {}
    pending = state.pending_user_input or {}
    if state.status != "waiting_for_user":
        return False
    return (workflow.get("kind"), pending.get("gate")) in (
        ("autoresearch_pipeline", "lab_instance_flow"),
        ("zero_code_reproduction_pipeline", "zero_code_step_0_cpu_instance"),
    )


async def _latest_user_message(store: MessageStore, conversation_id: int) -> str:
    messages = await store.list_messages(conversation_id)
    for message in reversed(messages):
        if message.role.value == "user":
            return message.content
    return ""


def _raw_assistant_content(raw: dict[str, Any]) -> list[dict[str, Any]] | None:
    content = raw.get("content") if isinstance(raw, dict) else None
    if not isinstance(content, list):
        return None
    blocks = [dict(item) for item in content if isinstance(item, dict)]
    return blocks or None
