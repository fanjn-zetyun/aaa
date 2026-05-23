# 当前开发进度

更新日期：2026-05-21

## 已完成

- 项目级协作入口已补充：根目录新增 `AGENTS.md`，用于 Codex / Agents 进入项目时读取，并指向 `CLAUDE.md`、`docs/proposal.md`、`README.md`。
- 历史遗留的 `claw-instances` 接口和旧版 Runner 已完成代码侧清理，当前主链路只保留 `conversations` 和 `cloud-instances`。
- V2 数据模型已落地：
  - `LLMConfig`：按用户保存 `provider / base_url / api_key / model / max_tokens`。
  - `Conversation`：保存对话/任务、任务类型、状态、metadata、JSONL 日志路径。
  - `ConversationMessage`：保存 user / assistant / tool / system 消息。
- V2 API 已实现：
  - `POST /api/conversations`
  - `GET /api/conversations`
  - `GET /api/conversations/{id}`
  - `POST /api/conversations/{id}/messages`
  - `POST /api/conversations/{id}/stop`
  - `WS /api/conversations/{id}/stream`
  - `GET /api/llm-config`
  - `PUT /api/llm-config`
- V2 Agent Loop 已实现基础闭环：
  - 支持读取对话历史和 metadata。
  - 支持 system prompt 组装。
  - 支持调用 Anthropic-compatible `/v1/messages` 真实模型接口。
  - 未配置 API Key 或模型调用失败时，会降级为本地 fallback，保证基础流程可运行。
  - 支持 tool event 流式推送和对话消息持久化。
- 前端已切换到 V2 对话入口：
  - WelcomePage 创建 `/api/conversations`。
  - ChatPage 展示多轮消息、Agent Markdown 渲染、消息时间、复制按钮和停止执行按钮。
  - Tool Events 已移动到 RightPanel 右侧栏展示。
  - Sidebar 历史记录读取 `/api/conversations`。
  - RightPanel 展示 V2 conversation 详情。
  - 新增 `/model-settings` 模型设置页，可配置真实模型 `base_url / api_key / model / max_tokens`。
- WebSocket 稳定性已优化：
  - 前端仅在对话 `active/running` 且 token 存在时建立 WS。
  - 后端避免在断开后重复 `close()`，减少 Vite `ECONNABORTED` 代理噪音。
- 验证脚本已补充：
  - 新增 `backend/tests/smoke_v2.py`，覆盖登录、LLM 配置、创建 V2 对话、Agent Loop 执行、消息回看。
- Skill 系统最小闭环已落地：
  - 新增 `backend/app/services/skills.py`，实现 `SkillDefinition`、`SkillLoader` 和 `select_skill`。
  - 支持扫描 `skills/*/SKILL.md`，解析 frontmatter 中的 `name / description / triggers / when_to_use / allowed_tools`。
  - `lab4ai-auto-reproduct` 会自动加载同目录 `project_reproduce.yaml`，作为 workflow context 注入模型请求。
  - `backend/app/services/agent_loop.py` 已接入 SkillLoader，不再只记录“已选择 skill”，而是把选中 skill 正文和工作流上下文注入 system prompt。
  - 新增 `backend/tests/test_skills.py`，覆盖 skill 解析、workflow 加载和 reproduce 任务选择。
- 对话记忆、压缩与 HITL 确认管线已落地：
  - 新增 `backend/app/services/conversation_memory.py`，将结构化 memory 存入 `Conversation.metadata`。
  - memory 当前包含 `summary / facts / decisions / open_questions / artifacts / last_compacted_at / compacted_through_message_id / compaction_count`。
  - ToolRegistry 已声明化，`lab4ai_create_instance` 走统一 HITL 确认，`ssh_execute` 仅在检测到高风险命令时确认。
  - reproduce 任务会在创建资源前通过 `ask_user` 暂停，写入 `pending_user_input`、`workflow_state=waiting_for_user` 和当前 `workflow_run_id`。
  - 用户回复后，后端会把回答分类为 `approved / needs_revision / rejected / stopped`，只在当前运行中生效，避免新一轮复用旧确认。
  - 对话上下文支持压缩：老消息会被汇总写回 `memory.summary`，并记录 `memory_compacted` 事件。
  - ChatPage 已支持等待确认卡片、快捷选项和等待态输入。
  - 新增 `backend/tests/test_conversation_memory.py`、`backend/tests/test_tools.py`，覆盖等待问题、决策写入、压缩与工具确认策略。
