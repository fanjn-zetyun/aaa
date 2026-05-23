# Agent Runtime First Design

## Status

方案已由用户确认：采用方案 A，先建设通用 Agent Runtime，再把 Lab4AI 复现 workflow 作为 skill / contract 插件接入。

本设计不修改 `skills/` 目录。后续如果需要迁移 `skills/lab4ai-auto-reproduct/project_reproduce.yaml` 的格式，必须单独确认迁移方案，并同步更新 `docs/proposal.md`。

## Problem

当前 LOBSTER 已有模型配置、SkillLoader、ToolRegistry、WorkflowRunner 和部分 step 内模型 tool-use，但主执行权仍在 `SkillWorkflowRunner` 和后端固定 step executor 中。结果是：

- skill 主要被后端预选并注入 prompt，模型不能像 Claude Code 一样主动调用 skill。
- workflow instruction 与真实执行语义分离，`allowed_tools`、completion contract 和许多 step 逻辑写在 Python 代码里。
- 工具失败、schema 错误、postcondition 失败没有形成稳定的 `tool_result -> model recovery -> revalidate` 闭环。
- `Conversation.metadata.workflow_steps` 能表达流程状态，但不能完整 replay 一次 agent 执行轨迹。
- 继续在 `workflow.py` 增加 `if step.id == ...` 会让系统更像固定 workflow 引擎，而不是通用 Agent 客户端。

目标是把 LOBSTER 改造成 Claude Code 类 Agent 客户端：用户配置 Anthropic-compatible 模型后，模型在后端 Agent Runtime 中通过 tools 和 skills 完成任务；后端负责权限、审计、资源归属、HITL、事件流和验收。

## Goals

1. 建立通用 `AgentRuntime / QueryEngine`，作为 conversation 执行的唯一主循环。
2. 实现标准 tool-use 循环：`assistant tool_use -> ToolExecutor -> user/tool_result -> next model turn`。
3. 让 skill 成为模型可调用的工具，而不是后端启动时硬编码选择后的 prompt 拼接。
4. 将 Tool 从服务函数集合升级为协议对象，具备 schema、权限、执行、结果映射、审计和上下文修改能力。
5. 将 Lab4AI 复现 workflow 降级为 Agent Runtime 内部的 contract layer：约束 step 顺序、allowed tools、postconditions 和 cleanup，不再主导所有执行。
6. 保留现有 FastAPI、React、SQLAlchemy、多用户、Lab4AI 归属和 WebSocket 事件流。
7. 不修改 `skills/` 目录，除非用户后续明确批准 skill schema 迁移。

## Non-Goals

- 不复用 `claude-code-analysis` 的 CLI/TUI、Ink、bridge 或本地 sandbox 代码。
- 不把模型 API key、SSH 密码、Lab4AI 凭证暴露给模型或前端普通事件。
- 不允许 Tool mock 成功推进生产 workflow。
- 不在第一阶段实现本地 IDE/code-editing agent 的完整能力。
- 不引入向量库作为 Agent Runtime 的前置依赖。

## Target Architecture

```text
User Message
  -> Conversation API
  -> AgentRuntime
     -> RuntimeState / MessageStore
     -> ContextBuilder
     -> SkillRegistry + SkillTool
     -> WorkflowContractRuntime
     -> LLMAdapter
     -> ToolExecutor
        -> ToolProtocol
        -> Permission / HITL
        -> ToolRegistry
     -> EventBus / WebSocket
     -> CleanupManager
```

### AgentRuntime

`AgentRuntime` is the top-level execution owner for a conversation run. It replaces the current pattern where `AgentLoopManager` enters `SkillWorkflowRunner` and workflow-specific executors drive the task.

Responsibilities:

- Load current `Conversation`, user model config, message history, pending runtime state and metadata.
- Create or resume a `runtime_run_id`.
- Build each model request from persisted messages, compacted memory, active skill context, active workflow contract and available tools.
- Persist every assistant message, tool use and tool result in order.
- Execute the model loop until final answer, HITL pause, stop request, max turn limit, unrecoverable error or cleanup.
- Publish structured WebSocket events for model text, tool activity, workflow progress, HITL and final answer.
- Own resource cleanup semantics for stopped / failed runs.

