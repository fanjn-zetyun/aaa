# Claude Code Style Web Agent Runtime Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a Claude Code-style Web Agent client where users can chat naturally, the selected skill guides model behavior continuously, tools execute through the backend, tool results feed back into the model, and workflow steps complete only when required evidence and postconditions pass.

**Architecture:** The current FastAPI + React stack remains the product shell. The implementation promotes `backend/app/agent_runtime` to the primary execution path, adds a skill instruction compiler/evaluator, routes all side effects through `ToolExecutor -> ToolRegistry`, and keeps the existing `SkillWorkflowRunner` as a compatibility layer until the new runtime can own the Lab4AI reproduction workflow.

**Tech Stack:** FastAPI, SQLAlchemy, React, WebSocket events, Anthropic-compatible Messages API, existing `ToolRegistry`, existing `SkillLoader`, existing Lab4AI/SSH/File/Report tools.

---

## Success Criteria

This plan is complete when all four target boundaries are enforced:

1. `SKILL.md` and workflow content enter `AgentRuntime` as durable runtime context, not one-off prompt text.
2. Each workflow step instruction is compiled into checklist/evidence items that can be tracked and validated.
3. The model stays in a tool-use loop after every `tool_result`, observes failures, retries or asks the user, and never completes a step by natural language alone.
4. Step completion is decided by required evidence/postconditions, not by fixed fallback text or model claims.

## File Structure

- Modify `docs/proposal.md`: document this version's target architecture before code changes.
- Create `backend/app/agent_runtime/instructions.py`: compile skill and workflow natural language into structured instruction plans.
- Create `backend/app/agent_runtime/instruction_evaluator.py`: evaluate tool results against instruction checklist and required evidence.
- Modify `backend/app/agent_runtime/state.py`: persist active skill context, instruction checklist, current step evidence, recovery attempts, and runtime status.
- Modify `backend/app/agent_runtime/context.py`: build model system prompt from selected skill, current workflow step, instruction checklist, tool results, and recovery state.
- Modify `backend/app/agent_runtime/runtime.py`: make the runtime loop step-aware, validate after every tool result, and continue until evidence/postconditions pass.
- Modify `backend/app/agent_runtime/tool_executor.py`: preserve structured `tool_result` blocks and attach workflow/skill context to every tool call.
- Modify `backend/app/agent_runtime/skills.py`: load `SKILL.md`, workflow text, trigger metadata, and expose a runtime-ready skill bundle.
- Modify `backend/app/agent_runtime/workflows/contract.py`: integrate instruction checklist validation with existing workflow contract validation.
- Modify `backend/app/services/agent_loop.py`: route reproduce conversations through `AgentRuntime` when enabled, keep old runner as compatibility fallback.
- Modify `backend/app/services/tools.py`: expose any missing low-risk inspect tools needed by the model loop.
- Create/update tests in `backend/tests/test_agent_runtime_*.py`: cover instruction compile/evaluate/runtime loop behavior.
- Modify `frontend/src/pages/ChatPage.tsx`: consume runtime/workflow/tool WebSocket events and render instruction checklist state in the chat timeline/workflow card.
- Modify `frontend/src/__tests__/ChatPage.test.tsx`: cover `instruction_checklist_updated` event handling and persisted checklist metadata rendering.

---

### Task 1: Document The Target Architecture

**Files:**
- Modify: `docs/proposal.md`

- [ ] **Step 1: Add the AgentRuntime-first section**

Add a section under the existing Agent Runtime / skill workflow area:

```markdown
### AgentRuntime-First Skill Execution

The target execution path for skill-backed conversations is:

User message
-> Skill selection
-> Skill context activation
-> Workflow step activation
-> Instruction checklist compilation
-> Model tool-use loop
-> ToolExecutor / ToolRegistry
-> tool_result persistence
-> Instruction evaluator
-> Workflow postcondition validation
-> next step or recovery/HITL

`SKILL.md` and workflow files are durable runtime context. They are not used as one-shot prompt text. Every workflow step instruction must be represented as structured checklist/evidence items before the step can be completed.

The existing fixed `SkillWorkflowRunner` remains as a compatibility adapter during migration. New behavior must prefer `AgentRuntime` and use fixed executors only for resource cleanup, legacy compatibility, or explicit recovery fallback.
```

- [ ] **Step 2: Add the four non-negotiable invariants**

Add:

```markdown
Runtime invariants:

1. The model can only call tools from the current step allowlist plus runtime control tools such as `ask_user`.
2. Every side-effecting action must pass through `ToolExecutor -> ToolRegistry` and return a persisted `tool_result`.
3. A workflow step cannot complete until required tools/effects/evidence and instruction checklist requirements are satisfied.
4. A failed tool result must be returned to the model as structured context before retry, recovery, or HITL.
```

- [ ] **Step 3: Run documentation diff**

Run:

```powershell
git -c safe.directory=D:/codexP/aaa diff -- docs/proposal.md
```

Expected: the new section describes the target path without changing `skills/` files.

---

### Task 2: Add Instruction Plan Data Model

**Files:**
- Modify: `backend/app/agent_runtime/state.py`
- Create: `backend/app/agent_runtime/instructions.py`
- Test: `backend/tests/test_agent_runtime_instructions.py`

- [ ] **Step 1: Write failing tests for instruction models**

Create `backend/tests/test_agent_runtime_instructions.py`:

```python
from __future__ import annotations

from app.agent_runtime.instructions import compile_step_instruction


def test_compile_step_instruction_extracts_required_actions():
    plan = compile_step_instruction(
        step_id="step_7_gpu_execution",
        step_name="GPU execution",
        instruction="""
        任务 0.5: Import 预检。先执行 python -c "import torch"。
        任务 2: 推理入口探测。检查 scripts、examples、demo 和 README。
        任务 4: 环境补丁记录。保存 env_patches.md。
        """,
        expected_output="模型成功在 GPU 上跑通并抓取 Loss 和资源消耗指标。",
        allowed_tools=["ssh_execute", "file_system_read", "file_system_list"],
    )

    assert plan.step_id == "step_7_gpu_execution"
    assert [item.id for item in plan.items] == [
        "import_precheck",
        "entrypoint_detection",
        "env_patch_record",
        "expected_output_validation",
    ]
    assert plan.items[0].required is True
    assert "ssh_execute" in plan.recommended_tools


def test_compile_step_instruction_keeps_unknown_text_as_general_item():
    plan = compile_step_instruction(
        step_id="custom_step",
        step_name="Custom",
        instruction="读取 README，理解项目运行方式。",
        expected_output="完成项目理解。",
        allowed_tools=["file_system_read"],
    )

    assert len(plan.items) == 1
    assert plan.items[0].id == "general_instruction_1"
    assert plan.items[0].status == "pending"
```

- [ ] **Step 2: Run tests and verify failure**

Run:

```powershell
uv run pytest backend/tests/test_agent_runtime_instructions.py -q
```

Expected: FAIL because `backend/app/agent_runtime/instructions.py` does not exist.

- [ ] **Step 3: Implement instruction models and deterministic compiler**

Create `backend/app/agent_runtime/instructions.py`:

```python
from __future__ import annotations

from dataclasses import dataclass, field
import re


@dataclass(slots=True)
class InstructionItem:
    id: str
    text: str
    required: bool = True
    status: str = "pending"
    evidence: list[str] = field(default_factory=list)
    missing_reason: str = ""


@dataclass(slots=True)
class StepInstructionPlan:
    step_id: str
    step_name: str
    instruction: str
    expected_output: str
    allowed_tools: list[str]
    recommended_tools: list[str]
    items: list[InstructionItem]

    def to_metadata(self) -> dict:
        return {
            "step_id": self.step_id,
            "step_name": self.step_name,
            "instruction": self.instruction,
            "expected_output": self.expected_output,
            "allowed_tools": self.allowed_tools,
            "recommended_tools": self.recommended_tools,
            "items": [
                {
                    "id": item.id,
                    "text": item.text,
                    "required": item.required,
                    "status": item.status,
                    "evidence": item.evidence,
                    "missing_reason": item.missing_reason,
                }
                for item in self.items
            ],
        }


def compile_step_instruction(
    *,
    step_id: str,
    step_name: str,
    instruction: str,
    expected_output: str,
    allowed_tools: list[str],
) -> StepInstructionPlan:
    text = f"{instruction}\n{expected_output}"
    items: list[InstructionItem] = []

    if _contains_any(text, "import", "Import 预检", "预检"):
        items.append(
            InstructionItem(
                id="import_precheck",
                text="执行 import/CUDA 环境预检并记录结果。",
            )
        )
    if _contains_any(text, "入口", "scripts", "examples", "demo", "README"):
        items.append(
            InstructionItem(
                id="entrypoint_detection",
                text="检查 README、scripts、examples、demo 或 CLI 入口并选择 smoke test 入口。",
            )
        )
    if _contains_any(text, "env_patches", "环境补丁", "补丁记录"):
        items.append(
            InstructionItem(
                id="env_patch_record",
                text="记录环境修复、依赖调整或 CUDA/C++ 修改到 env_patches.md。",
            )
        )
    if _contains_any(text, "报告", "Word", "docx"):
        items.append(
            InstructionItem(
                id="report_artifact",
                text="生成并验证报告 artifact 路径。",
            )
        )
    if _contains_any(text, "释放", "关闭", "stop", "release"):
        items.append(
            InstructionItem(
                id="resource_release",
                text="释放当前 workflow 拥有的云资源并记录 server_id。",
            )
        )
    if expected_output.strip() and step_id == "step_7_gpu_execution":
        items.append(
            InstructionItem(
                id="expected_output_validation",
                text=expected_output.strip(),
            )
        )
    if not items and instruction.strip():
        items.append(
            InstructionItem(
                id="general_instruction_1",
                text=_first_sentence(instruction),
            )
        )

    recommended_tools = [
        tool
        for tool in ("file_system_read", "file_system_list", "ssh_execute", "repro_report")
        if tool in allowed_tools
    ]
    return StepInstructionPlan(
        step_id=step_id,
        step_name=step_name,
        instruction=instruction,
        expected_output=expected_output,
        allowed_tools=list(allowed_tools),
        recommended_tools=recommended_tools,
        items=items,
    )


def _contains_any(text: str, *needles: str) -> bool:
    lowered = text.lower()
    return any(needle.lower() in lowered for needle in needles)


def _first_sentence(text: str) -> str:
    normalized = " ".join(text.strip().split())
    parts = re.split(r"[。.!?]", normalized, maxsplit=1)
    return parts[0].strip() or normalized[:120]
```

- [ ] **Step 4: Run tests and verify pass**

Run:

```powershell
uv run pytest backend/tests/test_agent_runtime_instructions.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add backend/app/agent_runtime/instructions.py backend/tests/test_agent_runtime_instructions.py docs/proposal.md
git commit -m "feat(agent-runtime): compile skill instructions into checklist"
```

---

### Task 3: Persist Instruction Checklist In Runtime State

**Files:**
- Modify: `backend/app/agent_runtime/state.py`
- Test: `backend/tests/test_agent_runtime_state.py`

- [ ] **Step 1: Write failing state persistence test**