- Skill Workflow Runtime 首版已落地：
  - 新增 `backend/app/services/workflow.py`，解析 `project_reproduce.yaml` 的 `tasks / depends_on / instruction / expected_output`。
  - `Conversation.metadata` 已持久化 `workflow_name / workflow_version / workflow_current_step_id / workflow_steps / workflow_resources / workflow_results`。
  - workflow 解析边界已将历史 `claw-workflow/*` 版本号归一化为 `lab4ai-workflow/*`，避免运行时 metadata 继续暴露旧命名。
  - Agent Loop 已在 `lab4ai-auto-reproduct` 复现任务中使用 WorkflowRunner 推进 9 步状态机，并推送 `workflow_loaded / workflow_step_* / workflow_cleanup_*` 事件。
  - 用户在 HITL 确认后可恢复对应 workflow step，失败、异常和用户停止时会根据 `workflow_resources` 兜底释放 CPU/GPU 实例。
  - ChatPage 时间线和 RightPanel 已展示 workflow 加载、步骤状态、资源占用/释放和报告路径。
- Lab4AI Tool 已改为真实 API 路径：
  - `lab4ai_create_instance / lab4ai_stop_instance / lab4ai_list_instances` 直接调用 Lab4AI REST API，不再依赖 Runner/mock 开关。
  - 创建实例会写入 `CloudInstance.user_id / conversation_id / server_id / instance_id / ssh_host / ssh_port / raw_payload`，停止实例会更新状态和停止时间。
  - 管理员未配置 Lab4AI 凭证时，workflow 进入 `lab4ai_credentials_required` 人工介入状态，由前端弹出管理员凭证配置弹窗；平台 API 调用失败时返回结构化错误，不再回退到 mock 创建计费实例。
- SkillRuntime 与真实 executor 已落地：
  - 新增 `backend/app/services/skill_runtime.py`，扫描 `tools.yaml / manifest.yaml`，把 `repo_audit / paper_analyze / generate_repro_report` 等 skill 声明映射为后端真实 Tool 适配器。
  - `analyze_repo` 调用 `lab4ai-project-analysis` 的真实仓库审计脚本，输出审计报告 artifact 和评分。
  - `analyze_paper` 通过后端适配器复用 `lab4ai-paper-analysis` 的下载、PDF 解析、结构化抽取和 Markdown 报告逻辑，不修改 `skills/` 目录。
  - `ssh_execute` 已改为基于 `CloudInstance` 连接信息和 `paramiko` 的真实 SSH executor；缺少实例、SSH 凭证、依赖、超时或非零退出码都会返回结构化失败。
  - `file_write` 已从模拟改为受控写入 `runtime/workspaces/<conversation_id>/...`，远程路径通过当前任务绑定实例 SFTP 写入，仍禁止写入 `skills/`。
  - `repro_report` 已生成真实 `.docx` artifact 到任务 workspace。
  - Workflow step1 已同时执行仓库审计和论文分析，step4/7/8 依据真实 ToolResult 推进，不再写死 `score=75` 或 “MVP simulated”。
- 旧 OpenClaw / vendor skill 适配方案已文档化：
  - 新增 [docs/skill-adapter-plan.md](skill-adapter-plan.md)，记录 `claw-shell`、`sshpass`、`ssh-essentials`、`file-system`、`lab4ai-project-prep`、`lab4ai-instance-manage` 等能力到后端 Tool 的映射计划。
  - [docs/proposal.md](proposal.md) 已增加该计划入口，并明确 P0/P1/P2 推进顺序。
  - 当前约定仍是不修改 `skills/` 目录，所有适配落在后端 runtime、ToolRegistry 和测试中。
- P0/P1 适配首轮已落地：
  - `claw_shell_run` 和 `ssh_essentials_execute` 已注册为兼容 Tool；实际执行统一转入 `ssh_execute`，不运行 vendor `handler.js` 或本机 `tmux`。
  - step 内模型 tool-use 会把 `claw-shell` / `claw_shell_run` 规范化为 `ssh_execute`，并把 `sshpass ... ssh ... "<remote command>"` wrapper 编译成远程命令；无法提取远程命令或存在未渲染模板时直接失败。
  - `step_4_cpu_env_setup` 与 `step_7_gpu_execution` 的 allowlist 已加入 `claw_shell_run`、`file_system_read`、`file_system_list` 和安全文件写入能力；`step_4` 同时允许 `remote_project_prep`。
  - `file_system_read / file_system_list / file_system_write` 已映射到受控任务 workspace 或当前任务绑定远程实例的 SFTP 路径，仍拒绝访问 `skills/`。
