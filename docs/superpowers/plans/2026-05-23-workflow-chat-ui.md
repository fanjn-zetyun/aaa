# Workflow Chat UI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the noisy Agent reply process display with a natural skill-selection card, a YAML-step-driven workflow card, and step-embedded human input panels.

**Architecture:** Keep backend workflow execution unchanged, but stream structured skill-selection evidence so the frontend does not infer model choice from text. In the frontend, treat one Agent run as a composed UI state: skill selection, workflow state, optional step-level human input, and final answer. Workflow progress and tool events are merged into the relevant step instead of being rendered as separate timeline blocks.

**Tech Stack:** FastAPI backend, existing AgentLoop stream events, React 19, TypeScript, TanStack Query, Vitest, Testing Library, Tailwind utility classes.

---

## File Structure

- Modify `backend/app/services/agent_loop.py`
  - Add structured `skill_selection` and `workflow_path` fields to the existing `stage="skill_selection"` progress event.
  - Keep workflow execution unchanged.

- Modify `backend/tests/test_agent_loop.py`
  - Add a focused unit test that verifies the skill-selection progress payload exposes safe evidence fields.

- Modify `frontend/src/pages/ChatPage.tsx`
  - Extend frontend conversation/stream/message types.
  - Store skill selection state on the active Agent message.
  - Route workflow step events into the workflow card only.
  - Render `SkillSelectionCard`, vertical `WorkflowRunCard`, and `HumanInputPanel`.
  - Keep final answer rendering for end-of-run summary only.

- Modify `frontend/src/__tests__/ChatPage.test.tsx`
  - Update existing expectations away from timeline-heavy UI.
  - Add tests for skill selection evidence, YAML-step workflow display, step-level human input, and Lab4AI credential submission.

- Optional after the first passing implementation: create `frontend/src/components/AgentRunCard.tsx`
  - Move the new presentational components out of `ChatPage.tsx` if the file becomes difficult to review.
  - Do this only after tests pass once in-place, so behavior and refactor are separate commits.

---

### Task 1: Stream Structured Skill Selection Evidence

**Files:**
- Modify: `backend/app/services/agent_loop.py`
- Test: `backend/tests/test_agent_loop.py`

- [ ] **Step 1: Write the failing backend test**

Append this test to `backend/tests/test_agent_loop.py`:

```python
async def test_skill_selection_progress_exposes_structured_evidence():
    manager = AgentLoopManager()
    conversation_id = 123
    manager._active_runs[conversation_id] = "run-skill"

    metadata = {
        "skill_selection": {
            "selected_skill": "lab4ai-auto-reproduct",
            "source": "model",
            "model_choice": "lab4ai-auto-reproduct",
            "fallback_choice": None,
            "reason": "Model selected registered skill `lab4ai-auto-reproduct`.",
            "confidence": None,
            "error": None,
        }
    }

    await manager._progress(
        conversation_id,
        "已选择 skill：lab4ai-auto-reproduct（来源：model）。",
        stage="skill_selection",
        extra={
            "skill_selection": metadata["skill_selection"],
            "workflow_path": "skills/lab4ai-auto-reproduct/project_reproduce.yaml",
        },
    )

    event = manager._streams[conversation_id].history[-1]
    assert event["type"] == "progress"
    assert event["stage"] == "skill_selection"
    assert event["skill_selection"]["source"] == "model"
    assert event["skill_selection"]["model_choice"] == "lab4ai-auto-reproduct"
    assert event["workflow_path"] == "skills/lab4ai-auto-reproduct/project_reproduce.yaml"
    assert "workflow_context" not in event["skill_selection"]
    assert "body" not in event["skill_selection"]
```

- [ ] **Step 2: Run the backend test to verify the current payload path is covered**

Run:

```powershell
uv run pytest backend/tests/test_agent_loop.py::test_skill_selection_progress_exposes_structured_evidence -q
```

Expected before implementation: the test may pass if `_progress(extra=...)` already preserves arbitrary fields. If it passes, keep it; it protects the next step. If it fails, the failure should mention missing `skill_selection` or `workflow_path` in the progress event.

- [ ] **Step 3: Add workflow path helper and structured progress payload**

In `backend/app/services/agent_loop.py`, add this helper near `_requires_workflow_task`:

```python
def _workflow_display_path_for_skill(skill: SkillDefinition | None) -> str | None:
    if not skill or not skill.workflow_context:
        return None
    if skill.name == "lab4ai-auto-reproduct":
        return f"skills/{skill.name}/project_reproduce.yaml"
    return f"skills/{skill.name}/workflow.yaml"
```

Then update the existing skill-selection progress call inside `_run()` from:

```python
extra={"skill_selection_source": selection_source},
```

to:

```python
extra={
    "skill_selection_source": selection_source,
    "skill_selection": metadata.get("skill_selection"),
    "workflow_path": _workflow_display_path_for_skill(skill),
},
```

- [ ] **Step 4: Run targeted backend tests**

Run:

```powershell
uv run pytest backend/tests/test_agent_loop.py backend/tests/test_skill_selector.py -q
```

Expected: all selected tests pass.

- [ ] **Step 5: Commit backend stream evidence**

```powershell
git add backend/app/services/agent_loop.py backend/tests/test_agent_loop.py
git commit -m "feat: stream skill selection evidence"
```

---

### Task 2: Add Frontend Skill Selection State and Tests

**Files:**
- Modify: `frontend/src/pages/ChatPage.tsx`
- Test: `frontend/src/__tests__/ChatPage.test.tsx`

- [ ] **Step 1: Write the failing frontend test for model selection evidence**

Add this test to `frontend/src/__tests__/ChatPage.test.tsx`:

```tsx
it("shows model-selected skill evidence from conversation metadata", async () => {
  conversationPayload.metadata = {
    task_type: "reproduce",
    github_url: "https://github.com/jsnzwu/motion-guided-flow",
    skill_selection: {
      selected_skill: "lab4ai-auto-reproduct",
      source: "model",
      model_choice: "lab4ai-auto-reproduct",
      fallback_choice: null,
      reason: "Model selected registered skill `lab4ai-auto-reproduct`.",
      confidence: null,
      error: null,
    },
    workflow_name: "Lab4AI_Auto_Reproduction_Pipeline",
    workflow_steps: [],
  };

  renderChat();

  expect(await screen.findByText("模型选择了 lab4ai-auto-reproduct")).toBeInTheDocument();
  expect(screen.getByText("模型选择")).toBeInTheDocument();

  fireEvent.click(screen.getByText("查看选择证据"));

  expect(screen.getByText("source")).toBeInTheDocument();
  expect(screen.getByText("model")).toBeInTheDocument();
  expect(screen.getByText("model_choice")).toBeInTheDocument();
  expect(screen.getAllByText("lab4ai-auto-reproduct").length).toBeGreaterThan(0);
  expect(screen.queryByText("workflow_context")).not.toBeInTheDocument();
});
```

