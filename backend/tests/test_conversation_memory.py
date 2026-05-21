from __future__ import annotations

from types import SimpleNamespace

from app.services.conversation_memory import (
    CONFIRM_RESOURCE_STEP,
    DECISION_APPROVED,
    DECISION_NEEDS_REVISION,
    DECISION_STOPPED,
    classify_user_decision,
    compact_memory_from_messages,
    WORKFLOW_WAITING_FOR_USER,
    build_memory_context,
    ensure_memory,
    has_approved_decision,
    mark_running,
    mark_waiting_for_user,
    resolve_pending_user_input,
)


def test_waiting_question_is_resolved_into_decision():
    metadata = ensure_memory({"task_type": "reproduce"})
    metadata = mark_waiting_for_user(
        metadata,
        question="是否继续创建实例？",
        options=["继续执行", "停止任务"],
        step=CONFIRM_RESOURCE_STEP,
    )

    assert metadata["workflow_state"] == WORKFLOW_WAITING_FOR_USER
    assert metadata["pending_user_input"]["question"] == "是否继续创建实例？"

    metadata = resolve_pending_user_input(metadata, answer="继续执行")

    assert metadata["pending_user_input"] is None
    assert has_approved_decision(metadata, CONFIRM_RESOURCE_STEP)
    assert metadata["memory"]["open_questions"] == []
    assert metadata["memory"]["decisions"][0]["answer"] == "继续执行"
    assert metadata["memory"]["decisions"][0]["outcome"] == DECISION_APPROVED


def test_memory_context_includes_summary_and_pending_question():
    metadata = ensure_memory({})
    metadata["memory"]["summary"] = "复现 demo 仓库"
    metadata = mark_waiting_for_user(
        metadata,
        question="是否继续？",
        options=["继续"],
        step=CONFIRM_RESOURCE_STEP,
    )

    context = build_memory_context(metadata)

    assert "复现 demo 仓库" in context
    assert "是否继续？" in context


def test_user_decision_classifier_covers_common_responses():
    assert classify_user_decision("继续执行") == DECISION_APPROVED
    assert classify_user_decision("先修改方案") == DECISION_NEEDS_REVISION
    assert classify_user_decision("停止任务") == DECISION_STOPPED


def test_tool_confirmation_decisions_are_scoped_to_current_run():
    metadata = mark_running(ensure_memory({"task_type": "reproduce"}))
    metadata = mark_waiting_for_user(
        metadata,
        question="是否继续创建实例？",
        options=["继续执行", "停止任务"],
        step=CONFIRM_RESOURCE_STEP,
    )
    metadata = resolve_pending_user_input(metadata, answer="继续执行")

    assert has_approved_decision(metadata, CONFIRM_RESOURCE_STEP)

    metadata = mark_running(metadata)

    assert not has_approved_decision(metadata, CONFIRM_RESOURCE_STEP)


def test_tool_confirmation_decisions_can_be_scoped_to_tool_call_id():
    metadata = mark_running(ensure_memory({"task_type": "reproduce"}))
    metadata = mark_waiting_for_user(
        metadata,
        question="是否继续创建实例？",
        options=["继续执行", "停止任务"],
        step=CONFIRM_RESOURCE_STEP,
        tool_name="lab4ai_create_instance",
        tool_input={"workflow_step_id": "step_3_deploy_cpu"},
        tool_call_id="tool-call-1",
        workflow_step_id="step_3_deploy_cpu",
    )

    assert metadata["pending_user_input"]["tool_call_id"] == "tool-call-1"
    assert metadata["pending_user_input"]["workflow_step_id"] == "step_3_deploy_cpu"

    metadata = resolve_pending_user_input(metadata, answer="继续执行")

    assert has_approved_decision(
        metadata,
        CONFIRM_RESOURCE_STEP,
        tool_call_id="tool-call-1",
    )
    assert not has_approved_decision(
        metadata,
        CONFIRM_RESOURCE_STEP,
        tool_call_id="tool-call-2",
    )


def test_waiting_question_can_carry_structured_intervention():
    metadata = mark_running(ensure_memory({"task_type": "reproduce"}))
    metadata = mark_waiting_for_user(
        metadata,
        question="Lab4AI 凭证未配置，请先由管理员配置平台账号。",
        options=["已完成配置，继续执行", "停止任务"],
        step="admin_config:lab4ai:lab4ai_create_instance",
        tool_name="lab4ai_create_instance",
        tool_input={"workflow_step_id": "step_3_deploy_cpu"},
        intervention={"type": "lab4ai_credentials_required"},
    )

    pending = metadata["pending_user_input"]

    assert pending["intervention"]["type"] == "lab4ai_credentials_required"
    assert metadata["memory"]["open_questions"][0]["intervention"]["type"] == (
        "lab4ai_credentials_required"
    )


def test_memory_compaction_summarizes_old_messages():
    metadata = ensure_memory({"task_type": "reproduce"})
    messages = [
        SimpleNamespace(
            id=index,
            role="user" if index % 3 == 1 else "assistant" if index % 3 == 2 else "tool",
            content=f"message-{index}",
            message_metadata={"tool_name": "ssh_execute"} if index % 3 == 0 else {},
        )
        for index in range(1, 31)
    ]

    compacted, changed = compact_memory_from_messages(
        metadata,
        messages,
        trigger_messages=10,
        keep_recent_messages=4,
    )

    assert changed is True
    assert compacted["memory"]["compaction_count"] == 1
    assert compacted["memory"]["compacted_through_message_id"] == 26
    assert "压缩上下文" in compacted["memory"]["summary"]
    assert "message-1" in compacted["memory"]["summary"]
