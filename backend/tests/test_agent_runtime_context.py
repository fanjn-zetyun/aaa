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


def test_context_builder_includes_instruction_checklist_and_allowlist():
    state = RuntimeState.new(conversation_id=1, model="claude-test")
    state.allowed_tools = ["ssh_execute", "ask_user"]
    state.active_workflow = {
        "current_step_id": "step_7_gpu_execution",
        "steps": {
            "step_7_gpu_execution": {
                "instruction": "Run GPU smoke test.",
                "expected_output": "GPU smoke evidence.",
                "required_evidence": ["inline_cuda_smoke"],
            }
        },
    }
    state.instruction_plans = {
        "step_7_gpu_execution": {
            "items": [
                {"id": "import_precheck", "text": "Run import precheck.", "status": "pending"},
                {
                    "id": "entrypoint_detection",
                    "text": "Find entrypoint.",
                    "status": "completed",
                },
            ]
        }
    }

    context = ContextBuilder().build_system_prompt(state)

    assert "Only call tools from the current allowed tool list" in context
    assert "Allowed tools: ssh_execute, ask_user" in context
    assert "[pending] import_precheck: Run import precheck." in context
    assert "Required evidence: inline_cuda_smoke" in context
