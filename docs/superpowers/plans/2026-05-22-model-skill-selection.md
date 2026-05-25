# Model-Driven Skill Selection Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let the model choose `lab4ai-auto-reproduct` from available skill summaries for reproduce requests, while preserving the existing reproduce/GitHub rule as fallback.

**Architecture:** Add a focused `SkillSelector` service that performs model-first skill selection, validates the model result against the loaded skill registry, and returns a metadata-ready result. `AgentLoopManager` consumes that result, records it in conversation metadata, then loads and runs any selected skill workflow through the existing backend workflow runner.

**Tech Stack:** Python 3.13, FastAPI service layer, existing Anthropic-compatible `llm_client`, pytest, existing `SkillLoader`, `ToolRegistry`, and `SkillWorkflowRunner`.

---

## File Structure

- Modify `docs/proposal.md`: add the confirmed model-first skill selection rule with fallback, keeping proposal aligned with the approved design.
- Modify `backend/app/services/skills.py`: add safe skill summary support and keep the current rule as an explicit fallback helper.
- Create `backend/app/services/skill_selector.py`: model-first selection service, fallback logic, validation, and metadata serialization.
- Modify `backend/app/services/agent_loop.py`: replace direct rule selection with `SkillSelector`, record `metadata["skill_selection"]`, and run workflow based on `skill.workflow_context` instead of a hard-coded skill name.
- Create `backend/tests/test_skill_selector.py`: unit tests for model success, no-model fallback, unknown skill fallback, low-confidence fallback, and non-reproduce general fallback.
- Modify `backend/tests/test_skills.py`: add coverage for safe summaries and keep fallback behavior explicit.
- Modify `backend/tests/test_agent_loop.py`: add focused coverage that Agent Loop records selector metadata and resolves the selected skill.

## Scope Check

The approved spec covers one subsystem: skill selection before workflow execution. It does not require changing workflow step execution, Lab4AI tools, SSH execution, frontend UI behavior, or skill templates. This plan keeps implementation inside that boundary.

---

### Task 1: Update Proposal And Skill Summary Support

**Files:**
- Modify: `docs/proposal.md`
- Modify: `backend/app/services/skills.py`
- Modify: `backend/tests/test_skills.py`

- [ ] **Step 1: Add a failing test for safe skill summaries**

Append this test to `backend/tests/test_skills.py`:

```python
def test_skill_summary_exposes_safe_model_fields(tmp_path):
    skill_dir = tmp_path / "skills" / "demo"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        """---
name: demo
description: Demo skill
when_to_use: Use for demo requests
triggers:
  - demo
allowed_tools:
  - analyze_repo
---

# Demo
The full body should stay out of model selection summaries.
""",
        encoding="utf-8",
    )

    skill = SkillLoader(tmp_path / "skills").load_all()["demo"]

    assert skill.summary_for_selection() == {
        "name": "demo",
        "description": "Demo skill",
        "when_to_use": "Use for demo requests",
        "triggers": ["demo"],
        "allowed_tools": ["analyze_repo"],
        "has_workflow": False,
    }
```

- [ ] **Step 2: Run the new test and verify it fails**

Run:

```bash
uv run pytest backend/tests/test_skills.py::test_skill_summary_exposes_safe_model_fields -q
```

Expected: FAIL with `AttributeError: 'SkillDefinition' object has no attribute 'summary_for_selection'`.

- [ ] **Step 3: Add summary support to `SkillDefinition`**

In `backend/app/services/skills.py`, add this method inside `SkillDefinition`, below `prompt_context`:

```python
    def summary_for_selection(self) -> dict[str, object]:
        return {
            "name": self.name,
            "description": self.description,
            "when_to_use": self.when_to_use,
            "triggers": list(self.triggers),
            "allowed_tools": list(self.allowed_tools),
            "has_workflow": bool(self.workflow_context),
        }
```

- [ ] **Step 4: Rename the existing rule conceptually but keep compatibility**

