---
description: 为当前 LOBSTER 开发任务生成多 Agent 并行分工方案
argument-hint: "<开发任务描述>"
allowed-tools:
  - Agent
---

请把下面的 LOBSTER 开发任务拆成适合并行执行的多 Agent 分工，并在同一轮里启动互不冲突的 Agent：

任务：$ARGUMENTS

可用项目 Agent：

- `lobster-backend`：后端 API、模型、schema、服务层和后端测试。
- `lobster-frontend`：React/Vite 前端、页面、组件、API 客户端和前端测试。
- `lobster-agent-loop`：Agent Loop、ToolRegistry、SkillLoader、Workflow Runtime、HITL、Memory、Lab4AI 工具链。
- `lobster-reviewer`：只读审查、验证计划、风险与测试缺口检查。

调度规则：

1. 主 Agent 先判断任务是否涉及需求、架构或跨模块设计；如涉及，先按项目规则确认或更新 `docs/proposal.md`，不要直接派实现。
2. 只把能并行、写入范围不冲突的工作派出去；同一文件不要交给多个写入 Agent。
3. 每个实现 Agent 的提示必须写清楚：
   - 背景和目标；
   - 允许修改的文件或目录；
   - 禁止修改 `skills/`；
   - 需要运行的验证命令；
   - 完成后列出修改文件。
4. `lobster-reviewer` 只在实现基本完成后或能并行审查独立范围时启动；它不能编辑文件。
5. 主 Agent 保留最终集成、冲突处理和面向用户汇报责任。