Pseudo-flow:

```python
async def run(conversation_id: int, user_message: str | None) -> RuntimeResult:
    state = await state_store.load_or_create(conversation_id)
    await message_store.append_user_message(user_message)

    while state.can_continue():
        request = await context_builder.build_model_request(state)
        response = await llm_adapter.complete(request)
        await message_store.append_assistant_response(response)
        await event_bus.publish_assistant(response)

        if not response.tool_calls:
            return await finalizer.complete(state, response)

        tool_results = await tool_executor.execute_all(response.tool_calls, state)
        await message_store.append_tool_results(tool_results)
        await event_bus.publish_tool_results(tool_results)

        state = await state_reducer.apply_tool_results(state, tool_results)
        state = await workflow_contract_runtime.validate_after_turn(state)

    return await finalizer.stop_due_to_limit_or_pause(state)
```

### RuntimeState

`RuntimeState` is the durable state for one active run. It should be serializable into `Conversation.metadata.runtime` while canonical transcript data lives in `ConversationMessage`.

Fields:

```python
class RuntimeState:
    run_id: str
    conversation_id: int
    status: Literal["running", "waiting_for_user", "stopping", "completed", "failed", "stopped"]
    model: str
    max_turns: int
    turn_count: int
    active_skill: SkillInvocationState | None
    active_workflow: WorkflowContractState | None
    allowed_tools: list[str]
    pending_tool_call: PendingToolCall | None
    pending_user_input: dict | None
    token_budget: dict
    cleanup_required: bool
```

Existing `Conversation.metadata.workflow_*` can remain during migration, but new code should treat `runtime` as the parent state and workflow as one child state.

### MessageStore

The runtime must persist a replayable transcript, not only a workflow status snapshot.

Message roles:

- `user`: user text or tool_result blocks passed back to the model.
- `assistant`: assistant text and tool_use blocks.
- `tool`: normalized internal record for tool execution, including audit metadata.
- `system`: runtime progress, compaction markers or administrative state changes when useful for UI.

Every tool call record must include:

```json
{
  "run_id": "...",
  "tool_call_id": "...",
  "tool_name": "...",
  "workflow_step_id": "...",
  "input": {},
  "ok": true,
  "error_code": null,
  "retryable": null,
  "stdout": "",
  "stderr": "",
  "exit_code": null,
  "artifact_paths": [],
  "started_at": "...",
  "completed_at": "..."
}
```

This transcript becomes the source for resume, audit, debugging and frontend event reconstruction.

### LLMAdapter

`LLMAdapter` hides provider differences while keeping the runtime Anthropic-compatible first.

Input:

```python
class ModelRequest:
    system: str
    messages: list[dict]
    tools: list[dict]
    tool_choice: dict | None
    max_tokens: int
    temperature: float | None
```

Output:

```python
class ModelResponse:
    text: str
    tool_calls: list[ToolCall]
    stop_reason: str | None
    usage: dict
    raw: dict
```

If the configured model does not support tool-use, runtime should fail early for agentic tasks with a clear error, or enter pure chat mode for non-agent tasks. It should not silently run fixed backend workflows as a substitute for model tool-use.

### ToolProtocol

Tools become first-class protocol objects.

```python
class ToolProtocol(Protocol):
    name: str
    description: str
    input_schema: dict
    output_schema: dict | None
    read_only: bool
    destructive: bool
    concurrency_safe: bool
    risk_level: Literal["low", "medium", "high", "critical"]
    audit_category: Literal["lab4ai", "ssh", "file", "llm", "workflow", "skill", "general"]

    def anthropic_schema(self) -> dict: ...
    def validate_input(self, input: dict) -> ValidationResult: ...
    async def check_permission(self, input: dict, context: ToolContext) -> PermissionDecision: ...
    async def call(self, input: dict, context: ToolContext) -> ToolResult: ...
    def to_tool_result_block(self, result: ToolResult, tool_call_id: str) -> dict: ...
    def context_modifier(self, result: ToolResult) -> ContextModifier | None: ...
```

