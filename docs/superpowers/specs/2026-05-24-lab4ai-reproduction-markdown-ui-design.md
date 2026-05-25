# Lab4AI 复现 Markdown UI 展示增强设计

## 背景

当前复现任务已经由 `skills/lab4ai-auto-reproduct/SKILL.md` 和同目录 `project_reproduce.yaml` 定义流程。用户希望前端 UI 严格按照该 skill 中的展示输出规范呈现，尤其是：

- 9 个 YAML task 对齐的“复现流水线实时看板”Markdown 表格。
- 最终交付物页面展示，包括核心指标对比、H100 架构优化洞察、Word 报告路径和资源释放核对。

本次确认的范围是第一档：只改复现任务页，不把其他任务类型纳入统一改造。

## 已确认决策

1. 复现任务页采用现有 `ChatPage`，不新增独立复现工作台路由。
2. 展示来源以 Agent 输出的 Markdown 原文为准，不把 9 步表格转换成结构化看板。
3. 前端对命中 `SKILL.md` 模板特征的复现 Markdown 做专项增强：表格样式、状态高亮、长内容折行、最终交付区可读性。
4. 不修改 `skills/` 目录下任何文件。

## 目标

- 让 `SKILL.md` 中要求的实时进度看板在聊天区内可读、稳定、不横向撑破布局。
- 让 `[执行中] / [完成] / [中止] / [等待中]` 等状态在 Markdown 表格中有明确视觉区分。
- 让最终交付模板中的报告路径、指标对比、资源释放核对更容易扫描。
- 保持普通 Markdown 渲染不受复现专属样式影响。

## 非目标

- 不重写后端 workflow 执行逻辑。
- 不解析或修改 `project_reproduce.yaml`。
- 不要求前端把 Markdown 表格重新建模为结构化数据。
- 不把 search、paper-only、experiments、polish 等其他任务页纳入本轮样式规则。

## 前端设计

### 展示入口

`ChatPage` 根据 conversation 的 `task_type` 或 metadata 判断当前是否为复现任务。复现任务中的 Agent Markdown 渲染时传入复现展示上下文，例如：

```tsx
<MarkdownContent content={message.content} variant="reproduction" />
```

普通任务继续使用默认展示模式。

### 模板识别

`MarkdownContent` 在 `variant="reproduction"` 时启用复现专属样式。可同时通过标题和表格内容识别关键区块：

- `复现流水线实时看板`
- `任务完成`
- `核心指标对比`
- `Word 报告`
- `资源监控核对`

识别只用于添加 CSS class 和状态高亮，不用于改变 Markdown 内容含义。

### 表格增强

复现 Markdown 表格需要满足：

- 表格容器横向滚动，避免压缩整个 ChatPage。
- 序号列和状态列较窄，详情列允许折行。
- 包含 `step_1_audit` 到 `step_9_release_gpu` 的表格使用更紧凑的行高。
- 状态文本按语义高亮：
  - 执行中：蓝色。
  - 完成：绿色。
  - 中止 / 失败：红色。
  - 等待中 / 等待确认：琥珀色。

### 最终交付区增强

对最终交付模板中的 Markdown 保持原样渲染，但在复现模式下：

- 二级标题和加粗段落有更清晰的间距。
- 报告路径所在代码块保持可横向滚动。
- 指标对比表沿用表格增强样式。
- 资源释放核对文案通过状态高亮显示，不需要额外弹窗。

## 组件边界

- `frontend/src/pages/ChatPage.tsx`：只负责判断当前消息是否处于复现展示上下文，并把 variant 传给 Markdown 组件。
- `frontend/src/components/MarkdownContent.tsx`：负责 Markdown 渲染和复现专属 class 标记。
- `frontend/src/index.css`：承载少量复现 Markdown 样式，避免把复杂 Tailwind 条件散落在 Markdown renderer 中。
- `frontend/src/__tests__/MarkdownContent.test.tsx`：补充复现表格和普通 Markdown 隔离测试。

## 测试策略

前端测试覆盖：

1. 默认 Markdown 表格仍按普通样式渲染。
2. `variant="reproduction"` 下，包含 `复现流水线实时看板` 的内容会渲染复现容器 class。
3. 复现表格中的 `执行中`、`完成`、`中止`、`等待中` 状态有可测试的语义 class 或标签。
4. `ChatPage` 在 `task_type=reproduce` 时向 Agent Markdown 传入复现展示模式。

验证命令：

```bash
cd frontend
npm run test -- MarkdownContent.test.tsx ChatPage.test.tsx
npm run build
```

## 风险与取舍

- 因为展示来源以 Markdown 原文为准，若 Agent 没有输出 `SKILL.md` 中约定的标题或表格结构，前端只能回退到普通 Markdown 展示。
- 本设计不把 Markdown 转成结构化看板，避免与用户选择的“Markdown 原样为准”冲突。
- 后续如果需要更可靠的实时看板，可以在另一个设计中切换到 metadata 驱动的结构化 UI。

## 验收标准

- 复现任务页内，`SKILL.md` 的 9 步流水线 Markdown 表格在桌面宽度下清晰可读。
- 长详情不会撑破聊天区布局。
- 状态文本具备明显视觉区分。
- 普通任务的 Markdown 样式不出现复现专属视觉规则。
- 本轮不修改 `skills/` 目录。