In `backend/app/services/skills.py`, replace the existing `select_skill` function with this pair:

```python
def fallback_skill_name(metadata: dict) -> str:
    if metadata.get("task_type") == "reproduce" or metadata.get("github_url"):
        return "lab4ai-auto-reproduct"
    return "general-chat"


def select_skill(skills: dict[str, SkillDefinition], metadata: dict) -> SkillDefinition | None:
    name = fallback_skill_name(metadata)
    return skills.get(name)
```

This preserves current callers and tests while making the fallback rule explicit.

- [ ] **Step 5: Update `docs/proposal.md` with the confirmed rule**

Find the Agent Loop / Skill section in `docs/proposal.md` and add this paragraph near the existing skill selection description:

```markdown
Skill 选择采用模型优先、规则兜底：后端先向模型提供当前可用 skill 的安全摘要，由模型返回 `skill_name / reason / confidence`；后端只接受 `SkillLoader` registry 中存在的 skill 名称，并由后端固定加载该 skill 绑定的 workflow 文件。若模型未配置、调用失败、返回未知 skill、置信度不足或当前任务需要 workflow 但所选 skill 无 workflow，则退回现有规则：`reproduce` 任务或存在 `github_url` 时选择 `lab4ai-auto-reproduct`，其他任务进入普通对话路径。workflow 执行仍由 `project_reproduce.yaml`、`SkillWorkflowRunner`、step allowlist、ToolRegistry 和 HITL 策略控制。
```

If the file already contains equivalent wording from another pending change, keep the existing wording and adjust only the missing facts: model-first, fallback, registry validation, backend-controlled workflow path.

- [ ] **Step 6: Run the skills test file**

Run:

```bash
uv run pytest backend/tests/test_skills.py -q
```

Expected: PASS.

---

### Task 2: Add The SkillSelector Service

**Files:**
- Create: `backend/app/services/skill_selector.py`
- Create: `backend/tests/test_skill_selector.py`

- [ ] **Step 1: Write failing tests for the selector**

Create `backend/tests/test_skill_selector.py` with:

```python
from __future__ import annotations

import pytest

from app.services.llm_client import LLMRuntimeConfig, LLMToolResponse, LLMToolUse
from app.services.skill_selector import SkillSelector
from app.services.skills import SkillDefinition


pytestmark = pytest.mark.asyncio


def _config(api_key: str | None = "key") -> LLMRuntimeConfig:
    return LLMRuntimeConfig(
        provider="anthropic",
        base_url="https://api.example.com",
        api_key=api_key,
        model="claude-compatible",
        max_tokens=1024,
    )


def _skills() -> dict[str, SkillDefinition]:
    return {
        "lab4ai-auto-reproduct": SkillDefinition(
            name="lab4ai-auto-reproduct",
            description="Project reproduction",
            triggers=["reproduce", "github"],
            when_to_use="Use for GitHub project reproduction.",
            allowed_tools=["analyze_repo"],
            workflow_context="name: lab4ai-auto-reproduct\nsteps: []",
        ),
        "lab4ai-paper-analysis": SkillDefinition(
            name="lab4ai-paper-analysis",
            description="Paper analysis",
            triggers=["paper"],
            when_to_use="Use for paper-only analysis.",
            allowed_tools=["analyze_paper"],
        ),
    }


async def test_model_skill_choice_wins(monkeypatch):
    captured: dict[str, object] = {}

    async def fake_tool_use(config, *, system, messages, tools):
        captured["system"] = system
        captured["messages"] = messages
        captured["tools"] = tools
        return LLMToolResponse(
            text="",
            tool_calls=[
                LLMToolUse(
                    id="toolu-select",
                    name="select_skill",
                    input={
                        "skill_name": "lab4ai-auto-reproduct",
                        "reason": "用户提供 GitHub 仓库并要求复现项目",
                        "confidence": 0.93,
                    },
                )
            ],
            stop_reason="tool_use",
            raw={},
        )

    monkeypatch.setattr("app.services.skill_selector.call_anthropic_compatible_tool_use", fake_tool_use)

    result = await SkillSelector().select(
        config=_config(),
        skills=_skills(),
        metadata={
            "task_type": "reproduce",
            "github_url": "https://github.com/jsnzwu/motion-guided-flow",
        },
        latest_user="帮我复现这个项目：https://github.com/jsnzwu/motion-guided-flow",
    )

    assert result.skill_name == "lab4ai-auto-reproduct"
    assert result.source == "model"
    assert result.model_choice == "lab4ai-auto-reproduct"
    assert result.fallback_choice is None
    assert result.error is None
    assert result.confidence == 0.93
    assert captured["tools"] == [SkillSelector.select_skill_tool_schema()]
    assert "motion-guided-flow" in str(captured["messages"])


async def test_unconfigured_model_uses_reproduce_fallback(monkeypatch):
    async def fake_tool_use(config, *, system, messages, tools):
        raise AssertionError("model should not be called when config is incomplete")

    monkeypatch.setattr("app.services.skill_selector.call_anthropic_compatible_tool_use", fake_tool_use)

    result = await SkillSelector().select(
        config=_config(api_key=None),
        skills=_skills(),
        metadata={"task_type": "reproduce"},
        latest_user="帮我复现这个项目",
    )

    assert result.skill_name == "lab4ai-auto-reproduct"
    assert result.source == "fallback"
    assert result.fallback_choice == "lab4ai-auto-reproduct"
    assert result.error == "llm_not_configured"


async def test_unknown_model_skill_falls_back(monkeypatch):
    async def fake_tool_use(config, *, system, messages, tools):
        return LLMToolResponse(
            text="",
            tool_calls=[
                LLMToolUse(
                    id="toolu-select",
                    name="select_skill",
                    input={"skill_name": "missing-skill", "reason": "bad choice", "confidence": 0.9},
                )
            ],
            stop_reason="tool_use",
            raw={},
        )

    monkeypatch.setattr("app.services.skill_selector.call_anthropic_compatible_tool_use", fake_tool_use)

    result = await SkillSelector().select(
        config=_config(),
        skills=_skills(),
        metadata={"task_type": "reproduce", "github_url": "https://github.com/example/repo"},
        latest_user="复现这个仓库",
    )

    assert result.skill_name == "lab4ai-auto-reproduct"
    assert result.source == "fallback"
    assert result.model_choice == "missing-skill"
    assert result.fallback_choice == "lab4ai-auto-reproduct"
    assert result.error == "unknown_skill"


async def test_low_confidence_model_skill_falls_back(monkeypatch):
    async def fake_tool_use(config, *, system, messages, tools):
        return LLMToolResponse(
            text="",
            tool_calls=[
                LLMToolUse(
                    id="toolu-select",
                    name="select_skill",
                    input={
                        "skill_name": "lab4ai-auto-reproduct",
                        "reason": "weak match",
                        "confidence": 0.5,
                    },
                )
            ],
            stop_reason="tool_use",
            raw={},
        )

    monkeypatch.setattr("app.services.skill_selector.call_anthropic_compatible_tool_use", fake_tool_use)

    result = await SkillSelector().select(
        config=_config(),
        skills=_skills(),
        metadata={"task_type": "reproduce"},
        latest_user="复现",
    )

    assert result.skill_name == "lab4ai-auto-reproduct"
    assert result.source == "fallback"
    assert result.model_choice == "lab4ai-auto-reproduct"
    assert result.error == "low_confidence"


async def test_general_task_fallback_does_not_pick_reproduct(monkeypatch):
    async def fake_tool_use(config, *, system, messages, tools):
        raise AssertionError("model should not be called when config is incomplete")

    monkeypatch.setattr("app.services.skill_selector.call_anthropic_compatible_tool_use", fake_tool_use)

    result = await SkillSelector().select(
        config=_config(api_key=None),
        skills=_skills(),
        metadata={"task_type": "general"},
        latest_user="你好",
    )

    assert result.skill_name == "general-chat"
    assert result.source == "fallback"
    assert result.fallback_choice == "general-chat"
    assert result.error == "llm_not_configured"
```

