# Lab4AI SKILL.md Agent 展示面板设计

## 背景

用户要求当前前端 Agent 回答展示严格按 `skills/lab4ai-auto-reproduct/SKILL.md` 的“页面展示规范”呈现。现有 `WorkflowBoard` 是 AutoResearch24 自定义 Workbench，不是 skill 中规定的 9 行实时看板和最终交付物页面。

本次不修改 `skills/` 目录，只改前端展示层。

## 已确认决策

1. 复现任务采用前端专用 Agent 展示面板。
2. 数据来源优先使用 workflow metadata，而不是依赖模型是否完整输出 Markdown。
3. 面板文案、表头、9 个 YAML step、状态和结项区对齐 `SKILL.md` 模板。
4. 普通任务继续使用现有 Agent 回答展示，不进入复现面板。

## 目标

- 复现任务出现 workflow metadata 时，Agent 气泡内展示 `复现流水线实时看板: [项目名]`。
- 表格固定展示 9 个 YAML 节点，列名为 `序号 / 执行步骤 (对应 YAML Task) / 当前状态 / 核心产出 / 详情`。
- 状态文本按 `SKILL.md` 风格展示：`[等待中...] / [执行中] / [完成] / [中止]`，并用颜色增强。
- `核心产出 / 详情` 列按 `SKILL.md` 中 9 个步骤的槽位含义展示对应真实信息，例如把 `[可行性评分 / 论文 Baseline / 超参数]` 填充为 `可行性评分：83；论文 Baseline：PSNR=28.4；超参数：lr=1e-4`，把 `[serverId / SSH 信息]` 填充为真实 `serverId` 与 SSH 连接信息。对应数据缺失时显示 `待生成：...` 或 `待记录` 提示。
- 复现看板必须在 Agent 气泡宽度内自适应换行，不在气泡底部产生横向滚动条；长路径、serverId、SSH 信息和指标文本使用自动换行展示。
- 复现 Agent 面板不在表格下方显示 `查看选择证据` 折叠区；skill 选择摘要可保留在面板头部。
- 普通 HITL 确认卡不展示 `修改方案` 选项，只保留 `继续执行` 等仍可直接推进当前受控动作的选项。
- 全部 9 步完成后，在同一 Agent 面板下展示最终交付物页面：任务完成标题、核心指标对比、H100 架构优化洞察、Word 报告路径、资源监控核对。

## 非目标

- 不改后端 workflow 执行逻辑。
- 不修改 `skills/lab4ai-auto-reproduct/SKILL.md` 或 `project_reproduce.yaml`。
- 不在本轮重新设计 Sidebar、RightPanel、登录页或普通 Chat UI。
- 不删除旧 WorkflowBoard 的内部辅助能力，先在复现任务入口替换展示。

## 组件设计

在 `ChatPage.tsx` 中新增复现专用展示组件：

- `ReproductionAgentPanel`
  - 接收 `workflow / pendingInput / onSubmit / skillSelection / workflowPath / events`。
  - 输出 skill 规定的实时看板和结项页面。
- `ReproductionPipelineTable`
  - 固定渲染 9 行，顺序来自 `REPRO_WORKFLOW_STEPS`。
  - 不按阶段分组，不折叠为 Workbench。
- `ReproductionFinalDelivery`
  - 在 9 步完成，或存在 `word_report_path/report_path` 时显示。
  - 从 `workflow.results.baseline_metrics` 与 `workflow.results.smoke_test_metrics` 生成指标对比表。
  - 报告路径使用 `workflowReportPath(workflow)`。

`AgentResponse` 中，当 `markdownVariant === "reproduction"` 且 message 有 workflow 时，渲染 `ReproductionAgentPanel`，不再渲染旧 `WorkflowBoard`。

## 测试策略

- 添加 ChatPage 测试：workflow metadata 存在时显示 `复现流水线实时看板: PhotoDoodle` 和 9 行 step。
- 添加 ChatPage 测试：状态映射为 `[完成] / [执行中] / [等待中...] / [中止]`。
- 添加 ChatPage 测试：所有步骤完成且存在报告和指标时，显示 `任务完成：PhotoDoodle 自动化复现已结项`、核心指标对比、H100 架构优化洞察、Word 报告路径、资源监控核对。
- 添加 ChatPage 测试：复现 Agent 面板不显示 `查看选择证据`，HITL 选项中不显示 `修改方案`。
- 保留普通 Markdown 渲染测试，确保非 reproduce 任务不受影响。

## 验收标准

- 复现任务 Agent 面板不再显示 `Research Reproduction Workbench`。
- 页面主要展示形态与 `SKILL.md` 页面展示规范一致。
- `npm run test:run -- src/__tests__/ChatPage.test.tsx` 通过。
- `npm run test:run` 和 `npm run build` 通过。
