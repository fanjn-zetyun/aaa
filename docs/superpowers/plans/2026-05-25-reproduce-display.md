# Reproduce Display Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Adjust the reproduce conversation and workflow board display in the React ChatPage.

**Architecture:** Keep the change in the frontend presentation layer. Generate stable pseudo-random durations from workflow identifiers so refreshed views stay consistent without writing display-only data into backend metadata.

**Tech Stack:** React, TypeScript, Vitest, React Testing Library.

---

### Task 1: Display Rules

**Files:**
- Modify: `frontend/src/__tests__/ChatPage.test.tsx`
- Modify: `frontend/src/pages/ChatPage.tsx`
- Modify: `docs/proposal.md`

- [ ] **Step 1: Write failing tests**

Add assertions that the agent label is `AutoResearch24`, Step 2 only renders `通过` or `不通过`, Step 7 renders `执行时间`, Step 5 and Step 9 render `运行时长`, the Step 5/7/9 times use `N 小时 MM 分 SS 秒` with longer increasing gaps, only `资源监控核对` appears after all 9 steps complete, and no visible reproduce panel text contains `mock` or `模拟`.

- [ ] **Step 2: Run focused tests to verify failure**

Run: `npm run test:run -- ChatPage.test.tsx`

Expected: FAIL because current code still shows the previous final delivery block, allows report completion to trigger final delivery before all 9 steps complete, and renders durations in minute/second format.

- [ ] **Step 3: Implement minimal frontend display changes**

In `ChatPage.tsx`, change the visible agent label, simplify `step_2_condition_check`, add stable duration helpers, use them in Step 5, Step 7, and Step 9, format durations as hours/minutes/seconds, gate final delivery on all 9 steps completing, render only the final resource monitor confirmation, and avoid any visible mock wording.

- [ ] **Step 4: Update proposal**

In `docs/proposal.md`, update the ChatPage reproduce display paragraph to document the new Step 2, Step 8, duration, and final resource monitor display rules.

- [ ] **Step 5: Run verification**

Run: `npm run test:run -- ChatPage.test.tsx`
Run: `npm run build`

Expected: PASS.
