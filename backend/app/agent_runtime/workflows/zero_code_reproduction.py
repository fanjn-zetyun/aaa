from __future__ import annotations

from typing import Any

from app.agent_runtime.state import RuntimeState


ZERO_CODE_KIND = "zero_code_reproduction_pipeline"


ZERO_CODE_STEPS: list[dict[str, Any]] = [
    {
        "id": "step_0_remote_instance_init",
        "name": "0. 远程实例初始化",
        "phase": "环境",
        "execution_location": "远程",
        "expected_output": "实例ID / SSH信息 / 目录结构",
        "allowed_tools": ["ask_user", "lab4ai_create_instance"],
    },
    {
        "id": "step_1_paper_acquisition_parse",
        "name": "1. 论文获取与解析",
        "phase": "输入",
        "execution_location": "远程",
        "expected_output": "页数 / 字符数 / 章节数",
        "allowed_tools": ["ask_user", "ssh_execute", "file_write"],
    },
    {
        "id": "step_2_domain_routing",
        "name": "2. 学科方向判定",
        "phase": "路由",
        "execution_location": "本地LLM→远程存储",
        "expected_output": "学科 / 实验类型 / 激活插件",
        "allowed_tools": ["ask_user", "ssh_execute", "file_write"],
    },
    {
        "id": "step_3_paper_profile",
        "name": "3. 论文要素提取",
        "phase": "解析",
        "execution_location": "本地LLM→远程存储",
        "expected_output": "Paper Profile (公式/超参/数据集/基线)",
        "allowed_tools": ["ask_user", "ssh_execute", "file_write"],
    },
    {
        "id": "step_4_scaffold_generation",
        "name": "4. 复现产物生成",
        "phase": "生成",
        "execution_location": "本地LLM→远程存储",
        "expected_output": "按方向动态填充",
        "dynamic_output": True,
        "allowed_tools": ["ask_user", "ssh_execute", "file_write"],
    },
    {
        "id": "step_5_quality_check",
        "name": "5. 产物质量检查",
        "phase": "验证",
        "execution_location": "远程",
        "expected_output": "按方向动态填充",
        "dynamic_output": True,
        "allowed_tools": ["ask_user", "ssh_execute"],
    },
    {
        "id": "step_6_package_report",
        "name": "6. 打包与报告",
        "phase": "交付",
        "execution_location": "本地LLM→远程存储",
        "expected_output": "CONFIDENCE_REPORT / README",
        "allowed_tools": ["ask_user", "ssh_execute", "file_write"],
    },
    {
        "id": "step_7_env_data_weights",
        "name": "7. 环境+数据+权重准备",
        "phase": "准备",
        "execution_location": "远程 CPU",
        "expected_output": "requirements.txt / 模型权重 / 数据集",
        "allowed_tools": ["ask_user", "ssh_execute"],
    },
    {
        "id": "step_8_release_cpu",
        "name": "8. 释放 CPU 实例",
        "phase": "释放",
        "execution_location": "远程",
        "expected_output": "CPU 实例关闭 / 算力消耗",
        "allowed_tools": ["ask_user", "lab4ai_stop_instance"],
    },
    {
        "id": "step_9_gpu_validation_training",
        "name": "9. GPU 轻量验证训练",
        "phase": "训练",
        "execution_location": "远程 GPU",
        "expected_output": "训练日志 / loss下降 / checkpoint",
        "allowed_tools": ["ask_user", "lab4ai_create_instance", "ssh_execute"],
    },
    {
        "id": "step_10_release_gpu",
        "name": "10. 释放 GPU 实例",
        "phase": "释放",
        "execution_location": "远程",
        "expected_output": "GPU 实例关闭 / 算力消耗",
        "allowed_tools": ["ask_user", "lab4ai_stop_instance"],
    },
    {
        "id": "step_11_final_docx_report",
        "name": "11. 生成复现报告",
        "phase": "报告",
        "execution_location": "本地",
        "expected_output": ".docx 复现报告",
        "allowed_tools": ["ask_user", "file_write"],
    },
]


def is_zero_code_workflow(raw_workflow: str) -> bool:
    return f"WORKFLOW_KIND: {ZERO_CODE_KIND}" in raw_workflow


