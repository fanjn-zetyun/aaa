# Agent Runtime First Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 LOBSTER 从 workflow 主导执行迁移为通用 Agent Runtime 主导执行，并保留现有 Lab4AI、Skill、Tool、Workflow 能力的可回退路径。

**Architecture:** 新增 `backend/app/agent_runtime/` 作为 V3 runtime。第一阶段通过 feature flag 接入，不删除现有 `backend/app/services/agent_loop.py`、`tools.py`、`workflow.py` 行为；后续任务逐步把 tool-use、skill.invoke、workflow contract 和 recovery loop 接入新 runtime。

**Tech Stack:** Python 3.13、FastAPI、SQLAlchemy async、pytest、React + TypeScript + Vitest。

---

## Scope Check

本计划覆盖 Agent Runtime 主链路的第一轮可执行迁移。它不会修改 `skills/` 目录，也不会直接删除现有 `SkillWorkflowRunner`。所有生产入口先通过 `agent_runtime_v3_enabled` 控制，默认关闭，保证现有复现链路不被第一步破坏。

## File Structure

新增后端 runtime 包：

- Create: `backend/app/agent_runtime/__init__.py`：导出 runtime 公共类型。
- Create: `backend/app/agent_runtime/state.py`：运行状态、metadata 序列化、HITL/pending tool 状态。
- Create: `backend/app/agent_runtime/messages.py`：ConversationMessage 读写与 Anthropic messages 构造。
- Create: `backend/app/agent_runtime/llm.py`：模型请求/响应归一化。
- Create: `backend/app/agent_runtime/events.py`：runtime 事件 sink，适配现有 WebSocket publish。
- Create: `backend/app/agent_runtime/tool_protocol.py`：Tool 协议、schema 校验和 ToolResult block 映射。
- Create: `backend/app/agent_runtime/tool_executor.py`：统一执行 tool_use、权限、HITL、审计、tool_result。
- Create: `backend/app/agent_runtime/skills.py`：`skill.invoke` runtime tool。
- Create: `backend/app/agent_runtime/runtime.py`：AgentRuntime 主循环。
- Create: `backend/app/agent_runtime/workflows/__init__.py`：workflow contract 子包导出。
- Create: `backend/app/agent_runtime/workflows/contract.py`：workflow contract 兼容解析、状态推进和验收接口。

修改现有后端文件：

- Modify: `backend/app/core/config.py`：增加 `agent_runtime_v3_enabled` feature flag。
- Modify: `backend/app/services/agent_loop.py`：在 flag 开启时委托 `AgentRuntime`，关闭时保留现有逻辑。
- Modify: `backend/app/services/tools.py`：补齐 `ToolResult` 标准字段，保证 adapter 可读。
- Modify: `backend/app/services/llm_client.py`：只在必要时复用现有 `call_anthropic_compatible_tool_use`，不改变公开行为。

新增/修改测试：

- Create: `backend/tests/test_agent_runtime_state.py`
- Create: `backend/tests/test_agent_runtime_messages.py`
- Create: `backend/tests/test_agent_runtime_llm.py`
- Create: `backend/tests/test_agent_runtime_tool_executor.py`
- Create: `backend/tests/test_agent_runtime_runtime.py`
- Create: `backend/tests/test_agent_runtime_skills.py`
- Create: `backend/tests/test_agent_runtime_workflow_contract.py`
- Modify: `backend/tests/test_agent_loop.py`
- Modify: `frontend/src/__tests__/ChatPage.test.tsx`

## Task 1: Runtime Feature Flag 与包骨架

**Files:**
- Modify: `backend/app/core/config.py`
- Create: `backend/app/agent_runtime/__init__.py`
- Create: `backend/tests/test_agent_runtime_state.py`

- [ ] **Step 1: 写失败测试，验证 feature flag 默认关闭**

```python
# backend/tests/test_agent_runtime_state.py
from app.core.config import Settings


def test_agent_runtime_v3_feature_flag_defaults_to_disabled():
    settings = Settings()

    assert settings.agent_runtime_v3_enabled is False
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest backend/tests/test_agent_runtime_state.py::test_agent_runtime_v3_feature_flag_defaults_to_disabled -q`

Expected: FAIL，错误包含 `Settings` 没有 `agent_runtime_v3_enabled`。

- [ ] **Step 3: 增加配置字段**

在 `backend/app/core/config.py` 的 `skills_dir` 后加入：

```python
    agent_runtime_v3_enabled: bool = False
```

- [ ] **Step 4: 创建 runtime 包导出**

```python
# backend/app/agent_runtime/__init__.py
"""Agent Runtime V3 package."""

from app.agent_runtime.state import RuntimeState

__all__ = ["RuntimeState"]
```

此时 `RuntimeState` 还不存在，下一步测试会驱动创建它。

- [ ] **Step 5: 运行测试确认通过**

Run: `uv run pytest backend/tests/test_agent_runtime_state.py::test_agent_runtime_v3_feature_flag_defaults_to_disabled -q`

Expected: PASS。

## Task 2: RuntimeState 与 metadata 序列化

**Files:**
- Create: `backend/app/agent_runtime/state.py`
- Modify: `backend/tests/test_agent_runtime_state.py`

- [ ] **Step 1: 写 RuntimeState 创建和恢复测试**

追加到 `backend/tests/test_agent_runtime_state.py`：

```python
from app.agent_runtime.state import RuntimeState, load_runtime_state, save_runtime_state


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
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest backend/tests/test_agent_runtime_state.py -q`

Expected: FAIL，错误包含 `No module named 'app.agent_runtime.state'` 或缺少 `RuntimeState`。

- [ ] **Step 3: 实现 RuntimeState**

```python
# backend/app/agent_runtime/state.py
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal
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

    @classmethod
    def new(cls, *, conversation_id: int, model: str) -> "RuntimeState":
        return cls(
            run_id=f"runtime-{uuid4().hex}",
            conversation_id=conversation_id,
            status="running",
            model=model,
        )

    def can_continue(self) -> bool:
        return self.status == "running" and self.turn_count < self.max_turns

    def next_turn(self) -> "RuntimeState":
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
        )

    def mark_waiting_for_user(
        self,
        *,
        pending_tool_call: dict[str, Any],
        pending_user_input: dict[str, Any],
    ) -> "RuntimeState":
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
        status=str(raw.get("status") or "running"),  # type: ignore[arg-type]
        model=str(raw.get("model") or ""),
        max_turns=int(raw.get("max_turns") or 8),
        turn_count=int(raw.get("turn_count") or 0),
        active_skill=raw.get("active_skill") if isinstance(raw.get("active_skill"), dict) else None,
        active_workflow=raw.get("active_workflow") if isinstance(raw.get("active_workflow"), dict) else None,
        allowed_tools=[str(item) for item in raw.get("allowed_tools") or ["skill.invoke", "ask_user"]],
        pending_tool_call=raw.get("pending_tool_call") if isinstance(raw.get("pending_tool_call"), dict) else None,
        pending_user_input=raw.get("pending_user_input") if isinstance(raw.get("pending_user_input"), dict) else None,
        token_budget=dict(raw.get("token_budget") or {"planning": 2048, "final": 8192}),
        cleanup_required=bool(raw.get("cleanup_required") or False),
    )
```

- [ ] **Step 4: 运行测试确认通过**

Run: `uv run pytest backend/tests/test_agent_runtime_state.py -q`

Expected: PASS。

## Task 3: MessageStore 与模型消息构造

**Files:**
- Create: `backend/app/agent_runtime/messages.py`
- Create: `backend/tests/test_agent_runtime_messages.py`

- [ ] **Step 1: 写消息持久化和 Anthropic messages 测试**

```python
# backend/tests/test_agent_runtime_messages.py
import pytest

from app.agent_runtime.messages import MessageStore
from app.models import Conversation, ConversationMessage, ConversationStatus, ConversationTaskType, MessageRole


@pytest.mark.asyncio
async def test_message_store_appends_assistant_and_tool_result(db_session, test_user):
    conversation = Conversation(
        user_id=test_user.id,
        task_type=ConversationTaskType.GENERAL,
        title="runtime",
        status=ConversationStatus.RUNNING,
        metadata_={},
    )
    db_session.add(conversation)
    await db_session.commit()
    await db_session.refresh(conversation)

    store = MessageStore(db_session)
    await store.append_assistant(
        conversation.id,
        "我将调用工具。",
        metadata={"run_id": "run-1", "tool_calls": [{"id": "toolu_1", "name": "ask_user"}]},
    )
    await store.append_tool_result(
        conversation.id,
        tool_name="ask_user",
        content="已向用户提问。",
        metadata={"run_id": "run-1", "tool_call_id": "toolu_1", "ok": True},
    )

    rows = await store.list_messages(conversation.id)

    assert [row.role for row in rows] == [MessageRole.ASSISTANT, MessageRole.TOOL]
    assert rows[1].message_metadata["tool_call_id"] == "toolu_1"


@pytest.mark.asyncio
async def test_message_store_builds_model_messages(db_session, test_user):
    conversation = Conversation(
        user_id=test_user.id,
        task_type=ConversationTaskType.GENERAL,
        title="runtime",
        status=ConversationStatus.RUNNING,
        metadata_={},
    )
    db_session.add(conversation)
    await db_session.commit()
    await db_session.refresh(conversation)
    db_session.add(
        ConversationMessage(
            conversation_id=conversation.id,
            role=MessageRole.USER,
            content="你好",
            message_metadata={},
        )
    )
    await db_session.commit()

    store = MessageStore(db_session)

    assert await store.build_model_messages(conversation.id) == [{"role": "user", "content": "你好"}]
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest backend/tests/test_agent_runtime_messages.py -q`

Expected: FAIL，错误包含缺少 `MessageStore`。

- [ ] **Step 3: 实现 MessageStore**

```python
# backend/app/agent_runtime/messages.py
from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import ConversationMessage, MessageRole


class MessageStore:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list_messages(self, conversation_id: int) -> list[ConversationMessage]:
        result = await self.session.execute(
            select(ConversationMessage)
            .where(ConversationMessage.conversation_id == conversation_id)
            .order_by(ConversationMessage.created_at.asc(), ConversationMessage.id.asc())
        )
        return list(result.scalars().all())

    async def append_assistant(
        self,
        conversation_id: int,
        content: str,
        *,
        metadata: dict[str, Any],
    ) -> ConversationMessage:
        message = ConversationMessage(
            conversation_id=conversation_id,
            role=MessageRole.ASSISTANT,
            content=content,
            message_metadata=dict(metadata),
        )
        self.session.add(message)
        await self.session.commit()
        await self.session.refresh(message)
        return message

    async def append_tool_result(
        self,
        conversation_id: int,
        *,
        tool_name: str,
        content: str,
        metadata: dict[str, Any],
    ) -> ConversationMessage:
        message = ConversationMessage(
            conversation_id=conversation_id,
            role=MessageRole.TOOL,
            content=content,
            message_metadata={"tool_name": tool_name, **dict(metadata)},
        )
        self.session.add(message)
        await self.session.commit()
        await self.session.refresh(message)
        return message

    async def build_model_messages(self, conversation_id: int) -> list[dict[str, Any]]:
        messages = []
        for row in await self.list_messages(conversation_id):
            if row.role == MessageRole.USER:
                messages.append({"role": "user", "content": row.content})
            elif row.role == MessageRole.ASSISTANT:
                tool_calls = row.message_metadata.get("tool_calls")
                if tool_calls:
                    content: list[dict[str, Any]] = []
                    if row.content:
                        content.append({"type": "text", "text": row.content})
                    for call in tool_calls:
                        content.append(
                            {
                                "type": "tool_use",
                                "id": call["id"],
                                "name": call["name"],
                                "input": call.get("input") or {},
                            }
                        )
                    messages.append({"role": "assistant", "content": content})
                else:
                    messages.append({"role": "assistant", "content": row.content})
            elif row.role == MessageRole.TOOL:
                tool_call_id = str(row.message_metadata.get("tool_call_id") or "")
                messages.append(
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "tool_result",
                                "tool_use_id": tool_call_id,
                                "content": row.content,
                                "is_error": not bool(row.message_metadata.get("ok", True)),
                            }
                        ],
                    }
                )
        return messages
```

- [ ] **Step 4: 运行测试确认通过**

Run: `uv run pytest backend/tests/test_agent_runtime_messages.py -q`

Expected: PASS。

## Task 4: LLMAdapter 归一化

**Files:**
- Create: `backend/app/agent_runtime/llm.py`
- Create: `backend/tests/test_agent_runtime_llm.py`

- [ ] **Step 1: 写 fake LLM adapter 测试**

```python
# backend/tests/test_agent_runtime_llm.py
import pytest

from app.agent_runtime.llm import LLMAdapter, ModelRequest
from app.services.llm_client import LLMRuntimeConfig, LLMToolResponse, LLMToolUse


@pytest.mark.asyncio
async def test_llm_adapter_normalizes_tool_response(monkeypatch):
    async def fake_call(config, *, system, messages, tools):
        return LLMToolResponse(
            text="我需要调用工具。",
            tool_calls=[LLMToolUse(id="toolu_1", name="ask_user", input={"question": "继续吗？"})],
            stop_reason="tool_use",
            raw={"usage": {"input_tokens": 10, "output_tokens": 5}},
        )

    monkeypatch.setattr("app.agent_runtime.llm.call_anthropic_compatible_tool_use", fake_call)
    adapter = LLMAdapter(
        LLMRuntimeConfig(
            provider="anthropic",
            base_url="https://example.com",
            api_key="key",
            model="claude-test",
            max_tokens=4096,
        )
    )

    response = await adapter.complete(
        ModelRequest(
            system="system",
            messages=[{"role": "user", "content": "hi"}],
            tools=[{"name": "ask_user", "description": "ask", "input_schema": {"type": "object"}}],
            max_tokens=2048,
        )
    )

    assert response.text == "我需要调用工具。"
    assert response.tool_calls[0].name == "ask_user"
    assert response.usage == {"input_tokens": 10, "output_tokens": 5}
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest backend/tests/test_agent_runtime_llm.py -q`

Expected: FAIL，缺少 `app.agent_runtime.llm`。

- [ ] **Step 3: 实现 LLMAdapter**

