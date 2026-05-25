# Lab4AI Reproduction Markdown UI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Enhance reproduce-task Markdown rendering so Agent output that follows `skills/lab4ai-auto-reproduct/SKILL.md` is readable as a workflow-style page while preserving the original Markdown source.

**Architecture:** `ChatPage` decides whether an Agent message belongs to a reproduce conversation and passes a Markdown rendering variant. `MarkdownContent` keeps normal rendering unchanged by default and adds reproduction-only classes/status wrappers when the variant is enabled. `index.css` carries the visual rules so Markdown renderer logic stays small.

**Tech Stack:** React 19, TypeScript, react-markdown, remark-gfm, rehype-sanitize, Vitest, React Testing Library, Tailwind CSS 4.

---

## Files

- Modify: `frontend/src/components/MarkdownContent.tsx`
  Adds `variant?: "default" | "reproduction"`, reproduction container classes, and status token rendering for Markdown table cells.
- Modify: `frontend/src/pages/ChatPage.tsx`
  Passes `variant="reproduction"` for Agent Markdown in `reproduce` conversations.
- Modify: `frontend/src/index.css`
  Adds scoped reproduction Markdown styles.
- Modify: `frontend/src/__tests__/MarkdownContent.test.tsx`
  Adds red/green tests for reproduction Markdown behavior and default isolation.
- Modify: `frontend/src/__tests__/ChatPage.test.tsx`
  Adds a test that reproduce conversations pass the reproduction Markdown variant into rendered Agent content.

## Task 1: MarkdownContent Reproduction Variant

**Files:**
- Modify: `frontend/src/__tests__/MarkdownContent.test.tsx`
- Modify: `frontend/src/components/MarkdownContent.tsx`
- Modify: `frontend/src/index.css`

- [ ] **Step 1: Write failing tests for the reproduction variant**

Add tests that render:

```tsx
<MarkdownContent
  variant="reproduction"
  content={`#### 复现流水线实时看板 \`PhotoDoodle\`

| 序号 | 执行步骤 (对应 YAML Task) | 当前状态 | 核心产出 / 详情 |
| :--- | :--- | :--- | :--- |
| 1 | \`step_1_audit\`: 项目与论文双重审计 | [完成] | score=80 |
| 2 | \`step_2_condition_check\`: 复现可行性熔断判断 | [执行中] | 正在判断 |
| 3 | \`step_3_deploy_cpu\`: 创建 CPU 实例 | [等待中] | 等待确认 |
| 4 | \`step_4_cpu_env_setup\`: 环境构建 | [中止] | SSH 失败 |`}
/>
```

Expected assertions:

```tsx
expect(screen.getByTestId("markdown-content")).toHaveClass("markdown-reproduction");
expect(screen.getByTestId("reproduction-status-done")).toHaveTextContent("[完成]");
expect(screen.getByTestId("reproduction-status-running")).toHaveTextContent("[执行中]");
expect(screen.getByTestId("reproduction-status-waiting")).toHaveTextContent("[等待中]");
expect(screen.getByTestId("reproduction-status-error")).toHaveTextContent("[中止]");
```

Also assert default Markdown has no reproduction class:

```tsx
render(<MarkdownContent content="| A | B |\n| --- | --- |\n| [完成] | normal |" />);
expect(screen.getByTestId("markdown-content")).not.toHaveClass("markdown-reproduction");
expect(screen.queryByTestId("reproduction-status-done")).not.toBeInTheDocument();
```

- [ ] **Step 2: Run test to verify RED**

Run:

```bash
cd frontend
npm run test:run -- src/__tests__/MarkdownContent.test.tsx
```

Expected: FAIL because `variant` and `data-testid="markdown-content"` do not exist yet.

- [ ] **Step 3: Implement minimal MarkdownContent changes**

Add the prop:

```tsx
type MarkdownVariant = "default" | "reproduction";

interface MarkdownContentProps {
  content: string;
  variant?: MarkdownVariant;
}
```

Wrap root with:

```tsx
<div
  data-testid="markdown-content"
  className={`space-y-3 whitespace-normal break-words ${
    variant === "reproduction" ? "markdown-reproduction" : ""
  }`}
