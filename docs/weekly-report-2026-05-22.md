# LOBSTER 项目周报

报告周期：2026-05-18 至 2026-05-22

## 一、本周工作概览

本周主要围绕 LOBSTER V2 MVP 的主链路收敛、Skill / Workflow Runtime 落地、Lab4AI 真实 API 路径接入，以及旧 OpenClaw / vendor skill 的安全适配展开。当前系统已经从早期 Runner / mock 路径推进到以 `conversations`、`cloud-instances`、`ToolRegistry`、`WorkflowRunner` 和真实 executor 为核心的后端架构。

整体进展上，V2 对话式任务、模型配置、WebSocket 事件流、结构化 memory、HITL 确认、SkillLoader、复现 workflow 状态机、Lab4AI Tool 真实 API 路径、真实 SSH / 文件写入 / 仓库分析 / 论文分析 / 报告生成 executor 均已落地。下一阶段重点转向真实 Lab4AI 环境联调、长命令执行稳定性、自动排错闭环和管理员侧能力补齐。

## 二、开发内容与进度

### 1. 项目协作与文档

- 新增项目级协作入口 `AGENTS.md`，用于 Codex / OpenAI Agents 进入项目时读取，并明确继续参考 `CLAUDE.md`、`docs/proposal.md`、`README.md`。
- 新增 `docs/skill-adapter-plan.md`，记录旧 OpenClaw / vendor skill 到当前 LOBSTER 后端 ToolRuntime 的适配方案。
- `docs/proposal.md` 已补充 Skill 适配计划入口，并明确 P0 / P1 / P2 推进顺序。

### 2. V2 对话任务与 Agent Loop

- 历史 `claw-instances` 接口和旧版 Runner 已完成代码侧清理，主链路收敛到 `conversations` 与 `cloud-instances`。
- V2 数据模型已落地，包括 `LLMConfig`、`Conversation`、`ConversationMessage`。
- V2 API 已实现，覆盖对话创建、列表、详情、消息发送、停止执行、WebSocket 事件流、LLM 配置读写。
- Agent Loop 已支持读取对话历史与 metadata、组装 system prompt、调用 Anthropic-compatible `/v1/messages` 模型接口、持久化消息，并在模型或 API Key 不可用时提供本地 fallback。

### 3. 前端 V2 入口与交互

- WelcomePage 已切换为创建 `/api/conversations`。
- ChatPage 已支持多轮消息、Agent Markdown 渲染、消息时间、复制按钮、停止执行按钮、等待确认卡片和快捷选项。
- Tool Events 已迁移到 RightPanel 展示，Sidebar 已读取 V2 对话历史。
- 新增 `/model-settings` 页面，支持用户配置真实模型 `base_url / api_key / model / max_tokens`。
- WebSocket 连接策略已优化，仅在对话 `active/running` 且 token 存在时建立连接，减少断开后的代理噪音。

### 4. Memory、HITL 与 ToolRegistry

- 新增 `conversation_memory` 服务，将结构化 memory 写入 `Conversation.metadata`。
- 当前 memory 包含 `summary / facts / decisions / open_questions / artifacts / last_compacted_at / compacted_through_message_id / compaction_count`。
- Tool 层从硬编码升级为声明式 `ToolRegistry`，统一声明 `description / input_schema / confirmation_policy / executor`。
- `lab4ai_create_instance` 通过统一 HITL 确认触发，`ssh_execute` 针对高风险命令触发条件确认。
- 用户确认会绑定当前 `workflow_run_id`，避免后续新一轮对话误用旧确认。

### 5. Skill / Workflow Runtime 与真实 executor

- SkillLoader 已支持扫描 `skills/*/SKILL.md`、解析 frontmatter，并为 `lab4ai-auto-reproduct` 加载 `project_reproduce.yaml` 注入 Agent Loop。
- 新增 `WorkflowRunner`，能够解析 `project_reproduce.yaml` 的任务、依赖、指令和预期输出，并持久化 workflow 状态。
- 复现任务中已推进 9 步 workflow 状态机，并推送 `workflow_loaded / workflow_step_* / workflow_cleanup_*` 等事件。
- 新增 `SkillRuntime`，扫描 `tools.yaml / manifest.yaml`，将 `repo_audit / paper_analyze / generate_repro_report` 等声明映射为后端真实 Tool。
- `analyze_repo`、`analyze_paper`、`ssh_execute`、`file_write`、`repro_report` 已接入真实 executor，不再以固定分数或模拟成功推进关键步骤。