```python
# backend/app/agent_runtime/llm.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.services.llm_client import LLMRuntimeConfig, LLMToolUse, call_anthropic_compatible_tool_use


@dataclass(slots=True)
class ModelRequest:
    system: str
    messages: list[dict[str, Any]]
    tools: list[dict[str, Any]]
    max_tokens: int
    tool_choice: dict[str, Any] | None = None
    temperature: float | None = None


@dataclass(slots=True)
class ModelResponse:
    text: str
    tool_calls: list[LLMToolUse]
    stop_reason: str | None
    usage: dict[str, Any]
    raw: dict[str, Any]


class LLMAdapter:
    def __init__(self, config: LLMRuntimeConfig) -> None:
        self.config = config

    async def complete(self, request: ModelRequest) -> ModelResponse:
        if not self.config.configured:
            raise RuntimeError("模型配置不完整，无法启动 Agent Runtime。")
        runtime_config = LLMRuntimeConfig(
            provider=self.config.provider,
            base_url=self.config.base_url,
            api_key=self.config.api_key,
            model=self.config.model,
            max_tokens=request.max_tokens,
        )
        response = await call_anthropic_compatible_tool_use(
            runtime_config,
            system=request.system,
            messages=request.messages,
            tools=request.tools,
        )
        raw = response.raw or {}
        usage = raw.get("usage") if isinstance(raw.get("usage"), dict) else {}
        return ModelResponse(
            text=response.text,
            tool_calls=list(response.tool_calls),
            stop_reason=response.stop_reason,
            usage=dict(usage),
            raw=raw,
        )
```

- [ ] **Step 4: 运行测试确认通过**

Run: `uv run pytest backend/tests/test_agent_runtime_llm.py -q`

Expected: PASS。

## Task 5: ToolProtocol Adapter 与 schema 校验

**Files:**
- Create: `backend/app/agent_runtime/tool_protocol.py`
- Modify: `backend/app/services/tools.py`
- Create: `backend/tests/test_agent_runtime_tool_executor.py`

- [ ] **Step 1: 写 Tool adapter schema 测试**

```python
# backend/tests/test_agent_runtime_tool_executor.py
from app.agent_runtime.tool_protocol import RegistryToolAdapter, validate_tool_input
from app.services.tools import ToolDefinition, ToolResult


def test_validate_tool_input_reports_missing_required_property():
    schema = {
        "type": "object",
        "required": ["question"],
        "properties": {"question": {"type": "string"}},
    }

    result = validate_tool_input(schema, {})

    assert result.ok is False
    assert result.error == "缺少必填参数：question"


def test_registry_tool_adapter_maps_result_to_tool_result_block():
    definition = ToolDefinition(
        name="ask_user",
        description="ask",
        input_schema={"type": "object", "properties": {"question": {"type": "string"}}},
        read_only=True,
    )
    adapter = RegistryToolAdapter(definition)

    block = adapter.to_tool_result_block(
        ToolResult("ask_user", "已提问", ok=True, metadata={"answer_required": True}),
        tool_call_id="toolu_1",
    )

    assert block == {
        "type": "tool_result",
        "tool_use_id": "toolu_1",
        "content": "已提问",
        "is_error": False,
    }
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest backend/tests/test_agent_runtime_tool_executor.py::test_validate_tool_input_reports_missing_required_property backend/tests/test_agent_runtime_tool_executor.py::test_registry_tool_adapter_maps_result_to_tool_result_block -q`

Expected: FAIL，缺少 `tool_protocol`。

- [ ] **Step 3: 补齐 ToolResult 标准字段**

在 `backend/app/services/tools.py` 的 `ToolResult` dataclass 中保留现有字段，并增加标准字段。目标结构：

```python
@dataclass(slots=True)
class ToolResult:
    name: str
    content: str
    ok: bool = True
    metadata: dict[str, Any] = field(default_factory=dict)
    error_code: str | None = None
    retryable: bool | None = None
    recovery_suggestion: str | None = None
```

如果现有字段顺序不同，保持向后兼容：所有旧调用 `ToolResult(name, content, metadata={"error_code": "sample"})` 必须继续可用。

- [ ] **Step 4: 实现 ToolProtocol adapter**

```python
# backend/app/agent_runtime/tool_protocol.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.services.tools import ToolDefinition, ToolResult


@dataclass(slots=True)
class ValidationResult:
    ok: bool
    error: str = ""


def validate_tool_input(schema: dict[str, Any], value: dict[str, Any]) -> ValidationResult:
    if schema.get("type") not in (None, "object"):
        return ValidationResult(False, "工具 input_schema 必须是 object。")
    required = schema.get("required") or []
    for key in required:
        if key not in value:
            return ValidationResult(False, f"缺少必填参数：{key}")
    properties = schema.get("properties") or {}
    for key, raw_schema in properties.items():
        if key not in value or not isinstance(raw_schema, dict):
            continue
        expected = raw_schema.get("type")
        actual = value[key]
        if expected == "string" and not isinstance(actual, str):
            return ValidationResult(False, f"参数 `{key}` 必须是 string。")
        if expected == "number" and not isinstance(actual, int | float):
            return ValidationResult(False, f"参数 `{key}` 必须是 number。")
        if expected == "integer" and not isinstance(actual, int):
            return ValidationResult(False, f"参数 `{key}` 必须是 integer。")
        if expected == "boolean" and not isinstance(actual, bool):
            return ValidationResult(False, f"参数 `{key}` 必须是 boolean。")
        if expected == "array" and not isinstance(actual, list):
            return ValidationResult(False, f"参数 `{key}` 必须是 array。")
        if expected == "object" and not isinstance(actual, dict):
            return ValidationResult(False, f"参数 `{key}` 必须是 object。")
    return ValidationResult(True)


class RegistryToolAdapter:
    def __init__(self, definition: ToolDefinition) -> None:
        self.definition = definition
        self.name = definition.name

    def anthropic_schema(self) -> dict[str, Any]:
        return self.definition.anthropic_schema()

    def validate_input(self, input_value: dict[str, Any]) -> ValidationResult:
        return validate_tool_input(self.definition.input_schema, input_value)

    def to_tool_result_block(self, result: ToolResult, *, tool_call_id: str) -> dict[str, Any]:
        return {
            "type": "tool_result",
            "tool_use_id": tool_call_id,
            "content": result.content,
            "is_error": not result.ok,
        }
```

- [ ] **Step 5: 运行测试确认通过，并确认旧 Tool 测试不退化**

Run: `uv run pytest backend/tests/test_agent_runtime_tool_executor.py::test_validate_tool_input_reports_missing_required_property backend/tests/test_agent_runtime_tool_executor.py::test_registry_tool_adapter_maps_result_to_tool_result_block backend/tests/test_tools.py -q`

Expected: PASS。

## Task 6: ToolExecutor 基础执行、allowlist、错误回流

**Files:**
- Create: `backend/app/agent_runtime/events.py`
- Create: `backend/app/agent_runtime/tool_executor.py`
- Modify: `backend/tests/test_agent_runtime_tool_executor.py`

- [ ] **Step 1: 写 ToolExecutor allowlist 和 schema 错误测试**

追加到 `backend/tests/test_agent_runtime_tool_executor.py`：

```python
import pytest

from app.agent_runtime.events import ListEventSink
from app.agent_runtime.state import RuntimeState
from app.agent_runtime.tool_executor import ToolExecutor
from app.services.llm_client import LLMToolUse
from app.services.tools import ToolDefinition, ToolResult


class FakeRegistry:
    def __init__(self):
        self.definitions = {
            "ask_user": ToolDefinition(
                name="ask_user",
                description="ask",
                input_schema={
                    "type": "object",
                    "required": ["question"],
                    "properties": {"question": {"type": "string"}},
                },
                read_only=True,
            )
        }

    def definition(self, name):
        return self.definitions[name]

    def list_definitions(self, allowed_tools=None):
        allowed = set(allowed_tools or [])
        return [item for item in self.definitions.values() if not allowed or item.name in allowed]

    def confirmation_for(self, name, tool_input):
        return None

    async def invoke(self, name, tool_input, context=None):
        return ToolResult(name, f"called {name}", ok=True, metadata={"echo": tool_input})


@pytest.mark.asyncio
async def test_tool_executor_rejects_tool_outside_allowlist():
    state = RuntimeState.new(conversation_id=1, model="claude-test")
    state.allowed_tools = ["skill.invoke"]
    events = ListEventSink()
    executor = ToolExecutor(registry=FakeRegistry(), event_sink=events)

    result = await executor.execute_one(
        LLMToolUse(id="toolu_1", name="ask_user", input={"question": "继续吗？"}),
        state=state,
    )

    assert result.paused is False
    assert result.tool_result.ok is False
    assert result.tool_result.metadata["error_code"] == "tool_not_allowed"
    assert result.tool_result_block["is_error"] is True


@pytest.mark.asyncio
async def test_tool_executor_returns_schema_error_as_tool_result():
    state = RuntimeState.new(conversation_id=1, model="claude-test")
    state.allowed_tools = ["ask_user"]
    executor = ToolExecutor(registry=FakeRegistry(), event_sink=ListEventSink())

    result = await executor.execute_one(
        LLMToolUse(id="toolu_1", name="ask_user", input={}),
        state=state,
    )

    assert result.paused is False
    assert result.tool_result.ok is False
    assert result.tool_result.metadata["error_code"] == "invalid_tool_input"
    assert "缺少必填参数" in result.tool_result.content
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest backend/tests/test_agent_runtime_tool_executor.py -q`

Expected: FAIL，缺少 `events` 或 `tool_executor`。

- [ ] **Step 3: 实现事件 sink**

```python
# backend/app/agent_runtime/events.py
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable


class EventSink:
    async def publish(self, event: dict[str, Any]) -> None:
        raise NotImplementedError


@dataclass(slots=True)
class ListEventSink(EventSink):
    events: list[dict[str, Any]] = field(default_factory=list)

    async def publish(self, event: dict[str, Any]) -> None:
        self.events.append(dict(event))


class CallbackEventSink(EventSink):
    def __init__(self, callback: Callable[[dict[str, Any]], Awaitable[None] | None]) -> None:
        self.callback = callback

    async def publish(self, event: dict[str, Any]) -> None:
        result = self.callback(dict(event))
        if result is not None:
            await result
```

- [ ] **Step 4: 实现 ToolExecutor 基础逻辑**

```python
# backend/app/agent_runtime/tool_executor.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.agent_runtime.events import EventSink
from app.agent_runtime.state import RuntimeState
from app.agent_runtime.tool_protocol import RegistryToolAdapter
from app.services.llm_client import LLMToolUse
from app.services.tools import ToolExecutionContext, ToolRegistry, ToolResult


@dataclass(slots=True)
class ExecutedToolResult:
    tool_call_id: str
    tool_name: str
    tool_result: ToolResult
    tool_result_block: dict[str, Any]
    paused: bool = False
    updated_state: RuntimeState | None = None


class ToolExecutor:
    def __init__(self, *, registry: ToolRegistry, event_sink: EventSink) -> None:
        self.registry = registry
        self.event_sink = event_sink

    async def execute_one(
        self,
        tool_call: LLMToolUse,
        *,
        state: RuntimeState,
        context: ToolExecutionContext | None = None,
    ) -> ExecutedToolResult:
        if tool_call.name not in set(state.allowed_tools):
            result = ToolResult(
                tool_call.name,
                f"工具 `{tool_call.name}` 不在当前 allowlist 中，已拒绝执行。",
                ok=False,
                metadata={"error_code": "tool_not_allowed", "retryable": False},
            )
            return self._as_executed(tool_call, result)

        try:
            definition = self.registry.definition(tool_call.name)
        except Exception:
            result = ToolResult(
                tool_call.name,
                f"未知工具：{tool_call.name}",
                ok=False,
                metadata={"error_code": "unknown_tool", "retryable": False},
            )
            return self._as_executed(tool_call, result)

        adapter = RegistryToolAdapter(definition)
        validation = adapter.validate_input(tool_call.input)
        if not validation.ok:
            result = ToolResult(
                tool_call.name,
                validation.error,
                ok=False,
                metadata={"error_code": "invalid_tool_input", "retryable": True},
            )
            return self._as_executed(tool_call, result)

        confirmation = self.registry.confirmation_for(
            tool_call.name,
            {
                **tool_call.input,
                "workflow_run_id": state.run_id,
                "tool_call_id": tool_call.id,
                "workflow_step_id": _workflow_step_id(state),
            },
        )
        if confirmation:
            pending = confirmation.as_pending_input()
            updated_state = state.mark_waiting_for_user(
                pending_tool_call={
                    "tool_call_id": tool_call.id,
                    "tool_name": tool_call.name,
                    "workflow_step_id": pending.get("workflow_step_id"),
                },
                pending_user_input=pending,
            )
            result = ToolResult(
                tool_call.name,
                confirmation.question,
                ok=False,
                metadata={"error_code": "waiting_for_user", "retryable": True},
            )
            executed = self._as_executed(tool_call, result)
            executed.paused = True
            executed.updated_state = updated_state
            await self.event_sink.publish({"type": "permission_requested", **pending})
            return executed

        await self.event_sink.publish(
            {
                "type": "tool_started",
                "tool_name": tool_call.name,
                "tool_call_id": tool_call.id,
                "workflow_step_id": _workflow_step_id(state),
            }
        )
        result = await self.registry.invoke(
            tool_call.name,
            {
                **tool_call.input,
                "workflow_run_id": state.run_id,
                "tool_call_id": tool_call.id,
                "workflow_step_id": _workflow_step_id(state),
            },
            context=context,
        )
        await self.event_sink.publish(
            {
                "type": "tool_completed" if result.ok else "tool_error",
                "tool_name": tool_call.name,
                "tool_call_id": tool_call.id,
                "workflow_step_id": _workflow_step_id(state),
                "ok": result.ok,
            }
        )
        return self._as_executed(tool_call, result)

    def _as_executed(self, tool_call: LLMToolUse, result: ToolResult) -> ExecutedToolResult:
        definition = self.registry.definition(tool_call.name) if tool_call.name in _registry_names(self.registry) else None
        block = {
            "type": "tool_result",
            "tool_use_id": tool_call.id,
            "content": result.content,
            "is_error": not result.ok,
        }
        if definition:
            block = RegistryToolAdapter(definition).to_tool_result_block(result, tool_call_id=tool_call.id)
        return ExecutedToolResult(
            tool_call_id=tool_call.id,
            tool_name=tool_call.name,
            tool_result=result,
            tool_result_block=block,
        )


def _workflow_step_id(state: RuntimeState) -> str | None:
    workflow = state.active_workflow or {}
    current = workflow.get("current_step_id")
    return str(current) if current else None


def _registry_names(registry: ToolRegistry) -> set[str]:
    try:
        return {item.name for item in registry.list_definitions()}
    except Exception:
        return set()
```