>
```

For `td`, wrap reproduction status text with a status span using exact status-token matching.

- [ ] **Step 4: Add scoped CSS**

Add `.markdown-reproduction` styles for table containers, compact cells, title spacing, code blocks, and status spans:

```css
.markdown-reproduction table {
  min-width: 760px;
}
.markdown-reproduction td,
.markdown-reproduction th {
  white-space: normal;
}
.markdown-reproduction .reproduction-status {
  display: inline-flex;
  border-radius: 0.375rem;
  padding: 0.125rem 0.5rem;
  font-weight: 700;
}
```

- [ ] **Step 5: Run test to verify GREEN**

Run:

```bash
cd frontend
npm run test:run -- src/__tests__/MarkdownContent.test.tsx
```

Expected: PASS.

## Task 2: ChatPage Passes Reproduction Variant

**Files:**
- Modify: `frontend/src/__tests__/ChatPage.test.tsx`
- Modify: `frontend/src/pages/ChatPage.tsx`

- [ ] **Step 1: Write failing ChatPage test**

Add an assistant message containing the reproduction workflow table to a `task_type: "reproduce"` conversation and assert the rendered agent message contains a reproduction Markdown container:

```tsx
conversationPayload.messages.push({
  id: 2,
  role: "assistant",
  content:
    "#### 复现流水线实时看板 `PhotoDoodle`\n\n" +
    "| 序号 | 执行步骤 (对应 YAML Task) | 当前状态 | 核心产出 / 详情 |\n" +
    "| :--- | :--- | :--- | :--- |\n" +
    "| 1 | `step_1_audit`: 项目与论文双重审计 | [完成] | score=80 |",
  message_metadata: {},
  created_at: "2026-05-20T00:00:10Z",
});
```

Expected assertion:

```tsx
const agentMessage = await screen.findByTestId("agent-message");
expect(within(agentMessage).getByTestId("markdown-content")).toHaveClass("markdown-reproduction");
```

- [ ] **Step 2: Run test to verify RED**

Run:

```bash
cd frontend
npm run test:run -- src/__tests__/ChatPage.test.tsx
```

Expected: FAIL because `ChatPage` does not pass the reproduction variant.

- [ ] **Step 3: Implement minimal ChatPage wiring**

Find the Agent Markdown render and pass:

```tsx
<MarkdownContent
  content={message.content}
  variant={isReproduceConversation(conversation) ? "reproduction" : "default"}
/>
```

Add a local helper:

```tsx
function isReproduceConversation(conversation?: Conversation) {
  return conversation?.task_type === "reproduce" || conversation?.metadata?.task_type === "reproduce";
}
```

- [ ] **Step 4: Run focused tests**

Run:

```bash
cd frontend
npm run test:run -- src/__tests__/ChatPage.test.tsx src/__tests__/MarkdownContent.test.tsx
```

Expected: PASS.

## Task 3: Verification

**Files:**
- Verify only.

- [ ] **Step 1: Build frontend**

Run:

```bash
cd frontend
npm run build
```

Expected: exit code 0.

- [ ] **Step 2: Inspect diff**

Run:

```bash
git -c safe.directory=D:/codexP/aaa diff -- frontend/src/components/MarkdownContent.tsx frontend/src/pages/ChatPage.tsx frontend/src/index.css frontend/src/__tests__/MarkdownContent.test.tsx frontend/src/__tests__/ChatPage.test.tsx docs/superpowers/specs/2026-05-24-lab4ai-reproduction-markdown-ui-design.md docs/superpowers/plans/2026-05-24-lab4ai-reproduction-markdown-ui.md docs/proposal.md
```

Expected: diff only contains the planned Markdown UI enhancement and documentation updates.

## Self-Review

- Spec coverage: The plan covers reproduction-only scope, Markdown as source of truth, table/status styling, final delivery readability via CSS, and ordinary Markdown isolation.
- Placeholder scan: No TBD/TODO placeholders are present.
- Type consistency: `variant` is defined in `MarkdownContent` and consumed by `ChatPage` as `"reproduction"` or `"default"`.