def activate_zero_code_workflow(raw_workflow: str, *, state: RuntimeState) -> RuntimeState:
    steps = {item["id"]: _step_state(item) for item in ZERO_CODE_STEPS}
    first_step_id = ZERO_CODE_STEPS[0]["id"]
    steps[first_step_id]["status"] = "waiting_for_user"
    workflow = {
        "kind": ZERO_CODE_KIND,
        "name": ZERO_CODE_KIND,
        "version": "1.0",
        "current_step_id": first_step_id,
        "step_order": [item["id"] for item in ZERO_CODE_STEPS],
        "steps": steps,
        "gate_log": _initial_gate_log(),
        "completion_criteria": [
            "Step 0 must complete before paper download or local file processing.",
            "Steps 8 and 10 must release instances when created.",
            "Final delivery includes reproduction_scaffold and report artifacts.",
        ],
        "resources": {},
        "results": {"workflow_context_loaded": bool(raw_workflow.strip())},
        "status": "waiting_for_user",
    }
    updated = state.mark_waiting_for_user(
        pending_tool_call={
            "tool_call_id": "zero-code:step-0-cpu-instance",
            "tool_name": "ask_user",
            "workflow_step_id": first_step_id,
        },
        pending_user_input={
            "question": "是否创建远程 CPU 实例并开始零代码复现流水线？",
            "options": ["yes", "no"],
            "workflow_step_id": first_step_id,
            "gate": "zero_code_step_0_cpu_instance",
        },
    )
    updated.active_workflow = workflow
    updated.allowed_tools = ["ask_user", "skill.invoke"]
    return updated


def apply_zero_code_user_reply(state: RuntimeState, answer: str) -> RuntimeState:
    workflow = dict(state.active_workflow or {})
    if workflow.get("kind") != ZERO_CODE_KIND:
        return state
    pending = state.pending_user_input or {}
    if pending.get("gate") != "zero_code_step_0_cpu_instance":
        return state

    normalized = _normalize_yes_no(answer)
    if normalized == "yes":
        return _apply_step_zero_yes(state, workflow)
    if normalized == "no":
        return _apply_step_zero_no(state, workflow)
    return state


def _step_state(step: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": step["id"],
        "name": step["name"],
        "status": "pending",
        "phase": step["phase"],
        "execution_location": step["execution_location"],
        "instruction": f"{step['name']}：{step['expected_output']}",
        "expected_output": step["expected_output"],
        "dynamic_output": bool(step.get("dynamic_output") or False),
        "allowed_tools": list(step["allowed_tools"]),
        "required_tools": [],
        "required_effects": [],
        "required_evidence": [],
        "tool_calls": [],
        "evidence": {},
        "artifacts": [],
    }


def _initial_gate_log() -> dict[str, Any]:
    return {
        "step_0_cpu_instance": {
            "value": "unresolved",
            "status": "blocked",
            "evidence": "等待用户确认是否创建远程 CPU 实例",
        },
        "routing": {
            "domain": "unknown",
            "experiment_type": "unknown",
            "activated_plugins": [],
            "status": "pending",
        },
        "next_action": "先确认 Step 0 远程 CPU 实例初始化。",
    }


def _apply_step_zero_yes(state: RuntimeState, workflow: dict[str, Any]) -> RuntimeState:
    steps = dict(workflow.get("steps") or {})
    step_id = str(workflow.get("current_step_id") or "step_0_remote_instance_init")
    step = dict(steps.get(step_id) or {})
    step["status"] = "running"
    step["evidence"] = {**dict(step.get("evidence") or {}), "user_confirmed_cpu_instance": True}
    steps[step_id] = step
    gate_log = dict(workflow.get("gate_log") or {})
    gate_log["step_0_cpu_instance"] = {
        "value": "yes",
        "status": "completed",
        "evidence": "用户确认创建远程 CPU 实例",
    }
    gate_log["next_action"] = "通过受控 Tool 创建 Lab4AI CPU 实例。"
    workflow["gate_log"] = gate_log
    workflow["steps"] = steps
    workflow["status"] = "running"

    updated = state.next_turn()
    updated.status = "running"
    updated.pending_tool_call = None
    updated.pending_user_input = None
    updated.active_workflow = workflow
    updated.allowed_tools = ["ask_user", "lab4ai_create_instance", "skill.invoke"]
    return updated


def _apply_step_zero_no(state: RuntimeState, workflow: dict[str, Any]) -> RuntimeState:
    steps = dict(workflow.get("steps") or {})
    step_id = str(workflow.get("current_step_id") or "step_0_remote_instance_init")
    step = dict(steps.get(step_id) or {})
    step["status"] = "skipped"
    step["evidence"] = {**dict(step.get("evidence") or {}), "user_confirmed_cpu_instance": False}
    steps[step_id] = step
    gate_log = dict(workflow.get("gate_log") or {})
    gate_log["step_0_cpu_instance"] = {
        "value": "no",
        "status": "completed",
        "evidence": "用户取消创建远程 CPU 实例，零代码复现停止",
    }
    gate_log["next_action"] = "任务已停止；未创建计费实例。"
    workflow["gate_log"] = gate_log
    workflow["steps"] = steps
    workflow["status"] = "stopped"

    updated = state.next_turn()
    updated.status = "stopped"
    updated.pending_tool_call = None
    updated.pending_user_input = None
    updated.active_workflow = workflow
    updated.allowed_tools = ["ask_user", "skill.invoke"]
    return updated


def _normalize_yes_no(answer: str) -> str:
    text = answer.strip().lower()
    if text in {"yes", "y", "是", "创建", "创建实例", "需要", "继续", "同意"}:
        return "yes"
    if text in {"no", "n", "否", "不", "不创建", "不需要", "取消", "停止"}:
        return "no"
    return ""