- [ ] **Step 5: 运行测试确认通过**

Run: `uv run pytest backend/tests/test_agent_runtime_tool_executor.py -q`

Expected: PASS。

## Task 7: AgentRuntime 主循环最小闭环

**Files:**
- Create: `backend/app/agent_runtime/runtime.py`
- Create: `backend/tests/test_agent_runtime_runtime.py`

- [ ] **Step 1: 写 fake model + fake tool 的多轮 runtime 测试**

```python
# backend/tests/test_agent_runtime_runtime.py
import pytest

from app.agent_runtime.events import ListEventSink
from app.agent_runtime.llm import ModelResponse
from app.agent_runtime.runtime import AgentRuntime
from app.models import Conversation, ConversationStatus, ConversationTaskType
from app.services.llm_client import LLMToolUse


class FakeLLM:
    def __init__(self):
        self.calls = 0

    async def complete(self, request):
        self.calls += 1
        if self.calls == 1:
            return ModelResponse(
                text="需要询问用户。",
                tool_calls=[LLMToolUse(id="toolu_1", name="ask_user", input={"question": "继续吗？"})],
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


@pytest.mark.asyncio
async def test_agent_runtime_runs_tool_loop_until_final_answer(db_session, test_user):
    conversation = Conversation(
        user_id=test_user.id,
        task_type=ConversationTaskType.GENERAL,
        title="runtime",
        status=ConversationStatus.RUNNING,
        metadata_={},
    )
    db_session.add(conversation)
    await db_session.commit()
    await db_session.refresh(conversation)

    events = ListEventSink()
    runtime = AgentRuntime.for_test(session=db_session, llm=FakeLLM(), event_sink=events)

    result = await runtime.run_conversation(conversation.id, model="claude-test")

    assert result.status == "completed"
    assert result.final_text == "完成。"
    assert [event["type"] for event in events.events if event["type"].startswith("runtime_")] == [
        "runtime_started",
        "runtime_completed",
    ]
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest backend/tests/test_agent_runtime_runtime.py -q`

Expected: FAIL，缺少 `AgentRuntime`。

- [ ] **Step 3: 实现 AgentRuntime**

```python
# backend/app/agent_runtime/runtime.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.agent_runtime.events import EventSink, ListEventSink
from app.agent_runtime.llm import LLMAdapter, ModelRequest
from app.agent_runtime.messages import MessageStore
from app.agent_runtime.state import RuntimeState, save_runtime_state
from app.agent_runtime.tool_executor import ToolExecutor
from app.models import Conversation, ConversationStatus
from app.services.tools import ToolRegistry


@dataclass(slots=True)
class RuntimeRunResult:
    status: str
    final_text: str
    metadata: dict[str, Any]


class AgentRuntime:
    def __init__(
        self,
        *,
        session: AsyncSession,
        llm: LLMAdapter,
        tool_executor: ToolExecutor,
        event_sink: EventSink,
    ) -> None:
        self.session = session
        self.llm = llm
        self.tool_executor = tool_executor
        self.event_sink = event_sink

    @classmethod
    def for_test(cls, *, session: AsyncSession, llm, event_sink: EventSink | None = None) -> "AgentRuntime":
        sink = event_sink or ListEventSink()
        return cls(
            session=session,
            llm=llm,
            tool_executor=ToolExecutor(registry=ToolRegistry(), event_sink=sink),
            event_sink=sink,
        )

    async def run_conversation(self, conversation_id: int, *, model: str) -> RuntimeRunResult:
        conversation = await self.session.get(Conversation, conversation_id)
        if conversation is None:
            raise RuntimeError(f"Conversation not found: {conversation_id}")

        state = RuntimeState.new(conversation_id=conversation_id, model=model)
        conversation.metadata_ = save_runtime_state(conversation.metadata_ or {}, state)
        conversation.status = ConversationStatus.RUNNING
        await self.session.commit()
        await self.event_sink.publish({"type": "runtime_started", "run_id": state.run_id})

        store = MessageStore(self.session)
        final_text = ""
        while state.can_continue():
            messages = await store.build_model_messages(conversation_id)
            response = await self.llm.complete(
                ModelRequest(
                    system=_system_prompt(state),
                    messages=messages,
                    tools=[item for item in self._tool_schemas(state)],
                    max_tokens=state.token_budget["planning"],
                )
            )
            await store.append_assistant(
                conversation_id,
                response.text,
                metadata={
                    "run_id": state.run_id,
                    "tool_calls": [
                        {"id": call.id, "name": call.name, "input": call.input}
                        for call in response.tool_calls
                    ],
                    "usage": response.usage,
                },
            )
            if not response.tool_calls:
                final_text = response.text
                state.status = "completed"
                break

            for tool_call in response.tool_calls:
                executed = await self.tool_executor.execute_one(tool_call, state=state)
                await store.append_tool_result(
                    conversation_id,
                    tool_name=executed.tool_name,
                    content=executed.tool_result.content,
                    metadata={
                        "run_id": state.run_id,
                        "tool_call_id": executed.tool_call_id,
                        "ok": executed.tool_result.ok,
                        **(executed.tool_result.metadata or {}),
                    },
                )
                if executed.paused and executed.updated_state:
                    state = executed.updated_state
                    break
            if state.status == "waiting_for_user":
                break
            state = state.next_turn()

        conversation.metadata_ = save_runtime_state(conversation.metadata_ or {}, state)
        conversation.status = ConversationStatus.COMPLETED if state.status == "completed" else ConversationStatus.ACTIVE
        await self.session.commit()
        if state.status == "completed":
            await self.event_sink.publish({"type": "runtime_completed", "run_id": state.run_id})
        return RuntimeRunResult(status=state.status, final_text=final_text, metadata=conversation.metadata_)

    def _tool_schemas(self, state: RuntimeState) -> list[dict[str, Any]]:
        return self.tool_executor.registry.list_anthropic_tools(state.allowed_tools)


def _system_prompt(state: RuntimeState) -> str:
    return (
        "你是 LOBSTER Agent Runtime。所有副作用必须通过后端 Tool 执行。"
        f"当前 run_id：{state.run_id}。"
    )
```

- [ ] **Step 4: 运行测试确认通过**

Run: `uv run pytest backend/tests/test_agent_runtime_runtime.py -q`

Expected: PASS。

## Task 8: AgentLoopManager Feature Flag 委托

**Files:**
- Modify: `backend/app/services/agent_loop.py`
- Modify: `backend/tests/test_agent_loop.py`

- [ ] **Step 1: 写 flag 开启时委托 AgentRuntime 的测试**

追加到 `backend/tests/test_agent_loop.py`：

```python
@pytest.mark.asyncio
async def test_agent_loop_delegates_to_agent_runtime_when_v3_flag_enabled(monkeypatch):
    calls = []

    class FakeSettings:
        agent_runtime_v3_enabled = True
        skills_dir_path = "skills"

    class FakeRuntime:
        async def run_conversation(self, conversation_id, *, model):
            calls.append((conversation_id, model))
            return None

    monkeypatch.setattr("app.services.agent_loop.get_settings", lambda: FakeSettings())
    monkeypatch.setattr("app.services.agent_loop.AgentRuntime", lambda **kwargs: FakeRuntime())

    manager = AgentLoopManager()
    config = LLMRuntimeConfig(
        provider="anthropic",
        base_url="https://example.com",
        api_key="key",
        model="claude-test",
        max_tokens=4096,
    )
    handled = await manager._run_with_agent_runtime_v3(conversation_id=123, config=config)

    assert handled is True
    assert calls == [(123, "claude-test")]
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest backend/tests/test_agent_loop.py::test_agent_loop_delegates_to_agent_runtime_when_v3_flag_enabled -q`

Expected: FAIL，缺少 `AgentRuntime` 导入或 `_run_with_agent_runtime_v3`。

- [ ] **Step 3: 增加委托方法**

在 `backend/app/services/agent_loop.py` 顶部 import 区加入：

```python
from app.agent_runtime.runtime import AgentRuntime
from app.agent_runtime.events import CallbackEventSink
from app.agent_runtime.llm import LLMAdapter
from app.agent_runtime.tool_executor import ToolExecutor
```

在 `AgentLoopManager` 内新增：

```python
    async def _run_with_agent_runtime_v3(self, *, conversation_id: int, config: LLMRuntimeConfig) -> bool:
        settings = get_settings()
        if not settings.agent_runtime_v3_enabled:
            return False
        if not config.configured:
            return False
        async with SessionLocal() as session:
            event_sink = CallbackEventSink(lambda event: self._publish(conversation_id, event))
            runtime = AgentRuntime(
                session=session,
                llm=LLMAdapter(config),
                tool_executor=ToolExecutor(registry=self._tools, event_sink=event_sink),
                event_sink=event_sink,
            )
            await runtime.run_conversation(conversation_id, model=config.model)
        return True
```

- [ ] **Step 4: 在 `_run` 开头接入 flag**

在 `_run()` 已执行 `llm_config = await _load_llm_config(user_id)` 后、进入旧 skill/workflow 选择前调用：

```python
if await self._run_with_agent_runtime_v3(conversation_id=conversation_id, config=llm_config):
    return
```

这个调用必须在已确认 `config.configured` 之后执行，避免未配置模型时改变现有错误提示。

- [ ] **Step 5: 运行测试确认通过，并跑旧 Agent Loop 测试**

Run: `uv run pytest backend/tests/test_agent_loop.py -q`

Expected: PASS。

## Task 9: SkillTool 作为 runtime tool

**Files:**
- Create: `backend/app/agent_runtime/skills.py`
- Modify: `backend/app/agent_runtime/tool_executor.py`
- Create: `backend/tests/test_agent_runtime_skills.py`

- [ ] **Step 1: 写 `skill.invoke` 更新 runtime state 的测试**

```python
# backend/tests/test_agent_runtime_skills.py
import pytest

from app.agent_runtime.skills import SkillInvokeTool
from app.agent_runtime.state import RuntimeState
from app.services.skills import SkillDefinition
from app.services.tools import ToolResult


@pytest.mark.asyncio
async def test_skill_invoke_sets_active_skill_and_allowed_tools(tmp_path):
    skill = SkillDefinition(
        name="demo-skill",
        description="demo",
        triggers=["demo"],
        when_to_use="demo task",
        allowed_tools=["ask_user"],
        body="执行 demo skill。",
        base_dir=tmp_path,
        workflow_context="",
    )
    tool = SkillInvokeTool({"demo-skill": skill})
    state = RuntimeState.new(conversation_id=1, model="claude-test")

    result, updated = await tool.call({"skill": "demo-skill", "args": {}}, state=state)

    assert isinstance(result, ToolResult)
    assert result.ok is True
    assert updated.active_skill["name"] == "demo-skill"
    assert updated.allowed_tools == ["ask_user", "skill.invoke"]
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest backend/tests/test_agent_runtime_skills.py -q`

Expected: FAIL，缺少 `SkillInvokeTool`。

- [ ] **Step 3: 实现 SkillInvokeTool**

```python
# backend/app/agent_runtime/skills.py
from __future__ import annotations

from typing import Any

from app.agent_runtime.state import RuntimeState
from app.services.skills import SkillDefinition
from app.services.tools import ToolDefinition, ToolResult


class SkillInvokeTool:
    name = "skill.invoke"

    def __init__(self, skills: dict[str, SkillDefinition]) -> None:
        self.skills = skills
        self.definition = ToolDefinition(
            name=self.name,
            description="加载一个 skill，并把 skill 指令、workflow contract 和 allowed tools 注入当前 Agent Runtime。",
            input_schema={
                "type": "object",
                "required": ["skill"],
                "properties": {
                    "skill": {"type": "string"},
                    "args": {"type": "object"},
                },
            },
            read_only=True,
            confirmation_policy="never",
            risk_level="low",
            audit_category="skill",
        )

    async def call(self, input_value: dict[str, Any], *, state: RuntimeState) -> tuple[ToolResult, RuntimeState]:
        skill_name = str(input_value.get("skill") or "").strip()
        skill = self.skills.get(skill_name)
        if not skill:
            return (
                ToolResult(
                    self.name,
                    f"未知 skill：{skill_name}",
                    ok=False,
                    metadata={"error_code": "unknown_skill", "retryable": True},
                ),
                state,
            )
        updated = state.next_turn()
        updated.active_skill = {
            "name": skill.name,
            "description": skill.description,
            "body": skill.body,
            "workflow_context": skill.workflow_context,
            "args": input_value.get("args") or {},
        }
        updated.allowed_tools = list(dict.fromkeys([*skill.allowed_tools, "skill.invoke", "ask_user"]))
        return (
            ToolResult(
                self.name,
                f"Launching skill: {skill.name}",
                ok=True,
                metadata={
                    "skill": skill.name,
                    "allowed_tools": list(updated.allowed_tools),
                    "workflow_contract_loaded": bool(skill.workflow_context),
                },
            ),
            updated,
        )
```

- [ ] **Step 4: 修改 ToolExecutor 优先处理 runtime tools**

在 `ToolExecutor.__init__` 增加参数：

```python
runtime_tools: dict[str, object] | None = None
```

并保存：

```python
self.runtime_tools = dict(runtime_tools or {})
```

在 `execute_one()` allowlist 校验后、registry lookup 前加入：

```python
runtime_tool = self.runtime_tools.get(tool_call.name)
if runtime_tool is not None:
    result, updated_state = await runtime_tool.call(tool_call.input, state=state)
    executed = self._as_executed(tool_call, result)
    executed.updated_state = updated_state
    return executed
```

`_as_executed()` 对 runtime tool 没有 registry definition 时保留通用 block。

- [ ] **Step 5: 运行 skill 和 tool executor 测试**

Run: `uv run pytest backend/tests/test_agent_runtime_skills.py backend/tests/test_agent_runtime_tool_executor.py -q`

Expected: PASS。

## Task 10: ContextBuilder 合并 skill / workflow 上下文

**Files:**
- Create: `backend/app/agent_runtime/context.py`
- Modify: `backend/app/agent_runtime/runtime.py`
- Create: `backend/tests/test_agent_runtime_context.py`