- Agent Runtime V3 骨架已落地：
  - 新增 `RuntimeState`、`MessageStore`、`LLMAdapter`、`ToolExecutor`、`SkillInvokeTool`、`ContextBuilder` 和 `WorkflowContractRuntime` compatibility layer。
  - `agent_runtime_v3_enabled` 默认关闭；开启后 `AgentLoopManager` 会委托 `AgentRuntime`，现有 `SkillWorkflowRunner` 链路在默认配置下保持可用。
  - V3 已支持 `model -> tool_use -> ToolExecutor -> tool_result -> model` 循环、`skill.invoke` 激活 skill/workflow contract、workflow required tool/evidence 基础验收，以及 ChatPage runtime/tool 事件展示。
  - 真实 Lab4AI E2E 已增加显式 opt-in guard：默认 `pytest` 不会创建计费 CPU/GPU 实例，只有设置 `LOBSTER_RUN_LAB4AI_INTEGRATION=1` 的集成测试才允许进入真实实例联调。

## 当前验证结果

已通过以下检查：

```bash
uv run python backend/tests/smoke_v2.py
uv run pytest
uv run ruff check backend/app backend/tests/test_tools.py backend/tests/test_workflow.py backend/tests/test_agent_loop.py
cd frontend && npm test -- --run
cd frontend && npm run build
```

当前验证结果：

- `uv run pytest` 通过 45 个后端用例；Workflow Runtime、Tool 真实路径、HITL 和 memory 均有单元测试覆盖。
- `uv run python backend/tests/smoke_v2.py` 通过；脚本会在 HITL 创建真实 Lab4AI 实例前选择停止，避免误触发计费资源。
- 本轮触及的后端文件通过定向 `ruff check`；全量 `ruff check backend/app` 仍会命中既有 `backend/app/core/config.py` 未用 `Field` import，本轮未改这个历史问题。
- 前端生产构建通过；本轮未重新启动本地 dev server。

## 当前限制

- V2 Agent Loop 已能调用真实模型；Lab4AI Tool 已移除 Runner/mock 分支，真实调用还需要管理员凭证和线上环境联调。
- `ssh_execute` 已是真实 executor，但仍需要真实 Lab4AI 实例与线上 SSH 环境联调；当前单元测试覆盖缺少实例、模板未渲染等失败路径，尚未覆盖真实远程服务器端到端。
- `api_key` 当前存储在 `LLMConfig.api_key_encrypted` 字段中，但实现上尚未做真正加密；后续需要接入统一加密方案。
- V2 Agent Loop 目前是“模型规划 + 后端顺序执行固定工具链 + 模型总结”，还不是完整 LLM tool-use 自动循环。
- Tool 层仍以声明式 registry 和统一确认入口为主；Lab4AI、SSH、文件写入、仓库/论文分析和报告生成均已接入真实 executor。
- Skills 目录仍保留原 `SKILL.md` 形态；当前已支持 frontmatter 解析、workflow 注入和 `tools.yaml / manifest.yaml` 后端适配，但尚未完全标准化为统一 `SKILL.yaml` + allowed tools 规范。
- Memory 当前是轻量 metadata 实现，尚未做跨对话长期记忆。
- HITL 已覆盖资源创建前确认，并对高风险 SSH 命令做条件确认，但还不是完整权限系统。
- 管理员前端页面仍未完整实现。
- `skills/` 原始模板中仍包含历史 `claw-workflow` / `openclaw` / `claw-shell` 命名；根据当前项目约束本轮未修改 `skills/` 目录，后续如需标准化需先单独确认模板迁移方案。
- P0/P1 适配首轮已完成单元测试覆盖，但仍需真实 Lab4AI 实例联调验证长脚本、远程 SFTP 和实际网络/依赖安装耗时场景。
- 真实 SSH 代码路径已接入；Lab4AI API 与真实账号、真实远程 SSH 仍需线上联调。

## 下一步建议

1. 用真实 Lab4AI 账号联调 `lab4ai_create_instance / lab4ai_stop_instance / lab4ai_list_instances`，确认创建、查询、停止、SSH 字段和异常释放的响应字段与错误处理。
2. 用真实 Lab4AI CPU/GPU 实例跑 PhotoDoodle dry-run，验收没有 `已模拟执行`、没有未渲染 `{{step_...}}`、没有固定 `score=75`。
3. 深化 `ssh_execute` 的日志流式回传和长命令取消机制。
4. 按 [docs/skill-adapter-plan.md](skill-adapter-plan.md) 继续处理 P1 剩余 workflow：`lab4ai-auto-research` 和 `lab4ai-lf-data-preprocess` 的专用 runner。
5. 将 Agent Loop 从受控 step tool-use 继续扩展到更多任务类型。
6. 扩展 HITL 到网络代理/镜像、受限数据集和高风险远程命令等人工决策。
7. 为用户 LLM API Key 接入加密存储。
8. 完成管理员前端页面。
