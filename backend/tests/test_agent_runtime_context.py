from app.agent_runtime.context import ContextBuilder
from app.agent_runtime.state import RuntimeState


def test_context_builder_includes_active_skill_and_workflow_step():
    state = RuntimeState.new(conversation_id=1, model="claude-test")
    state.active_skill = {"name": "demo", "body": "你必须按 demo skill 执行。"}
    state.active_workflow = {
        "current_step_id": "step_1",
        "steps": {
            "step_1": {
                "instruction": "分析仓库。",
                "expected_output": "仓库审计结果。",
                "allowed_tools": ["analyze_repo"],
            }
        },
    }

    context = ContextBuilder().build_system_prompt(state)

    assert "你必须按 demo skill 执行。" in context
    assert "当前 workflow step：step_1" in context
    assert "分析仓库。" in context