- [ ] **Step 1: 写 context 生成测试**

```python
# backend/tests/test_agent_runtime_context.py
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
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest backend/tests/test_agent_runtime_context.py -q`

Expected: FAIL，缺少 `ContextBuilder`。

- [ ] **Step 3: 实现 ContextBuilder**

```python
# backend/app/agent_runtime/context.py
from __future__ import annotations

from app.agent_runtime.state import RuntimeState


class ContextBuilder:
    def build_system_prompt(self, state: RuntimeState) -> str:
        parts = [
            "你是 LOBSTER Agent Runtime。",
            "所有会产生副作用、费用、远程执行或文件写入的动作都必须通过后端 Tool。",
            "不要要求用户提供 Lab4AI 密码、SSH 密码或 API Key；这些由后端凭证服务读取。",
            f"当前 run_id：{state.run_id}",
        ]
        if state.active_skill:
            parts.extend(
                [
                    "",
                    f"已激活 skill：{state.active_skill.get('name')}",
                    str(state.active_skill.get("body") or ""),
                ]
            )
        workflow = state.active_workflow or {}
        current_step_id = workflow.get("current_step_id")
        steps = workflow.get("steps") if isinstance(workflow.get("steps"), dict) else {}
        current_step = steps.get(current_step_id) if current_step_id else None
        if isinstance(current_step, dict):
            parts.extend(
                [
                    "",
                    f"当前 workflow step：{current_step_id}",
                    f"instruction：{current_step.get('instruction') or ''}",
                    f"expected_output：{current_step.get('expected_output') or ''}",
                    "只能调用当前 runtime allowed_tools 中的工具。",
                ]
            )
        return "\n".join(part for part in parts if part is not None)
```

- [ ] **Step 4: Runtime 使用 ContextBuilder**

在 `backend/app/agent_runtime/runtime.py` 中引入：

```python
from app.agent_runtime.context import ContextBuilder
```

在 `AgentRuntime.__init__` 增加：

```python
self.context_builder = ContextBuilder()
```

把 `_system_prompt(state)` 替换为：

```python
system=self.context_builder.build_system_prompt(state)
```

- [ ] **Step 5: 运行 context 和 runtime 测试**

Run: `uv run pytest backend/tests/test_agent_runtime_context.py backend/tests/test_agent_runtime_runtime.py -q`

Expected: PASS。

## Task 11: WorkflowContractRuntime 兼容层

**Files:**
- Create: `backend/app/agent_runtime/workflows/__init__.py`
- Create: `backend/app/agent_runtime/workflows/contract.py`
- Create: `backend/tests/test_agent_runtime_workflow_contract.py`

- [ ] **Step 1: 写 workflow contract 兼容解析测试**

```python
# backend/tests/test_agent_runtime_workflow_contract.py
from pathlib import Path

from app.agent_runtime.workflows.contract import WorkflowContractRuntime
from app.agent_runtime.state import RuntimeState


def test_workflow_contract_loads_current_project_reproduce_without_modifying_skills():
    raw = Path("skills/lab4ai-auto-reproduct/project_reproduce.yaml").read_text(encoding="utf-8")
    state = RuntimeState.new(conversation_id=1, model="claude-test")

    updated = WorkflowContractRuntime().activate(raw, state=state)

    assert updated.active_workflow["name"]
    assert updated.active_workflow["current_step_id"] == "step_1_audit"
    assert "step_1_audit" in updated.active_workflow["steps"]
    assert updated.active_workflow["steps"]["step_1_audit"]["instruction"]
    assert updated.allowed_tools
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest backend/tests/test_agent_runtime_workflow_contract.py -q`

Expected: FAIL，缺少 workflow contract 模块。

- [ ] **Step 3: 实现 compatibility contract**

```python
# backend/app/agent_runtime/workflows/__init__.py
"""Workflow contract runtime for Agent Runtime V3."""

from app.agent_runtime.workflows.contract import WorkflowContractRuntime

__all__ = ["WorkflowContractRuntime"]
```

```python
# backend/app/agent_runtime/workflows/contract.py
from __future__ import annotations

from typing import Any

from app.agent_runtime.state import RuntimeState
from app.services.workflow import parse_workflow, public_workflow_steps


class WorkflowContractRuntime:
    def activate(self, raw_workflow: str, *, state: RuntimeState) -> RuntimeState:
        workflow = parse_workflow(raw_workflow)
        public_steps = public_workflow_steps(workflow)
        steps: dict[str, dict[str, Any]] = {}
        for item in public_steps:
            step_id = str(item["id"])
            steps[step_id] = {
                "id": step_id,
                "name": item.get("name") or step_id,
                "instruction": item.get("instruction") or "",
                "expected_output": item.get("expected_output") or "",
                "depends_on": list(item.get("depends_on") or []),
                "allowed_tools": list(item.get("allowed_tools") or []),
                "required_tools": list((item.get("contract") or {}).get("required_tools") or []),
                "required_evidence": list((item.get("contract") or {}).get("required_evidence") or []),
            }
        current_step_id = public_steps[0]["id"] if public_steps else ""
        updated = state.next_turn()
        updated.active_workflow = {
            "name": workflow.name,
            "version": workflow.version,
            "current_step_id": current_step_id,
            "steps": steps,
            "compatibility_mode": True,
        }
        current_tools = steps.get(current_step_id, {}).get("allowed_tools") or []
        updated.allowed_tools = list(dict.fromkeys([*current_tools, "skill.invoke", "ask_user"]))
        return updated
```

- [ ] **Step 4: 运行测试确认通过**

Run: `uv run pytest backend/tests/test_agent_runtime_workflow_contract.py -q`

Expected: PASS。

## Task 12: SkillTool 自动激活 workflow contract

**Files:**
- Modify: `backend/app/agent_runtime/skills.py`
- Modify: `backend/tests/test_agent_runtime_skills.py`

- [ ] **Step 1: 写 skill.invoke 加载 workflow 的测试**

追加到 `backend/tests/test_agent_runtime_skills.py`：

```python
@pytest.mark.asyncio
async def test_skill_invoke_activates_workflow_contract(tmp_path):
    workflow = """
version: agent-workflow/v1
name: Demo
description: Demo workflow
tasks:
  - id: step_1_audit
    name: Audit
    instruction: |
      分析仓库。
    expected_output: |
      输出审计。
"""
    skill = SkillDefinition(
        name="workflow-skill",
        description="workflow",
        triggers=["workflow"],
        when_to_use="workflow task",
        allowed_tools=["analyze_repo"],
        body="执行 workflow skill。",
        base_dir=tmp_path,
        workflow_context=workflow,
    )
    tool = SkillInvokeTool({"workflow-skill": skill})
    state = RuntimeState.new(conversation_id=1, model="claude-test")

    result, updated = await tool.call({"skill": "workflow-skill", "args": {}}, state=state)

    assert result.ok is True
    assert updated.active_workflow["current_step_id"] == "step_1_audit"
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest backend/tests/test_agent_runtime_skills.py::test_skill_invoke_activates_workflow_contract -q`

Expected: FAIL，`active_workflow` 仍为空。

- [ ] **Step 3: SkillInvokeTool 调用 WorkflowContractRuntime**

在 `backend/app/agent_runtime/skills.py` 中加入：

```python
from app.agent_runtime.workflows.contract import WorkflowContractRuntime
```

在 `SkillInvokeTool.__init__` 中加入：

```python
self.workflow_runtime = WorkflowContractRuntime()
```

在 `call()` 中设置 `active_skill` 后加入：

```python
if skill.workflow_context:
    updated = self.workflow_runtime.activate(skill.workflow_context, state=updated)
```

随后再合并 skill 级工具：

```python
updated.allowed_tools = list(dict.fromkeys([*updated.allowed_tools, *skill.allowed_tools, "skill.invoke", "ask_user"]))
```

- [ ] **Step 4: 运行 skill/workflow 测试**

Run: `uv run pytest backend/tests/test_agent_runtime_skills.py backend/tests/test_agent_runtime_workflow_contract.py -q`

Expected: PASS。

## Task 13: Workflow Postcondition 接口与 recovery 状态

**Files:**
- Modify: `backend/app/agent_runtime/workflows/contract.py`
- Create: `backend/tests/test_agent_runtime_workflow_recovery.py`

- [ ] **Step 1: 写缺少 required tool 时不能完成 step 的测试**

```python
# backend/tests/test_agent_runtime_workflow_recovery.py
from app.agent_runtime.state import RuntimeState
from app.agent_runtime.workflows.contract import WorkflowContractRuntime
from app.services.tools import ToolResult


def test_workflow_contract_stays_on_step_when_required_tool_missing():
    state = RuntimeState.new(conversation_id=1, model="claude-test")
    state.active_workflow = {
        "current_step_id": "step_1",
        "steps": {
            "step_1": {
                "allowed_tools": ["analyze_repo"],
                "required_tools": ["analyze_repo"],
                "required_evidence": ["repo_audit"],
                "tool_calls": [],
                "evidence": {},
            }
        },
    }

    updated = WorkflowContractRuntime().validate_after_tool_results(state, [])

    assert updated.active_workflow["current_step_id"] == "step_1"
    assert updated.active_workflow["steps"]["step_1"]["status"] == "recovery"
    assert updated.active_workflow["steps"]["step_1"]["validation_failures"] == [
        "missing required tool(s): analyze_repo",
        "missing required evidence: repo_audit",
    ]


def test_workflow_contract_records_successful_tool_call_as_evidence():
    state = RuntimeState.new(conversation_id=1, model="claude-test")
    state.active_workflow = {
        "current_step_id": "step_1",
        "steps": {
            "step_1": {
                "allowed_tools": ["analyze_repo"],
                "required_tools": ["analyze_repo"],
                "required_evidence": ["repo_audit"],
                "tool_calls": [],
                "evidence": {},
            }
        },
    }
    result = ToolResult("analyze_repo", "ok", ok=True, metadata={"evidence": {"repo_audit": True}})

    updated = WorkflowContractRuntime().validate_after_tool_results(state, [result])

    assert updated.active_workflow["steps"]["step_1"]["status"] == "completed"
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest backend/tests/test_agent_runtime_workflow_recovery.py -q`

Expected: FAIL，缺少 `validate_after_tool_results`。

- [ ] **Step 3: 实现 postcondition 基础接口**

在 `WorkflowContractRuntime` 中加入：

```python
    def validate_after_tool_results(self, state: RuntimeState, results: list[ToolResult]) -> RuntimeState:
        workflow = dict(state.active_workflow or {})
        current_step_id = str(workflow.get("current_step_id") or "")
        steps = dict(workflow.get("steps") or {})
        step = dict(steps.get(current_step_id) or {})
        tool_calls = list(step.get("tool_calls") or [])
        evidence = dict(step.get("evidence") or {})
        for result in results:
            tool_calls.append({"name": result.name, "ok": result.ok, "metadata": result.metadata})
            raw_evidence = (result.metadata or {}).get("evidence")
            if isinstance(raw_evidence, dict):
                evidence.update(raw_evidence)
        completed_tools = {item["name"] for item in tool_calls if item.get("ok")}
        missing_tools = [name for name in step.get("required_tools") or [] if name not in completed_tools]
        missing_evidence = [name for name in step.get("required_evidence") or [] if not evidence.get(name)]
        failures = []
        if missing_tools:
            failures.append(f"missing required tool(s): {', '.join(missing_tools)}")
        if missing_evidence:
            failures.append(f"missing required evidence: {', '.join(missing_evidence)}")
        step["tool_calls"] = tool_calls
        step["evidence"] = evidence
        step["validation_failures"] = failures
        step["status"] = "recovery" if failures else "completed"
        steps[current_step_id] = step
        workflow["steps"] = steps
        updated = state.next_turn()
        updated.active_workflow = workflow
        return updated
```

- [ ] **Step 4: ToolExecutor / Runtime 调用 contract validation**

在 `AgentRuntime.run_conversation()` 每轮 tool results 写入消息后收集 `ToolResult` 列表，并调用：

```python
from app.agent_runtime.workflows.contract import WorkflowContractRuntime

self.workflow_runtime = WorkflowContractRuntime()
```

循环内：

```python
turn_results: list[ToolResult] = []
for tool_call in response.tool_calls:
    executed = await self.tool_executor.execute_one(tool_call, state=state)
    turn_results.append(executed.tool_result)
if state.active_workflow and turn_results:
    state = self.workflow_runtime.validate_after_tool_results(state, turn_results)
```

- [ ] **Step 5: 运行 runtime/workflow 测试**

Run: `uv run pytest backend/tests/test_agent_runtime_runtime.py backend/tests/test_agent_runtime_workflow_recovery.py -q`

Expected: PASS。

## Task 14: WebSocket runtime 事件前端兼容

**Files:**
- Modify: `frontend/src/pages/ChatPage.tsx`
- Modify: `frontend/src/__tests__/ChatPage.test.tsx`

- [ ] **Step 1: 写前端 runtime event 测试**

在 `frontend/src/__tests__/ChatPage.test.tsx` 增加测试：

```tsx
it("renders runtime tool activity events in the current agent bubble", async () => {
  render(<ChatPage />);
  await waitFor(() => expect(MockWebSocket.instances.length).toBe(1));
  const ws = MockWebSocket.instances[0];

  ws.emit({
    type: "runtime_started",
    run_id: "runtime-1",
  });
  ws.emit({
    type: "tool_started",
    tool_name: "ask_user",
    tool_call_id: "toolu_1",
  });
  ws.emit({
    type: "tool_completed",
    tool_name: "ask_user",
    tool_call_id: "toolu_1",
    ok: true,
  });
  ws.emit({
    type: "runtime_completed",
    run_id: "runtime-1",
  });

  expect(await screen.findByText(/ask_user/)).toBeInTheDocument();
  expect(screen.getByText(/runtime-1/)).toBeInTheDocument();
});
```

当前 `MockWebSocket` 已提供 `emit(payload: unknown)` 方法，测试直接使用 `ws.emit({ type: "runtime_started" })` 这一类调用注入 runtime event。

- [ ] **Step 2: 运行前端测试确认失败**

Run: `cd frontend; npm run test:run -- ChatPage.test.tsx`

Expected: FAIL，页面尚未渲染 runtime event。

- [ ] **Step 3: 在 ChatPage 事件 reducer 中接收 runtime 事件**