The current `ToolRegistry` can be adapted rather than rewritten immediately. Existing Lab4AI, SSH, repo, paper and report tools remain the concrete executors.

### ToolExecutor

`ToolExecutor` is the only component that executes model requested tools.

Responsibilities:

- Canonicalize tool names and aliases.
- Reject tools outside current `allowed_tools`.
- Validate input against schema before permission checks.
- Render runtime/workflow templates before Tool call when applicable.
- Enforce HITL and pause runtime when approval is required.
- Execute tools serially by default.
- Convert all errors into model-visible `tool_result` blocks.
- Persist audit metadata and publish `tool_started`, `tool_completed`, `tool_error`, `permission_requested` events.
- Apply context modifiers after successful tool results.

Important rule: schema errors, unknown tools, denied tools and executor failures are still returned to the model as `tool_result` content unless the run must pause for HITL or cleanup.

### SkillRegistry and SkillTool

`SkillRegistry` loads skill metadata, body and declared workflow files. `SkillTool` makes skills model-callable.

Tool name:

```text
skill.invoke
```

Input:

```json
{
  "skill": "lab4ai-auto-reproduct",
  "args": {
    "github_url": "...",
    "paper_url": "..."
  }
}
```

Output:

```json
{
  "success": true,
  "skill": "lab4ai-auto-reproduct",
  "new_messages": [],
  "allowed_tools": [],
  "workflow_contract_loaded": true,
  "model_hints": {}
}
```

Effects:

- Inject skill body and relevant workflow contract into runtime context.
- Narrow `allowed_tools` to the intersection of skill allowlist, workflow step allowlist and globally enabled tools.
- Set `active_skill`.
- If the skill has a workflow, initialize `active_workflow`.

`SkillTool` must not execute side effects directly. It launches context and constraints; real actions still go through regular tools.

### WorkflowContractRuntime

Workflow becomes a contract layer inside `AgentRuntime`, not the top-level executor.

Responsibilities:

- Parse workflow documents into strict `WorkflowContract`.
- Maintain current step, dependency state, attempts, recovery attempts and evidence.
- Expose current step instruction and allowed tools to `ContextBuilder`.
- Validate that tool calls are legal for the current step.
- Validate postconditions after each relevant turn.
- Advance to next step only when required tools, required evidence and postconditions pass.
- Enter recovery mode when ToolResult or postcondition fails.
- Request HITL or fail when recovery is exhausted.
- Trigger cleanup for owned Lab4AI resources on stop/failure.

The runtime should eventually support this schema shape:

```yaml
version: agent-workflow/v1
name: lab4ai-auto-reproduct
entry: step_1_audit
tasks:
  - id: step_1_audit
    instruction: ...
    allowed_tools:
      - analyze_repo
      - analyze_paper
    required_tools:
      - analyze_repo
      - analyze_paper
    required_evidence:
      - repo_audit
      - paper_analysis
    postconditions:
      - type: metadata_exists
        path: workflow_results.repo_audit
    recovery:
      max_attempts: 2
      allowed_tools:
        - analyze_repo
        - analyze_paper
```

Because current `project_reproduce.yaml` is not valid standard YAML, first implementation should add a compatibility parser plus validator that reports format defects clearly. It should not silently infer execution semantics with regex long-term.

### ContextBuilder

`ContextBuilder` composes the model request. It should be deterministic and testable.

Context sections:

- LOBSTER system rules: multi-user Web, backend-only Tool execution, no secret leakage.
- Current user task and conversation summary.
- Active skill instruction, if any.
- Active workflow current step instruction, expected output, allowed tools and postconditions.
- Available tools as schemas.
- Recent messages and compacted transcript.
- Relevant long-term memory, if enabled.
- Recovery context when previous turn failed.

It must not include Lab4AI credentials, SSH passwords, raw API keys or hidden admin settings.

### EventBus and Frontend Model

WebSocket events should be derived from runtime events, not from workflow-only state.

Core event types:

- `runtime_started`
- `assistant_delta`
- `assistant_message`
- `tool_started`
- `tool_completed`
- `tool_error`
- `permission_requested`
- `runtime_waiting_for_user`
- `workflow_loaded`
- `workflow_step_started`
- `workflow_step_progress`
- `workflow_step_completed`
- `workflow_step_failed`
- `workflow_recovery_started`
- `cleanup_started`
- `cleanup_completed`
- `runtime_completed`
- `runtime_failed`
- `runtime_stopped`

The frontend should show a transcript-oriented activity stream and keep the workflow board as a specialized view of `active_workflow`.

## Data Flows

### General Chat Without Skill

1. User sends message.
2. AgentRuntime builds model request with base tools such as `skill.invoke`, `ask_user`, safe read-only tools.
3. Model answers directly or calls a tool.
4. Tool results are returned to the model until no tool calls remain.
5. Final assistant answer is persisted and streamed.

### Skill Invocation

1. User asks for a reproducible research task.
2. Runtime exposes `skill.invoke` and skill summaries.
3. Model calls `skill.invoke` with `lab4ai-auto-reproduct`.
4. ToolExecutor runs SkillTool.
5. SkillTool loads skill body and workflow contract into runtime state.
6. Next model turn sees current skill/workflow context and the narrowed tool set.

### Workflow Step Execution

1. WorkflowContractRuntime exposes current step instruction and allowed tools.
2. Model calls one or more allowed tools.
3. ToolExecutor executes them and returns tool_result blocks.
4. WorkflowContractRuntime records tool calls, effects, artifacts and evidence.
5. Postconditions run after the relevant tool results.
6. Step advances only when contract passes.

### Tool Failure Recovery

1. Tool returns `ok=false` or postcondition fails.
2. ToolResult is persisted with `error_code`, `retryable`, logs and recovery suggestion.
3. Runtime enters recovery turn for the same step.
4. Model sees failure context and can call only recovery-allowed tools.
5. Postcondition is re-run after repair.
6. If max attempts are exhausted, runtime enters `waiting_for_user` or `failed`.

### HITL

1. Tool permission check returns `ask`.
2. Runtime persists `pending_tool_call` with `run_id + tool_call_id + workflow_step_id + tool_name`.
3. Runtime status becomes `waiting_for_user`.
4. Frontend shows an in-chat confirmation card.
5. User reply resumes exactly the same pending tool call.
6. Old approvals cannot be reused for a different run or tool call.

## Migration Plan

### Phase 0: Proposal Alignment

- Update `docs/proposal.md` to state that AgentRuntime is the top-level runtime and WorkflowContractRuntime is a contract layer.
- Keep existing statements about `skills/` as read-only contract source.
- Explicitly deprecate adding new fixed step executors as the main path.

### Phase 1: Runtime Skeleton

- Create `backend/app/agent_runtime/` with `runtime.py`, `state.py`, `messages.py`, `events.py`, `context.py` and `llm.py`.
- Route non-workflow conversations through the new runtime first.
- Preserve existing API and WebSocket contracts.
- Add fake LLM tests that prove multi-turn tool-use works.

### Phase 2: Tool Protocol Adapter

- Wrap existing `ToolRegistry` definitions in `ToolProtocol`.
- Move tool-use execution logic out of `agent_loop.py` into `agent_runtime/tool_executor.py`.
- Ensure schema errors and tool failures become model-visible tool_result blocks.
- Keep existing Lab4AI and SSH executors.

### Phase 3: SkillTool

- Add `skill.invoke` as a normal tool.
- Expose skill summaries to model context.
- On invocation, inject skill body, allowed tools and workflow metadata into runtime state.
- Keep existing rule fallback only as a bootstrapping path when model selection is unavailable, and record it as fallback.

### Phase 4: Workflow Contract Integration

- Add `WorkflowContractRuntime` under `agent_runtime/workflows/`.
- Parse current workflow with compatibility mode, then validate and normalize to a strict internal contract.
- Make workflow state a child of runtime state.
- Stop adding new fixed step executor branches; instead encode required tools, evidence and postconditions in contract adapters.

### Phase 5: Recovery Loop

- Implement `ToolResult(ok=false)` and postcondition failures as recovery turns.
- Persist recovery attempts.
- Add max attempts and HITL escalation.
- Re-run postconditions after repair.

