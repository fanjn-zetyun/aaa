from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, cast
from uuid import uuid4


RuntimeStatus = Literal["running", "waiting_for_user", "stopping", "completed", "failed", "stopped"]


@dataclass(slots=True)
class RuntimeState:
    run_id: str
    conversation_id: int
    status: RuntimeStatus
    model: str
    max_turns: int = 8
    turn_count: int = 0
    active_skill: dict[str, Any] | None = None
    active_workflow: dict[str, Any] | None = None
    allowed_tools: list[str] = field(default_factory=lambda: ["skill.invoke", "ask_user"])
    pending_tool_call: dict[str, Any] | None = None
    pending_user_input: dict[str, Any] | None = None
    token_budget: dict[str, int] = field(default_factory=lambda: {"planning": 2048, "final": 8192})
    cleanup_required: bool = False
    instruction_plans: dict[str, Any] = field(default_factory=dict)
    instruction_failures: dict[str, list[str]] = field(default_factory=dict)
    last_tool_results: list[dict[str, Any]] = field(default_factory=list)

    @classmethod
    def new(cls, *, conversation_id: int, model: str) -> RuntimeState:
        return cls(
            run_id=f"runtime-{uuid4().hex}",
            conversation_id=conversation_id,
            status="running",
            model=model,
        )

    def can_continue(self) -> bool:
        return self.status == "running" and self.turn_count < self.max_turns

    def next_turn(self) -> RuntimeState:
        return RuntimeState(
            run_id=self.run_id,
            conversation_id=self.conversation_id,
            status=self.status,
            model=self.model,
            max_turns=self.max_turns,
            turn_count=self.turn_count + 1,
            active_skill=self.active_skill,
            active_workflow=self.active_workflow,
            allowed_tools=list(self.allowed_tools),
            pending_tool_call=self.pending_tool_call,
            pending_user_input=self.pending_user_input,
            token_budget=dict(self.token_budget),
            cleanup_required=self.cleanup_required,
            instruction_plans=dict(self.instruction_plans),
            instruction_failures={
                str(key): list(value) for key, value in self.instruction_failures.items()
            },
            last_tool_results=[dict(item) for item in self.last_tool_results],
        )

    def mark_waiting_for_user(
        self,
        *,
        pending_tool_call: dict[str, Any],
        pending_user_input: dict[str, Any],
    ) -> RuntimeState:
        updated = self.next_turn()
        updated.status = "waiting_for_user"
        updated.pending_tool_call = dict(pending_tool_call)
        updated.pending_user_input = dict(pending_user_input)
        return updated

    def to_metadata(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "conversation_id": self.conversation_id,
            "status": self.status,
            "model": self.model,
            "max_turns": self.max_turns,
            "turn_count": self.turn_count,
            "active_skill": self.active_skill,
            "active_workflow": self.active_workflow,
            "allowed_tools": list(self.allowed_tools),
            "pending_tool_call": self.pending_tool_call,
            "pending_user_input": self.pending_user_input,
            "token_budget": dict(self.token_budget),
            "cleanup_required": self.cleanup_required,
            "instruction_plans": dict(self.instruction_plans),
            "instruction_failures": {
                str(key): list(value) for key, value in self.instruction_failures.items()
            },
            "last_tool_results": [dict(item) for item in self.last_tool_results],
        }


def save_runtime_state(metadata: dict[str, Any], state: RuntimeState) -> dict[str, Any]:
    updated = dict(metadata)
    updated["runtime"] = state.to_metadata()
    updated["runtime_run_id"] = state.run_id
    updated["runtime_state"] = state.status
    return updated


def load_runtime_state(metadata: dict[str, Any], *, conversation_id: int) -> RuntimeState:
    raw = metadata.get("runtime")
    if not isinstance(raw, dict):
        return RuntimeState.new(conversation_id=conversation_id, model="")
    return RuntimeState(
        run_id=str(raw.get("run_id") or f"runtime-{uuid4().hex}"),
        conversation_id=int(raw.get("conversation_id") or conversation_id),
        status=cast(RuntimeStatus, str(raw.get("status") or "running")),
        model=str(raw.get("model") or ""),
        max_turns=int(raw.get("max_turns") or 8),
        turn_count=int(raw.get("turn_count") or 0),
        active_skill=raw.get("active_skill") if isinstance(raw.get("active_skill"), dict) else None,
        active_workflow=raw.get("active_workflow") if isinstance(raw.get("active_workflow"), dict) else None,
        allowed_tools=[
            str(item) for item in raw.get("allowed_tools") or ["skill.invoke", "ask_user"]
        ],
        pending_tool_call=raw.get("pending_tool_call")
        if isinstance(raw.get("pending_tool_call"), dict)
        else None,
        pending_user_input=raw.get("pending_user_input")
        if isinstance(raw.get("pending_user_input"), dict)
        else None,
        token_budget=dict(raw.get("token_budget") or {"planning": 2048, "final": 8192}),
        cleanup_required=bool(raw.get("cleanup_required") or False),
        instruction_plans=dict(raw.get("instruction_plans") or {}),
        instruction_failures={
            str(key): [str(item) for item in value]
            for key, value in dict(raw.get("instruction_failures") or {}).items()
            if isinstance(value, list)
        },
        last_tool_results=[
            dict(item) for item in raw.get("last_tool_results") or [] if isinstance(item, dict)
        ],
    )