在 `frontend/src/pages/ChatPage.tsx` 的 WebSocket message 分支中，把这些事件并入当前 agent bubble 的 activity 列表：

```ts
const runtimeActivityTypes = new Set([
  "runtime_started",
  "tool_started",
  "tool_completed",
  "tool_error",
  "permission_requested",
  "runtime_waiting_for_user",
  "runtime_completed",
  "runtime_failed",
  "runtime_stopped",
]);
```

处理逻辑应生成稳定文本：

```ts
const activityText =
  event.type === "runtime_started"
    ? `Runtime started: ${event.run_id ?? ""}`
    : event.type === "runtime_completed"
      ? `Runtime completed: ${event.run_id ?? ""}`
      : "tool_name" in event
        ? `${event.type}: ${event.tool_name}`
        : event.type;
```

- [ ] **Step 4: 运行前端测试**

Run: `cd frontend; npm run test:run -- ChatPage.test.tsx`

Expected: PASS。

## Task 15: 总体验证与保护旧链路

**Files:**
- Modify: `docs/proposal.md`
- Modify: `docs/progress.md`

- [ ] **Step 1: 更新 proposal 中 Agent Runtime 优先决策**

在 `docs/proposal.md` 的 `5.3 Agent Loop` 和 `5.5 Skill 系统` 附近加入明确决策：

```markdown
下一阶段采用 Agent Runtime First：`AgentRuntime` 是 conversation 的顶层执行循环，Workflow 只作为 contract layer 约束当前 step 的 allowed tools、required evidence、postconditions、recovery 和 cleanup。新增能力不得继续以 `if step.id == "step_1_audit"` 这类固定 executor 作为主路径；确需兼容旧 workflow 时必须通过 compatibility adapter，并把缺失能力暴露为结构化错误或 HITL。
```

- [ ] **Step 2: 更新 progress**

在 `docs/progress.md` 增加当前状态：

```markdown
- 已新增 Agent Runtime V3 骨架：RuntimeState、MessageStore、LLMAdapter、ToolExecutor、SkillTool、WorkflowContractRuntime compatibility layer 和 feature flag。默认仍关闭，现有 WorkflowRunner 链路保持可用。
```

- [ ] **Step 3: 运行后端核心测试**

Run:

```powershell
uv run pytest backend/tests/test_agent_runtime_state.py backend/tests/test_agent_runtime_messages.py backend/tests/test_agent_runtime_llm.py backend/tests/test_agent_runtime_tool_executor.py backend/tests/test_agent_runtime_runtime.py backend/tests/test_agent_runtime_skills.py backend/tests/test_agent_runtime_workflow_contract.py backend/tests/test_agent_runtime_workflow_recovery.py backend/tests/test_agent_loop.py backend/tests/test_tools.py backend/tests/test_workflow.py -q
```

Expected: PASS。

- [ ] **Step 4: 运行前端测试**

Run:

```powershell
cd frontend
npm run test:run -- ChatPage.test.tsx
```

Expected: PASS。

- [ ] **Step 5: 运行全量后端测试**

Run:

```powershell
uv run pytest backend/tests -q
```

Expected: PASS。

## Task 16: Existing Skill Contract Validator

**Files:**
- Create: `backend/app/agent_runtime/workflows/validator.py`
- Create: `backend/tests/test_agent_runtime_existing_skill_validator.py`

- [ ] **Step 1: 写现有 skill contract validator 测试**

```python
# backend/tests/test_agent_runtime_existing_skill_validator.py
from pathlib import Path

from app.agent_runtime.workflows.contract import WorkflowContractRuntime
from app.agent_runtime.workflows.validator import validate_workflow_contract
from app.agent_runtime.state import RuntimeState


def test_existing_lab4ai_reproduce_skill_normalizes_to_contract_without_fatal_errors():
    raw = Path("skills/lab4ai-auto-reproduct/project_reproduce.yaml").read_text(encoding="utf-8")
    state = RuntimeState.new(conversation_id=1, model="claude-test")
    state = WorkflowContractRuntime().activate(raw, state=state)

    report = validate_workflow_contract(state.active_workflow)

    assert report.ok is True
    assert report.fatal_errors == []
    assert report.step_count >= 9
    assert "step_1_audit" in report.step_ids
    assert "step_9_release_gpu" in report.step_ids
    assert "legacy_compatibility_mode" in report.warnings
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest backend/tests/test_agent_runtime_existing_skill_validator.py -q`

Expected: FAIL，缺少 `validate_workflow_contract`。

- [ ] **Step 3: 实现 validator**

```python
# backend/app/agent_runtime/workflows/validator.py
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class WorkflowValidationReport:
    ok: bool
    step_count: int
    step_ids: list[str]
    warnings: list[str] = field(default_factory=list)
    fatal_errors: list[str] = field(default_factory=list)


def validate_workflow_contract(active_workflow: dict[str, Any] | None) -> WorkflowValidationReport:
    if not isinstance(active_workflow, dict):
        return WorkflowValidationReport(
            ok=False,
            step_count=0,
            step_ids=[],
            fatal_errors=["missing active workflow contract"],
        )
    steps = active_workflow.get("steps")
    if not isinstance(steps, dict) or not steps:
        return WorkflowValidationReport(
            ok=False,
            step_count=0,
            step_ids=[],
            fatal_errors=["workflow contract contains no steps"],
        )
    warnings: list[str] = []
    fatal_errors: list[str] = []
    if active_workflow.get("compatibility_mode"):
        warnings.append("legacy_compatibility_mode")
    for step_id, step in steps.items():
        if not isinstance(step, dict):
            fatal_errors.append(f"step `{step_id}` is not an object")
            continue
        if not step.get("instruction"):
            fatal_errors.append(f"step `{step_id}` missing instruction")
        if "allowed_tools" not in step:
            fatal_errors.append(f"step `{step_id}` missing allowed_tools")
    return WorkflowValidationReport(
        ok=not fatal_errors,
        step_count=len(steps),
        step_ids=list(steps.keys()),
        warnings=warnings,
        fatal_errors=fatal_errors,
    )
```

- [ ] **Step 4: 运行测试确认通过**

Run: `uv run pytest backend/tests/test_agent_runtime_existing_skill_validator.py -q`

Expected: PASS。

## Task 17: Legacy Tool Alias Adapter for Current Skills

**Files:**
- Create: `backend/app/agent_runtime/workflows/tool_mapping.py`
- Create: `backend/tests/test_agent_runtime_tool_mapping.py`

- [ ] **Step 1: 写历史工具名映射测试**

```python
# backend/tests/test_agent_runtime_tool_mapping.py
from app.agent_runtime.workflows.tool_mapping import normalize_tool_name, normalize_allowed_tools


def test_normalize_legacy_claw_tools_to_runtime_tools():
    assert normalize_tool_name("claw_shell_run") == "ssh_execute"
    assert normalize_tool_name("ssh_essentials_execute") == "ssh_execute"
    assert normalize_tool_name("file_system_read") == "file_system_read"
    assert normalize_tool_name("file_system_write") == "file_system_write"


def test_normalize_allowed_tools_deduplicates_preserving_order():
    assert normalize_allowed_tools(
        ["claw_shell_run", "ssh_execute", "file_system_read", "ask_user"]
    ) == ["ssh_execute", "file_system_read", "ask_user"]
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest backend/tests/test_agent_runtime_tool_mapping.py -q`

Expected: FAIL，缺少 `tool_mapping`。

- [ ] **Step 3: 实现工具名兼容映射**

```python
# backend/app/agent_runtime/workflows/tool_mapping.py
from __future__ import annotations


LEGACY_TOOL_ALIASES = {
    "claw_shell_run": "ssh_execute",
    "ssh_essentials_execute": "ssh_execute",
    "instance_create": "lab4ai_create_instance",
    "instance_stop": "lab4ai_stop_instance",
    "repo_audit": "analyze_repo",
    "paper_analyze": "analyze_paper",
    "generate_repro_report": "repro_report",
}


def normalize_tool_name(name: str) -> str:
    value = str(name or "").strip()
    return LEGACY_TOOL_ALIASES.get(value, value)


def normalize_allowed_tools(names: list[str]) -> list[str]:
    normalized: list[str] = []
    seen: set[str] = set()
    for name in names:
        value = normalize_tool_name(name)
        if value and value not in seen:
            normalized.append(value)
            seen.add(value)
    return normalized
```

- [ ] **Step 4: 在 WorkflowContractRuntime 中应用映射**

在 `backend/app/agent_runtime/workflows/contract.py` 中引入：

```python
from app.agent_runtime.workflows.tool_mapping import normalize_allowed_tools
```

把当前 step 的 `allowed_tools` 写入替换为：

```python
"allowed_tools": normalize_allowed_tools(list(item.get("allowed_tools") or [])),
```

并把 `current_tools` 读取保持为 normalized 后的值。

- [ ] **Step 5: 运行映射和 contract 测试**

Run: `uv run pytest backend/tests/test_agent_runtime_tool_mapping.py backend/tests/test_agent_runtime_workflow_contract.py -q`

Expected: PASS。

## Task 18: Runtime Template Renderer and Secret-Safe Context

**Files:**
- Create: `backend/app/agent_runtime/workflows/rendering.py`
- Create: `backend/tests/test_agent_runtime_template_rendering.py`

- [ ] **Step 1: 写模板渲染测试**

```python
# backend/tests/test_agent_runtime_template_rendering.py
from app.agent_runtime.workflows.rendering import render_runtime_templates


def test_render_runtime_templates_resolves_known_values():
    payload = {
        "github_url": "{{parameters.github_url}}",
        "server_id": "{{workflow_resources.cpu.server_id}}",
    }
    context = {
        "parameters": {"github_url": "https://github.com/example/repo"},
        "workflow_resources": {"cpu": {"server_id": "cpu-1"}},
    }

    rendered = render_runtime_templates(payload, context)

    assert rendered.ok is True
    assert rendered.value == {
        "github_url": "https://github.com/example/repo",
        "server_id": "cpu-1",
    }


def test_render_runtime_templates_rejects_unresolved_value():
    rendered = render_runtime_templates(
        {"server_id": "{{workflow_resources.gpu.server_id}}"},
        {"workflow_resources": {}},
    )

    assert rendered.ok is False
    assert rendered.error_code == "unresolved_template_variable"
    assert rendered.unresolved_variables == ["workflow_resources.gpu.server_id"]
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest backend/tests/test_agent_runtime_template_rendering.py -q`

Expected: FAIL，缺少 `rendering`。

- [ ] **Step 3: 实现模板渲染器**

```python
# backend/app/agent_runtime/workflows/rendering.py
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
import re


TEMPLATE_RE = re.compile(r"{{\s*([^{}]+?)\s*}}")


@dataclass(slots=True)
class RenderedValue:
    ok: bool
    value: Any = None
    error_code: str | None = None
    unresolved_variables: list[str] = field(default_factory=list)


def render_runtime_templates(value: Any, context: dict[str, Any]) -> RenderedValue:
    unresolved: list[str] = []

    def resolve(path: str) -> Any:
        current: Any = context
        for part in path.split("."):
            if isinstance(current, dict) and part in current:
                current = current[part]
            else:
                unresolved.append(path)
                return ""
        return current

    def render_item(item: Any) -> Any:
        if isinstance(item, dict):
            return {key: render_item(inner) for key, inner in item.items()}
        if isinstance(item, list):
            return [render_item(inner) for inner in item]
        if not isinstance(item, str):
            return item
        matches = list(TEMPLATE_RE.finditer(item))
        if not matches:
            return item
        if len(matches) == 1 and matches[0].span() == (0, len(item)):
            return resolve(matches[0].group(1).strip())
        return TEMPLATE_RE.sub(lambda match: str(resolve(match.group(1).strip())), item)

    rendered = render_item(value)
    if unresolved:
        return RenderedValue(
            ok=False,
            value=rendered,
            error_code="unresolved_template_variable",
            unresolved_variables=sorted(set(unresolved)),
        )
    return RenderedValue(ok=True, value=rendered)
```

- [ ] **Step 4: ToolExecutor 调用前渲染模板**

在 `ToolExecutor.execute_one()` 中，在 permission check 之前构建 runtime context：

```python
template_context = {
    "parameters": (state.active_skill or {}).get("args") or {},
    "workflow_resources": (state.active_workflow or {}).get("resources") or {},
    "workflow_results": (state.active_workflow or {}).get("results") or {},
}
rendered = render_runtime_templates(tool_call.input, template_context)
if not rendered.ok:
    result = ToolResult(
        tool_call.name,
        f"工具参数存在未解析模板变量：{', '.join(rendered.unresolved_variables)}",
        ok=False,
        metadata={
            "error_code": rendered.error_code,
            "unresolved_variables": rendered.unresolved_variables,
            "retryable": True,
        },
    )
    return self._as_executed(tool_call, result)
tool_input = rendered.value
```

后续 schema validation 和 registry invoke 使用 `tool_input`，不再直接使用 `tool_call.input`。

- [ ] **Step 5: 运行模板和 ToolExecutor 测试**

Run: `uv run pytest backend/tests/test_agent_runtime_template_rendering.py backend/tests/test_agent_runtime_tool_executor.py -q`

Expected: PASS。

## Task 19: Current Reproduce Workflow Postcondition Catalog

**Files:**
- Create: `backend/app/agent_runtime/workflows/postconditions.py`
- Modify: `backend/app/agent_runtime/workflows/contract.py`
- Create: `backend/tests/test_agent_runtime_existing_skill_postconditions.py`

- [ ] **Step 1: 写现有复现 workflow 关键验收测试**

```python
# backend/tests/test_agent_runtime_existing_skill_postconditions.py
from app.agent_runtime.workflows.postconditions import evaluate_step_postconditions


def test_step_3_requires_cpu_instance_resource():
    result = evaluate_step_postconditions(
        "step_3_deploy_cpu",
        workflow_state={"resources": {"cpu": {"server_id": "cpu-1"}}},
        step_state={"evidence": {"cpu_instance_created": True}},
    )

    assert result.ok is True


def test_step_7_inline_cuda_smoke_alone_is_not_reproduction_success():
    result = evaluate_step_postconditions(
        "step_7_gpu_execution",
        workflow_state={"resources": {"gpu": {"server_id": "gpu-1"}}},
        step_state={"evidence": {"inline_cuda_smoke": True}},
    )

    assert result.ok is False
    assert "project_reproduction_log" in result.missing_evidence


def test_step_8_requires_report_artifact_path():
    result = evaluate_step_postconditions(
        "step_8_generate_report",
        workflow_state={"results": {}},
        step_state={"evidence": {}},
    )

    assert result.ok is False
    assert "report_path" in result.missing_evidence
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest backend/tests/test_agent_runtime_existing_skill_postconditions.py -q`

