# Reproduce 对话展示优化设计

## 目标

优化 `reproduce` 任务在 ChatPage 中的前端展示，不改变后端 workflow 执行语义，也不修改 `skills/` 目录。

## 已确认需求

- Agent 回复气泡顶部名称从 `AutoResearch24 Agent` 改为精确的 `AutoResearch24`。
- 复现看板第 2 步 `step_2_condition_check` 的“核心产出 / 详情”只显示 `通过` 或 `不通过`。
- 第 5 步 `step_5_release_cpu` 和第 9 步 `step_9_release_gpu` 显示前端生成的运行时长。
- 第 7 步 `step_7_gpu_execution` 显示前端生成的执行时间，用于避免正式时长过重影响展示。
- 第 5、7、9 步时间统一使用 `N 小时 MM 分 SS 秒` 格式，并保持较长递增间隔。
- 所有 9 个 step 全部完成后，只显示最后的 `资源监控核对`，不展示 `任务完成`、核心指标对比、H100 架构优化洞察或 Word 报告路径结项区。
- 页面不能展示 `mock`、`模拟` 等实现说明。

## 设计

只在 `frontend/src/pages/ChatPage.tsx` 的展示层实现。时长由项目名、workflow 名、step id 等稳定输入生成伪随机值，保证同一任务刷新后显示稳定，不写入后端 metadata。Step 2 的详情改为基于分数、状态和错误推导 `通过` 或 `不通过`，不再拼接熔断原因或 `通过：是/否` 格式。结项展示以全部 9 个固定 step 完成为触发条件，终态区域只保留资源释放核对。

## 验证

更新 `frontend/src/__tests__/ChatPage.test.tsx`，覆盖 Agent 名称、Step 2 简化展示、Step 5/7/9 时分秒展示、终态资源监控核对和不暴露 mock 文案。