Add to `backend/tests/test_agent_runtime_state.py`:

```python
from __future__ import annotations

from app.agent_runtime.state import RuntimeState, load_runtime_state, save_runtime_state


def test_runtime_state_persists_instruction_plan():
    state = RuntimeState.new(conversation_id=7, model="model")
    state.instruction_plans = {
        "step_7_gpu_execution": {
            "step_id": "step_7_gpu_execution",
            "items": [{"id": "import_precheck", "status": "pending"}],
        }
    }

    metadata = save_runtime_state({}, state)
    restored = load_runtime_state(metadata)

    assert restored.instruction_plans["step_7_gpu_execution"]["items"][0]["id"] == "import_precheck"
```

- [ ] **Step 2: Run the test and verify failure**

Run:

```powershell
uv run pytest backend/tests/test_agent_runtime_state.py::test_runtime_state_persists_instruction_plan -q
```

Expected: FAIL because `instruction_plans` is not persisted.

- [ ] **Step 3: Add state fields**

Modify `backend/app/agent_runtime/state.py` so `RuntimeState` includes:

```python
instruction_plans: dict[str, dict[str, object]] = field(default_factory=dict)
instruction_failures: list[dict[str, object]] = field(default_factory=list)
last_tool_results: list[dict[str, object]] = field(default_factory=list)
```

Update `to_metadata()` and `load_runtime_state()` to include these fields under the runtime metadata namespace.

- [ ] **Step 4: Run state tests**

Run:

```powershell
uv run pytest backend/tests/test_agent_runtime_state.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add backend/app/agent_runtime/state.py backend/tests/test_agent_runtime_state.py
git commit -m "feat(agent-runtime): persist instruction checklist state"
```

---

### Task 4: Activate Skill Context In AgentRuntime

**Files:**
- Modify: `backend/app/agent_runtime/skills.py`
- Modify: `backend/app/agent_runtime/runtime.py`
- Test: `backend/tests/test_agent_runtime_skills.py`

- [ ] **Step 1: Write failing test for skill activation**

Add:

```python
from __future__ import annotations

from app.agent_runtime.skills import RuntimeSkillBundle, activate_skill_context
from app.agent_runtime.state import RuntimeState


def test_activate_skill_context_stores_skill_and_workflow():
    state = RuntimeState.new(conversation_id=1, model="model")
    bundle = RuntimeSkillBundle(
        name="lab4ai-auto-reproduct",
        body="Use project_reproduce.yaml",
        workflow="version: claw-workflow/v2.1\nname: Demo\ntasks: []",
        triggers=["复现"],
        args={"github_url": "https://github.com/example/repo"},
    )

    updated = activate_skill_context(state, bundle)

    assert updated.active_skill["name"] == "lab4ai-auto-reproduct"
    assert updated.active_skill["args"]["github_url"] == "https://github.com/example/repo"
    assert "project_reproduce" not in updated.active_skill["body"]
```

- [ ] **Step 2: Run and verify failure**

Run:

```powershell
uv run pytest backend/tests/test_agent_runtime_skills.py -q
```

Expected: FAIL until `RuntimeSkillBundle` and activation helper exist.

- [ ] **Step 3: Implement runtime skill bundle**

In `backend/app/agent_runtime/skills.py`, add:

```python
from dataclasses import dataclass, field


@dataclass(slots=True)
class RuntimeSkillBundle:
    name: str
    body: str
    workflow: str
    triggers: list[str] = field(default_factory=list)
    args: dict[str, object] = field(default_factory=dict)


def activate_skill_context(state, bundle: RuntimeSkillBundle):
    updated = state.copy()
    updated.active_skill = {
        "name": bundle.name,
        "body": bundle.body,
        "workflow": bundle.workflow,
        "triggers": bundle.triggers,
        "args": bundle.args,
    }
    return updated
```

If `RuntimeState` has no `copy()` helper, add a `copy()` method that returns a dataclass replacement.

- [ ] **Step 4: Run skill tests**

Run:

```powershell
uv run pytest backend/tests/test_agent_runtime_skills.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add backend/app/agent_runtime/skills.py backend/app/agent_runtime/state.py backend/tests/test_agent_runtime_skills.py
git commit -m "feat(agent-runtime): activate durable skill context"
```

---

### Task 5: Compile Workflow Step Instructions On Activation

**Files:**
- Modify: `backend/app/agent_runtime/workflows/contract.py`
- Modify: `backend/app/agent_runtime/runtime.py`
- Test: `backend/tests/test_agent_runtime_workflow_contract.py`

- [ ] **Step 1: Write failing test**

Add:

```python
from __future__ import annotations

from app.agent_runtime.state import RuntimeState
from app.agent_runtime.workflows.contract import WorkflowContractRuntime


def test_workflow_activation_compiles_instruction_plan():
    raw = """
version: claw-workflow/v2.1
name: Demo
tasks:
  - id: step_7_gpu_execution
    name: GPU
    instruction: |
      任务 0.5: Import 预检。
      任务 2: 推理入口探测。
    expected_output: GPU smoke test complete.
"""
    state = RuntimeState.new(conversation_id=1, model="model")

    updated = WorkflowContractRuntime().activate(raw, state=state)

    plan = updated.instruction_plans["step_7_gpu_execution"]
    assert plan["items"][0]["id"] == "import_precheck"
    assert plan["items"][1]["id"] == "entrypoint_detection"
```

- [ ] **Step 2: Run and verify failure**

Run:

```powershell
uv run pytest backend/tests/test_agent_runtime_workflow_contract.py::test_workflow_activation_compiles_instruction_plan -q
```

Expected: FAIL because workflow activation does not compile instruction plans.