Expected: FAIL，缺少 `postconditions`。

- [ ] **Step 3: 实现 postcondition catalog**

```python
# backend/app/agent_runtime/workflows/postconditions.py
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class PostconditionResult:
    ok: bool
    missing_evidence: list[str] = field(default_factory=list)


STEP_REQUIRED_EVIDENCE = {
    "step_3_deploy_cpu": ["cpu_instance_created"],
    "step_4_cpu_env_setup": ["remote_workspace_ready", "repo_cloned"],
    "step_6_deploy_gpu": ["gpu_instance_created"],
    "step_7_gpu_execution": ["project_reproduction_log", "gpu_execution_attempted"],
    "step_8_generate_report": ["report_path"],
    "step_5_release_cpu": ["cpu_instance_released"],
    "step_9_release_gpu": ["gpu_instance_released"],
}


def evaluate_step_postconditions(
    step_id: str,
    *,
    workflow_state: dict[str, Any],
    step_state: dict[str, Any],
) -> PostconditionResult:
    evidence = dict(step_state.get("evidence") or {})
    results = dict(workflow_state.get("results") or {})
    resources = dict(workflow_state.get("resources") or {})
    if step_id == "step_3_deploy_cpu" and resources.get("cpu", {}).get("server_id"):
        evidence["cpu_instance_created"] = True
    if step_id == "step_6_deploy_gpu" and resources.get("gpu", {}).get("server_id"):
        evidence["gpu_instance_created"] = True
    if step_id == "step_8_generate_report" and results.get("report_path"):
        evidence["report_path"] = True
    missing = [
        name
        for name in STEP_REQUIRED_EVIDENCE.get(step_id, [])
        if not evidence.get(name)
    ]
    return PostconditionResult(ok=not missing, missing_evidence=missing)
```

- [ ] **Step 4: contract validation 调用 postcondition catalog**

在 `WorkflowContractRuntime.validate_after_tool_results()` 中，在原有 `missing_evidence` 后加入：

```python
from app.agent_runtime.workflows.postconditions import evaluate_step_postconditions

postcondition = evaluate_step_postconditions(
    current_step_id,
    workflow_state=workflow,
    step_state=step,
)
for item in postcondition.missing_evidence:
    if item not in missing_evidence:
        missing_evidence.append(item)
```

- [ ] **Step 5: 运行 postcondition 和 recovery 测试**

Run: `uv run pytest backend/tests/test_agent_runtime_existing_skill_postconditions.py backend/tests/test_agent_runtime_workflow_recovery.py -q`

Expected: PASS。

## Task 20: Bounded Recovery Loop for Existing Skills

**Files:**
- Create: `backend/app/agent_runtime/recovery.py`
- Modify: `backend/app/agent_runtime/runtime.py`
- Create: `backend/tests/test_agent_runtime_recovery.py`

- [ ] **Step 1: 写 recovery policy 测试**

```python
# backend/tests/test_agent_runtime_recovery.py
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
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest backend/tests/test_agent_runtime_recovery.py -q`

Expected: FAIL，缺少 `recovery`。

- [ ] **Step 3: 实现 RecoveryPolicy**

```python
# backend/app/agent_runtime/recovery.py
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
```

- [ ] **Step 4: Runtime 接入 recovery decision**

在 `AgentRuntime.run_conversation()` 中，当 `state.active_workflow` 的当前 step status 为 `recovery` 时：

```python
decision = self.recovery_policy.decide(state, retryable=True)
if decision.action == "hitl":
    state = state.mark_waiting_for_user(
        pending_tool_call={
            "tool_call_id": f"recovery:{state.active_workflow.get('current_step_id')}",
            "tool_name": "workflow_recovery",
            "workflow_step_id": state.active_workflow.get("current_step_id"),
        },
        pending_user_input={
            "question": "当前 workflow step 自动恢复次数已耗尽，请补充处理方式。",
            "options": ["继续重试", "停止任务"],
        },
    )
    break
```

`AgentRuntime.__init__` 中初始化：

```python
from app.agent_runtime.recovery import RecoveryPolicy

self.recovery_policy = RecoveryPolicy(max_attempts=3)
```

- [ ] **Step 5: 运行 recovery 和 runtime 测试**

Run: `uv run pytest backend/tests/test_agent_runtime_recovery.py backend/tests/test_agent_runtime_runtime.py -q`

Expected: PASS。

## Task 21: Existing Skill End-to-End Dry Run on Agent Runtime

**Files:**
- Create: `backend/tests/test_agent_runtime_existing_skill_e2e.py`

- [ ] **Step 1: 写现有 skill dry-run 端到端测试**

```python
# backend/tests/test_agent_runtime_existing_skill_e2e.py
import pytest

from app.agent_runtime.events import ListEventSink
from app.agent_runtime.llm import ModelResponse
from app.agent_runtime.runtime import AgentRuntime
from app.agent_runtime.skills import SkillInvokeTool
from app.agent_runtime.tool_executor import ToolExecutor
from app.models import Conversation, ConversationStatus, ConversationTaskType
from app.services.llm_client import LLMToolUse
from app.services.skills import SkillLoader
from app.services.tools import ToolDefinition, ToolResult
from app.core.config import get_settings


class ExistingSkillFakeLLM:
    def __init__(self):
        self.calls = 0

    async def complete(self, request):
        self.calls += 1
        if self.calls == 1:
            return ModelResponse(
                text="加载复现 skill。",
                tool_calls=[
                    LLMToolUse(
                        id="toolu_skill",
                        name="skill.invoke",
                        input={
                            "skill": "lab4ai-auto-reproduct",
                            "args": {
                                "github_url": "https://github.com/example/repo",
                                "paper_url": "https://arxiv.org/abs/0000.00000",
                            },
                        },
                    )
                ],
                stop_reason="tool_use",
                usage={},
                raw={},
            )
        return ModelResponse(text="dry-run 完成。", tool_calls=[], stop_reason="end_turn", usage={}, raw={})


class ExistingSkillFakeRegistry:
    def __init__(self):
        self.definitions = {
            "ask_user": ToolDefinition(
                name="ask_user",
                description="ask",
                input_schema={"type": "object", "properties": {"question": {"type": "string"}}},
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
        return ToolResult(name, f"{name} ok", ok=True, metadata={})


@pytest.mark.asyncio
async def test_existing_skill_loads_through_skill_invoke_not_fixed_workflow(db_session, test_user):
    conversation = Conversation(
        user_id=test_user.id,
        task_type=ConversationTaskType.REPRODUCE,
        title="runtime skill dry run",
        status=ConversationStatus.RUNNING,
        metadata_={},
    )
    db_session.add(conversation)
    await db_session.commit()
    await db_session.refresh(conversation)
    events = ListEventSink()
    skills = SkillLoader(get_settings().skills_dir_path).load_all()
    executor = ToolExecutor(
        registry=ExistingSkillFakeRegistry(),
        event_sink=events,
        runtime_tools={"skill.invoke": SkillInvokeTool(skills)},
    )
    runtime = AgentRuntime(
        session=db_session,
        llm=ExistingSkillFakeLLM(),
        tool_executor=executor,
        event_sink=events,
    )

    result = await runtime.run_conversation(conversation.id, model="claude-test")

    assert result.status == "completed"
    assert result.metadata["runtime"]["active_skill"]["name"] == "lab4ai-auto-reproduct"
    assert result.metadata["runtime"]["active_workflow"]["current_step_id"] == "step_1_audit"
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest backend/tests/test_agent_runtime_existing_skill_e2e.py -q`

Expected: FAIL，当前 runtime 尚未把 `runtime_tools` 传入真实 `ToolExecutor` 或未持久化 active skill/workflow。

- [ ] **Step 3: 修复 runtime tool state 持久化**

在 `AgentRuntime.run_conversation()` 执行 tool 后，如果 `executed.updated_state` 存在，无论是否 paused 都更新 state：

```python
if executed.updated_state:
    state = executed.updated_state
```

保存 metadata 时确保 `active_skill` 和 `active_workflow` 已进入 `save_runtime_state()`。

- [ ] **Step 4: 运行端到端 dry-run 测试**

Run: `uv run pytest backend/tests/test_agent_runtime_existing_skill_e2e.py -q`

Expected: PASS。

## Task 22: Integration Gate for Complete Existing Skill Execution

**Files:**
- Create: `backend/tests/test_agent_runtime_existing_skill_integration_guard.py`
- Modify: `docs/progress.md`

- [ ] **Step 1: 写集成门禁测试**

```python
# backend/tests/test_agent_runtime_existing_skill_integration_guard.py
import os

import pytest


@pytest.mark.skipif(
    os.environ.get("LOBSTER_RUN_LAB4AI_INTEGRATION") != "1",
    reason="requires explicit Lab4AI integration opt-in",
)
def test_lab4ai_integration_requires_explicit_opt_in():
    assert os.environ["LOBSTER_RUN_LAB4AI_INTEGRATION"] == "1"
```

- [ ] **Step 2: 运行默认测试确认跳过**

Run: `uv run pytest backend/tests/test_agent_runtime_existing_skill_integration_guard.py -q`

Expected: SKIPPED，原因包含 `requires explicit Lab4AI integration opt-in`。

- [ ] **Step 3: 更新 progress 说明完整稳定执行边界**

在 `docs/progress.md` 增加：

```markdown
- Agent Runtime V3 的当前版本目标已扩展为“现有 lab4ai-auto-reproduct skill 完整稳定执行”：通过 `skill.invoke` 加载现有 skill，通过 compatibility contract 解析历史 workflow，通过 ToolExecutor 执行所有副作用，通过 postconditions / required evidence 验收关键步骤。真实 Lab4AI CPU/GPU 端到端验证必须显式设置 `LOBSTER_RUN_LAB4AI_INTEGRATION=1`，默认测试不创建计费实例。
```

- [ ] **Step 4: 运行扩展后端测试集合**

Run:

```powershell
uv run pytest backend/tests/test_agent_runtime_existing_skill_validator.py backend/tests/test_agent_runtime_tool_mapping.py backend/tests/test_agent_runtime_template_rendering.py backend/tests/test_agent_runtime_existing_skill_postconditions.py backend/tests/test_agent_runtime_recovery.py backend/tests/test_agent_runtime_existing_skill_e2e.py backend/tests/test_agent_runtime_existing_skill_integration_guard.py -q
```

Expected: PASS with one skipped integration guard。

## Task 23: Intent Routing and Skill Trigger Semantics

**Files:**
- Create: `backend/app/agent_runtime/intent.py`
- Create: `backend/tests/test_agent_runtime_intent.py`
- Modify: `backend/app/agent_runtime/context.py`
- Modify: `backend/app/agent_runtime/runtime.py`

- [ ] **Step 1: 写 skill triggers 只产生候选、不直接执行的测试**

```python
# backend/tests/test_agent_runtime_intent.py
from pathlib import Path

from app.agent_runtime.intent import (
    IntentDecision,
    build_skill_candidates,
    should_require_skill_invoke,
)
from app.services.skills import SkillDefinition


def _skill() -> SkillDefinition:
    return SkillDefinition(
        name="lab4ai-auto-reproduct",
        description="全自动项目复现专家",
        triggers=["复现这个项目", "帮我跑通", "论文复现", "项目复现", "reproduce", "帮我复现"],
        when_to_use="用户明确要求复现、跑通、训练或实验时使用。",
        allowed_tools=["analyze_repo", "lab4ai_create_instance"],
        body="复现 skill 正文",
        base_dir=Path("skills/lab4ai-auto-reproduct"),
        workflow_context="workflow",
    )


def test_triggers_create_candidate_but_do_not_auto_invoke_skill():
    candidates = build_skill_candidates(
        "帮我复现这个项目：https://github.com/jsnzwu/motion-guided-flow",
        {"lab4ai-auto-reproduct": _skill()},
        task_type="reproduce",
    )

    assert candidates[0].skill_name == "lab4ai-auto-reproduct"
    assert candidates[0].matched_triggers == ["帮我复现"]
    assert candidates[0].should_auto_execute is False


def test_github_analysis_request_does_not_require_reproduce_skill():
    decision = should_require_skill_invoke(
        "帮我看看这个 GitHub 项目是做什么的：https://github.com/jsnzwu/motion-guided-flow",
        task_type="reproduce",
    )

    assert decision == IntentDecision.NORMAL_CHAT_OR_READONLY_TOOLS


def test_explicit_reproduce_request_requires_model_skill_invoke():
    decision = should_require_skill_invoke(
        "帮我复现这个项目：https://github.com/jsnzwu/motion-guided-flow",
        task_type="general",
    )

    assert decision == IntentDecision.REQUIRE_MODEL_SKILL_INVOKE


def test_ambiguous_reproduce_without_url_requires_clarification():
    decision = should_require_skill_invoke("帮我复现", task_type="general")

    assert decision == IntentDecision.ASK_USER_FOR_MISSING_INPUT
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest backend/tests/test_agent_runtime_intent.py -q`

Expected: FAIL，缺少 `app.agent_runtime.intent`。

- [ ] **Step 3: 实现 intent routing 模块**