- [ ] **Step 2: Run the frontend test to verify it fails**

Run:

```powershell
cd frontend
npm run test:run -- src/__tests__/ChatPage.test.tsx -t "shows model-selected skill evidence"
```

Expected: FAIL because `ChatPage` does not yet render skill-selection metadata.

- [ ] **Step 3: Extend TypeScript interfaces**

In `frontend/src/pages/ChatPage.tsx`, add these interfaces after `PendingUserInput`:

```tsx
interface SkillSelectionState {
  selected_skill?: string;
  source?: "model" | "fallback" | string;
  model_choice?: string | null;
  fallback_choice?: string | null;
  reason?: string | null;
  confidence?: number | null;
  error?: string | null;
}
```

Extend `Conversation["metadata"]`:

```tsx
skill_selection?: SkillSelectionState;
```

Extend `StreamPayload`:

```tsx
skill_selection?: SkillSelectionState;
skill_selection_source?: string;
workflow_path?: string | null;
```

Extend `ChatMessage`:

```tsx
skillSelection?: SkillSelectionState;
workflowPath?: string | null;
```

- [ ] **Step 4: Add selection helpers**

Add these helpers near `workflowStateFromConversation`:

```tsx
function skillSelectionFromConversation(conversation?: Conversation): SkillSelectionState | undefined {
  const selection = conversation?.metadata?.skill_selection;
  if (!selection?.selected_skill && !selection?.model_choice && !selection?.fallback_choice) {
    return undefined;
  }
  return selection;
}

function skillSelectionFromPayload(payload: StreamPayload): SkillSelectionState | undefined {
  if (payload.skill_selection) return payload.skill_selection;
  if (!payload.skill_selection_source) return undefined;
  return {
    selected_skill: undefined,
    source: payload.skill_selection_source,
    model_choice: null,
    fallback_choice: null,
    reason: payload.content || null,
    confidence: null,
    error: null,
  };
}

function workflowPathFromSelection(selection?: SkillSelectionState, payloadPath?: string | null) {
  if (payloadPath) return payloadPath;
  if (selection?.selected_skill === "lab4ai-auto-reproduct") {
    return "skills/lab4ai-auto-reproduct/project_reproduce.yaml";
  }
  return null;
}
```

- [ ] **Step 5: Attach selection state to persisted messages**

Update `buildChatMessages()` return line from:

```tsx
return attachWorkflowToLastAgent(result, workflowStateFromConversation(conversation), conversation?.updated_at);
```

to:

```tsx
return attachRunStateToLastAgent(
  result,
  workflowStateFromConversation(conversation),
  skillSelectionFromConversation(conversation),
  workflowPathFromSelection(skillSelectionFromConversation(conversation)),
  conversation?.updated_at
);
```

Replace `attachWorkflowToLastAgent` with:

```tsx
function attachRunStateToLastAgent(
  messages: ChatMessage[],
  workflow: WorkflowState | undefined,
  skillSelection: SkillSelectionState | undefined,
  workflowPath: string | null,
  updatedAt?: string
) {
  if (!workflow && !skillSelection) return messages;
  const lastAgentIndex = findLastIndex(messages, (item) => item.role === "agent");
  if (lastAgentIndex >= 0) {
    return messages.map((item, index) =>
      index === lastAgentIndex
        ? {
            ...item,
            workflow: item.workflow || workflow,
            skillSelection: item.skillSelection || skillSelection,
            workflowPath: item.workflowPath || workflowPath,
          }
        : item
    );
  }
  return [
    ...messages,
    {
      id: `workflow-${updatedAt || workflow?.name || skillSelection?.selected_skill || "run"}`,
      role: "agent" as const,
      content: "",
      created_at: updatedAt || new Date().toISOString(),
      type: "text" as const,
      workflow,
      skillSelection,
      workflowPath,
    },
  ];
}
```

- [ ] **Step 6: Render a first version of SkillSelectionCard**

In `AgentResponse`, add `message.skillSelection` to `hasProcess`:

```tsx
const hasProcess = !!message.skillSelection || !!message.workflow || !!message.events?.length;
```

Render the card before the workflow card:

```tsx
{message.skillSelection && (
  <SkillSelectionCard
    selection={message.skillSelection}
    workflowPath={message.workflowPath}
  />
)}
```

Add this component below `RunningState`:

```tsx
function SkillSelectionCard({
  selection,
  workflowPath,
}: {
  selection: SkillSelectionState;
  workflowPath?: string | null;
}) {
  const selected = selection.selected_skill || selection.model_choice || selection.fallback_choice || "未选择";
  const sourceLabel = selection.source === "model" ? "模型选择" : "规则兜底";
  const sourceClass =
    selection.source === "model"
      ? "border-blue-100 bg-blue-50 text-blue-700"
      : "border-amber-100 bg-amber-50 text-amber-700";
  return (
    <section className="overflow-hidden rounded-xl border border-slate-200 bg-white shadow-sm">
      <div className="border-b border-slate-100 bg-slate-50 px-4 py-3">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0">
            <div className="text-ui-meta font-semibold uppercase tracking-wide text-slate-400">
              Skill Selection
            </div>
            <h3 className="mt-1 break-words text-md-h3 font-semibold text-slate-800">
              {sourceLabel === "模型选择" ? "模型选择了" : "规则兜底选择了"} {selected}
            </h3>
            {workflowPath && (
              <p className="mt-1 break-words text-ui-small text-slate-500">
                已加载 {workflowPath}
              </p>
            )}
          </div>
          <span className={`shrink-0 rounded-full border px-2.5 py-1 text-ui-micro font-medium ${sourceClass}`}>
            {sourceLabel}
          </span>
        </div>
      </div>
      <details className="group">
        <summary className="flex cursor-pointer list-none items-center justify-between gap-3 px-4 py-3 text-ui-small font-medium text-slate-600 hover:bg-slate-50">
          <span>查看选择证据</span>
          <ChevronIcon className="h-4 w-4 shrink-0 text-slate-400 transition-transform group-open:rotate-180" />
        </summary>
        <div className="grid grid-cols-[120px_minmax(0,1fr)] gap-x-3 gap-y-2 border-t border-slate-100 px-4 py-3 text-ui-small">
          <EvidenceRow label="source" value={selection.source || "-"} />
          <EvidenceRow label="selected_skill" value={selection.selected_skill || "-"} />
          <EvidenceRow label="model_choice" value={selection.model_choice || "-"} />
          <EvidenceRow label="fallback_choice" value={selection.fallback_choice || "-"} />
          <EvidenceRow label="workflow" value={workflowPath || "-"} />
          <EvidenceRow label="reason" value={selection.reason || "-"} />
          {selection.error && <EvidenceRow label="error" value={selection.error} />}
        </div>
      </details>
    </section>
  );
}

function EvidenceRow({ label, value }: { label: string; value: string }) {
  return (
    <>
      <span className="font-mono text-slate-400">{label}</span>
      <span className="min-w-0 break-words font-mono text-slate-700">{value}</span>
    </>
  );
}
```

