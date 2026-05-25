# SKILL.md Agent Panel Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rebuild the reproduce-task Agent display panel so it follows `skills/lab4ai-auto-reproduct/SKILL.md` page-display templates.

**Architecture:** `ChatPage` keeps existing message plumbing, but reproduce workflow messages render a new `ReproductionAgentPanel` instead of the generic `WorkflowBoard`. The panel derives the 9-step table and final delivery section from `WorkflowState` metadata, while ordinary tasks continue through the current Markdown/final-answer path.

**Tech Stack:** React 19, TypeScript, Vitest, React Testing Library, Tailwind CSS 4.

---

## Files

- Modify: `frontend/src/pages/ChatPage.tsx`
  Adds `ReproductionAgentPanel`, SKILL.md table row helpers, final delivery section, and routes reproduce workflow messages to the new panel.
- Modify: `frontend/src/__tests__/ChatPage.test.tsx`
  Adds failing tests for SKILL.md table, status mapping, and final delivery section.
- Modify: `docs/proposal.md`
  Updates the frontend experience requirement from Markdown-only enhancement to metadata-driven SKILL.md Agent panel for reproduce tasks.

## Task 1: Add Failing Tests

- [ ] **Step 1: Add SKILL.md table test**

In `frontend/src/__tests__/ChatPage.test.tsx`, add a test with `workflow_name`, `workflow_current_step_id`, `workflow_results.repo_name`, and partial `workflow_steps`. Assert:

```tsx
expect(await screen.findByTestId("reproduction-agent-panel")).toBeInTheDocument();
expect(screen.getByRole("heading", { name: "复现流水线实时看板: PhotoDoodle" })).toBeInTheDocument();
expect(screen.getByRole("columnheader", { name: "执行步骤 (对应 YAML Task)" })).toBeInTheDocument();
expect(screen.getAllByTestId(/^reproduction-step-row-/)).toHaveLength(9);
expect(screen.queryByText("Research Reproduction Workbench")).not.toBeInTheDocument();
```

- [ ] **Step 2: Add status mapping test**

Use workflow steps with `completed`, `running`, `pending`, and `failed`. Assert the panel shows `[完成]`, `[执行中]`, `[等待中...]`, and `[中止]` in the corresponding rows.

- [ ] **Step 3: Add final delivery test**

Use 9 completed workflow steps and `workflow_results` containing `word_report_path`, `baseline_metrics`, and `smoke_test_metrics`. Assert the panel shows:

```tsx
expect(screen.getByText("任务完成：PhotoDoodle 自动化复现已结项")).toBeInTheDocument();
expect(screen.getByText("核心指标对比 (Smoke Test 实测)")).toBeInTheDocument();
expect(screen.getByText("H100 架构优化洞察")).toBeInTheDocument();
expect(screen.getByText("Word 报告已排版落盘，请前往该绝对路径获取：")).toBeInTheDocument();
expect(screen.getByText("资源监控核对")).toBeInTheDocument();
```

- [ ] **Step 4: Run tests for RED**

Run:

```bash
cd frontend
npm run test:run -- src/__tests__/ChatPage.test.tsx
```

Expected: FAIL because `ReproductionAgentPanel` does not exist.

## Task 2: Implement Panel

- [ ] **Step 1: Route reproduce workflow messages**

In `AgentResponse`, compute:

```tsx
const useReproductionPanel = markdownVariant === "reproduction" && !!message.workflow;
```

Render `ReproductionAgentPanel` for this case and skip `WorkflowBoard`.

- [ ] **Step 2: Implement SKILL.md table**

Create `ReproductionAgentPanel` and table helpers in `ChatPage.tsx`. The table must always render 9 rows from `REPRO_WORKFLOW_STEPS`, with row details from `workflowStepDetail(step)`.

- [ ] **Step 3: Implement final delivery section**

Show final delivery when all 9 rows are completed or a report path exists. Build the metrics table by merging keys from `baseline_metrics` and `smoke_test_metrics`, adding VRAM when present.

- [ ] **Step 4: Keep HITL usable**

If `pendingInputForStep(...)` matches a step, render the existing `HumanInputPanel` below the table so confirmations still work.

- [ ] **Step 5: Run focused tests for GREEN**

Run:

```bash
cd frontend
npm run test:run -- src/__tests__/ChatPage.test.tsx
```

Expected: PASS.

## Task 3: Verification

- [ ] **Step 1: Run full frontend test suite**

Run:

```bash
cd frontend
npm run test:run
```

Expected: PASS.

- [ ] **Step 2: Build frontend**

Run:

```bash
cd frontend
npm run build
```

Expected: exit code 0.

- [ ] **Step 3: Inspect diff**

Run:

```bash
git -c safe.directory=D:/codexP/aaa diff -- frontend/src/pages/ChatPage.tsx frontend/src/__tests__/ChatPage.test.tsx docs/proposal.md docs/superpowers/specs/2026-05-24-skill-md-agent-panel-design.md docs/superpowers/plans/2026-05-24-skill-md-agent-panel.md
```

Expected: diff only contains the SKILL.md Agent panel work and docs.

## Self-Review

- Spec coverage: The plan covers reproduce-only scope, metadata-driven 9-step table, final delivery section, HITL preservation, tests, and verification.
- Placeholder scan: No TBD/TODO placeholders are present.
- Type consistency: The panel uses existing `WorkflowState`, `WorkflowStepState`, `PendingUserInput`, and helper functions already present in `ChatPage.tsx`.
