# Zero-Code Board Demo Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a front-end-only interactive demo flow for the existing “纯论文复现（无代码）” entry that shows a realistic zero-code reproduction Agent board with HITL confirmation.

**Architecture:** `/paper-only` submits to a demo route instead of creating a conversation. The demo route renders a chat-like page backed by local React state and reuses a shared zero-code panel component extracted from `ChatPage.tsx`.

**Tech Stack:** React 19, React Router, TypeScript, Vitest, React Testing Library, Tailwind utility classes.

---

## File Structure

- Modify `frontend/src/components/WelcomePage.tsx`: add an optional demo submit path so `/paper-only` can navigate locally without calling `/api/conversations`.
- Modify `frontend/src/pages/PaperOnlyPage.tsx`: pass the demo submit path.
- Modify `frontend/src/App.tsx`: register `/paper-only/demo/zero-code-board`.
- Create `frontend/src/components/ZeroCodeAgentPanel.tsx`: shared zero-code workflow panel plus HITL panel dependencies extracted from `ChatPage.tsx`.
- Modify `frontend/src/pages/ChatPage.tsx`: import and use shared `ZeroCodeAgentPanel`.
- Create `frontend/src/pages/ZeroCodeBoardDemoPage.tsx`: chat-like local demo with realistic workflow state and HITL transitions.
- Modify `frontend/src/__tests__/WelcomePage.test.tsx`: test demo navigation and no conversation creation.
- Create `frontend/src/__tests__/ZeroCodeBoardDemoPage.test.tsx`: test initial HITL, continue, and stop flows.

## Task 1: Demo Submit Route

**Files:**
- Modify: `frontend/src/components/WelcomePage.tsx`
- Modify: `frontend/src/pages/PaperOnlyPage.tsx`
- Test: `frontend/src/__tests__/WelcomePage.test.tsx`

- [ ] **Step 1: Write failing WelcomePage demo submit test**

Add a test asserting `demoSubmitPath` navigates locally and does not call `fetch`.

- [ ] **Step 2: Run test and verify RED**

Run: `cd frontend; npm run test:run -- src/__tests__/WelcomePage.test.tsx`

Expected: FAIL because `demoSubmitPath` is not implemented.

- [ ] **Step 3: Implement minimal demo submit path**

Add `demoSubmitPath?: string` to `WelcomePageProps`. In `handleSubmit`, after URL parsing and validation, if `demoSubmitPath` exists, navigate to `${demoSubmitPath}?paper_url=${encodeURIComponent(paperUrl || input.trim())}&prompt=${encodeURIComponent(userPrompt || input.trim())}` and return before `apiPost`.

- [ ] **Step 4: Configure PaperOnlyPage**

Pass `demoSubmitPath="/paper-only/demo/zero-code-board"` from `PaperOnlyPage`.

- [ ] **Step 5: Run test and verify GREEN**

Run: `cd frontend; npm run test:run -- src/__tests__/WelcomePage.test.tsx`

Expected: PASS.

## Task 2: Shared Zero-Code Panel

**Files:**
- Create: `frontend/src/components/ZeroCodeAgentPanel.tsx`
- Modify: `frontend/src/pages/ChatPage.tsx`
- Test: `frontend/src/__tests__/ChatPage.test.tsx`

- [ ] **Step 1: Run existing ChatPage zero-code tests before refactor**

Run: `cd frontend; npm run test:run -- src/__tests__/ChatPage.test.tsx -t "zero-code"`

Expected: existing zero-code panel tests pass or reveal existing unrelated failures before refactor.

- [ ] **Step 2: Extract panel without behavior change**

Move `ZeroCodeAgentPanel`, `zeroCodeGateRows`, and the small helpers it directly needs into `frontend/src/components/ZeroCodeAgentPanel.tsx`. Export the needed TypeScript interfaces from the component file. Keep existing labels, table columns, status classes, and `data-testid` values unchanged.

- [ ] **Step 3: Import shared panel in ChatPage**

Remove the local zero-code panel definition from `ChatPage.tsx` and import `ZeroCodeAgentPanel` from `../components/ZeroCodeAgentPanel`.

- [ ] **Step 4: Run ChatPage tests**

Run: `cd frontend; npm run test:run -- src/__tests__/ChatPage.test.tsx`

Expected: PASS or only pre-existing unrelated failures.

## Task 3: Demo Page Initial HITL

**Files:**
- Create: `frontend/src/pages/ZeroCodeBoardDemoPage.tsx`
- Modify: `frontend/src/App.tsx`
- Test: `frontend/src/__tests__/ZeroCodeBoardDemoPage.test.tsx`

- [ ] **Step 1: Write failing initial render test**

Test renders `/paper-only/demo/zero-code-board?paper_url=https%3A%2F%2Farxiv.org%2Fabs%2F2301.12345`, expects user message, `zero-code-agent-panel`, `step_0_remote_instance_init`, `root@182.242.159.112:30043` absent before confirmation, and HITL option `创建远程 CPU 实例并开始`.

- [ ] **Step 2: Run test and verify RED**

Run: `cd frontend; npm run test:run -- src/__tests__/ZeroCodeBoardDemoPage.test.tsx`

Expected: FAIL because route/page does not exist.

- [ ] **Step 3: Implement route and initial demo page**