- [ ] **Step 7: Run the targeted frontend test**

Run:

```powershell
cd frontend
npm run test:run -- src/__tests__/ChatPage.test.tsx -t "shows model-selected skill evidence"
```

Expected: PASS.

- [ ] **Step 8: Commit frontend skill selection card**

```powershell
git add frontend/src/pages/ChatPage.tsx frontend/src/__tests__/ChatPage.test.tsx
git commit -m "feat: show skill selection evidence in chat"
```

---

### Task 3: Route Workflow Events Into the Workflow Card Only

**Files:**
- Modify: `frontend/src/pages/ChatPage.tsx`
- Test: `frontend/src/__tests__/ChatPage.test.tsx`

- [ ] **Step 1: Write the failing test for non-noisy workflow rendering**

Replace the expectations in the existing test named `"renders streamed assistant deltas, tool timeline, and skill workflow board in one round"` with this renamed test:

```tsx
it("renders skill selection and workflow updates without a noisy process timeline", async () => {
  renderChat();

  await waitFor(() => {
    expect(MockWebSocket.instances.length).toBe(1);
  });
  const ws = MockWebSocket.instances[0];

  act(() => {
    ws.emit({
      seq: 1,
      type: "progress",
      run_id: "run-1",
      stage: "skill_selection",
      content: "已选择 skill：lab4ai-auto-reproduct。",
      skill_selection_source: "model",
      skill_selection: {
        selected_skill: "lab4ai-auto-reproduct",
        source: "model",
        model_choice: "lab4ai-auto-reproduct",
        fallback_choice: null,
        reason: "Model selected registered skill `lab4ai-auto-reproduct`.",
        confidence: null,
        error: null,
      },
      workflow_path: "skills/lab4ai-auto-reproduct/project_reproduce.yaml",
      timestamp: "2026-05-20T00:00:01Z",
    });
    ws.emit({
      seq: 2,
      type: "workflow_loaded",
      run_id: "run-1",
      workflow: {
        name: "Lab4AI_Auto_Reproduction_Pipeline",
        project_name: "PhotoDoodle",
        steps: [{ id: "step_1_audit", name: "项目复现可行性分析", status: "running" }],
      },
      timestamp: "2026-05-20T00:00:02Z",
    });
    ws.emit({
      seq: 3,
      type: "workflow_step_progress",
      run_id: "run-1",
      workflow_step_id: "step_1_audit",
      content: "Invoking tool: analyze_repo",
      step: {
        id: "step_1_audit",
        name: "项目复现可行性分析",
        status: "running",
        progress: ["Invoking tool: analyze_repo"],
      },
      timestamp: "2026-05-20T00:00:02Z",
    });
    ws.emit({
      seq: 4,
      type: "workflow_step_completed",
      run_id: "run-1",
      workflow_step_id: "step_1_audit",
      step: {
        id: "step_1_audit",
        name: "项目复现可行性分析",
        status: "completed",
        output: "score=75；已完成项目审计。",
        progress: ["Invoking tool: analyze_repo", "Tool completed: analyze_repo"],
        tool_calls: [{ tool_call_id: "tool-1", name: "analyze_repo", status: "completed", ok: true }],
      },
      timestamp: "2026-05-20T00:00:03Z",
    });
    ws.emit({
      seq: 5,
      type: "assistant_started",
      run_id: "run-1",
      timestamp: "2026-05-20T00:00:04Z",
    });
    ws.emit({
      seq: 6,
      type: "assistant_delta",
      run_id: "run-1",
      delta: "最终结论：仓库审计已完成，下一步需要创建 CPU 实例。",
    });
  });

  expect(await screen.findByText("模型选择了 lab4ai-auto-reproduct")).toBeInTheDocument();
  expect(screen.getByRole("heading", { name: "PhotoDoodle 复现流水线" })).toBeInTheDocument();
  expect(screen.getByText("项目复现可行性分析")).toBeInTheDocument();
  expect(screen.getByText("score=75；已完成项目审计。")).toBeInTheDocument();
  expect(screen.getByText("分析 GitHub 仓库")).toBeInTheDocument();
  expect(screen.queryByText("思考过程")).not.toBeInTheDocument();
  expect(screen.queryByText("执行过程")).not.toBeInTheDocument();
  expect(screen.queryByText("工作流已加载")).not.toBeInTheDocument();
  expect(screen.getByText("最终结论：仓库审计已完成，下一步需要创建 CPU 实例。")).toBeInTheDocument();
});
```

- [ ] **Step 2: Run the renamed test to verify it fails**

Run:

```powershell
cd frontend
npm run test:run -- src/__tests__/ChatPage.test.tsx -t "renders skill selection and workflow updates"
```

Expected: FAIL because current code appends workflow and skill-selection events into timeline sections.

- [ ] **Step 3: Add `updateSkillSelection`**

In `ChatPage.tsx`, add this function near `updateWorkflowBoard`:

```tsx
function updateSkillSelection(payload: StreamPayload) {
  const incoming = skillSelectionFromPayload(payload);
  if (!incoming) return;
  setMessages((prev) => {
    const { messages: next, id } = ensureActiveAgentMessage(prev, payload);
    activeAgentMessageIdRef.current = id;
    return next.map((msg) =>
      msg.id === id
        ? {
            ...msg,
            skillSelection: { ...(msg.skillSelection || {}), ...incoming },
            workflowPath: workflowPathFromSelection(incoming, payload.workflow_path || msg.workflowPath),
          }
        : msg
    );
  });
}
```