### Phase 6: Frontend Transcript Activity

- Update ChatPage to render runtime events as the primary activity stream.
- Keep workflow board as a filtered view.
- Ensure final answer is separate from tool logs and intermediate events.

### Phase 7: Real Lab4AI End-to-End Validation

- Run with real Lab4AI credentials against CPU and GPU instances.
- Verify SSH execution, remote workspace, report artifacts and cleanup.
- Remove or quarantine smoke-test fallbacks that can prove only environment health rather than task success.

## Testing Strategy

Unit tests:

- `AgentRuntime` stops when model returns no tool_use.
- `AgentRuntime` continues after tool_result when model returns another tool_use.
- Unknown tool becomes tool_result error.
- Invalid tool input becomes tool_result schema error.
- Tool outside allowlist is rejected and visible to model.
- `skill.invoke` updates active skill and allowed tools.
- Workflow step cannot complete without required evidence.
- Postcondition failure triggers recovery state.
- HITL pauses and resumes by `run_id + tool_call_id`.

Integration tests:

- Fake model + fake tools replay a complete skill invocation flow.
- Fake model + fake workflow complete multiple steps without fixed step executor branches.
- Tool failure recovery succeeds after one repair turn.
- Runtime stop triggers cleanup for owned resources.
- WebSocket event order matches persisted transcript order.

End-to-end tests:

- Reproduce task reaches Lab4AI credential HITL without creating resources in test mode.
- Real Lab4AI smoke environment creates and releases CPU instance under an explicit integration flag.
- Real GPU validation proves project command/report artifact success, not just CUDA availability.

## Acceptance Criteria

The migration is successful when:

1. A configured Anthropic-compatible model can run a multi-turn tool-use loop from persisted conversation state.
2. The model can call `skill.invoke` to activate a skill, and the runtime changes context and allowed tools accordingly.
3. Tool execution always goes through ToolExecutor and ToolProtocol, with schema validation, permission checks, audit metadata and model-visible tool_result.
4. Workflow progression is controlled by contract validation, not Python `if step.id == ...` branches.
5. Tool failures and postcondition failures are recoverable through bounded model turns.
6. HITL resumes the exact pending tool call and cannot reuse stale approvals.
7. A transcript can be replayed or inspected to explain why the agent did each action.
8. No production path marks Lab4AI reproduction complete from mock output or generic CUDA smoke alone.

## Risks

- Some configured models may claim Anthropic compatibility but emit invalid tool_use. Mitigation: strict parsing, tool_result schema errors and explicit model capability test.
- Current workflow files contain historical names and non-standard YAML. Mitigation: compatibility parser first, strict normalized contract next, skill file migration only after explicit approval.
- Moving execution ownership from WorkflowRunner to AgentRuntime can break current reproduce happy path. Mitigation: migrate non-workflow first, then reproduce behind feature flag.
- Long Lab4AI tasks need streaming and cancellation. Mitigation: preserve current WebSocket events and add runtime-level cancellation/cleanup before changing deep workflow behavior.
- ToolProtocol abstraction may grow too broad. Mitigation: first adapter only covers fields needed for existing tools; defer concurrency and context modifiers beyond `skill.invoke`.

## Open Decisions

- Whether to update `docs/proposal.md` in the same PR as Phase 0 or keep this spec as the review artifact first.
- Whether `skill.invoke` should be exposed for all tasks by default or only when skill summaries have high relevance.
- Whether compatibility workflow parsing should accept current invalid YAML indefinitely or only for one migration release.
- Whether the first production rollout should use a feature flag such as `AGENT_RUNTIME_V3_ENABLED`.

## Implementation Handoff

After this spec is reviewed, the implementation plan should be split into small tasks:

1. Proposal alignment and feature flag.
2. Runtime state and transcript store.
3. LLM adapter normalization.
4. ToolProtocol adapter and ToolExecutor.
5. Basic runtime loop with fake LLM tests.
6. SkillTool and skill context injection.
7. WorkflowContractRuntime compatibility layer.
8. Recovery loop and postcondition validation.
9. WebSocket/frontend event alignment.
10. Lab4AI integration validation.