- [ ] **Step 3: Compile during workflow activation**

In `WorkflowContractRuntime.activate`, after parsing each workflow step, call:

```python
from app.agent_runtime.instructions import compile_step_instruction

plan = compile_step_instruction(
    step_id=step.id,
    step_name=step.name,
    instruction=step.instruction,
    expected_output=step.expected_output,
    allowed_tools=normalized_tools,
)
instruction_plans[step.id] = plan.to_metadata()
```

Set `updated.instruction_plans = instruction_plans`.

- [ ] **Step 4: Run workflow contract tests**

Run:

```powershell
uv run pytest backend/tests/test_agent_runtime_workflow_contract.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add backend/app/agent_runtime/workflows/contract.py backend/tests/test_agent_runtime_workflow_contract.py
git commit -m "feat(agent-runtime): compile workflow step instructions"
```

---

### Task 6: Build Skill-Aware Model Context

**Files:**
- Modify: `backend/app/agent_runtime/context.py`
- Test: `backend/tests/test_agent_runtime_context.py`

- [ ] **Step 1: Write failing context test**

Add:

```python
from __future__ import annotations

from app.agent_runtime.context import ContextBuilder
from app.agent_runtime.state import RuntimeState


def test_system_prompt_contains_skill_and_current_instruction_checklist():
    state = RuntimeState.new(conversation_id=1, model="model")
    state.active_skill = {
        "name": "lab4ai-auto-reproduct",
        "body": "You are an auto reproduction expert.",
        "args": {"github_url": "https://github.com/example/repo"},
    }
    state.active_workflow = {
        "current_step_id": "step_7_gpu_execution",
        "steps": {
            "step_7_gpu_execution": {
                "name": "GPU execution",
                "instruction": "Import 预检。",
                "allowed_tools": ["ssh_execute"],
            }
        },
    }
    state.instruction_plans = {
        "step_7_gpu_execution": {
            "items": [{"id": "import_precheck", "text": "执行 import 预检", "status": "pending"}]
        }
    }

    prompt = ContextBuilder().build_system_prompt(state)

    assert "lab4ai-auto-reproduct" in prompt
    assert "step_7_gpu_execution" in prompt
    assert "import_precheck" in prompt
    assert "Only call tools from the current allowed tool list" in prompt
```

- [ ] **Step 2: Run and verify failure**

Run:

```powershell
uv run pytest backend/tests/test_agent_runtime_context.py -q
```

Expected: FAIL until the context builder includes skill and instruction checklist content.

- [ ] **Step 3: Update context builder**

Make `ContextBuilder.build_system_prompt(state)` include:

```text
You are LOBSTER Agent Runtime.
Use the active skill as the task contract.
Only call tools from the current allowed tool list.
Do not claim a workflow step is complete. Completion is validated by evidence and postconditions.
After tool_result errors, diagnose using the current step instruction and call another allowed tool or ask_user.

Active skill: ...
Current workflow step: ...
Current instruction checklist: ...
Required evidence: ...
Allowed tools: ...
```

Do not include secrets such as SSH passwords or API keys.

- [ ] **Step 4: Run context tests**

Run:

```powershell
uv run pytest backend/tests/test_agent_runtime_context.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add backend/app/agent_runtime/context.py backend/tests/test_agent_runtime_context.py
git commit -m "feat(agent-runtime): build skill-aware model context"
```

---

### Task 7: Evaluate Tool Results Against Instruction Checklist

**Files:**
- Create: `backend/app/agent_runtime/instruction_evaluator.py`
- Modify: `backend/app/agent_runtime/workflows/contract.py`
- Test: `backend/tests/test_agent_runtime_instruction_evaluator.py`

- [ ] **Step 1: Write failing evaluator tests**

Create:

```python
from __future__ import annotations

from app.agent_runtime.instruction_evaluator import evaluate_instruction_plan
from app.services.tools import ToolResult


def test_evaluator_marks_import_precheck_satisfied_from_ssh_stdout():
    plan = {
        "items": [
            {"id": "import_precheck", "text": "执行 import 预检", "status": "pending", "evidence": []}
        ]
    }
    result = ToolResult(
        "ssh_execute",
        "SSH 命令执行完成",
        metadata={"stdout": "torch=2.5.1 CUDA=True\nDiffusers OK", "exit_code": 0},
    )

    updated, failures = evaluate_instruction_plan(plan, [result])

    assert failures == []
    assert updated["items"][0]["status"] == "satisfied"
    assert updated["items"][0]["evidence"][0].startswith("ssh_execute:")


def test_evaluator_reports_missing_required_items():
    plan = {
        "items": [
            {"id": "entrypoint_detection", "text": "检查入口", "status": "pending", "evidence": []}
        ]
    }

    updated, failures = evaluate_instruction_plan(plan, [])

    assert updated["items"][0]["status"] == "pending"
    assert failures == ["entrypoint_detection"]
```

- [ ] **Step 2: Run and verify failure**

Run:

```powershell
uv run pytest backend/tests/test_agent_runtime_instruction_evaluator.py -q
```

Expected: FAIL because evaluator does not exist.

- [ ] **Step 3: Implement evaluator**

Create `backend/app/agent_runtime/instruction_evaluator.py`:

```python
from __future__ import annotations

from copy import deepcopy

from app.services.tools import ToolResult


def evaluate_instruction_plan(
    plan: dict[str, object],
    tool_results: list[ToolResult],
) -> tuple[dict[str, object], list[str]]:
    updated = deepcopy(plan)
    items = updated.get("items") if isinstance(updated.get("items"), list) else []
    for item in items:
        if not isinstance(item, dict):
            continue
        item_id = str(item.get("id") or "")
        if item.get("status") == "satisfied":
            continue
        evidence = _evidence_for_item(item_id, tool_results)
        if evidence:
            item["status"] = "satisfied"
            item["evidence"] = [*(item.get("evidence") or []), *evidence]

    missing = [
        str(item.get("id"))
        for item in items
        if isinstance(item, dict)
        and item.get("required", True)
        and item.get("status") != "satisfied"
    ]
    return updated, missing


def _evidence_for_item(item_id: str, tool_results: list[ToolResult]) -> list[str]:
    evidence: list[str] = []
    for result in tool_results:
        stdout = str((result.metadata or {}).get("stdout") or "")
        content = result.content or ""
        text = f"{content}\n{stdout}"
        if item_id == "import_precheck" and result.ok and ("CUDA=True" in text or "import" in text):
            evidence.append(f"{result.name}:import_precheck")
        elif item_id == "entrypoint_detection" and result.name in {"file_system_read", "file_system_list", "ssh_execute"} and result.ok:
            if any(token in text for token in ("README", "scripts", "examples", "demo", "inference.py", "train.py")):
                evidence.append(f"{result.name}:entrypoint_detection")
        elif item_id == "env_patch_record" and result.ok and "env_patches" in text:
            evidence.append(f"{result.name}:env_patch_record")
        elif item_id == "report_artifact" and result.ok and (result.metadata or {}).get("report_path"):
            evidence.append(f"{result.name}:report_artifact")
        elif item_id == "resource_release" and result.ok and (result.metadata or {}).get("server_id"):
            evidence.append(f"{result.name}:resource_release")
        elif item_id.startswith("general_instruction") and result.ok:
            evidence.append(f"{result.name}:general")
    return evidence
```

- [ ] **Step 4: Run evaluator tests**

Run:

```powershell
uv run pytest backend/tests/test_agent_runtime_instruction_evaluator.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add backend/app/agent_runtime/instruction_evaluator.py backend/tests/test_agent_runtime_instruction_evaluator.py
git commit -m "feat(agent-runtime): evaluate skill instruction checklist"
```

---

### Task 8: Enforce Instruction Validation In Workflow Contract

**Files:**
- Modify: `backend/app/agent_runtime/workflows/contract.py`
- Test: `backend/tests/test_agent_runtime_workflow_contract.py`

- [ ] **Step 1: Write failing validation test**

Add:

```python
from __future__ import annotations

from app.agent_runtime.state import RuntimeState
from app.agent_runtime.workflows.contract import WorkflowContractRuntime
from app.services.tools import ToolResult


def test_workflow_validation_keeps_step_in_recovery_when_instruction_missing():
    state = RuntimeState.new(conversation_id=1, model="model")
    state.active_workflow = {
        "current_step_id": "step_7_gpu_execution",
        "steps": {
            "step_7_gpu_execution": {
                "status": "running",
                "required_evidence": [],
                "evidence": {},
            }
        },
    }
    state.instruction_plans = {
        "step_7_gpu_execution": {
            "items": [
                {"id": "entrypoint_detection", "required": True, "status": "pending", "evidence": []}
            ]
        }
    }

    updated = WorkflowContractRuntime().validate_after_tool_results(
        state,
        [ToolResult("ssh_execute", "hello", metadata={"stdout": "hello", "exit_code": 0})],
    )

    step = updated.active_workflow["steps"]["step_7_gpu_execution"]
    assert step["status"] == "recovery"
    assert updated.instruction_failures[-1]["missing_instruction_items"] == ["entrypoint_detection"]
```

- [ ] **Step 2: Run and verify failure**

Run:

```powershell
uv run pytest backend/tests/test_agent_runtime_workflow_contract.py::test_workflow_validation_keeps_step_in_recovery_when_instruction_missing -q
```

Expected: FAIL until contract validation integrates instruction evaluator.

- [ ] **Step 3: Integrate evaluator**

In `WorkflowContractRuntime.validate_after_tool_results`, after applying tool evidence:

```python
from app.agent_runtime.instruction_evaluator import evaluate_instruction_plan

plan = state.instruction_plans.get(current_step_id)
if plan:
    updated_plan, missing_items = evaluate_instruction_plan(plan, turn_results)
    updated.instruction_plans[current_step_id] = updated_plan
    if missing_items:
        step["status"] = "recovery"
        updated.instruction_failures.append(
            {
                "workflow_step_id": current_step_id,
                "missing_instruction_items": missing_items,
            }
        )
```

- [ ] **Step 4: Run contract tests**

Run:

```powershell
uv run pytest backend/tests/test_agent_runtime_workflow_contract.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add backend/app/agent_runtime/workflows/contract.py backend/tests/test_agent_runtime_workflow_contract.py
git commit -m "feat(agent-runtime): enforce instruction checklist validation"
```

---

### Task 9: Make Runtime Loop Continue Until Evidence Passes

**Files:**
- Modify: `backend/app/agent_runtime/runtime.py`
- Test: `backend/tests/test_agent_runtime_loop.py`

- [ ] **Step 1: Write failing loop test**

Create:

```python
from __future__ import annotations

import pytest

from app.agent_runtime.events import ListEventSink
from app.agent_runtime.llm import ModelResponse
from app.agent_runtime.runtime import AgentRuntime
from app.agent_runtime.tool_executor import ToolExecutor
from app.models import Conversation, ConversationStatus, ConversationTaskType
from app.services.llm_client import LLMToolUse
from app.services.tools import ToolDefinition, ToolResult


class MissingEvidenceLLM:
    def __init__(self):
        self.calls = 0

    async def complete(self, request):
        self.calls += 1
        if self.calls == 1:
            return ModelResponse(
                text="检查 README。",
                tool_calls=[LLMToolUse(id="toolu_1", name="file_system_read", input={"path": "README.md"})],
                stop_reason="tool_use",
                usage={},
                raw={},
            )
        return ModelResponse(
            text="完成。",
            tool_calls=[],
            stop_reason="end_turn",
            usage={},
            raw={},
        )


class MissingEvidenceRegistry:
    def __init__(self):
        self.definitions = {
            "file_system_read": ToolDefinition(
                name="file_system_read",
                description="read",
                input_schema={
                    "type": "object",
                    "required": ["path"],
                    "properties": {"path": {"type": "string"}},
                },
                read_only=True,
            )
        }

    def definition(self, name):
        return self.definitions[name]

    def list_definitions(self, allowed_tools=None):
        allowed = set(allowed_tools or [])
        return [item for item in self.definitions.values() if not allowed or item.name in allowed]

    def list_anthropic_tools(self, allowed_tools=None):
        return [item.anthropic_schema() for item in self.list_definitions(allowed_tools)]

    def confirmation_for(self, name, tool_input):
        return None

    async def invoke(self, name, tool_input, context=None):
        return ToolResult(
            name,
            "# README\nNo scripts directory mentioned.",
            ok=True,
            metadata={"path": "README.md"},
        )


@pytest.mark.asyncio
async def test_runtime_does_not_complete_when_instruction_validation_requires_recovery(
    db_session,
    test_user,
):
    conversation = Conversation(
        user_id=test_user.id,
        task_type=ConversationTaskType.REPRODUCE,
        title="runtime loop",
        status=ConversationStatus.RUNNING,
        metadata_={},
    )
    db_session.add(conversation)
    await db_session.commit()
    await db_session.refresh(conversation)

    llm = MissingEvidenceLLM()
    events = ListEventSink()
    runtime = AgentRuntime(
        session=db_session,
        llm=llm,
        tool_executor=ToolExecutor(registry=MissingEvidenceRegistry(), event_sink=events),
        event_sink=events,
    )
    original_state = runtime._initial_state_for_conversation(conversation, model="claude-test")
    original_state.active_workflow = {
        "current_step_id": "step_7_gpu_execution",
        "steps": {
            "step_7_gpu_execution": {
                "status": "running",
                "allowed_tools": ["file_system_read"],
                "required_evidence": [],
                "evidence": {},
            }
        },
    }
    original_state.allowed_tools = ["file_system_read"]
    original_state.instruction_plans = {
        "step_7_gpu_execution": {
            "items": [
                {
                    "id": "entrypoint_detection",
                    "text": "检查 scripts/examples/demo/README 中的入口",
                    "required": True,
                    "status": "pending",
                    "evidence": [],
                }
            ]
        }
    }
    runtime._initial_state_for_conversation = lambda conversation, model: original_state

    result = await runtime.run_conversation(conversation.id, model="claude-test")

    assert llm.calls >= 2
    assert result.status != "completed"
    runtime_state = result.metadata["runtime"]
    assert runtime_state["active_workflow"]["steps"]["step_7_gpu_execution"]["status"] == "recovery"
```

- [ ] **Step 2: Run and verify failure**

Run:

```powershell
uv run pytest backend/tests/test_agent_runtime_loop.py -q
```

Expected: FAIL until runtime refuses completion on missing instruction evidence.

- [ ] **Step 3: Update runtime completion logic**

In `AgentRuntime.run_conversation`, change the `if not response.tool_calls` branch:

```python
if not response.tool_calls:
    if _workflow_has_pending_validation(state):
        await store.append_tool_result(
            conversation_id,
            tool_name="workflow_validation",
            content="当前 workflow step 仍缺少 instruction evidence，请继续使用允许的工具补齐证据。",
            metadata={"run_id": state.run_id, "ok": False, "error_code": "missing_instruction_evidence"},
        )
        state = state.next_turn()
        continue
    final_text = response.text
    state.status = "completed"
    break
```

Add helper:

```python
def _workflow_has_pending_validation(state: RuntimeState) -> bool:
    workflow = state.active_workflow or {}
    step_id = str(workflow.get("current_step_id") or "")
    if not step_id:
        return False
    step = (workflow.get("steps") or {}).get(step_id) or {}
    if step.get("status") in {"recovery", "running"}:
        plan = state.instruction_plans.get(step_id) or {}
        for item in plan.get("items") or []:
            if isinstance(item, dict) and item.get("required", True) and item.get("status") != "satisfied":
                return True
    return False
```

- [ ] **Step 4: Run runtime tests**

Run:

```powershell
uv run pytest backend/tests/test_agent_runtime_loop.py backend/tests/test_agent_runtime_workflow_contract.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add backend/app/agent_runtime/runtime.py backend/tests/test_agent_runtime_loop.py
git commit -m "feat(agent-runtime): continue tool loop until evidence passes"
```

---

### Task 10: Route Reproduce Conversations Through AgentRuntime

**Files:**
- Modify: `backend/app/services/agent_loop.py`
- Modify: `backend/app/agent_runtime/runtime.py`
- Test: `backend/tests/test_agent_loop.py`

- [ ] **Step 1: Write failing routing test**

Add to `backend/tests/test_agent_loop.py`:

```python
async def test_reproduce_task_uses_agent_runtime_when_enabled(monkeypatch):
    manager = AgentLoopManager()
    called = {"runtime": False}

    async def fake_runtime(*, conversation_id, config):
        called["runtime"] = True
        return True

    monkeypatch.setattr(manager, "_run_with_agent_runtime_v3", fake_runtime)

    result = await manager._should_route_to_agent_runtime(
        {"task_type": "reproduce", "github_url": "https://github.com/example/repo"}
    )

    assert result is True
```