- [ ] **Step 4: Route stream events away from the timeline**

In `handleStreamPayload`, replace the `progress` branch with:

```tsx
if (payload.type === "progress") {
  if (payload.stage === "skill_selection") {
    updateSkillSelection(payload);
    return;
  }
  appendTimelineEvent(payload, {
    id: `progress-${payload.stage || "general"}`,
    title: progressTitle(payload.stage, payload.content),
    content: progressContent(payload.stage, payload.content),
    created_at: payload.timestamp || new Date().toISOString(),
    status: "info",
    kind: "thinking",
  });
  return;
}
```

Replace the `workflow_loaded` branch with:

```tsx
if (payload.type === "workflow_loaded") {
  updateWorkflowBoard(payload);
  return;
}
```

Replace the `workflow_step_` branch with:

```tsx
if (payload.type.startsWith("workflow_step_") && payload.step) {
  updateWorkflowBoard(payload);
  return;
}
```

- [ ] **Step 5: Preserve selection state on assistant completion**

In `completeAssistantMessage`, keep existing run UI state when replacing the active streaming message:

```tsx
const current = next[activeIndex];
next[activeIndex] = {
  ...current,
  id: message.id,
  content: message.content,
  created_at: message.created_at,
  streaming: false,
  type: "text",
  run_id: runId ?? current.run_id,
  skillSelection: current.skillSelection,
  workflowPath: current.workflowPath,
  workflow: current.workflow,
  events: current.events,
};
```

- [ ] **Step 6: Run the targeted frontend test**

Run:

```powershell
cd frontend
npm run test:run -- src/__tests__/ChatPage.test.tsx -t "renders skill selection and workflow updates"
```

Expected: PASS.

- [ ] **Step 7: Commit workflow event routing**

```powershell
git add frontend/src/pages/ChatPage.tsx frontend/src/__tests__/ChatPage.test.tsx
git commit -m "feat: merge workflow events into run card"
```

---

### Task 4: Replace the Table Workflow Board With a Step-Driven Run Card

**Files:**
- Modify: `frontend/src/pages/ChatPage.tsx`
- Test: `frontend/src/__tests__/ChatPage.test.tsx`

- [ ] **Step 1: Write the failing test for vertical YAML step display**

Add this test:

```tsx
it("shows workflow steps as a vertical run card with the current step expanded", async () => {
  conversationPayload.status = "running";
  conversationPayload.metadata = {
    workflow_name: "Lab4AI_Auto_Reproduction_Pipeline",
    workflow_current_step_id: "step_4_cpu_env_setup",
    workflow_results: { repo_name: "motion-guided-flow" },
    workflow_steps: [
      {
        id: "step_1_audit",
        name: "项目复现可行性分析",
        status: "completed",
        output: "score=82；审计报告已生成。",
        progress: ["Tool completed: analyze_repo"],
      },
      {
        id: "step_4_cpu_env_setup",
        name: "在 CPU 上拉取代码与智能环境/数据构建",
        status: "running",
        output: "正在执行当前步骤。",
        progress: [
          "Start step: 在 CPU 上拉取代码与智能环境/数据构建",
          "Invoking tool: ssh_execute",
          "Invoking tool: lab4ai_project_prep",
        ],
        tool_calls: [
          { tool_call_id: "ssh-1", name: "ssh_execute", status: "completed", ok: true },
          { tool_call_id: "prep-1", name: "lab4ai_project_prep", status: "running" },
        ],
      },
    ],
  };

  renderChat();

  expect(await screen.findByRole("heading", { name: "motion-guided-flow 复现流水线" })).toBeInTheDocument();
  expect(screen.queryByRole("table")).not.toBeInTheDocument();
  expect(screen.getByText("2/2 完成")).toBeInTheDocument();
  expect(screen.getByText("step_1_audit")).toBeInTheDocument();
  expect(screen.getByText("score=82；审计报告已生成。")).toBeInTheDocument();
  expect(screen.getByText("step_4_cpu_env_setup")).toBeInTheDocument();
  expect(screen.getByText("正在执行当前步骤。")).toBeInTheDocument();
  expect(screen.getByText("执行远程命令")).toBeInTheDocument();
  expect(screen.getByText("lab4ai_project_prep")).toBeInTheDocument();
});
```

The text `"2/2 完成"` intentionally reflects the current `workflow_steps` fixture. If the implementation uses the full 9-step fallback list when metadata only has two steps, adjust this assertion to `"1/9 完成"` only after the component intentionally pads missing YAML steps.

- [ ] **Step 2: Run the test to verify it fails**

Run:

```powershell
cd frontend
npm run test:run -- src/__tests__/ChatPage.test.tsx -t "vertical run card"
```

Expected: FAIL because the current board is a table.

- [ ] **Step 3: Replace `WorkflowBoard` markup with vertical card**

Replace the existing `WorkflowBoard` function with:

```tsx
function WorkflowBoard({ workflow, pendingInput, onSubmit }: {
  workflow: WorkflowState;
  pendingInput?: PendingUserInput | null;
  onSubmit: (content: string) => Promise<void>;
}) {
  const steps = workflow.steps && workflow.steps.length > 0 ? workflow.steps : REPRO_WORKFLOW_STEPS;
  const completedCount = steps.filter((step) => step.status === "completed").length;
  const totalCount = steps.length;
  return (
    <section className="overflow-hidden rounded-xl border border-slate-200 bg-white shadow-sm">
      <div className="flex flex-wrap items-start justify-between gap-3 border-b border-slate-100 bg-slate-50 px-4 py-3">
        <div className="min-w-0">
          <div className="text-ui-meta font-semibold uppercase tracking-wide text-slate-400">
            Project Reproduction Workflow
          </div>
          <h3 className="mt-1 break-words text-md-h3 font-semibold text-slate-800">
            {workflow.project_name || "项目"} 复现流水线
          </h3>
          <p className="mt-1 text-ui-small text-slate-500">
            按 project_reproduce.yaml 的步骤持续更新。
          </p>
        </div>
        <span className="shrink-0 rounded-full border border-slate-200 bg-white px-2.5 py-1 text-ui-micro font-medium text-slate-500">
          {completedCount}/{totalCount} 完成
        </span>
      </div>
      <div className="divide-y divide-slate-100">
        {steps.map((step, index) => (
          <WorkflowStepRow
            key={step.id}
            step={step}
            index={index}
            pendingInput={pendingInputForStep(pendingInput, step, workflow)}
            onSubmit={onSubmit}
          />
        ))}
      </div>
    </section>
  );
}
```

