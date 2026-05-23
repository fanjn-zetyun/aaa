from app.agent_runtime.recovery import RecoveryPolicy
from app.agent_runtime.state import RuntimeState


def test_recovery_policy_allows_bounded_retry_for_step_failure():
    state = RuntimeState.new(conversation_id=1, model="claude-test")
    state.active_workflow = {
        "current_step_id": "step_7_gpu_execution",
        "recovery_attempts": {"step_7_gpu_execution": 1},
    }

    decision = RecoveryPolicy(max_attempts=3).decide(state, retryable=True)

    assert decision.action == "retry"
    assert decision.next_attempt == 2


def test_recovery_policy_escalates_after_max_attempts():
    state = RuntimeState.new(conversation_id=1, model="claude-test")
    state.active_workflow = {
        "current_step_id": "step_7_gpu_execution",
        "recovery_attempts": {"step_7_gpu_execution": 3},
    }

    decision = RecoveryPolicy(max_attempts=3).decide(state, retryable=True)

    assert decision.action == "hitl"
    assert decision.reason == "recovery_attempts_exhausted"