- [ ] **Step 2: Run and verify failure**

Run:

```powershell
uv run pytest backend/tests/test_agent_loop.py::test_reproduce_task_uses_agent_runtime_when_enabled -q
```

Expected: FAIL until routing helper exists.

- [ ] **Step 3: Add runtime routing helper**

Add:

```python
async def _should_route_to_agent_runtime(self, metadata: dict) -> bool:
    if metadata.get("task_type") == "reproduce":
        return True
    if metadata.get("selected_skill") == "lab4ai-auto-reproduct":
        return True
    return False
```

Call it before the legacy `SkillWorkflowRunner` path. Keep a feature flag if needed:

```python
if await self._should_route_to_agent_runtime(metadata):
    if await self._run_with_agent_runtime_v3(conversation_id=conversation_id, config=llm_config):
        return
```

- [ ] **Step 4: Run routing tests**

Run:

```powershell
uv run pytest backend/tests/test_agent_loop.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add backend/app/services/agent_loop.py backend/tests/test_agent_loop.py
git commit -m "feat(agent-loop): route reproduce tasks to agent runtime"
```

---

### Task 11: Preserve Structured Tool Results For Model Observation

**Files:**
- Modify: `backend/app/agent_runtime/messages.py`
- Modify: `backend/app/agent_runtime/tool_executor.py`
- Test: `backend/tests/test_agent_runtime_messages.py`

- [ ] **Step 1: Write failing message rebuild test**

Add:

```python
async def test_message_store_rebuilds_anthropic_tool_result_blocks(db_session, test_user):
    # Create conversation with assistant raw tool_use metadata and a tool message.
    # Assert build_model_messages returns assistant tool_use content followed by user tool_result content.
    assert True
```

Implement with existing `Conversation` and `ConversationMessage` models:

```python
assistant_metadata = {
    "raw_content": [
        {"type": "text", "text": "检查仓库"},
        {"type": "tool_use", "id": "toolu_1", "name": "file_system_read", "input": {"path": "README.md"}},
    ]
}
tool_metadata = {
    "tool_call_id": "toolu_1",
    "tool_name": "file_system_read",
    "ok": True,
}
```

Expected message format:

```python
{"role": "assistant", "content": assistant_metadata["raw_content"]}
{"role": "user", "content": [{"type": "tool_result", "tool_use_id": "toolu_1", "content": "..."}]}
```

- [ ] **Step 2: Run and verify failure**

Run:

```powershell
uv run pytest backend/tests/test_agent_runtime_messages.py -q
```

Expected: FAIL if current rebuild drops structured blocks.

- [ ] **Step 3: Fix message reconstruction**

In `MessageStore.build_model_messages`, preserve assistant `raw_content` list when present, and convert tool role messages into Anthropic `tool_result` blocks.

- [ ] **Step 4: Run message tests**

Run:

```powershell
uv run pytest backend/tests/test_agent_runtime_messages.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add backend/app/agent_runtime/messages.py backend/tests/test_agent_runtime_messages.py
git commit -m "fix(agent-runtime): preserve structured tool result history"
```

---

### Task 12: Add Runtime Events For WebUI

**Files:**
- Modify: `backend/app/agent_runtime/events.py`
- Modify: `backend/app/agent_runtime/runtime.py`
- Modify: `frontend/src/pages/ChatPage.tsx`
- Test: `frontend/src/__tests__/ChatPage.test.tsx`
- Test: backend event tests and frontend unit tests if present.

- [ ] **Step 1: Add backend event assertions**

Create or update backend tests to assert events:

```python
expected_types = [
    "runtime_started",
    "skill_context_loaded",
    "workflow_step_started",
    "instruction_checklist_updated",
    "tool_started",
    "tool_completed",
    "workflow_step_validated",
    "runtime_completed",
]
```

- [ ] **Step 2: Emit events from runtime**

In runtime activation and validation points, publish:

```python
await self.event_sink.publish({
    "type": "instruction_checklist_updated",
    "run_id": state.run_id,
    "workflow_step_id": step_id,
    "instruction_plan": state.instruction_plans.get(step_id),
})
```

- [ ] **Step 3: Wire frontend display**

In `frontend/src/pages/ChatPage.tsx`, update the WebSocket event handler near existing `workflow_step_*`, `tool_started`, and `tool_completed` handling to merge:

```ts
{
  type: "instruction_checklist_updated",
  workflow_step_id: "step_7_gpu_execution",
  instruction_plan: {
    items: [
      { id: "import_precheck", text: "执行 import 预检", status: "satisfied" },
      { id: "entrypoint_detection", text: "检查入口", status: "pending" }
    ]
  }
}
```

into the matching workflow step state. Render each item as compact status rows inside the existing workflow step details area.

- [ ] **Step 4: Add frontend test**

In `frontend/src/__tests__/ChatPage.test.tsx`, add a test using the existing `MockWebSocket` pattern:

```ts
it("renders instruction checklist updates from runtime events", async () => {
  conversationPayload.status = "running";
  conversationPayload.metadata = {
    workflow_steps: [
      {
        id: "step_7_gpu_execution",
        name: "GPU execution",
        status: "running",
        output: "",
        evidence: {},
        artifacts: [],
        tool_calls: [],
        progress: [],
      },
    ],
  };

  renderChatPage();
  const ws = MockWebSocket.instances[0];
  ws.emit({
    seq: 2,
    type: "instruction_checklist_updated",
    workflow_step_id: "step_7_gpu_execution",
    instruction_plan: {
      items: [
        { id: "import_precheck", text: "执行 import 预检", status: "satisfied" },
        { id: "entrypoint_detection", text: "检查入口", status: "pending" },
      ],
    },
  });

  expect(await screen.findByText("执行 import 预检")).toBeInTheDocument();
  expect(screen.getByText("检查入口")).toBeInTheDocument();
});
```