- [ ] **Step 2: Run selector tests and verify they fail because the module is missing**

Run:

```bash
uv run pytest backend/tests/test_skill_selector.py -q
```

Expected: FAIL with `ModuleNotFoundError: No module named 'app.services.skill_selector'`.

- [ ] **Step 3: Implement `backend/app/services/skill_selector.py`**

Create `backend/app/services/skill_selector.py`:

```python
"""Model-first skill selection with deterministic fallback."""

from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Literal

from app.services.llm_client import LLMRuntimeConfig, call_anthropic_compatible_tool_use
from app.services.skills import SkillDefinition, fallback_skill_name


SKILL_SELECTION_CONFIDENCE_THRESHOLD = 0.6


@dataclass(slots=True)
class SkillSelectionResult:
    skill_name: str
    reason: str
    confidence: float | None
    source: Literal["model", "fallback"]
    model_choice: str | None = None
    fallback_choice: str | None = None
    error: str | None = None

    def to_metadata(self) -> dict[str, object]:
        return {
            "selected_skill": self.skill_name,
            "source": self.source,
            "model_choice": self.model_choice,
            "fallback_choice": self.fallback_choice,
            "reason": self.reason,
            "confidence": self.confidence,
            "error": self.error,
        }


class SkillSelector:
    async def select(
        self,
        *,
        config: LLMRuntimeConfig,
        skills: dict[str, SkillDefinition],
        metadata: dict,
        latest_user: str,
    ) -> SkillSelectionResult:
        if not config.configured:
            return self._fallback(
                skills,
                metadata,
                reason="模型未配置，使用规则兜底选择 skill。",
                error="llm_not_configured",
            )

        try:
            response = await call_anthropic_compatible_tool_use(
                config,
                system=self._system_prompt(),
                messages=[
                    {
                        "role": "user",
                        "content": self._selection_context(skills, metadata, latest_user),
                    }
                ],
                tools=[self.select_skill_tool_schema()],
            )
        except Exception as exc:
            return self._fallback(
                skills,
                metadata,
                reason=f"模型选择 skill 失败，使用规则兜底。错误：{type(exc).__name__}: {exc}",
                error="model_call_failed",
            )

        payload = self._extract_selection_payload(response)
        if payload is None:
            return self._fallback(
                skills,
                metadata,
                reason="模型未返回可解析的 skill 选择，使用规则兜底。",
                error="invalid_model_response",
            )

        model_choice = str(payload.get("skill_name") or "").strip()
        reason = str(payload.get("reason") or "模型选择 skill。").strip()
        confidence = _coerce_confidence(payload.get("confidence"))

        if model_choice not in skills:
            return self._fallback(
                skills,
                metadata,
                reason=f"模型返回的 skill `{model_choice}` 不存在，使用规则兜底。",
                model_choice=model_choice,
                confidence=confidence,
                error="unknown_skill",
            )

        if confidence is None or confidence < SKILL_SELECTION_CONFIDENCE_THRESHOLD:
            return self._fallback(
                skills,
                metadata,
                reason=f"模型选择 `{model_choice}` 的置信度不足，使用规则兜底。",
                model_choice=model_choice,
                confidence=confidence,
                error="low_confidence",
            )

        selected = skills[model_choice]
        if _requires_workflow(metadata) and not selected.workflow_context:
            return self._fallback(
                skills,
                metadata,
                reason=f"当前任务需要 workflow，但模型选择的 skill `{model_choice}` 没有 workflow，使用规则兜底。",
                model_choice=model_choice,
                confidence=confidence,
                error="missing_workflow",
            )

        return SkillSelectionResult(
            skill_name=model_choice,
            reason=reason,
            confidence=confidence,
            source="model",
            model_choice=model_choice,
        )

    @staticmethod
    def select_skill_tool_schema() -> dict[str, object]:
        return {
            "name": "select_skill",
            "description": "Select exactly one available skill for the user's task.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "skill_name": {
                        "type": "string",
                        "description": "The exact name of one skill from the provided skill list.",
                    },
                    "reason": {
                        "type": "string",
                        "description": "A concise reason for the selection.",
                    },
                    "confidence": {
                        "type": "number",
                        "minimum": 0,
                        "maximum": 1,
                        "description": "Confidence from 0 to 1.",
                    },
                },
                "required": ["skill_name", "reason", "confidence"],
            },
        }

    def _fallback(
        self,
        skills: dict[str, SkillDefinition],
        metadata: dict,
        *,
        reason: str,
        error: str,
        model_choice: str | None = None,
        confidence: float | None = None,
    ) -> SkillSelectionResult:
        fallback = fallback_skill_name(metadata)
        if fallback not in skills and fallback != "general-chat":
            fallback = "general-chat"
        return SkillSelectionResult(
            skill_name=fallback,
            reason=reason,
            confidence=confidence,
            source="fallback",
            model_choice=model_choice,
            fallback_choice=fallback,
            error=error,
        )

    @staticmethod
    def _system_prompt() -> str:
        return (
            "你是 LOBSTER 的 skill 选择器。"
            "你只能从用户提供的 skill 列表中选择一个 skill_name。"
            "不要执行任务，不要规划工具调用，不要返回文件路径。"
            "如果用户提供 GitHub 仓库并要求复现，通常应选择项目复现类 skill。"
        )

    @staticmethod
    def _selection_context(
        skills: dict[str, SkillDefinition],
        metadata: dict,
        latest_user: str,
    ) -> str:
        summaries = [skill.summary_for_selection() for skill in sorted(skills.values(), key=lambda item: item.name)]
        return "\n".join(
            [
                "请为当前任务选择一个 skill。",
                f"用户最新输入：{latest_user}",
                "任务 metadata：",
                json.dumps(metadata, ensure_ascii=False, sort_keys=True),
                "可用 skill 摘要：",
                json.dumps(summaries, ensure_ascii=False, sort_keys=True),
            ]
        )

    @staticmethod
    def _extract_selection_payload(response) -> dict[str, object] | None:
        for tool_call in response.tool_calls:
            if tool_call.name == "select_skill" and isinstance(tool_call.input, dict):
                return dict(tool_call.input)
        return _extract_json_object(response.text)


def _extract_json_object(text: str) -> dict[str, object] | None:
    stripped = text.strip()
    if not stripped:
        return None
    try:
        parsed = json.loads(stripped)
    except json.JSONDecodeError:
        start = stripped.find("{")
        end = stripped.rfind("}")
        if start < 0 or end <= start:
            return None
        try:
            parsed = json.loads(stripped[start : end + 1])
        except json.JSONDecodeError:
            return None
    return parsed if isinstance(parsed, dict) else None


def _coerce_confidence(value: object) -> float | None:
    try:
        confidence = float(value)
    except (TypeError, ValueError):
        return None
    if confidence < 0 or confidence > 1:
        return None
    return confidence


def _requires_workflow(metadata: dict) -> bool:
    return metadata.get("task_type") == "reproduce" or bool(metadata.get("github_url"))
```

