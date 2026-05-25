from app.core.config import Settings
from app.agent_runtime.state import RuntimeState, load_runtime_state, save_runtime_state


def test_agent_runtime_v3_feature_flag_defaults_to_disabled():
    settings = Settings()

    assert settings.agent_runtime_v3_enabled is False


def test_runtime_state_round_trips_through_conversation_metadata():
    state = RuntimeState.new(conversation_id=42, model="claude-test")
    metadata = save_runtime_state({}, state)

    restored = load_runtime_state(metadata, conversation_id=42)

    assert restored.run_id == state.run_id
    assert restored.conversation_id == 42
    assert restored.status == "running"
    assert restored.allowed_tools == ["skill.invoke", "ask_user"]
    assert metadata["runtime"]["run_id"] == state.run_id


def test_runtime_state_waiting_for_user_stores_pending_tool_call():
    state = RuntimeState.new(conversation_id=7, model="claude-test")
    state = state.mark_waiting_for_user(
        pending_tool_call={
            "tool_call_id": "toolu_1",
            "tool_name": "lab4ai_create_instance",
            "workflow_step_id": "step_3_deploy_cpu",
        },
        pending_user_input={"question": "是否创建 CPU 实例？"},
    )

    metadata = save_runtime_state({}, state)
    restored = load_runtime_state(metadata, conversation_id=7)

    assert restored.status == "waiting_for_user"
    assert restored.pending_tool_call["tool_call_id"] == "toolu_1"
    assert restored.pending_user_input["question"] == "是否创建 CPU 实例？"


def test_runtime_state_persists_instruction_plan():
    state = RuntimeState.new(conversation_id=7, model="claude-test")
    state.instruction_plans = {
        "step_7_gpu_execution": {
            "step_id": "step_7_gpu_execution",
            "items": [{"id": "import_precheck", "status": "pending"}],
        }
    }
    state.instruction_failures = {"step_7_gpu_execution": ["missing instruction item: import_precheck"]}
    state.last_tool_results = [{"name": "ssh_execute", "ok": False}]

    metadata = save_runtime_state({}, state)
    restored = load_runtime_state(metadata, conversation_id=7)

    assert restored.instruction_plans["step_7_gpu_execution"]["items"][0]["id"] == "import_precheck"
    assert restored.instruction_failures["step_7_gpu_execution"] == [
        "missing instruction item: import_precheck"
    ]
    assert restored.last_tool_results == [{"name": "ssh_execute", "ok": False}]