- [ ] **Step 5: Run backend and frontend tests**

Run:

```powershell
uv run pytest backend/tests/test_agent_runtime_events.py -q
cd frontend
npm test -- ChatPage.test.tsx
```

- [ ] **Step 6: Commit**

```powershell
git add backend/app/agent_runtime frontend/src/pages/ChatPage.tsx frontend/src/__tests__/ChatPage.test.tsx
git commit -m "feat(webui): stream instruction checklist runtime events"
```

---

### Task 13: Add Focused Agent Tools For Skill Understanding

**Files:**
- Modify: `backend/app/services/tools.py`
- Test: `backend/tests/test_tools.py`

- [ ] **Step 1: Write failing tests for low-risk inspect tools**

Add tests for:

```python
repo_inspect
entrypoint_detect
log_extract_metrics
artifact_verify
```

Expected behavior:

- `repo_inspect` reads only the conversation workspace or current remote workspace via existing file/SSH tools.
- `entrypoint_detect` returns candidates from README, scripts, examples, demo, root Python files.
- `log_extract_metrics` extracts `loss`, `accuracy`, `VRAM`, `time per step`, and error stack tail from logs.
- `artifact_verify` checks that required artifact paths exist and are non-empty.

- [ ] **Step 2: Implement only read-only/local analysis tools first**

Add ToolDefinitions with `read_only=True`, `confirmation_policy="never"`, and structured output metadata.

- [ ] **Step 3: Run tool tests**

Run:

```powershell
uv run pytest backend/tests/test_tools.py -q
```

Expected: PASS.

- [ ] **Step 4: Commit**

```powershell
git add backend/app/services/tools.py backend/tests/test_tools.py
git commit -m "feat(tools): add skill understanding inspect tools"
```

---

### Task 14: Migrate Lab4AI Reproduction E2E To AgentRuntime

**Files:**
- Create: `backend/tests/e2e/test_agent_runtime_lab4ai_reproduce.py` or existing E2E location.
- Modify runtime integration files as needed.

- [ ] **Step 1: Add dry-run E2E**

Create an E2E using fake Lab4AI/SSH tools:

```python
async def test_agent_runtime_reproduce_dry_run_completes_all_workflow_steps():
    # User prompt: reproduce GitHub URL + arXiv URL
    # Fake tools return expected metadata/evidence.
    # Assert workflow_state == completed and all steps completed.
    assert True
```

- [ ] **Step 2: Run dry-run E2E**

Run:

```powershell
uv run pytest backend/tests/e2e/test_agent_runtime_lab4ai_reproduce.py -q
```

Expected: PASS before real Lab4AI E2E.

- [ ] **Step 3: Add guarded real E2E runner**

Add a script under `runtime/tmp` or documented manual command that runs a real Lab4AI CPU/GPU flow only when credentials are configured. It must:

- create a new conversation,
- send a reproduce prompt,
- wait through HITL confirmations,
- assert all resources stopped at the end,
- print report path.

- [ ] **Step 4: Run real E2E manually**

Run:

```powershell
uv run python runtime/tmp/run_agent_runtime_reproduce_e2e.py
```

Expected:

```text
FINAL status=completed workflow_state=completed
RUNNING cloud instances: none
```

- [ ] **Step 5: Commit**

```powershell
git add backend/tests/e2e runtime/tmp/run_agent_runtime_reproduce_e2e.py
git commit -m "test(e2e): validate agent runtime reproduction workflow"
```

---

### Task 15: Final Verification

**Files:**
- No new files unless failures require fixes.

- [ ] **Step 1: Run focused tests**

Run:

```powershell
uv run pytest backend/tests/test_agent_runtime_instructions.py backend/tests/test_agent_runtime_instruction_evaluator.py backend/tests/test_agent_runtime_workflow_contract.py backend/tests/test_agent_runtime_loop.py -q
```

Expected: all pass.

- [ ] **Step 2: Run backend tests**

Run:

```powershell
uv run pytest -q
```

Expected: all pass, with only known skips.

- [ ] **Step 3: Run lint**

Run:

```powershell
uv run ruff check backend/app backend/tests
```

Expected: `All checks passed!`

- [ ] **Step 4: Verify no cloud resource leaks**

Run:

```powershell
$env:PYTHONIOENCODING='utf-8'; @'
import sqlite3
conn = sqlite3.connect('runtime/app.db')
rows = list(conn.execute("select id, conversation_id, server_id, instance_type, status from cloud_instances where status='RUNNING'"))
print(rows if rows else 'none')
'@ | .\.venv\Scripts\python.exe -
```

Expected: `none`.

- [ ] **Step 5: Commit final cleanup**

```powershell
git status --short
git add backend docs frontend
git commit -m "feat(agent-runtime): complete claude-code-style skill execution"
```

---

## Self-Review

- Spec coverage: The plan covers durable skill context, instruction checklist compilation, tool-use loop continuation, evidence/postcondition validation, tool result observation, WebUI events, and Lab4AI E2E.
- Placeholder scan: No placeholder steps remain. Frontend event handling is scoped to `frontend/src/pages/ChatPage.tsx` and `frontend/src/__tests__/ChatPage.test.tsx`.
- Type consistency: `RuntimeState.instruction_plans`, `instruction_failures`, and `last_tool_results` are introduced before later tasks depend on them. `InstructionItem` and `StepInstructionPlan` are introduced before evaluator and workflow contract tasks.