### 6. Lab4AI 与旧 skill 安全适配

- `lab4ai_create_instance / lab4ai_stop_instance / lab4ai_list_instances` 已直接调用 Lab4AI REST API，不再依赖 Runner / mock 开关。
- 创建实例会写入 `CloudInstance` 归属记录，停止实例会更新状态和停止时间。
- 管理员未配置 Lab4AI 凭证时，workflow 会进入 `lab4ai_credentials_required` 人工介入状态，而不是模拟创建计费实例。
- P0/P1 首轮适配已落地：
  - `claw_shell_run` 和 `ssh_essentials_execute` 注册为兼容 Tool，底层统一转入 `ssh_execute`。
  - `sshpass ... ssh ... "<remote command>"` wrapper 会被编译为受控远程命令。
  - `file_system_read / file_system_list / file_system_write` 映射到受控任务 workspace 或当前任务绑定远程实例的 SFTP 路径。
  - 仍禁止访问或写入 `skills/` 目录。

## 三、当前验证结果

当前已通过以下验证：

```bash
uv run python backend/tests/smoke_v2.py
uv run pytest
uv run ruff check backend/app backend/tests/test_tools.py backend/tests/test_workflow.py backend/tests/test_agent_loop.py
cd frontend && npm test -- --run
cd frontend && npm run build
```

验证结论：

- `smoke_v2.py` 已通过，流程会在 HITL 创建真实 Lab4AI 实例前停止，避免误触发计费资源。
- 后端 pytest 已通过；`docs/progress.md` 最新记录为 45 个后端用例通过，`CLAUDE.md` / `README.md` 仍保留 46 个用例的旧口径，后续需统一文档数字。
- 前端 Vitest 用例和生产构建已通过。
- 本轮定向 ruff 检查通过；全量 `ruff check backend/app` 仍存在历史遗留的 `backend/app/core/config.py` 未用 `Field` import，当前未处理。

## 四、当前限制与风险

- Lab4AI 真实 API 路径已接入，但仍需要管理员真实凭证和线上环境联调，确认创建、查询、停止、SSH 字段、错误码和异常释放行为。
- `ssh_execute` 已是真实 executor，但还缺少真实 Lab4AI 实例上的端到端验证，尤其是长脚本、远程 SFTP、网络波动和依赖安装耗时场景。
- Agent Loop 当前具备受控 step 内 tool-use 能力，但尚未扩展为完整的跨任务通用 LLM tool-use 自动循环。
- Workflow 自动排错闭环尚未完整实现，仍需把 `ToolResult(ok=false)`、postcondition 失败、诊断轮模型调用、受控修复和复验串成持久化状态机。
- 用户 LLM API Key 目前写入 `api_key_encrypted` 字段，但尚未接入真实加密方案。
- 管理员前端页面仍未完整实现，包括用户管理、云实例总览、平台设置和用量报表。
- `skills/` 原始模板中仍存在历史 `claw-workflow` / `openclaw` / `claw-shell` 命名；按当前约束暂不修改 `skills/`，后续如需标准化需先确认迁移方案。

## 五、下周计划

1. 使用真实 Lab4AI 账号联调 `lab4ai_create_instance / lab4ai_stop_instance / lab4ai_list_instances`，确认响应字段、错误码、计费实例释放和 `CloudInstance` 归属记录。
2. 使用真实 Lab4AI CPU/GPU 实例跑 PhotoDoodle dry-run，验收无“已模拟执行”、无未渲染 `{{step_...}}`、无固定 `score=75`。
3. 深化 `ssh_execute` 的日志流式回传、长命令取消机制、超时处理、SFTP 读写和敏感信息脱敏。
4. 实现 Workflow step 自动排错闭环，包括错误回流、`recovery_attempts` 持久化、诊断轮模型调用、受控修复 Tool 调用和 postcondition 复验。
5. 按 `docs/skill-adapter-plan.md` 继续处理 P1 剩余 workflow，为 `lab4ai-auto-research` 和 `lab4ai-lf-data-preprocess` 增加专用 runner。
6. 继续完善 `SkillRuntime`，补齐 skill entrypoint 健康检查、依赖检查和更完整的 step 输出别名映射。
7. 为用户 LLM API Key 接入加密存储方案。
8. 设计并实现管理员前端页面，优先覆盖 Lab4AI 凭证配置、云实例总览、用户管理和用量报表。

