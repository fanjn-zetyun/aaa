"""Structured per-conversation memory stored inside Conversation.metadata."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4
from typing import Any

from app.services.tools import TOOL_CONFIRM_STEP_PREFIX

WORKFLOW_IDLE = "idle"
WORKFLOW_RUNNING = "running"
WORKFLOW_WAITING_FOR_USER = "waiting_for_user"
WORKFLOW_COMPLETED = "completed"
WORKFLOW_FAILED = "failed"
WORKFLOW_STOPPED = "stopped"

CONFIRM_RESOURCE_STEP = f"{TOOL_CONFIRM_STEP_PREFIX}lab4ai_create_instance"

DECISION_APPROVED = "approved"
DECISION_NEEDS_REVISION = "needs_revision"
DECISION_REJECTED = "rejected"
DECISION_STOPPED = "stopped"

COMPACT_TRIGGER_MESSAGES = 24
COMPACT_KEEP_RECENT_MESSAGES = 12


def ensure_memory(metadata: dict[str, Any] | None) -> dict[str, Any]:
    result = dict(metadata or {})
    memory = dict(result.get("memory") or {})
    memory.setdefault("summary", "")
    memory.setdefault("facts", [])
    memory.setdefault("decisions", [])
    memory.setdefault("open_questions", [])
    memory.setdefault("artifacts", [])
    memory.setdefault("last_compacted_at", None)
    memory.setdefault("compacted_through_message_id", None)
    memory.setdefault("compaction_count", 0)
    result["memory"] = memory
    result.setdefault("workflow_state", WORKFLOW_IDLE)
    result.setdefault("workflow_run_id", None)
    result.setdefault("pending_user_input", None)
    return result


def build_memory_context(metadata: dict[str, Any]) -> str:
    metadata = ensure_memory(metadata)
    memory = metadata["memory"]
    sections = ["对话结构化记忆："]
    if memory.get("summary"):
        sections.append(f"- 摘要：{memory['summary']}")
    for key, label in (
        ("facts", "已确认事实"),
        ("decisions", "用户决策"),
        ("open_questions", "待回答问题"),
        ("artifacts", "产物与资源"),
    ):
        values = memory.get(key) or []
        if values:
            sections.append(f"- {label}：")
            sections.extend(f"  - {_format_memory_item(item)}" for item in values[-8:])
    pending = metadata.get("pending_user_input")
    if pending:
        sections.append(f"- 当前等待用户：{pending.get('question', '')}")
    return "\n".join(sections)


def mark_running(metadata: dict[str, Any]) -> dict[str, Any]:
    result = ensure_memory(metadata)
    result["workflow_state"] = WORKFLOW_RUNNING
    result["workflow_run_id"] = str(uuid4())
    result["pending_user_input"] = None
    return result


def mark_idle(metadata: dict[str, Any]) -> dict[str, Any]:
    result = ensure_memory(metadata)
    result["workflow_state"] = WORKFLOW_IDLE
    result["pending_user_input"] = None
    return result


def mark_completed(metadata: dict[str, Any]) -> dict[str, Any]:
    result = ensure_memory(metadata)
    result["workflow_state"] = WORKFLOW_COMPLETED
    result["pending_user_input"] = None
    return result


def mark_failed(metadata: dict[str, Any]) -> dict[str, Any]:
    result = ensure_memory(metadata)
    result["workflow_state"] = WORKFLOW_FAILED
    return result


def mark_stopped(metadata: dict[str, Any]) -> dict[str, Any]:
    result = ensure_memory(metadata)
    result["workflow_state"] = WORKFLOW_STOPPED
    result["pending_user_input"] = None
    return result


def mark_waiting_for_user(
    metadata: dict[str, Any],
    *,
    question: str,
    options: list[str],
    step: str,
    tool_name: str | None = None,
    tool_input: dict[str, Any] | None = None,
) -> dict[str, Any]:
    result = ensure_memory(metadata)
    result["workflow_state"] = WORKFLOW_WAITING_FOR_USER
    pending = {
        "question": question,
        "options": options,
        "step": step,
        "asked_at": _now(),
        "run_id": result.get("workflow_run_id"),
    }
    if tool_name:
        pending["tool_name"] = tool_name
        pending["tool_input"] = dict(tool_input or {})
    result["pending_user_input"] = pending
    memory = result["memory"]
    open_questions = list(memory.get("open_questions") or [])
    open_questions.append(pending)
    memory["open_questions"] = open_questions
    return result


def resolve_pending_user_input(
    metadata: dict[str, Any],
    *,
    answer: str,
) -> dict[str, Any]:
    result = ensure_memory(metadata)
    pending = result.get("pending_user_input")
    if not pending:
        return mark_running(result)

    outcome = classify_user_decision(answer)
    decision = {
        "step": pending.get("step"),
        "question": pending.get("question"),
        "answer": answer,
        "outcome": outcome,
        "answered_at": _now(),
        "run_id": pending.get("run_id"),
    }
    if pending.get("tool_name"):
        decision["tool_name"] = pending.get("tool_name")
        decision["tool_input"] = pending.get("tool_input") or {}
    memory = result["memory"]
    memory["decisions"] = [*(memory.get("decisions") or []), decision]
    memory["open_questions"] = [
        item
        for item in (memory.get("open_questions") or [])
        if not (
            isinstance(item, dict)
            and item.get("step") == pending.get("step")
            and item.get("question") == pending.get("question")
        )
    ]
    result["pending_user_input"] = None
    result["workflow_state"] = WORKFLOW_RUNNING
    return result


def has_decision(metadata: dict[str, Any], step: str) -> bool:
    memory = ensure_memory(metadata)["memory"]
    return any(
        isinstance(item, dict) and item.get("step") == step
        for item in (memory.get("decisions") or [])
    )


def has_approved_decision(metadata: dict[str, Any], step: str) -> bool:
    return get_latest_decision_outcome(metadata, step) == DECISION_APPROVED


def get_latest_decision_outcome(metadata: dict[str, Any], step: str) -> str | None:
    result = ensure_memory(metadata)
    memory = result["memory"]
    run_id = result.get("workflow_run_id")
    for item in reversed(memory.get("decisions") or []):
        if (
            isinstance(item, dict)
            and item.get("step") == step
            and (run_id is None or item.get("run_id") == run_id)
        ):
            return str(item.get("outcome") or "")
    return None


def classify_user_decision(answer: str) -> str:
    lowered = answer.strip().lower()
    if not lowered:
        return DECISION_NEEDS_REVISION
    if any(key in lowered for key in ("停止", "中止", "取消", "stop", "cancel")):
        return DECISION_STOPPED
    if any(key in lowered for key in ("继续", "确认", "同意", "批准", "可以", "执行", "yes", "ok")):
        return DECISION_APPROVED
    if any(key in lowered for key in ("不要", "不执行", "否", "拒绝", "deny", "no")):
        return DECISION_REJECTED
    return DECISION_NEEDS_REVISION


def remember_fact(metadata: dict[str, Any], fact: str) -> dict[str, Any]:
    result = ensure_memory(metadata)
    memory = result["memory"]
    facts = list(memory.get("facts") or [])
    if fact not in facts:
        facts.append(fact)
    memory["facts"] = facts
    return result


def remember_artifact(metadata: dict[str, Any], artifact: str) -> dict[str, Any]:
    result = ensure_memory(metadata)
    memory = result["memory"]
    artifacts = list(memory.get("artifacts") or [])
    if artifact not in artifacts:
        artifacts.append(artifact)
    memory["artifacts"] = artifacts
    return result


def compact_memory_from_messages(
    metadata: dict[str, Any],
    messages: list[Any],
    *,
    trigger_messages: int = COMPACT_TRIGGER_MESSAGES,
    keep_recent_messages: int = COMPACT_KEEP_RECENT_MESSAGES,
) -> tuple[dict[str, Any], bool]:
    """Summarize old transcript messages into structured memory.

    The full DB transcript remains intact. Compaction only affects what the
    agent injects into the model context on later turns.
    """

    result = ensure_memory(metadata)
    if len(messages) <= trigger_messages:
        return result, False

    memory = result["memory"]
    compacted_through = memory.get("compacted_through_message_id")
    candidates = [
        item
        for item in messages
        if getattr(item, "id", 0) and (
            compacted_through is None or getattr(item, "id", 0) > compacted_through
        )
    ]
    if len(candidates) <= keep_recent_messages:
        return result, False

    to_compact = candidates[:-keep_recent_messages]
    if not to_compact:
        return result, False

    previous_summary = str(memory.get("summary") or "").strip()
    summary = _summarize_messages(to_compact)
    if previous_summary:
        memory["summary"] = f"{previous_summary}\n{summary}"
    else:
        memory["summary"] = summary
    memory["last_compacted_at"] = _now()
    memory["compacted_through_message_id"] = getattr(to_compact[-1], "id", None)
    memory["compaction_count"] = int(memory.get("compaction_count") or 0) + 1
    return result, True


def _format_memory_item(item: Any) -> str:
    if isinstance(item, dict):
        parts = []
        for key in ("step", "question", "answer", "value"):
            if item.get(key):
                parts.append(f"{key}={item[key]}")
        return "; ".join(parts) or str(item)
    return str(item)


def _summarize_messages(messages: list[Any]) -> str:
    user_items: list[str] = []
    assistant_items: list[str] = []
    tool_items: list[str] = []
    system_items: list[str] = []

    for msg in messages:
        role = getattr(getattr(msg, "role", ""), "value", getattr(msg, "role", ""))
        content = _truncate(str(getattr(msg, "content", "") or ""), 160)
        if not content:
            continue
        if role == "user":
            user_items.append(content)
        elif role == "assistant":
            assistant_items.append(content)
        elif role == "tool":
            tool_name = (getattr(msg, "message_metadata", {}) or {}).get("tool_name", "tool")
            tool_items.append(f"{tool_name}: {content}")
        else:
            system_items.append(content)

    parts = [f"[压缩上下文 {datetime.now(UTC).strftime('%Y-%m-%d %H:%M:%S UTC')}]"]
    if user_items:
        parts.append("用户输入：" + " | ".join(user_items[-4:]))
    if assistant_items:
        parts.append("助手回复：" + " | ".join(assistant_items[-4:]))
    if tool_items:
        parts.append("工具结果：" + " | ".join(tool_items[-6:]))
    if system_items:
        parts.append("系统事件：" + " | ".join(system_items[-3:]))
    return "\n".join(parts)


def _truncate(text: str, limit: int) -> str:
    compacted = " ".join(text.split())
    if len(compacted) <= limit:
        return compacted
    return compacted[: limit - 1] + "..."


def _now() -> str:
    return datetime.now(UTC).isoformat()