- [ ] **Step 4: Run selector tests**

Run:

```bash
uv run pytest backend/tests/test_skill_selector.py -q
```

Expected: PASS.

---

### Task 3: Integrate SkillSelector Into AgentLoopManager

**Files:**
- Modify: `backend/app/services/agent_loop.py`
- Modify: `backend/tests/test_agent_loop.py`

- [ ] **Step 1: Add a failing AgentLoop helper test**

Append this test to `backend/tests/test_agent_loop.py`:

```python
async def test_agent_loop_selects_skill_and_records_metadata(monkeypatch):
    from app.services.skill_selector import SkillSelectionResult
    from app.services.skills import SkillDefinition

    class FakeSelector:
        async def select(self, *, config, skills, metadata, latest_user):
            return SkillSelectionResult(
                skill_name="lab4ai-auto-reproduct",
                reason="model selected reproduction skill",
                confidence=0.91,
                source="model",
                model_choice="lab4ai-auto-reproduct",
            )

    manager = AgentLoopManager()
    manager._skill_selector = FakeSelector()
    manager._skills = {
        "lab4ai-auto-reproduct": SkillDefinition(
            name="lab4ai-auto-reproduct",
            workflow_context="name: lab4ai-auto-reproduct\nsteps: []",
        )
    }
    config = LLMRuntimeConfig(
        provider="anthropic",
        base_url="https://api.example.com",
        api_key="key",
        model="model",
        max_tokens=1024,
    )

    skill, skill_name, metadata = await manager._select_skill_for_run(
        config,
        {"task_type": "reproduce", "github_url": "https://github.com/example/repo"},
        "帮我复现这个项目",
    )

    assert skill is not None
    assert skill.name == "lab4ai-auto-reproduct"
    assert skill_name == "lab4ai-auto-reproduct"
    assert metadata["skill_selection"] == {
        "selected_skill": "lab4ai-auto-reproduct",
        "source": "model",
        "model_choice": "lab4ai-auto-reproduct",
        "fallback_choice": None,
        "reason": "model selected reproduction skill",
        "confidence": 0.91,
        "error": None,
    }
```