Add route in `App.tsx`. Implement `ZeroCodeBoardDemoPage` with initial workflow state: kind `zero_code_reproduction_pipeline`, 12 steps, Step 0 `waiting_for_user`, pending input bound to Step 0, and realistic user/agent chat layout.

- [ ] **Step 4: Run test and verify GREEN**

Run: `cd frontend; npm run test:run -- src/__tests__/ZeroCodeBoardDemoPage.test.tsx`

Expected: PASS.

## Task 4: Demo HITL State Transitions

**Files:**
- Modify: `frontend/src/pages/ZeroCodeBoardDemoPage.tsx`
- Test: `frontend/src/__tests__/ZeroCodeBoardDemoPage.test.tsx`

- [ ] **Step 1: Write failing continue-flow test**

Test clicks `创建远程 CPU 实例并开始`, then expects CPU serverId `481a8b5e60994cf98ed252ae0518edf0`, CPU SSH `root@182.242.159.112:30043`, GPU serverId `7f26d6d2f7a94b93b02fd48b1e4c9a65`, GPU SSH `root@182.242.159.118:30817`, plugin `zero-code-repro-biodefense`, and current step `step_9_gpu_validation_training`.

- [ ] **Step 2: Write failing stop-flow test**

Test clicks `停止任务`, then expects `演示任务已停止，未创建计费实例。` and no serverId values.

- [ ] **Step 3: Run tests and verify RED**

Run: `cd frontend; npm run test:run -- src/__tests__/ZeroCodeBoardDemoPage.test.tsx`

Expected: FAIL because button actions are not implemented.

- [ ] **Step 4: Implement continue and stop state builders**

Implement local `handleDemoSubmit(answer)` in the demo page. Continue clears pending input and sets Steps 0-8 completed, Step 9 running, Step 10-11 pending, with evidence and gate log. Stop clears pending input, sets Step 0 skipped, workflow status stopped, and gate log stopped message.

- [ ] **Step 5: Run tests and verify GREEN**

Run: `cd frontend; npm run test:run -- src/__tests__/ZeroCodeBoardDemoPage.test.tsx`

Expected: PASS.

## Task 5: Final Verification

**Files:**
- All touched frontend files.

- [ ] **Step 1: Run focused tests**

Run: `cd frontend; npm run test:run -- src/__tests__/WelcomePage.test.tsx src/__tests__/ZeroCodeBoardDemoPage.test.tsx src/__tests__/ChatPage.test.tsx`

Expected: PASS.

- [ ] **Step 2: Run full frontend tests**

Run: `cd frontend; npm run test:run`

Expected: PASS.

- [ ] **Step 3: Run frontend build**

Run: `cd frontend; npm run build`

Expected: PASS.

## Task 6: Demo Right-Side Instance And Workspace Panel

**Files:**
- Modify: `frontend/src/pages/ZeroCodeBoardDemoPage.tsx`
- Test: `frontend/src/__tests__/ZeroCodeBoardDemoPage.test.tsx`

- [ ] **Step 1: Write failing initial right-panel test**

Add assertions that the demo page renders a local right-side panel with `data-testid="zero-code-demo-right-panel"`, shows `Lab4AI 登录凭证`, account `138****8000`, and initial empty states `当前演示任务暂无 Lab4AI 实例连接信息。` plus `工作区待创建，确认后会展示生成文件。`.

- [ ] **Step 2: Write failing continued right-panel test**

Extend the continue-flow test to assert the right-side panel shows CPU/GPU `serverId`, SSH commands, workspace root `/workspace/user-data/codelab/geneclr-zero-code/`, and file rows `CONFIDENCE_REPORT.md`, `geneclr.py`, and `report.docx`.

- [ ] **Step 3: Write failing markdown preview test**

Add a test that clicks `CONFIDENCE_REPORT.md` in the demo workspace list, expects `data-testid="workspace-markdown-preview"` and markdown text `GeneCLR Zero-Code Reproduction Confidence Report`, then clicks `返回` and sees the file row again. Assert `fetch` is not called.

- [ ] **Step 4: Write failing stopped right-panel test**

Extend the stop-flow test to assert the right-side panel shows `未创建计费实例，工作区未生成。` and still hides both server IDs.

- [ ] **Step 5: Run tests and verify RED**

Run: `cd frontend; npm run test:run -- src/__tests__/ZeroCodeBoardDemoPage.test.tsx`

Expected: FAIL because the right-side demo panel does not exist.

- [ ] **Step 6: Implement local demo right panel**

In `ZeroCodeBoardDemoPage.tsx`, add a two-column desktop layout. Keep the existing chat board as the main column and add a local right-side panel with:
- `Lab4AI 登录凭证`: configured, account `138****8000`.
- Initial state: no instances and workspace pending.
- Continued state: CPU and GPU instance cards using the agreed `serverId` and SSH values, plus a local workspace file list rooted at `/workspace/user-data/codelab/geneclr-zero-code/`.
- Stopped state: no instances and stopped empty-state copy.
- Markdown preview for local `.md` files through `MarkdownContent`, without any API calls.

- [ ] **Step 7: Run tests and verify GREEN**

Run: `cd frontend; npm run test:run -- src/__tests__/ZeroCodeBoardDemoPage.test.tsx`

Expected: PASS.