- [ ] **Step 4: Pass pending input into `AgentResponse`**

Change `AgentResponse` signature:

```tsx
function AgentResponse({
  message,
  pendingInput,
  onSubmit,
}: {
  message: ChatMessage;
  pendingInput?: PendingUserInput | null;
  onSubmit: (content: string) => Promise<void>;
}) {
```

Update the call in `MessageBubble`:

```tsx
<AgentResponse message={message} pendingInput={pendingInput} onSubmit={onSubmit} />
```

Update `MessageBubble` props:

```tsx
function MessageBubble({
  message,
  copied,
  onCopy,
  pendingInput,
  onSubmit,
}: {
  message: ChatMessage;
  copied: boolean;
  onCopy: () => void;
  pendingInput?: PendingUserInput | null;
  onSubmit: (content: string) => Promise<void>;
}) {
```

Update the render loop:

```tsx
<MessageBubble
  key={`${msg.id}-${msg.role}`}
  message={msg}
  copied={copiedMessageId === msg.id}
  onCopy={() => copyMessage(msg)}
  pendingInput={pendingInput}
  onSubmit={submitMessage}
/>
```

- [ ] **Step 5: Add `WorkflowStepRow`**

Add this component after `WorkflowBoard`:

```tsx
function WorkflowStepRow({
  step,
  index,
  pendingInput,
  onSubmit,
}: {
  step: WorkflowStepState;
  index: number;
  pendingInput?: PendingUserInput | null;
  onSubmit: (content: string) => Promise<void>;
}) {
  const template = REPRO_WORKFLOW_STEPS.find((item) => item.id === step.id);
  const name = step.name || template?.name || step.id;
  const isOpen =
    step.status === "running" ||
    step.status === "failed" ||
    step.status === "waiting_for_user" ||
    !!pendingInput;
  const progressItems = (step.progress || []).slice(-3);
  const toolCalls = (step.tool_calls || []).slice(-4);
  const outcome = workflowStepOutcome(step);

  return (
    <details className="group" open={isOpen}>
      <summary className="flex cursor-pointer list-none gap-3 px-4 py-3 transition-colors hover:bg-slate-50">
        <span className={`mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-full text-ui-micro font-semibold ${workflowStepNumberClass(step.status)}`}>
          {index + 1}
        </span>
        <span className="min-w-0 flex-1">
          <span className="flex flex-wrap items-center gap-2">
            <span className="font-semibold text-slate-800">{name}</span>
            <code className="rounded bg-slate-100 px-1.5 py-0.5 text-ui-micro font-semibold text-slate-500">
              {step.id}
            </code>
          </span>
          {outcome && !isOpen && (
            <span className="mt-1 block break-words text-ui-small text-slate-500">{outcome}</span>
          )}
        </span>
        <span className={`h-fit shrink-0 rounded-full border px-2 py-0.5 text-ui-micro font-medium ${workflowStepStatusClass(step.status)}`}>
          {workflowStepStatusLabel(step.status)}
        </span>
        <ChevronIcon className="mt-1 h-4 w-4 shrink-0 text-slate-400 transition-transform group-open:rotate-180" />
      </summary>
      <div className="space-y-3 px-4 pb-4 pl-[62px]">
        {outcome && (
          <div className={`rounded-lg border px-3 py-2 text-ui-small ${workflowOutcomeClass(step.status)}`}>
            {outcome}
          </div>
        )}
        {progressItems.length > 0 && (
          <div className="space-y-1.5">
            {progressItems.map((item, itemIndex) => (
              <div key={`${step.id}-progress-${itemIndex}`} className="flex gap-2 text-ui-small text-slate-500">
                <span className="mt-2 h-1.5 w-1.5 shrink-0 rounded-full bg-blue-400" />
                <span className="break-words">{workflowProgressContent(item) || item}</span>
              </div>
            ))}
          </div>
        )}
        {toolCalls.length > 0 && (
          <div className="flex flex-wrap gap-1.5">
            {toolCalls.map((call, callIndex) => (
              <span
                key={call.tool_call_id || `${step.id}-tool-${callIndex}`}
                className={`inline-flex max-w-full items-center gap-1 rounded-full border px-2 py-0.5 text-ui-micro ${toolCallStatusClass(call)}`}
                title={call.error || undefined}
              >
                <span className="truncate">{toolTitle(String(call.name || "tool"))}</span>
                <span>{toolCallStatusLabel(call)}</span>
              </span>
            ))}
          </div>
        )}
        {pendingInput && <HumanInputPanel input={pendingInput} onSubmit={onSubmit} />}
      </div>
    </details>
  );
}
```

- [ ] **Step 6: Add step number class helper**

Add near `workflowStepStatusClass`:

```tsx
function workflowStepNumberClass(status: string) {
  if (status === "completed") return "bg-emerald-50 text-emerald-700";
  if (status === "failed") return "bg-red-50 text-red-700";
  if (status === "waiting_for_user") return "bg-amber-50 text-amber-700";
  if (status === "running") return "bg-blue-50 text-blue-700";
  return "bg-slate-100 text-slate-500";
}
```

- [ ] **Step 7: Run the vertical workflow test**

Run:

```powershell
cd frontend
npm run test:run -- src/__tests__/ChatPage.test.tsx -t "vertical run card"
```

Expected: PASS.

- [ ] **Step 8: Commit workflow card UI**

```powershell
git add frontend/src/pages/ChatPage.tsx frontend/src/__tests__/ChatPage.test.tsx
git commit -m "feat: show reproduction workflow as step card"
```

---

### Task 5: Embed Human Input in the Current Workflow Step

**Files:**
- Modify: `frontend/src/pages/ChatPage.tsx`
- Test: `frontend/src/__tests__/ChatPage.test.tsx`

- [ ] **Step 1: Write the failing test for step-level HITL**

Update the existing `"shows a step-level HITL reason on the workflow board"` test to assert the confirmation panel is inside the step card:

```tsx
it("embeds normal human confirmation in the current workflow step", async () => {
  conversationPayload.status = "active";
  conversationPayload.metadata = {
    workflow_state: "waiting_for_user",
    workflow_current_step_id: "step_3_deploy_cpu",
    selected_skill: "lab4ai-auto-reproduct",
    workflow_name: "Lab4AI_Auto_Reproduction_Pipeline",
    workflow_results: { repo_name: "PhotoDoodle" },
    workflow_steps: [
      {
        id: "step_3_deploy_cpu",
        name: "拉起廉价 CPU 实例",
        status: "waiting_for_user",
        output: "需要确认后才能创建 CPU 实例。",
        progress: ["Tool waiting for user: lab4ai_create_instance"],
        tool_calls: [{ tool_call_id: "tool-cpu", name: "lab4ai_create_instance", status: "waiting_for_user" }],
      },
    ],
    pending_user_input: {
      question: "是否继续创建 CPU 实例？",
      options: ["继续执行"],
      tool_name: "lab4ai_create_instance",
      workflow_step_id: "step_3_deploy_cpu",
    },
  };

  renderChat();

  const step = await screen.findByTestId("workflow-step-step_3_deploy_cpu");
  expect(within(step).getByText("等待你确认")).toBeInTheDocument();
  expect(within(step).getByText("需要你的输入")).toBeInTheDocument();
  expect(within(step).getByText("是否继续创建 CPU 实例？")).toBeInTheDocument();
  expect(within(step).getByRole("button", { name: "继续执行" })).toBeInTheDocument();
  expect(screen.queryByTestId("inline-human-decision")).not.toBeInTheDocument();
});
```

- [ ] **Step 2: Run the HITL test to verify it fails**

Run:

```powershell
cd frontend
npm run test:run -- src/__tests__/ChatPage.test.tsx -t "embeds normal human confirmation"
```

Expected: FAIL until the step row carries `data-testid` and renders `HumanInputPanel`.

- [ ] **Step 3: Add pending-input step matching**

Add this helper near workflow helpers:

```tsx
function pendingInputForStep(
  pendingInput: PendingUserInput | null | undefined,
  step: WorkflowStepState,
  workflow: WorkflowState
) {
  if (!pendingInput) return null;
  if (pendingInput.workflow_step_id === step.id) return pendingInput;
  if (pendingInput.step === step.id) return pendingInput;
  if (!pendingInput.workflow_step_id && workflow.current_step_id === step.id) return pendingInput;
  return null;
}
```

Extend `PendingUserInput`:

```tsx
workflow_step_id?: string;
```

- [ ] **Step 4: Add `data-testid` to workflow step rows**

In `WorkflowStepRow`, change the root `details` element to:

```tsx
<details className="group" open={isOpen} data-testid={`workflow-step-${step.id}`}>
```

- [ ] **Step 5: Add `HumanInputPanel` for normal confirmation**

Add this component below `WorkflowStepRow`:

```tsx
function HumanInputPanel({
  input,
  onSubmit,
}: {
  input: PendingUserInput;
  onSubmit: (content: string) => Promise<void>;
}) {
  if (input.intervention?.type === "lab4ai_credentials_required") {
    return <Lab4AICredentialPanel input={input} onSubmit={onSubmit} />;
  }
  return (
    <div className="rounded-lg border border-amber-200 bg-amber-50 px-3 py-3" data-testid="step-human-input">
      <div className="text-ui-small font-semibold text-amber-800">需要你的输入</div>
      {input.tool_name && (
        <div className="mt-1 text-ui-micro text-amber-700">
          操作：{toolTitle(input.tool_name)}
        </div>
      )}
      <div className="mt-2 whitespace-pre-wrap text-chat-body leading-relaxed text-slate-700">
        {input.question}
      </div>
      {input.options && input.options.length > 0 && (
        <div className="mt-3 flex flex-wrap gap-2">
          {input.options.map((option) => (
            <button
              key={option}
              type="button"
              onClick={() => void onSubmit(option)}
              className="rounded-lg border border-amber-200 bg-white px-3 py-1.5 text-ui-small text-slate-700 hover:bg-amber-100"
            >
              {option}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 6: Hide the old global inline decision when it is attached to a workflow step**

Near the current inline human decision render block, add:

```tsx
const pendingInputIsWorkflowScoped =
  !!pendingInput?.workflow_step_id ||
  !!conversation?.metadata?.workflow_current_step_id ||
  !!conversation?.metadata?.workflow_steps?.length;
