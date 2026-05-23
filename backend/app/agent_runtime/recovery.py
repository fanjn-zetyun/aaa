from __future__ import annotations

from dataclasses import dataclass

from app.agent_runtime.state import RuntimeState


@dataclass(slots=True)
class RecoveryDecision:
    action: str
    reason: str
    next_attempt: int


class RecoveryPolicy:
    def __init__(self, *, max_attempts: int = 3) -> None:
        self.max_attempts = max_attempts

    def decide(self, state: RuntimeState, *, retryable: bool) -> RecoveryDecision:
        if not retryable:
            return RecoveryDecision(action="hitl", reason="not_retryable", next_attempt=0)
        workflow = state.active_workflow or {}
        step_id = str(workflow.get("current_step_id") or "")
        attempts = workflow.get("recovery_attempts") or {}
        current = int(attempts.get(step_id) or 0)
        if current >= self.max_attempts:
            return RecoveryDecision(
                action="hitl",
                reason="recovery_attempts_exhausted",
                next_attempt=current,
            )
        return RecoveryDecision(action="retry", reason="retryable", next_attempt=current + 1)