```python
# backend/app/agent_runtime/intent.py
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import re

from app.services.skills import SkillDefinition


GITHUB_RE = re.compile(r"https?://github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+")


class IntentDecision(str, Enum):
    NORMAL_CHAT_OR_READONLY_TOOLS = "normal_chat_or_readonly_tools"
    REQUIRE_MODEL_SKILL_INVOKE = "require_model_skill_invoke"
    ASK_USER_FOR_MISSING_INPUT = "ask_user_for_missing_input"


@dataclass(slots=True)
class SkillCandidate:
    skill_name: str
    description: str
    matched_triggers: list[str] = field(default_factory=list)
    score: int = 0
    should_auto_execute: bool = False


def build_skill_candidates(
    user_message: str,
    skills: dict[str, SkillDefinition],
    *,
    task_type: str | None = None,
) -> list[SkillCandidate]:
    text = user_message.lower()
    candidates: list[SkillCandidate] = []
    for skill in skills.values():
        matched = [trigger for trigger in skill.triggers if trigger.lower() in text]
        score = len(matched) * 10
        if task_type and task_type == getattr(skill, "task_type", ""):
            score += 3
        if matched or score:
            candidates.append(
                SkillCandidate(
                    skill_name=skill.name,
                    description=skill.description,
                    matched_triggers=matched,
                    score=score,
                    should_auto_execute=False,
                )
            )
    return sorted(candidates, key=lambda item: item.score, reverse=True)


def should_require_skill_invoke(user_message: str, *, task_type: str | None = None) -> IntentDecision:
    text = user_message.lower()
    has_github = bool(GITHUB_RE.search(user_message))
    reproduce_words = ["复现", "跑通", "跑一下", "训练", "实验", "reproduce"]
    analysis_words = ["看看", "介绍", "是什么", "分析一下", "readme", "怎么运行", "解释"]
    wants_reproduce = any(word in text for word in reproduce_words)
    wants_readonly = any(word in text for word in analysis_words)
    if wants_readonly and not wants_reproduce:
        return IntentDecision.NORMAL_CHAT_OR_READONLY_TOOLS
    if wants_reproduce and not has_github:
        return IntentDecision.ASK_USER_FOR_MISSING_INPUT
    if wants_reproduce and has_github:
        return IntentDecision.REQUIRE_MODEL_SKILL_INVOKE
    return IntentDecision.NORMAL_CHAT_OR_READONLY_TOOLS
```

- [ ] **Step 4: ContextBuilder 注入 skill 候选而不是执行 skill**

在 `backend/app/agent_runtime/context.py` 增加方法：

```python
    def build_skill_candidate_prompt(self, candidates: list[dict[str, object]]) -> str:
        if not candidates:
            return ""
        lines = [
            "可选 skills：",
            "这些 triggers 只表示候选相关性，不会自动执行 skill。",
            "只有当用户明确要求该能力时，才调用 skill.invoke 激活完整 skill。",
        ]
        for candidate in candidates:
            triggers = ", ".join(str(item) for item in candidate.get("matched_triggers") or [])
            lines.append(
                f"- {candidate.get('skill_name')}: {candidate.get('description')}；matched_triggers={triggers}"
            )
        return "\n".join(lines)
```

在 `build_system_prompt()` 中，如果 `state` 的 metadata 或 `active_skill` 之外存在 `skill_candidates`，把候选提示追加到 system prompt。若当前 `RuntimeState` 还没有该字段，则在 Task 2 的 `RuntimeState` 中补：

```python
skill_candidates: list[dict[str, object]] = field(default_factory=list)
```

并在 `to_metadata()` / `load_runtime_state()` 中读写该字段。

- [ ] **Step 5: Runtime 使用 intent routing，但不自动执行 skill**

在 `AgentRuntime.run_conversation()` 读取最新 user message 后调用：

```python
from app.agent_runtime.intent import build_skill_candidates, should_require_skill_invoke, IntentDecision

decision = should_require_skill_invoke(latest_user_message, task_type=str(conversation.task_type.value))
state.skill_candidates = [
    {
        "skill_name": item.skill_name,
        "description": item.description,
        "matched_triggers": item.matched_triggers,
        "score": item.score,
        "should_auto_execute": item.should_auto_execute,
    }
    for item in build_skill_candidates(latest_user_message, self.skills, task_type=str(conversation.task_type.value))
]
```

行为约束：

```python
if decision == IntentDecision.ASK_USER_FOR_MISSING_INPUT:
    # 让模型优先调用 ask_user；如果模型直接调用 lab4ai_create_instance，ToolExecutor allowlist 仍会拒绝。
    state.allowed_tools = ["ask_user", "skill.invoke"]
elif decision == IntentDecision.REQUIRE_MODEL_SKILL_INVOKE:
    # 允许模型调用 skill.invoke，但不由后端直接调用。
    state.allowed_tools = ["skill.invoke", "ask_user"]
else:
    # 普通对话可以回答或使用只读工具；不应自动进入复现 workflow。
    state.allowed_tools = ["skill.invoke", "ask_user", "analyze_repo", "analyze_paper"]
```

这里的关键点是：后端只调整候选和 allowlist，不直接执行 `SkillInvokeTool.call()`。

- [ ] **Step 6: 写 runtime 不自动触发 skill 的测试**

追加到 `backend/tests/test_agent_runtime_intent.py`：

```python
def test_task_type_reproduce_is_only_hint_not_auto_execute():
    candidates = build_skill_candidates(
        "这个项目大概是做什么的？https://github.com/jsnzwu/motion-guided-flow",
        {"lab4ai-auto-reproduct": _skill()},
        task_type="reproduce",
    )

    assert candidates == []
    assert should_require_skill_invoke(
        "这个项目大概是做什么的？https://github.com/jsnzwu/motion-guided-flow",
        task_type="reproduce",
    ) == IntentDecision.NORMAL_CHAT_OR_READONLY_TOOLS
```

- [ ] **Step 7: 运行 intent 测试**

Run: `uv run pytest backend/tests/test_agent_runtime_intent.py -q`

Expected: PASS。

## Task 24: Real Lab4AI Existing Skill Main Flow E2E

**Files:**
- Create: `backend/tests/test_agent_runtime_existing_skill_real_e2e.py`
- Modify: `docs/progress.md`
- Modify: `docs/proposal.md`

This task is the hard acceptance gate for "通用 Agent 客户端加载 skill，并跑通现有 skill 主流程". It must run through `AgentRuntime -> skill.invoke -> WorkflowContractRuntime -> ToolExecutor -> ToolRegistry`. It must not call `SkillWorkflowRunner.run()` or any fixed step-id executor path as the primary execution path.

- [ ] **Step 1: 写真实 E2E 测试骨架，默认跳过**

```python
# backend/tests/test_agent_runtime_existing_skill_real_e2e.py
import os

import pytest


pytestmark = pytest.mark.skipif(
    os.environ.get("LOBSTER_RUN_LAB4AI_INTEGRATION") != "1",
    reason="requires LOBSTER_RUN_LAB4AI_INTEGRATION=1 and real Lab4AI credentials",
)


def test_real_e2e_guard_is_explicitly_enabled():
    assert os.environ["LOBSTER_RUN_LAB4AI_INTEGRATION"] == "1"
```

- [ ] **Step 2: 运行默认测试确认跳过**

Run: `uv run pytest backend/tests/test_agent_runtime_existing_skill_real_e2e.py -q`

Expected: SKIPPED，原因包含 `requires LOBSTER_RUN_LAB4AI_INTEGRATION=1`。

- [ ] **Step 3: 写真实主流程 E2E 测试**

在 `backend/tests/test_agent_runtime_existing_skill_real_e2e.py` 中追加：

```python
import pytest

from app.agent_runtime.events import ListEventSink
from app.agent_runtime.llm import ModelResponse
from app.agent_runtime.runtime import AgentRuntime
from app.agent_runtime.skills import SkillInvokeTool
from app.agent_runtime.tool_executor import ToolExecutor
from app.core.config import get_settings
from app.models import Conversation, ConversationStatus, ConversationTaskType
from app.services.llm_client import LLMToolUse
from app.services.skills import SkillLoader
from app.services.tools import ToolRegistry


class RealMainFlowScriptedLLM:
    """Scripted model for integration gating.

    The test still goes through AgentRuntime and tool_use blocks, but avoids relying
    on a live model's reasoning quality while validating the runtime/tool/workflow path.
    """

    def __init__(self):
        self.calls = 0

    async def complete(self, request):
        self.calls += 1
        if self.calls == 1:
            return ModelResponse(
                text="加载复现 skill。",
                tool_calls=[
                    LLMToolUse(
                        id="toolu_skill",
                        name="skill.invoke",
                        input={
                            "skill": "lab4ai-auto-reproduct",
                            "args": {
                                "github_url": "https://github.com/jsnzwu/motion-guided-flow",
                                "paper_url": "",
                            },
                        },
                    )
                ],
                stop_reason="tool_use",
                usage={},
                raw={},
            )
        if self.calls == 2:
            return ModelResponse(
                text="执行项目与论文审计。",
                tool_calls=[
                    LLMToolUse(
                        id="toolu_repo",
                        name="analyze_repo",
                        input={"github_url": "https://github.com/jsnzwu/motion-guided-flow"},
                    )
                ],
                stop_reason="tool_use",
                usage={},
                raw={},
            )
        if self.calls == 3:
            return ModelResponse(
                text="创建 CPU 实例。",
                tool_calls=[
                    LLMToolUse(
                        id="toolu_cpu",
                        name="lab4ai_create_instance",
                        input={"resource_kind": "CPU"},
                    )
                ],
                stop_reason="tool_use",
                usage={},
                raw={},
            )
        if self.calls == 4:
            return ModelResponse(
                text="准备 CPU 远程环境。",
                tool_calls=[
                    LLMToolUse(
                        id="toolu_cpu_prep",
                        name="remote_project_prep",
                        input={
                            "server_id": "{{workflow_resources.cpu.server_id}}",
                            "github_url": "https://github.com/jsnzwu/motion-guided-flow",
                        },
                    )
                ],
                stop_reason="tool_use",
                usage={},
                raw={},
            )
        if self.calls == 5:
            return ModelResponse(
                text="释放 CPU 实例。",
                tool_calls=[
                    LLMToolUse(
                        id="toolu_cpu_stop",
                        name="lab4ai_stop_instance",
                        input={"server_id": "{{workflow_resources.cpu.server_id}}"},
                    )
                ],
                stop_reason="tool_use",
                usage={},
                raw={},
            )
        if self.calls == 6:
            return ModelResponse(
                text="创建 GPU 实例。",
                tool_calls=[
                    LLMToolUse(
                        id="toolu_gpu",
                        name="lab4ai_create_instance",
                        input={"resource_kind": "GPU", "gpu_count": 1},
                    )
                ],
                stop_reason="tool_use",
                usage={},
                raw={},
            )
        if self.calls == 7:
            return ModelResponse(
                text="执行 GPU 主流程。",
                tool_calls=[
                    LLMToolUse(
                        id="toolu_gpu_run",
                        name="ssh_execute",
                        input={
                            "server_id": "{{workflow_resources.gpu.server_id}}",
                            "command": "bash -lc 'cd /workspace/user-data/codelab/motion-guided-flow/code && if [ -f scripts/run.sh ]; then bash scripts/run.sh; elif [ -f README.md ]; then python - <<PY\\nprint(\"project_reproduction_log=manual_entry_required\")\\nPY\\nelse exit 2; fi'",
                            "timeout": 7200,
                        },
                    )
                ],
                stop_reason="tool_use",
                usage={},
                raw={},
            )
        if self.calls == 8:
            return ModelResponse(
                text="生成复现报告。",
                tool_calls=[
                    LLMToolUse(
                        id="toolu_report",
                        name="repro_report",
                        input={
                            "repo_name": "motion-guided-flow",
                            "github_url": "https://github.com/jsnzwu/motion-guided-flow",
                            "server_id": "{{workflow_resources.gpu.server_id}}",
                        },
                    )
                ],
                stop_reason="tool_use",
                usage={},
                raw={},
            )
        if self.calls == 9:
            return ModelResponse(
                text="释放 GPU 实例。",
                tool_calls=[
                    LLMToolUse(
                        id="toolu_gpu_stop",
                        name="lab4ai_stop_instance",
                        input={"server_id": "{{workflow_resources.gpu.server_id}}"},
                    )
                ],
                stop_reason="tool_use",
                usage={},
                raw={},
            )
        return ModelResponse(
            text="现有 skill 主流程已完成，CPU/GPU 资源已释放，报告已生成。",
            tool_calls=[],
            stop_reason="end_turn",
            usage={},
            raw={},
        )


@pytest.mark.asyncio
async def test_real_lab4ai_existing_skill_main_flow(db_session, test_user):
    conversation = Conversation(
        user_id=test_user.id,
        task_type=ConversationTaskType.REPRODUCE,
        title="motion-guided-flow real e2e",
        status=ConversationStatus.RUNNING,
        metadata_={},
    )
    db_session.add(conversation)
    await db_session.commit()
    await db_session.refresh(conversation)

    events = ListEventSink()
    skills = SkillLoader(get_settings().skills_dir_path).load_all()
    executor = ToolExecutor(
        registry=ToolRegistry(),
        event_sink=events,
        runtime_tools={"skill.invoke": SkillInvokeTool(skills)},
    )
    runtime = AgentRuntime(
        session=db_session,
        llm=RealMainFlowScriptedLLM(),
        tool_executor=executor,
        event_sink=events,
    )

    result = await runtime.run_conversation(conversation.id, model="scripted-real-e2e")

    runtime_state = result.metadata["runtime"]
    workflow = runtime_state["active_workflow"]
    assert result.status == "completed"
    assert runtime_state["active_skill"]["name"] == "lab4ai-auto-reproduct"
    assert workflow["steps"]["step_3_deploy_cpu"]["status"] == "completed"
    assert workflow["steps"]["step_4_cpu_env_setup"]["status"] == "completed"
    assert workflow["steps"]["step_5_release_cpu"]["status"] == "completed"
    assert workflow["steps"]["step_6_deploy_gpu"]["status"] == "completed"
    assert workflow["steps"]["step_7_gpu_execution"]["status"] == "completed"
    assert workflow["steps"]["step_8_generate_report"]["status"] == "completed"
    assert workflow["steps"]["step_9_release_gpu"]["status"] == "completed"
    assert workflow["resources"]["cpu"]["released"] is True
    assert workflow["resources"]["gpu"]["released"] is True
    assert workflow["results"]["report_path"]
    assert not any(event["type"] == "workflow_fixed_executor_used" for event in events.events)
```

- [ ] **Step 4: 补齐 ToolResult 到 workflow evidence/resource/result 的归约**

如果 Step 3 测试失败，优先在通用归约层补齐，不写 step executor。新增或扩展 `WorkflowContractRuntime.apply_tool_result()`：