```

Change:

```tsx
{isWaitingForUser && pendingInput && (
```

to:

```tsx
{isWaitingForUser && pendingInput && !pendingInputIsWorkflowScoped && (
```

- [ ] **Step 7: Run the HITL test**

Run:

```powershell
cd frontend
npm run test:run -- src/__tests__/ChatPage.test.tsx -t "embeds normal human confirmation"
```

Expected: PASS.

- [ ] **Step 8: Commit step-level human input**

```powershell
git add frontend/src/pages/ChatPage.tsx frontend/src/__tests__/ChatPage.test.tsx
git commit -m "feat: embed human input in workflow steps"
```

---

### Task 6: Add Secure Lab4AI Credential Panel

**Files:**
- Modify: `frontend/src/pages/ChatPage.tsx`
- Test: `frontend/src/__tests__/ChatPage.test.tsx`

- [ ] **Step 1: Write the failing credential form test**

Replace the current `"shows Lab4AI credential request inline and continues from chat confirmation"` test with:

```tsx
it("saves Lab4AI credentials from the workflow step without sending secrets as chat text", async () => {
  conversationPayload.status = "active";
  conversationPayload.metadata = {
    workflow_state: "waiting_for_user",
    workflow_current_step_id: "step_3_deploy_cpu",
    workflow_name: "Lab4AI_Auto_Reproduction_Pipeline",
    workflow_results: { repo_name: "PhotoDoodle" },
    workflow_steps: [
      {
        id: "step_3_deploy_cpu",
        name: "拉起廉价 CPU 实例",
        status: "waiting_for_user",
        output: "申请 CPU 实例前需要 Lab4AI 登录凭证。",
      },
    ],
    pending_user_input: {
      question: "Lab4AI 凭证未配置，请先由管理员配置平台账号。",
      options: ["已完成配置，继续执行", "停止任务"],
      tool_name: "lab4ai_create_instance",
      workflow_step_id: "step_3_deploy_cpu",
      intervention: {
        type: "lab4ai_credentials_required",
        title: "需要配置 Lab4AI 平台账号",
        admin_endpoint: "/api/admin/settings/lab4ai",
      },
    },
  };

  globalThis.fetch = vi.fn().mockImplementation((path: string, options?: RequestInit) => {
    if (path === "/api/admin/settings/lab4ai" && options?.method === "PUT") {
      return Promise.resolve({
        ok: true,
        json: () => Promise.resolve({ configured: true, phone_masked: "138****8000" }),
      });
    }
    return Promise.resolve({
      ok: true,
      json: () => Promise.resolve(conversationPayload),
    });
  });

  renderChat();

  const step = await screen.findByTestId("workflow-step-step_3_deploy_cpu");
  fireEvent.change(within(step).getByLabelText("手机号/账号"), {
    target: { value: "13800008000" },
  });
  fireEvent.change(within(step).getByLabelText("密码"), {
    target: { value: "super-secret-password" },
  });
  fireEvent.click(within(step).getByRole("button", { name: "保存并继续" }));

  await waitFor(() => {
    expect(globalThis.fetch).toHaveBeenCalledWith(
      "/api/admin/settings/lab4ai",
      expect.objectContaining({
        method: "PUT",
        body: JSON.stringify({ phone: "13800008000", password: "super-secret-password" }),
      })
    );
  });

  await waitFor(() => {
    expect(globalThis.fetch).toHaveBeenCalledWith(
      "/api/conversations/7/messages",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({ content: "已完成配置，继续执行" }),
      })
    );
  });

  const messageCalls = (globalThis.fetch as unknown as { mock: { calls: unknown[][] } }).mock.calls
    .filter(([path]) => path === "/api/conversations/7/messages")
    .map(([, options]) => String((options as RequestInit).body || ""));
  expect(messageCalls.join("\n")).not.toContain("super-secret-password");
});
```

- [ ] **Step 2: Run the credential test to verify it fails**

Run:

```powershell
cd frontend
npm run test:run -- src/__tests__/ChatPage.test.tsx -t "saves Lab4AI credentials"
```

Expected: FAIL because `Lab4AICredentialPanel` is not implemented.

- [ ] **Step 3: Add PUT helper**

In the import from `../lib/api`, include `apiFetch` if it is not already imported. It is already imported in the current file:

```tsx
import { apiFetch, apiPost, getToken } from "../lib/api";
```

No new API wrapper is required. Use `apiFetch` directly inside the form submit handler.

- [ ] **Step 4: Implement `Lab4AICredentialPanel`**

Add this component below `HumanInputPanel`:

```tsx
function Lab4AICredentialPanel({
  input,
  onSubmit,
}: {
  input: PendingUserInput;
  onSubmit: (content: string) => Promise<void>;
}) {
  const [phone, setPhone] = useState("");
  const [password, setPassword] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const endpoint = String(input.intervention?.admin_endpoint || "/api/admin/settings/lab4ai");

  async function handleSave(e: FormEvent) {
    e.preventDefault();
    if (!phone.trim() || !password.trim()) {
      setError("请填写 Lab4AI 平台账号和密码。");
      return;
    }
    setSaving(true);
    setError("");
    try {
      await apiFetch(endpoint, {
        method: "PUT",
        body: JSON.stringify({ phone: phone.trim(), password }),
      });
      setPhone("");
      setPassword("");
      await onSubmit("已完成配置，继续执行");
    } catch (err) {
      setError(err instanceof Error ? err.message : "保存失败，请检查账号权限后重试。");
    } finally {
      setSaving(false);
    }
  }

  return (
    <form
      onSubmit={handleSave}
      className="rounded-lg border border-amber-200 bg-amber-50 px-3 py-3"
      data-testid="lab4ai-credential-panel"
    >
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <div className="text-ui-small font-semibold text-amber-800">需要你的输入</div>
          <div className="mt-1 text-ui-small leading-relaxed text-amber-700">
            {input.question}
          </div>
        </div>
        <span className="rounded-full border border-amber-200 bg-white px-2 py-0.5 text-ui-micro font-medium text-amber-700">
          Human Input
        </span>
      </div>
      <div className="mt-3 grid gap-2">
        <label className="grid gap-1 text-ui-small font-medium text-amber-900">
          手机号/账号
          <input
            value={phone}
            onChange={(event) => setPhone(event.target.value)}
            autoComplete="username"
            className="rounded-lg border border-amber-200 bg-white px-3 py-2 text-chat-body font-normal text-slate-700 outline-none focus:border-amber-300"
          />
        </label>
        <label className="grid gap-1 text-ui-small font-medium text-amber-900">
          密码
          <input
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            type="password"
            autoComplete="current-password"
            className="rounded-lg border border-amber-200 bg-white px-3 py-2 text-chat-body font-normal text-slate-700 outline-none focus:border-amber-300"
          />
        </label>
      </div>
      {error && <div className="mt-2 text-ui-small text-red-600">{error}</div>}
      <div className="mt-3 flex flex-wrap gap-2">
        <button
          type="submit"
          disabled={saving}
          className="rounded-lg bg-slate-800 px-3 py-1.5 text-ui-small font-medium text-white hover:bg-slate-700 disabled:bg-slate-300"
        >
          {saving ? "保存中..." : "保存并继续"}
        </button>
        <button
          type="button"
          onClick={() => void onSubmit("停止任务")}
          className="rounded-lg border border-amber-200 bg-white px-3 py-1.5 text-ui-small text-slate-700 hover:bg-amber-100"
        >
          稍后再说
        </button>
      </div>
      <div className="mt-2 text-ui-micro leading-relaxed text-amber-700">
        页面只会显示“凭证已配置”，不会把账号或密码写入普通聊天正文。
      </div>
    </form>
  );
}
```

- [ ] **Step 5: Run the credential test**

Run:

```powershell
cd frontend
npm run test:run -- src/__tests__/ChatPage.test.tsx -t "saves Lab4AI credentials"
```

Expected: PASS.

- [ ] **Step 6: Commit credential panel**

```powershell
git add frontend/src/pages/ChatPage.tsx frontend/src/__tests__/ChatPage.test.tsx
git commit -m "feat: save lab4ai credentials from workflow step"
```

---

### Task 7: Preserve Final Answer as Summary Only

**Files:**
- Modify: `frontend/src/pages/ChatPage.tsx`
- Test: `frontend/src/__tests__/ChatPage.test.tsx`

- [ ] **Step 1: Write the failing final-answer test**

Add this test:

```tsx
it("keeps intermediate workflow logs out of the final answer card", async () => {
  conversationPayload.messages = [
    ...conversationPayload.messages,
    {
      id: 2,
      role: "assistant",
      content:
        "工具执行结果如下\n| 序号 | 执行步骤 | 当前状态 | 核心产出 / 详情 |\n| --- | --- | --- | --- |\n| 1 | `step_1_audit` | 完成 | score=82 |\n\n最终结论：复现报告已生成。",
      message_metadata: {},
      created_at: "2026-05-20T00:00:30Z",
    },
  ];
  conversationPayload.metadata = {
    workflow_name: "Lab4AI_Auto_Reproduction_Pipeline",
    workflow_results: { repo_name: "motion-guided-flow" },
    workflow_steps: [
      {
        id: "step_1_audit",
        name: "项目复现可行性分析",
        status: "completed",
        output: "score=82",
      },
    ],
  };

  renderChat();

  const finalAnswer = await screen.findByText("最终回答");
  const card = finalAnswer.parentElement;
  expect(card).toHaveTextContent("最终结论：复现报告已生成。");
  expect(card).not.toHaveTextContent("工具执行结果如下");
  expect(card).not.toHaveTextContent("| 序号 |");
});
```

- [ ] **Step 2: Run the final-answer test**

Run:

```powershell
cd frontend
npm run test:run -- src/__tests__/ChatPage.test.tsx -t "keeps intermediate workflow logs"
```

Expected: PASS if `cleanFinalAnswer` already removes table/log content. If it fails, update `cleanFinalAnswer` with the exact logic in the next step.

- [ ] **Step 3: Harden `cleanFinalAnswer` if needed**

If the test fails, update `cleanFinalAnswer` to keep content from the last final marker:

```tsx
function cleanFinalAnswer(content: string, hasProcess: boolean) {
  if (!hasProcess) return content;
  const markers = ["最终结论：", "最终回答：", "复现结果："];
  for (const marker of markers) {
    const index = content.lastIndexOf(marker);
    if (index >= 0) return content.slice(index).trim();
  }
  return content
    .split("\n")
    .filter((line) => !line.includes("| 序号 |") && !line.includes("| --- |") && !line.startsWith("工具执行结果如下"))
    .join("\n")
    .trim();
}
```

- [ ] **Step 4: Run the final-answer test again**

Run:

```powershell
cd frontend
npm run test:run -- src/__tests__/ChatPage.test.tsx -t "keeps intermediate workflow logs"
```

Expected: PASS.

- [ ] **Step 5: Commit final-answer cleanup**

```powershell
git add frontend/src/pages/ChatPage.tsx frontend/src/__tests__/ChatPage.test.tsx
git commit -m "fix: keep workflow logs out of final answer"
```

---

### Task 8: Full Verification and Optional Component Split

**Files:**
- Optional create: `frontend/src/components/AgentRunCard.tsx`
- Optional modify: `frontend/src/pages/ChatPage.tsx`
- Test: `frontend/src/__tests__/ChatPage.test.tsx`

- [ ] **Step 1: Run all focused tests**

Run:

```powershell
uv run pytest backend/tests/test_agent_loop.py backend/tests/test_skill_selector.py -q
```

Expected: all selected backend tests pass.

Run:

```powershell
cd frontend
npm run test:run -- src/__tests__/ChatPage.test.tsx
```

Expected: all `ChatPage` tests pass.

- [ ] **Step 2: Run broader project checks**

Run:

```powershell
uv run pytest -q
```

Expected: all backend tests pass.

Run:

```powershell
cd frontend
npm run build
```

Expected: TypeScript and Vite build pass.

- [ ] **Step 3: Optional split if `ChatPage.tsx` became hard to review**

If `ChatPage.tsx` is difficult to review after the UI change, move only presentational run-card components to `frontend/src/components/AgentRunCard.tsx`:

```tsx
export function SkillSelectionCard(...) { ... }
export function WorkflowRunCard(...) { ... }
export function WorkflowStepRow(...) { ... }
export function HumanInputPanel(...) { ... }
export function Lab4AICredentialPanel(...) { ... }
```

Keep stateful stream handling, WebSocket handling, query invalidation, and `submitMessage` in `ChatPage.tsx`. Pass callback props into the component:

```tsx
<AgentRunCard
  message={message}
  pendingInput={pendingInput}
  onSubmitHumanInput={submitMessage}
/>
```

After the split, run:

```powershell
cd frontend
npm run test:run -- src/__tests__/ChatPage.test.tsx
npm run build
```

Expected: both commands pass with no behavior changes.

- [ ] **Step 4: Visual check with the local app**

Start the frontend dev server:

```powershell
cd frontend
npm run dev -- --host 127.0.0.1
```

Use the existing backend/dev setup for the app. Open the conversation page and verify:

- Skill selection appears as one card.
- `source=model` is visible only in the evidence expander.
- Workflow steps render as vertical rows.
- Current step is expanded.
- Lab4AI credential request appears inside `step_3_deploy_cpu`.
- Final answer card does not show intermediate tool tables.
- Desktop width and a narrow mobile width do not overlap text or form controls.

- [ ] **Step 5: Final commit**

If Task 8 only verified, no commit is needed. If Task 8 moved components, commit that refactor:

```powershell
git add frontend/src/pages/ChatPage.tsx frontend/src/components/AgentRunCard.tsx frontend/src/__tests__/ChatPage.test.tsx
git commit -m "refactor: split agent run card components"
```

---

## Self-Review

Spec coverage:

- Model skill selection evidence is covered by Tasks 1 and 2.
- YAML-step workflow rendering is covered by Tasks 3 and 4.
- Human input embedded in the current step is covered by Tasks 5 and 6.
- Final answer summary-only behavior is covered by Task 7.
- Security handling for Lab4AI credentials is covered by Task 6.
- Verification commands and visual checks are covered by Task 8.

Placeholder scan:

- This plan contains no unresolved placeholder markers or unspecified implementation steps.
- Every code-changing task includes concrete code snippets and exact verification commands.

Type consistency:

- `SkillSelectionState`, `PendingUserInput.workflow_step_id`, `StreamPayload.skill_selection`, `ChatMessage.skillSelection`, and `ChatMessage.workflowPath` are introduced before use.
- `pendingInputForStep` uses the existing backend field `workflow_step_id` from `mark_waiting_for_user`.
- Lab4AI credential form uses the existing `/api/admin/settings/lab4ai` API with `{ phone, password }`.