- [ ] **Step 2: Run the new AgentLoop test and verify it fails**

Run:

```bash
uv run pytest backend/tests/test_agent_loop.py::test_agent_loop_selects_skill_and_records_metadata -q
```

Expected: FAIL with `AttributeError: 'AgentLoopManager' object has no attribute '_select_skill_for_run'`.

- [ ] **Step 3: Import and instantiate `SkillSelector`**

In `backend/app/services/agent_loop.py`, change imports:

```python
from app.services.skills import SkillDefinition, SkillLoader
from app.services.skill_selector import SkillSelector
```

Remove `select_skill` from the import list.

In `AgentLoopManager.__init__`, add the selector:

```python
        self._skill_selector = SkillSelector()
```

Place it after `self._skills = SkillLoader(get_settings().skills_dir_path).load_all()`.

- [ ] **Step 4: Add `_select_skill_for_run` to `AgentLoopManager`**

Add this method inside `AgentLoopManager`, after `_restart_if_pending` and before `stop`:

```python
    async def _select_skill_for_run(
        self,
        config: LLMRuntimeConfig,
        metadata: dict,
        latest_user: str,
    ) -> tuple[SkillDefinition | None, str, dict]:
        selection = await self._skill_selector.select(
            config=config,
            skills=self._skills,
            metadata=metadata,
            latest_user=latest_user,
        )
        updated_metadata = dict(metadata)
        updated_metadata["skill_selection"] = selection.to_metadata()
        skill = self._skills.get(selection.skill_name)
        return skill, selection.skill_name, updated_metadata
```

- [ ] **Step 5: Replace direct skill selection in `_run`**

In `backend/app/services/agent_loop.py`, replace this block:

```python
            llm_config = await _load_llm_config(user_id)
            skill = select_skill(self._skills, metadata)
            skill_name = skill.name if skill else _select_skill(metadata)
            system_prompt = _build_system_prompt(metadata, skill_name, skill, self._tools)
```

with:

```python
            llm_config = await _load_llm_config(user_id)
            skill, skill_name, metadata = await self._select_skill_for_run(
                llm_config,
                metadata,
                latest_user,
            )
            await self._set_metadata(conversation_id, metadata)
            system_prompt = _build_system_prompt(metadata, skill_name, skill, self._tools)
```

- [ ] **Step 6: Make workflow execution depend on workflow context, not hard-coded skill name**

In `backend/app/services/agent_loop.py`, replace:

```python
            if skill and skill.name == "lab4ai-auto-reproduct" and skill.workflow_context:
```

with:

```python
            if skill and skill.workflow_context:
```

Keep the runner's `skill_name=skill.name` unchanged.

- [ ] **Step 7: Include selection source in the progress event**

In the `skill_selection` progress block, replace the first formatted sentence:

```python
                    f"已选择 skill：{skill_name}。"
```

with:

```python
                    f"已选择 skill：{skill_name}（来源：{metadata.get('skill_selection', {}).get('source', 'unknown')}）。"
```

- [ ] **Step 8: Remove the old `_select_skill` helper**

Delete this function from `backend/app/services/agent_loop.py`:

```python
def _select_skill(metadata: dict) -> str:
    if metadata.get("task_type") == "reproduce" or metadata.get("github_url"):
        return "lab4ai-auto-reproduct"
    return "general-chat"
```

The fallback rule now lives in `backend/app/services/skills.py` and is used by `SkillSelector`.

- [ ] **Step 9: Run the focused AgentLoop test**

Run:

```bash
uv run pytest backend/tests/test_agent_loop.py::test_agent_loop_selects_skill_and_records_metadata -q
```

Expected: PASS.

---

### Task 4: Verify Full Backend Behavior

**Files:**
- Modify only files changed by Tasks 1-3 if verification reveals a failure in those changes.

- [ ] **Step 1: Run focused test set**

Run:

```bash
uv run pytest backend/tests/test_skills.py backend/tests/test_skill_selector.py backend/tests/test_agent_loop.py -q
```

Expected: PASS.

- [ ] **Step 2: Run the full backend test suite**

Run:

```bash
uv run pytest
```

Expected: PASS. If unrelated pre-existing tests fail, capture the failing test names and error messages before deciding whether they are in scope.

- [ ] **Step 3: Run backend lint on modified service files**

Run:

```bash
uv run ruff check backend/app/services/skills.py backend/app/services/skill_selector.py backend/app/services/agent_loop.py backend/tests/test_skills.py backend/tests/test_skill_selector.py backend/tests/test_agent_loop.py
```

Expected: PASS.

- [ ] **Step 4: Inspect git diff for scope control**

Run:

```bash
git -c safe.directory=D:/codexP/aaa diff -- backend/app/services/skills.py backend/app/services/skill_selector.py backend/app/services/agent_loop.py backend/tests/test_skills.py backend/tests/test_skill_selector.py backend/tests/test_agent_loop.py docs/proposal.md
```

Expected:
- No changes under `skills/`.
- No changes to workflow step semantics.
- No model-controlled file path loading.
- `metadata["skill_selection"]` records selected skill, source, model choice, fallback choice, reason, confidence, and error.
- Existing fallback still chooses `lab4ai-auto-reproduct` for reproduce/GitHub tasks when model selection is unavailable or invalid.

---

## Self-Review

Spec coverage:
- Model-first selection is implemented by `SkillSelector.select()`.
- Rule fallback is implemented by `fallback_skill_name()` and `SkillSelector._fallback()`.
- Registry validation is implemented before accepting model output.
- Workflow path remains backend-controlled because Agent Loop only uses `skill.workflow_context`.
- Metadata recording is implemented by `SkillSelectionResult.to_metadata()` and `_select_skill_for_run()`.
- Tests cover success, missing model, unknown skill, low confidence, general fallback, and Agent Loop metadata wiring.

Placeholder scan:
- The plan contains concrete file paths, code snippets, commands, and expected results.
- The implementation tasks avoid open-ended instructions and keep changes within the approved scope.

Type consistency:
- `SkillSelectionResult.skill_name` is the runtime selected name.
- `SkillSelectionResult.to_metadata()` writes `selected_skill`.
- `AgentLoopManager._select_skill_for_run()` returns `(SkillDefinition | None, str, dict)`.
- `SkillDefinition.summary_for_selection()` returns JSON-serializable fields consumed by `SkillSelector`.