```python
def apply_tool_result(self, state: RuntimeState, result: ToolResult) -> RuntimeState:
    workflow = dict(state.active_workflow or {})
    resources = dict(workflow.get("resources") or {})
    results = dict(workflow.get("results") or {})
    current_step_id = str(workflow.get("current_step_id") or "")
    steps = dict(workflow.get("steps") or {})
    step = dict(steps.get(current_step_id) or {})
    evidence = dict(step.get("evidence") or {})

    if result.name == "lab4ai_create_instance" and result.metadata.get("server_id"):
        kind = "gpu" if str(result.metadata.get("resource_kind") or "").upper() == "GPU" else "cpu"
        resources[kind] = {"server_id": result.metadata["server_id"], "released": False}
        evidence[f"{kind}_instance_created"] = True
    if result.name == "lab4ai_stop_instance":
        server_id = str(result.metadata.get("server_id") or "")
        for kind, payload in resources.items():
            if isinstance(payload, dict) and payload.get("server_id") == server_id:
                payload["released"] = True
                evidence[f"{kind}_instance_released"] = True
    if result.name in {"ssh_execute", "remote_project_prep"} and result.ok:
        evidence["remote_workspace_ready"] = True
        evidence["repo_cloned"] = True
        if "project_reproduction_log" in result.content or "project_reproduction_log" in str(result.metadata):
            evidence["project_reproduction_log"] = True
            evidence["gpu_execution_attempted"] = True
    if result.name == "repro_report" and result.metadata.get("report_path"):
        results["report_path"] = result.metadata["report_path"]
        evidence["report_path"] = True

    step["evidence"] = evidence
    steps[current_step_id] = step
    workflow["steps"] = steps
    workflow["resources"] = resources
    workflow["results"] = results
    updated = state.next_turn()
    updated.active_workflow = workflow
    return updated
```

`AgentRuntime` 每次拿到 `ToolResult` 后先调用 `apply_tool_result()`，再调用 `validate_after_tool_results()`。这仍是通用 contract 归约，不是固定执行。

- [ ] **Step 5: 补齐 workflow step 自动推进**

如果测试停在 `step_1_audit`，在 `WorkflowContractRuntime` 中实现 `advance_if_completed()`：

```python
def advance_if_completed(self, state: RuntimeState) -> RuntimeState:
    workflow = dict(state.active_workflow or {})
    current_step_id = str(workflow.get("current_step_id") or "")
    steps = workflow.get("steps") or {}
    current = steps.get(current_step_id) or {}
    if current.get("status") != "completed":
        return state
    ordered = list(steps.keys())
    try:
        index = ordered.index(current_step_id)
    except ValueError:
        return state
    if index + 1 >= len(ordered):
        return state
    next_step_id = ordered[index + 1]
    updated = state.next_turn()
    updated.active_workflow = {**workflow, "current_step_id": next_step_id}
    next_tools = steps[next_step_id].get("allowed_tools") or []
    updated.allowed_tools = list(dict.fromkeys([*next_tools, "skill.invoke", "ask_user"]))
    return updated
```

`AgentRuntime` 在 validation 后调用 `advance_if_completed()`。

- [ ] **Step 6: 运行真实 E2E 测试**

Run:

```powershell
$env:LOBSTER_RUN_LAB4AI_INTEGRATION="1"
uv run pytest backend/tests/test_agent_runtime_existing_skill_real_e2e.py::test_real_lab4ai_existing_skill_main_flow -q -s
```

Expected: PASS。测试过程中会真实创建和释放 Lab4AI CPU/GPU 实例。

- [ ] **Step 7: 失败时记录真实适配缺口，不用固定 fallback 掩盖**

如果 Step 6 失败，只允许在以下层修复：

- `ToolRegistry` 真实工具实现或 schema。
- `WorkflowContractRuntime` contract 归约、step 推进、postcondition。
- `tool_mapping.py` 历史工具名适配。
- `rendering.py` 模板渲染。
- `recovery.py` 恢复策略。
- `ContextBuilder` skill/workflow 上下文。

不允许新增：

```python
if step.id == "step_7_gpu_execution":
    return mark_completed_without_real_evidence()
```

这类固定成功路径。

- [ ] **Step 8: 更新 docs/progress.md**

真实 E2E 通过后增加：

```markdown
- Agent Runtime V3 已通过真实 Lab4AI 主流程 E2E：使用 `skill.invoke` 激活 `lab4ai-auto-reproduct`，按现有 workflow contract 完成 CPU 创建、远程准备、CPU 释放、GPU 创建、GPU 主流程、报告生成和 GPU 释放。该路径未使用 `SkillWorkflowRunner` 固定 step executor，所有副作用均通过 `ToolExecutor -> ToolRegistry`。
```

如果未通过，增加：

```markdown
- Agent Runtime V3 真实 Lab4AI 主流程 E2E 尚未通过；失败点记录在测试输出中。当前禁止用固定 executor 或 CUDA smoke 假成功覆盖失败，后续只在 Tool、contract、模板渲染、recovery 和 postcondition 层修复。
```

- [ ] **Step 9: 更新 docs/proposal.md 的最终验收**

在 Agent Runtime First 章节增加：

```markdown
通用 Agent 客户端加载 skill 的最终生产验收以真实 Lab4AI E2E 为准：`AgentRuntime -> skill.invoke -> WorkflowContractRuntime -> ToolExecutor -> ToolRegistry` 必须跑通 `lab4ai-auto-reproduct` 主流程，且 CPU/GPU 实例必须释放、报告 artifact 必须生成、每个关键 step 必须有 required evidence。任何固定 executor 或不等价 fallback 不能作为通过依据。
```

## Execution Notes

- 每个任务完成后单独提交，提交信息使用 `feat(agent-runtime): add runtime state`、`test(agent-runtime): cover tool executor` 或 `docs(agent-runtime): align proposal` 这类具体描述。
- 不修改 `skills/` 目录。当前 invalid YAML 只通过 `WorkflowContractRuntime` compatibility mode 读取。
- `agent_runtime_v3_enabled` 默认关闭。只有测试或显式环境变量开启时才进入新 runtime。
- 新 runtime 失败时不要静默 fallback 到固定 workflow 成功路径；应返回结构化错误、HITL 或保持 feature flag 关闭。
- Lab4AI 真实联调不放进默认测试命令，避免误创建计费实例；需要显式设置 `LOBSTER_RUN_LAB4AI_INTEGRATION=1` 才能执行真实平台集成验证。

## Final Acceptance Mapping

最终开发成功必须同时满足以下四条。本节是执行计划的硬性验收映射，后续 review 时按这里逐项检查。

### 1. 用户配置任意 Anthropic-compatible 模型后，Agent 能稳定进入 tool-use 循环

实现落点：

- Task 3 `MessageStore`：把 assistant `tool_use` 和 user `tool_result` 按 Anthropic-compatible messages 结构持久化和回放。
- Task 4 `LLMAdapter`：把用户配置的 Anthropic-compatible 模型响应归一化为 `ModelResponse(text, tool_calls, usage, raw)`。
- Task 7 `AgentRuntime`：实现 `model -> tool_use -> ToolExecutor -> tool_result -> model` 主循环。
- Task 8 `AgentLoopManager`：在 `agent_runtime_v3_enabled=true` 时把 conversation 委托给 `AgentRuntime`。

必须通过的测试：

- `backend/tests/test_agent_runtime_messages.py::test_message_store_builds_model_messages`
- `backend/tests/test_agent_runtime_llm.py::test_llm_adapter_normalizes_tool_response`
- `backend/tests/test_agent_runtime_runtime.py::test_agent_runtime_runs_tool_loop_until_final_answer`
- `backend/tests/test_agent_loop.py::test_agent_loop_delegates_to_agent_runtime_when_v3_flag_enabled`

验收判定：

- fake LLM 第一轮返回 `tool_use`，runtime 执行工具并持久化 `tool_result`。
- fake LLM 第二轮能看到前一轮 `tool_result` 并输出 final answer。
- 未配置模型时不能静默回退到固定 workflow 冒充 agent tool-use。

### 2. 模型可以通过 `skill.invoke` 使用用户构造的 skill，而不是后端预写死流程

实现落点：

- Task 2 `RuntimeState`：默认暴露 `skill.invoke`，并能保存 `active_skill`。
- Task 23 `Intent Routing and Skill Trigger Semantics`：`SKILL.md` 中的 `triggers` 只产生候选 skill 和 prompt 提示，不直接执行 workflow。
- Task 9 `SkillInvokeTool`：实现模型可调用的 `skill.invoke` runtime tool，调用后更新 `active_skill` 和 `allowed_tools`。
- Task 10 `ContextBuilder`：把 active skill 的正文注入下一轮 system prompt。
- Task 12 `SkillTool 自动激活 workflow contract`：skill 带 workflow 时由 `skill.invoke` 激活 contract，而不是由后端固定 step executor 直接接管。

必须通过的测试：

- `backend/tests/test_agent_runtime_state.py::test_runtime_state_round_trips_through_conversation_metadata`
- `backend/tests/test_agent_runtime_intent.py::test_triggers_create_candidate_but_do_not_auto_invoke_skill`
- `backend/tests/test_agent_runtime_intent.py::test_task_type_reproduce_is_only_hint_not_auto_execute`
- `backend/tests/test_agent_runtime_skills.py::test_skill_invoke_sets_active_skill_and_allowed_tools`
- `backend/tests/test_agent_runtime_context.py::test_context_builder_includes_active_skill_and_workflow_step`
- `backend/tests/test_agent_runtime_skills.py::test_skill_invoke_activates_workflow_contract`

验收判定：

- `triggers` 命中只表示候选相关，不是后端硬开关。
- `task_type=reproduce` 只是 hint，不自动启动复现 workflow。
- runtime 中没有预先硬编码“复现任务必须进入某个固定 Python step executor”才能加载 skill。
- 模型调用 `skill.invoke({"skill": "lab4ai-auto-reproduct"})` 后，下一轮上下文和 allowed tools 发生变化。
- 未知 skill 返回 model-visible `tool_result` 错误，而不是后端伪造一个不存在的 skill。

### 3. 所有副作用都走 Tool，并有 schema、权限、审计、`tool_result`

实现落点：

- Task 5 `ToolProtocol Adapter`：统一 Tool schema 校验和 `tool_result` block 映射。
- Task 6 `ToolExecutor`：统一处理 allowlist、schema error、permission / HITL、tool execution、tool events 和 model-visible `tool_result`。
- Task 8 `AgentLoopManager Feature Flag 委托`：开启 V3 后，模型请求的工具统一从 `AgentRuntime -> ToolExecutor -> ToolRegistry` 进入。
- Task 14 前端 runtime 事件：把 `tool_started / tool_completed / tool_error / permission_requested` 展示在可审计活动流中。

必须通过的测试：

- `backend/tests/test_agent_runtime_tool_executor.py::test_validate_tool_input_reports_missing_required_property`
- `backend/tests/test_agent_runtime_tool_executor.py::test_registry_tool_adapter_maps_result_to_tool_result_block`
- `backend/tests/test_agent_runtime_tool_executor.py::test_tool_executor_rejects_tool_outside_allowlist`
- `backend/tests/test_agent_runtime_tool_executor.py::test_tool_executor_returns_schema_error_as_tool_result`
- `frontend/src/__tests__/ChatPage.test.tsx` 中 runtime tool activity event 测试

验收判定：

- 模型不能绕过 ToolExecutor 直接创建 Lab4AI 实例、执行 SSH、写文件或生成报告。
- 工具参数不符合 schema 时，错误以 `tool_result is_error=true` 回到模型。
- 高风险或计费工具仍走确认策略，产生 `permission_requested` / HITL 状态。
- 每次工具调用都有 `run_id / tool_call_id / tool_name / ok / error_code / audit metadata` 可追踪。

### 4. 复现 workflow 的完成由 required evidence / postconditions 判定，不由模型自然语言或固定 fallback 判定

实现落点：

- Task 11 `WorkflowContractRuntime`：把 workflow 解析为 runtime contract，并把当前 step 的 allowed tools、required tools、required evidence 放入状态。
- Task 12 `skill.invoke` 激活 workflow contract：workflow 成为 skill 调用后的 contract layer。
- Task 13 `Workflow Postcondition 接口与 recovery 状态`：每轮 tool results 后执行 contract validation；缺 required tool / evidence 时进入 recovery，不完成 step。
- Task 15 文档保护：在 `docs/proposal.md` 明确禁止新增 `if step.id == "step_1_audit"` 这类固定 executor 作为主路径。
- Task 24 真实 Lab4AI E2E：用真实 CPU/GPU 实例验证现有 skill 主流程，且不允许固定 executor 或不等价 fallback 作为通过依据。

必须通过的测试：

- `backend/tests/test_agent_runtime_workflow_contract.py::test_workflow_contract_loads_current_project_reproduce_without_modifying_skills`
- `backend/tests/test_agent_runtime_workflow_recovery.py::test_workflow_contract_stays_on_step_when_required_tool_missing`
- `backend/tests/test_agent_runtime_workflow_recovery.py::test_workflow_contract_records_successful_tool_call_as_evidence`
- 总体验证中的 `backend/tests/test_workflow.py`，确保旧链路在 feature flag 关闭时仍保持兼容。
- 显式设置 `LOBSTER_RUN_LAB4AI_INTEGRATION=1` 后，`backend/tests/test_agent_runtime_existing_skill_real_e2e.py::test_real_lab4ai_existing_skill_main_flow`

验收判定：

- step 缺少 `required_tools` 或 `required_evidence` 时，不能标记 completed。
- 模型自然语言“已完成复现”不能使 workflow step 完成。
- 固定 fallback 不能用不等价命令绕过 workflow contract；缺能力时进入 recovery、HITL 或 failed。
- GPU/CUDA smoke 只能作为环境证据，不能单独作为项目复现成功证据。
- 真实 E2E 必须看到 CPU/GPU 资源均释放，报告 artifact 生成，且事件流中没有 `workflow_fixed_executor_used`。

## Self-Review

- Spec coverage: 覆盖 RuntimeState、MessageStore、LLMAdapter、ToolProtocol、ToolExecutor、SkillTool、WorkflowContractRuntime、HITL 基础、前端事件和文档对齐。
- Placeholder scan: 已检查常见占位标记，计划中的任务、文件和验证命令均已具体化。
- Type consistency: `RuntimeState`、`ModelRequest`、`ModelResponse`、`ExecutedToolResult`、`SkillInvokeTool`、`WorkflowContractRuntime` 在首次出现时给出定义或创建任务。
- Scope control: 第一轮实现以 feature flag 旁路接入，不删除旧 workflow，不进行真实 Lab4AI 创建。
