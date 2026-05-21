# LOBSTER 自建 Agent Loop 科研助手 Web 应用 — 设计提案

> 本文是当前需求与架构的单一真源。已确认：项目彻底切换到自建 Agent Loop，不再接入外部 Agent CLI，也不再维护 CLI 进程、多实例 Runner 或相关 workspace 方案。

## 1. 项目概述

构建一个 Web 应用，让多用户通过浏览器共享同一个 Lab4AI 账号下的 GPU/CPU 算力资源，并通过对话式 Agent 自动完成科研任务，重点覆盖论文/项目复现、论文检索、实验执行和结果汇报。

系统核心能力：

- 用户以对话方式提交科研任务，例如 GitHub URL、论文 URL、自然语言指令。
- 后端自建 Agent Loop，直接调用用户配置的 Anthropic-compatible 模型。
- Agent 通过后端 Tool 系统创建 Lab4AI 云实例、执行 SSH 命令、分析仓库、读取资料并生成结果。
- WebSocket 实时推送模型输出、工具事件和执行状态。
- 后端记录云实例归属、算力配额和用量，保证多用户共享账号时的逻辑隔离。
- 异常退出时自动清理仍在运行的 Lab4AI 云实例，防止空转计费。

## 2. 已确认决策

| 维度 | 决策 |
|---|---|
| 产品名 | LOBSTER |
| 交互形态 | 对话式 AI 科研助手 |
| 智能核心 | 后端自建 Agent Loop |
| LLM 调用 | 后端直接调用，用户配置 `base_url / api_key / model`；输出 token 预算由 Agent Loop 按阶段控制 |
| Tool 执行 | 后端 Tool 系统统一调度 |
| 任务编排 | Skill 契约驱动 Workflow；`skills/` 内容是执行铁律，后端只能解析、渲染、适配并执行，不能绕开、重写或用固定流程替代 |
| Lab4AI 凭证 | 平台统一一个账号，管理员配置，所有用户共享算力池 |
| 云实例归属 | 后端记录 `server_id -> user_id / conversation_id` 映射 |
| 算力限额 | 按用户统计 GPU/CPU 使用时长并限制 |
| 后端技术栈 | Python 3.13 + FastAPI + SQLAlchemy |
| 前端技术栈 | React + TypeScript + Vite |
| 数据库 | SQLite（开发）→ PostgreSQL（生产） |
| 实时输出 | WebSocket |

## 3. 架构参考：claude-code-analysis

仓库内的 [claude-code-analysis/](../claude-code-analysis/) 是 Claude Code 相关源码的静态分析与源码镜像。它不作为本项目的直接代码底座，也不作为可直接部署的 Web 工程使用；原因是它主要面向本地 CLI/TUI、Ink 渲染、终端权限交互、远程 bridge 和本地代码执行场景，和 LOBSTER 的 FastAPI 多用户 Web 服务形态不同。

本项目借鉴它的**系统设计**，不复制它的 CLI/TUI 实现。

可借鉴内容：

| 模块 | `claude-code-analysis` 中的参考 | LOBSTER 中的落地方向 |
|---|---|---|
| Agent 主循环 | `src/query.ts`、`src/QueryEngine.ts` | Python 版 `AgentLoopManager`，负责模型调用、tool-use 循环和事件流 |
| Tool 协议 | `src/Tool.ts` | Python `Tool` / `ToolRegistry`，统一 schema、权限、执行、结果格式 |
| Tool 调度 | `src/services/tools/toolOrchestration.ts`、`StreamingToolExecutor.ts` | 支持串行/并发、超时、中断、错误回流 |
| Tool 执行管线 | `src/services/tools/toolExecution.ts` | 执行前校验、权限检查、审计日志、结构化 `tool_result` |
| Skill 加载 | `src/skills/loadSkillsDir.ts` | 扫描 `skills/<name>/SKILL.md`，解析 frontmatter 和正文 |
| Skill 调用 | `src/tools/SkillTool/SkillTool.ts` | Skill 不直接执行动作，而是把领域流程注入 Agent 上下文，由 Tool 落地执行 |
| 消息规范化 | `src/utils/messages.ts` | ConversationMessage 与 Anthropic-compatible messages 互转 |
| 会话持久化 | session storage / transcript 相关实现 | 数据库消息 + `runtime/conversations/*.jsonl` 事件回放 |
| Memory / Compact | SessionMemory、compact 相关实现 | 后续实现长对话压缩和任务记忆 |

不直接借鉴或需要重写的内容：

- CLI / TUI / Ink 组件。
- 本地 IDE、文件编辑、Git 工作区管理等 coding-agent 专属能力。
- 本地 sandbox、终端权限弹窗、bridge remote control。
- npm/Bun 构建体系和 TypeScript 运行时。
- 单用户本地运行假设。

本项目应保持当前技术栈：FastAPI + SQLAlchemy + React。`claude-code-analysis/` 只作为 Agent Runtime 的设计参考，最终实现必须服务于多用户 Web、Lab4AI 资源归属、WebSocket 事件流和管理员管控。

## 4. 架构总览

```text
浏览器 React
  | HTTP / WebSocket
  v
FastAPI 后端
  ├─ 用户认证 / JWT
  ├─ Conversation API
  ├─ Agent Loop
  │   ├─ System Prompt 组装
  │   ├─ LLM 适配层
  │   ├─ Tool 注册表
  │   ├─ Skill 加载器
  │   └─ 对话历史持久化
  ├─ Lab4AI Tool
  ├─ SSH Tool
  ├─ 仓库/论文分析 Tool
  ├─ 算力配额管理
  └─ WebSocket 事件流
  |
  | REST API / SSH
  v
Lab4AI 云平台与 GPU/CPU 实例
```

关键原则：

- 后端不是简单转发壳，而是 Agent 运行时。
- LLM 只通过后端统一调用，便于权限、配额、日志、审计和模型配置管理。
- 所有会产生费用或影响远程资源的操作都必须经过后端 Tool 层，不能绕过归属记录。

## 5. 核心模块

### 5.1 用户认证

- 注册 / 登录 / 当前用户信息。
- JWT 鉴权。
- 注册账号使用手机号作为登录标识，后端通过 `phonenumbers` 校验中国大陆手机号，注册时机构/学校为必填项。
- 注册页需要提供前端友好校验：手机号、机构/学校、密码、确认密码均需明确提示；后端 `422` 结构化错误需要在前端转换为用户可读中文文案。
- 开发环境保留管理员后门账号：`admin / admin123`，用于首次进入系统或恢复管理员登录。
- 角色：
  - `user`：管理自己的对话、任务、云实例和模型配置。
  - `admin`：管理用户、Lab4AI 凭证、配额、云实例总览和用量报表。

### 5.2 LLM 配置

用户自带模型 API Key，按 Anthropic-compatible Messages API 调用。

```python
class LLMConfig:
    provider: str
    base_url: str
    api_key_encrypted: str
    model: str
```

要求：

- 支持 `GET /api/llm-config` 和 `PUT /api/llm-config`。
- 支持 `POST /api/llm-config/test` 测试当前表单配置连通性。
- `api_key` 必须加密存储；当前 MVP 尚未完成真正加密，后续需要补齐。
- 模型需支持 tool use；不支持时可降级为固定工具链或纯对话模式。
- `max_tokens` 不作为用户配置项暴露。Agent Loop 内部按阶段控制输出预算：规划阶段使用较小预算，最终总结使用更大的安全预算，避免用户设置过大导致模型调用失败。

### 5.3 Agent Loop

Agent Loop 参考 Claude Code 的 tool-use 循环设计：

```python
async def agent_loop(conversation: Conversation, llm_config: LLMConfig):
    while True:
        messages = build_messages(conversation)
        system_prompt = build_system_prompt(conversation)

        response = await call_llm(
            system=system_prompt,
            messages=messages,
            tools=get_available_tools(conversation),
            config=llm_config,
        )

        if has_tool_use(response):
            tool_results = await execute_tools(response.tool_calls)
            persist_assistant_response(response)
            persist_tool_results(tool_results)
            await stream_events(tool_results)
            continue

        persist_assistant_response(response)
        await stream_events(response)
        break
```

过渡期可以用固定工具链推进闭环，但最终状态必须走真实 Tool executor，不允许用“模拟成功”完成 workflow：

1. 选择 skill / 任务类型。
2. 调用 `lab4ai_create_instance` 创建真实 Lab4AI 实例。
3. 调用 `ssh_execute` 通过真实 SSH 在远程实例执行命令。
4. 调用 `lab4ai_stop_instance` 释放真实 Lab4AI 实例。
5. 调用模型生成总结。

已确认目标态升级为 **Skill 契约驱动 Workflow + step 内模型 tool-use + SkillRuntime 真实 Tool 注册**。这里的核心不是让模型自由规划，也不是让后端用固定 executor 大概复刻流程，而是把 `skills/` 中声明的内容视为任务契约：后端运行时负责解释、渲染、适配和执行该契约。

- `SKILL.md`、`project_reproduce.yaml`、`tools.yaml`、`manifest.yaml` 是 skill 的执行边界。除非用户明确确认迁移方案，否则不得为了让流程跑通而修改 `skills/` 目录。
- Workflow 文件是复现类强流程任务的单一执行源，负责 step 顺序、依赖、状态持久化、前端展示和资源兜底释放。后端内置代码只能作为解释器和安全适配层，不能绕开 workflow instruction 另写一套语义不等价的流程。
- 每个 workflow step 内部可以调用模型，让模型返回 `tool_use`；后端只执行当前 step allowlist 中允许、且符合当前 skill instruction 语义的 Tool。
- 模型输出的 tool 参数不是最终可信输入。Tool 调用前必须经过 Skill Workflow Runtime 的上下文补齐、模板渲染、工具名适配和安全校验。
- 第一阶段允许接入 `lab4ai_create_instance`、`lab4ai_stop_instance`、`ssh_execute`、`file_write` 等高风险或计费 Tool，但必须经过 ToolRegistry 权限策略、HITL 确认和归属记录，不允许模型绕过。
- 每轮 tool-use 循环必须有最大轮数，例如 `max_tool_iterations=8`，防止模型无限调用工具。
- Tool 默认串行执行；只读 Tool 的并发执行留到后续优化，避免状态竞态。
- `tool_result` 必须回流为下一轮模型上下文，并同步持久化为 `ConversationMessage(role=tool)` 与 WebSocket 事件。
- 任何生产态 Tool 不允许返回伪造成功。功能尚未实现、依赖缺失、网络不可达或远程命令失败时，必须返回 `ok=false`、结构化 `error_code` 和可恢复建议，由 WorkflowRunner 决定重试、HITL 或失败收敛。
- 发生失败、中断或用户停止时，仍必须进入 `stopping -> cleanup -> stopped` 语义，资源释放逻辑优先于模型继续规划。

### 5.4 Tool 系统

每个 Tool 是结构化对象：

```python
class ToolDefinition:
    name: str
    description: str
    input_schema: dict
    read_only: bool
    confirmation_policy: Literal["never", "always", "risky"]
    confirmation_reason: str
    risk_level: Literal["low", "medium", "high", "critical"]
    audit_category: Literal["lab4ai", "ssh", "file", "llm", "workflow", "general"]

class ToolResult:
    name: str
    content: str
    ok: bool
    metadata: dict

class ToolRegistry:
    def confirmation_for(name: str, input: dict) -> ToolConfirmation | None: ...
    async def invoke(name: str, input: dict) -> ToolResult: ...
```

当前实现已经落地声明式 `ToolRegistry`：Tool 的 schema、只读属性、确认策略和执行器集中在 `backend/app/services/tools.py`。Agent Loop 不再手写某个资源确认分支，而是通过 `_invoke_tool_with_policy` 统一检查确认策略、暂停等待用户、再执行 Tool。

下一阶段 Tool 权限系统不先新建复杂权限中心，而是在 `ToolDefinition` 上补齐风险与审计元数据：

- `risk_level`：`low | medium | high | critical`。
- `audit_category`：`lab4ai | ssh | file | llm | workflow | general`。
- 审批绑定 `workflow_run_id + tool_call_id`，旧确认不能被新一轮或新工具调用复用。
- 第一阶段审计记录写入 `ConversationMessage.message_metadata`，后续如需要管理员级审计检索，再迁移为独立 `AuditLog` 表。

确认策略约定：

- `never`：只读或安全动作，不触发 HITL。
- `always`：创建算力实例等会产生费用或占用资源的动作，必须先确认。
- `risky`：如 SSH 命令，只有命中高风险模式时才确认。

核心 Tool：

| Tool | 功能 |
|---|---|
| `lab4ai_create_instance` | 创建 Lab4AI 云实例并记录归属 |
| `lab4ai_stop_instance` | 停止 Lab4AI 云实例并记录结束时间 |
| `lab4ai_list_instances` | 查询当前用户可见云实例 |
| `ssh_execute` | 在远程实例执行命令 |
| `analyze_repo` | 分析 GitHub 仓库结构 |
| `analyze_paper` | 下载/解析论文并抽取复现实验关键信息 |
| `read_url` | 读取网页、论文或文档内容 |
| `web_search` | 检索论文或资料 |
| `file_write` | 写入远程文件 |
| `repro_report` | 生成真实复现报告产物 |
| `ask_user` | 信息不足时向用户追问 |

所有会影响远程资源或产生费用的 Tool 必须：

- 校验用户权限和配额。
- 写入审计日志。
- 绑定 `conversation_id`。
- 失败时返回结构化错误，便于模型继续处理。

真实执行约束：

- `ToolRegistry` 负责统一注册内置 Tool 与 SkillRuntime 生成的 skill Tool；Agent Loop 和 WorkflowRunner 只能通过 `ToolRegistry.invoke()` 执行动作。
- Tool 的输入应当已经由 Skill Workflow Runtime 渲染完成。模板渲染属于 workflow 解释层职责，ToolRegistry 中的 `{{...}}` 拦截只是最后一道安全网，不应成为正常执行路径。
- `ssh_execute` 的输入必须是结构化参数，例如 `server_id / command / cwd / timeout / env / step_id`。SSH 主机、端口、用户名和密码从 `CloudInstance` 或凭证服务读取，不能由模型输出，也不能把密码注入 system prompt、前端事件或普通日志。
- `ssh_execute` 需使用后端 SSH 库执行真实连接，例如 `paramiko` 或 `asyncssh`，并返回 `exit_code / stdout / stderr / started_at / completed_at / timeout / remote_host`。Windows 后端不得依赖 `sshpass`。
- 如果 skill instruction 中出现 `sshpass ... ssh root@{{step_3.ssh_host}} ...` 这类历史 CLI 写法，后端应按其语义执行：使用当前任务绑定的 `CloudInstance` 和后端 SSH 库执行远程命令；不要求 Windows 后端逐字运行 `sshpass`，也不允许把 SSH 密码泄露给模型或前端。若未来要求逐字执行这些 shell wrapper，必须先修改本文档中的 SSH 安全约束。
- Tool 执行前必须拒绝未渲染模板变量，凡命令、路径或参数中仍包含 `{{...}}`，直接返回 `ok=false` 与 `error_code=unrendered_template`，不能继续下发远程命令。
- `file_write` 只能写受控任务 workspace 或通过 SFTP 写入当前任务绑定的远程 workspace；不得写入 `skills/`、系统目录或其他用户目录。
- `analyze_repo`、`analyze_paper`、`repro_report` 必须调用真实脚本或库并记录 artifact 路径，不能用固定分数、固定文案或“已模拟执行”代替结果。

### 5.5 Skill 系统

保留 `skills/` 目录作为任务模板和工具组合定义，但不再要求兼容任何外部 CLI。

参考 `claude-code-analysis` 的 Skill 机制时，需要明确两点：

- **Skill 内容是执行契约和铁律**。当任务选中某个 skill 后，后端必须以该 skill 的 `SKILL.md`、workflow 文件、工具声明和入口声明为准推进任务，不能因为后端已有固定实现就跳过或改写 skill 中的步骤。
- **Skill 文件本身不是直接执行器**。真正创建实例、执行 SSH、写文件、检索资料等副作用仍必须通过后端 Tool 完成。后端的职责是把 skill 契约编译为安全、结构化、可审计的 Tool 调用。

因此，`skills/` 目录具有只读契约属性：运行时可以读取、解析、渲染和适配其中内容，但不能在任务执行中擅自修改它。需要标准化或迁移 skill 模板时，必须先更新设计文档并由用户确认。

目标格式：

```yaml
---
name: lab4ai-auto-reproduct
description: 自动复现 GitHub 项目的实验结果
when_to_use: 用户提供 GitHub URL 并希望复现、训练或运行实验
task_type: reproduce
allowed_tools:
  - lab4ai_create_instance
  - lab4ai_stop_instance
  - ssh_execute
  - analyze_repo
  - read_url
  - ask_user
---

你是一个科研复现助手...
```

加载流程：

1. 启动时扫描 `skills/`。
2. 解析 frontmatter 或 YAML 元数据。
3. 读取 `SKILL.md` 正文，必要时读取同目录的 `project_reproduce.yaml` 等工作流文件。
4. 把 skill 摘要注入 system prompt，用于模型选择；选中后，完整 skill 契约由 Skill Workflow Runtime 执行，不只作为提示词。
5. 根据用户输入、前端 intent hint、`triggers` / `when_to_use` 选择 skill。
6. 将选中 skill 的正文、workflow、工具声明和 `allowed_tools` 交给 Skill Workflow Runtime，生成可追踪的 step 状态机和当前 step 的 Tool 白名单。
7. Agent Loop 在当前 step 内调用模型时，只允许模型补充决策、组装参数或请求 allowlist 内 Tool；最终 Tool 调用仍需由 runtime 渲染、适配、校验后执行。

Skill 执行链路：

```text
用户消息
  -> SkillLoader 扫描并解析 skills/<name>/SKILL.md
  -> SkillSelector 选择合适 skill
  -> Skill Workflow Runtime 解析 workflow / instruction / tool mapping
  -> LLM 在当前 step 内产生受控 tool_use 或决策补充
  -> Runtime 渲染模板、解析 step 输出、映射历史工具名
  -> ToolRegistry 执行具体 Tool
  -> tool_result 回流到 Conversation
  -> LLM 继续下一轮或总结完成
```

### 5.5.1 SkillRuntime（目标态：所有 skill 真实可执行）

当前问题的根因不是单个 step 漏调用，而是 `skills/` 目录仍主要被当成 prompt 模板注入，`tools.yaml`、`manifest.yaml` 和脚本入口没有被统一注册为后端 Tool。因此长期正确方案是新增 `SkillRuntime`，把每个 skill 的声明式工具变成 `ToolRegistry` 中可校验、可审计、可真实执行的 Tool。

`SkillRuntime` 启动时扫描：

- `SKILL.md`：作为任务说明、选择条件和上下文模板。
- `tools.yaml`：声明一个 skill 下的多个工具，例如 `repo_audit`、`paper_analyze`。
- `manifest.yaml`：声明单入口可执行 skill，例如远程项目准备、报告生成。
- `skill.json`：声明触发词、展示元数据和前端可见能力。

入口规范：

- Python 入口统一写成 `relative/path.py:function_name`，路径相对 skill 目录解析。
- 启动时必须 import-test 每个入口，缺失函数、依赖缺失、签名不匹配都要在健康检查中暴露，不能等用户任务执行到一半才发现。
- 入口函数接收结构化参数并返回 `dict` 或标准 `ToolResult`。异常必须被转换成 `ok=false`、`error_code`、`message`、`retryable` 和 `artifact_paths`。
- 脚本不得在请求处理中动态安装依赖；依赖应写入后端运行环境或 skill 依赖清单，启动健康检查负责报错。
- 网络访问必须使用系统代理/镜像配置，不能在 skill 脚本里硬编码代理地址。

当前 Lab4AI skills 的目标映射：

| Skill | 声明文件 | 后端 Tool | 真实入口与要求 |
|---|---|---|---|
| `lab4ai-project-analysis` | `tools.yaml` | `analyze_repo` / `repo_audit` | 调用 `scripts/main.py:audit_repo`，真实 clone 或读取仓库，输出依赖、启动命令、风险、评分和 audit artifact |
| `lab4ai-paper-analysis` | `tools.yaml` | `analyze_paper` / `paper_analyze` | 补齐 `scripts/analyze_paper.py:analyze_paper_tool`，复用现有解析逻辑，返回方法、数据集、指标、超参、baseline 和 markdown artifact |
| `lab4ai-project-prep` | `manifest.yaml` | `remote_project_prep` | 调用 `prep_runner.py:run_remote_prep` 或等价后端服务，通过 `ssh_execute` / SFTP 上传和执行脚本，不直接依赖 `sshpass` |
| `lab4ai-repro-report` | `manifest.yaml` | `repro_report` | 调用 `report_generator.py:generate_report`，生成真实 `.docx` 并记录 artifact |
| `lab4ai-image-manage` | `manifest.yaml` | `lab4ai_image_*` | 查询、筛选和确认镜像时返回结构化候选，不让模型猜镜像名称 |
| `lab4ai-instance-manage` | `manifest.yaml` | `lab4ai_create_instance` / `lab4ai_stop_instance` / `lab4ai_list_instances` | 以当前后端 Lab4AI API Tool 为权威实现，skill 脚本只能作为适配层或测试参考 |

历史兼容策略：

- `claw-shell`、`file-system`、`ssh-essentials` 这类 CLI/本地机 skill 不直接在 Web 后端执行，只映射为受控的 `ssh_execute`、`file_write`、workspace 读取等后端 Tool。
- `skills/` 中出现的 `openclaw`、`claw-workflow`、`/root/.openclaw` 等历史命名应通过兼容层转换为当前 LOBSTER runtime 语义；迁移模板本身需要另行确认，避免擅自改动 `skills/`。
- 本地分析 artifact 统一写入 `runtime/workspaces/<conversation_id>/<repo_name>/...`；远程实验 artifact 统一写入 `/workspace/user-data/codelab/<repo_name>/...`，并通过 metadata 记录。
- 旧 OpenClaw / vendor skill 的完整适配矩阵、优先级和验收标准见 [docs/skill-adapter-plan.md](skill-adapter-plan.md)。实施顺序按 P0（复现 workflow 安全闭环）→ P1（阻断任意 shell 与文件越界）→ P2（旧路径与脚本入口收敛）推进。
- P0/P1 适配完成前，模型即使读到 `claw-shell`、`sshpass`、`ssh-essentials` 或 `file-system` 指令，也只能通过当前 step allowlist 触发后端 Tool；不得直接运行 vendor `handler.js`、本机 `tmux`、本机 `sshpass` 或任意 shell。

依赖与健康检查：

- 后端运行环境至少需要补齐 `requests`、`pyyaml`、`pymupdf`、`python-docx`、`paramiko` 或 `asyncssh`。
- 启动健康检查输出每个 skill 的 `loaded / failed / missing_dependency / missing_entrypoint` 状态，管理员页面可查看。
- CI 必须包含 skill entrypoint import 测试、工具 schema 测试和最小 dry-run 测试，确保新增 skill 不会破坏现有 workflow。

### 5.5.2 Skill Workflow Runtime（已确认实施）

针对 `lab4ai-auto-reproduct` 这类强流程任务，不能只把 `SKILL.md` 和 `project_reproduce.yaml` 注入模型上下文后让模型自由发挥。后端需要把 workflow 文件解析为可追踪、可恢复、可展示的执行状态机。

用户在页面选择「论文与代码复现」并输入 GitHub URL、论文 URL 后，系统默认选择 `lab4ai-auto-reproduct`，加载同目录 `project_reproduce.yaml`，并按 YAML 中 `tasks` 数组逐步执行。

本 Runtime 的执行原则：

- `project_reproduce.yaml` 是当前复现 workflow 的单一真源。`tasks[*].instruction` 和 `expected_output` 是 step 执行契约，不能被固定后端流程替代。
- Runtime 负责把 instruction 中的历史工具名、模板变量和 shell 片段编译为当前后端 Tool 调用。编译结果必须语义等价，并保留 HITL、审计和资源归属约束。
- Step 内模型 tool-use 可以参与分析和组装参数，但不能越过 workflow 顺序，也不能把未渲染模板变量、SSH 密码或平台凭证直接交给 Tool。
- 如果某条 instruction 无法被安全适配，Runtime 必须返回结构化错误或进入 HITL，说明缺失的上下文或适配器，而不是悄悄执行另一条固定命令。

运行链路：

```text
页面选择论文与代码复现
  -> 创建 Conversation(task_type=reproduce, github_url, paper_url)
  -> SkillSelector 默认选择 lab4ai-auto-reproduct
  -> SkillLoader 加载 SKILL.md + project_reproduce.yaml
  -> WorkflowRunner 解析 tasks / depends_on / instruction / expected_output
  -> WorkflowRunner 按 step 状态机推进
  -> ToolRegistry 执行每一步需要的后端 Tool
  -> WebSocket 推送 workflow_step_* / tool_* / ask_user 事件
  -> 前端以结构化 9 步看板展示执行过程
```

状态存储在 `Conversation.metadata` 中，建议结构：

```json
{
  "selected_skill": "lab4ai-auto-reproduct",
  "workflow_name": "Lab4AI_Auto_Reproduction_Pipeline",
  "workflow_version": "lab4ai-workflow/v2.1",
  "workflow_current_step_id": "step_4_cpu_env_setup",
  "workflow_steps": [
    {
      "id": "step_1_audit",
      "name": "项目复现可行性分析",
      "status": "completed",
      "attempts": 1,
      "allowed_tools": ["analyze_repo", "analyze_paper", "read_url", "ask_user"],
      "tool_calls": [
        {
          "tool_call_id": "toolu_01...",
          "name": "analyze_repo",
          "status": "completed",
          "started_at": "2026-05-20T10:00:00Z",
          "completed_at": "2026-05-20T10:00:03Z"
        },
        {
          "tool_call_id": "toolu_02...",
          "name": "analyze_paper",
          "status": "completed",
          "started_at": "2026-05-20T10:00:03Z",
          "completed_at": "2026-05-20T10:00:08Z"
        }
      ],
      "artifacts": ["runtime/workspaces/.../repo_audit.md", "runtime/workspaces/.../paper_analysis.md"],
      "progress": ["已读取 README", "已提取依赖文件", "已解析论文方法和实验指标"],
      "error": null,
      "output": "已完成仓库与论文审计；评分来自真实分析脚本输出"
    }
  ],
  "workflow_resources": {
    "cpu": {"server_id": "xxx", "released": true},
    "gpu": {"server_id": "yyy", "released": false}
  },
  "workflow_results": {
    "repo_name": "PhotoDoodle",
    "score": 82,
    "audit_report_path": "runtime/workspaces/.../repo_audit.md",
    "paper_report_path": "runtime/workspaces/.../paper_analysis.md",
    "word_report_path": ""
  }
}
```

Workflow step metadata 需要比首版状态机更细：

- `attempts`：当前 step 的重试次数，用于恢复和失败诊断。
- `allowed_tools`：当前 step 内模型可调用的 Tool 白名单，必须来自 workflow/skill 的交集。
- `tool_calls`：当前 step 内已经发起的工具调用列表，至少记录 `tool_call_id / name / status / started_at / completed_at / ok / audit_category / risk_level`。
- `artifacts`：当前 step 产物路径或远程资源引用，例如审计报告、训练日志、结果图、Word 报告。
- `progress`：细粒度进展文本，可通过 `workflow_step_progress` 增量推给前端。
- `error`：结构化错误，至少包含 `type / message / retryable / tool_call_id`。

这些字段必须写入 `Conversation.metadata.workflow_steps[*]`，不能只存在内存中。恢复执行时，WorkflowRunner 先读取 metadata 判断上次停在何处，再决定继续、重试或进入 cleanup。

模板渲染与上下文解析：

- Runtime 维护当前 workflow 的渲染上下文，至少包含 `parameters.github_url / parameters.paper_url / repo_name / repo_name_underscore / workflow_results / workflow_resources`。
- 每个 step 的 ToolResult 必须保存结构化输出，供后续模板引用。例如 `step_3_deploy_cpu` 输出应至少提供 `serverId / server_id / ssh_host / ssh_port / ssh_user`，其中敏感的 `ssh_pass` 只能作为后端 secret 引用，不进入模型上下文或前端事件。
- 历史模板别名必须兼容。`{{step_3.ssh_host}}` 应解析到 `step_3_deploy_cpu` 的结构化输出；`{{step_6.ssh_port}}` 应解析到 `step_6_deploy_gpu` 的输出。Runtime 不应要求 skill 模板立刻改成新 step id。
- 模板渲染应发生在 ToolRegistry 调用之前。无法解析的变量要返回 `error_code=unresolved_template_variable`，并明确变量名和所在 step；不能把 `{{...}}` 原样传给 `ssh_execute`。
- `{{repo_name}}`、`{{repo_name_underscore}}` 等派生变量必须由 Runtime 从 `github_url` 或上游分析结果稳定生成，且经过路径安全过滤。

工具名与执行适配：

- `lab4ai-instance-manage (创建)` 映射为 `lab4ai_create_instance`；`lab4ai-instance-manage (关闭)` 映射为 `lab4ai_stop_instance`；查询类动作映射为 `lab4ai_list_instances`。
- `claw-shell`、`ssh-essentials`、包含 SSH wrapper 的 instruction 映射为受控 `ssh_execute`。Runtime 提取远程要执行的命令内容，连接信息由 `CloudInstance` 解析，不由模型或 skill 文本直接提供。
- `file-system` 映射为受控 workspace 读写能力；不得读取或写入 `skills/`、系统目录或其他用户目录。
- `lab4ai-project-prep` 映射为 `remote_project_prep` 或等价后端适配器，参数来自渲染上下文和模型组装结果，执行仍通过后端 SSH/SFTP 管线。
- `lab4ai-repro-report` 映射为 `repro_report`，报告内容来自前序 step 的结构化结果、artifact 和日志。

复现 workflow 的真实执行要求：

- `step_1_audit` 必须执行真实 `analyze_repo`；当用户提供论文 URL 时还必须执行真实 `analyze_paper`，并把仓库审计与论文可行性分析合并成 step 产物。不得再写死 `score=75`、`baseline_metrics` 或固定 MVP 文案。
- `step_3_deploy_cpu` 和 `step_6_deploy_gpu` 必须把 Lab4AI 返回的 `server_id / ssh_host / ssh_port / ssh_user` 写入 `CloudInstance` 与 `workflow_resources`。`ssh_pass` 等敏感字段只能保存在后端加密存储或受控 secret 字段，不能进入模型上下文和前端事件。
- `step_4_cpu_env_setup` 必须通过 `remote_project_prep` 或 `ssh_execute` 的结构化输入执行。后端负责渲染 `repo_url / repo_name / workspace / proxy` 等变量；如果命令中仍包含 `{{step_...}}`，必须失败并提示模板未渲染。
- `step_7_reproduce_on_gpu` 必须基于真实 GPU 实例执行训练、推理或最小 smoke test，并记录远程日志、退出码和结果 artifact。
- `step_8_generate_report` 必须调用 `repro_report` 生成真实 `.docx` 或同等报告 artifact，报告内容来自前序 step 的结构化结果和日志，不由模型凭空补写。
- step 是否完成只能依据 `ToolResult.ok`、退出码和 artifact 记录判断，不能依据模型自然语言“看起来完成了”判断。

Workflow step 状态：

| 状态 | 含义 |
|---|---|
| `pending` | 等待依赖步骤完成 |
| `running` | 当前正在执行 |
| `waiting_for_user` | 已暂停，等待用户确认或补充信息 |
| `completed` | 已完成并记录产出 |
| `failed` | 执行失败 |
| `skipped` | 因条件分支或熔断被跳过 |

WebSocket 事件补充：

| 事件 | 用途 |
|---|---|
| `workflow_loaded` | 通知前端已加载 workflow 和步骤列表 |
| `workflow_step_started` | 某一步开始执行 |
| `workflow_step_progress` | 某一步的中间进展 |
| `workflow_step_waiting` | 某一步进入 HITL 等待 |
| `workflow_step_completed` | 某一步完成 |
| `workflow_step_failed` | 某一步失败 |
| `workflow_cleanup_started` | 异常或停止后的资源兜底释放开始 |
| `workflow_cleanup_completed` | 资源兜底释放完成 |

资源释放规则：

- `step_3_deploy_cpu` 创建 CPU 实例后，必须把 `server_id` 写入 `workflow_resources.cpu`。
- `step_6_deploy_gpu` 创建 GPU 实例后，必须把 `server_id` 写入 `workflow_resources.gpu`。
- 任意 step 失败、中断或用户停止任务时，后端必须检查 `workflow_resources`：
  - CPU 未释放且已创建，则执行 `step_5_release_cpu` 对应的释放动作。
  - GPU 未释放且已创建，则执行 `step_9_release_gpu` 对应的释放动作。
- 用户发送「停止」「中断」「取消」时，不允许直接丢弃任务；必须进入 `stopping -> cleanup -> stopped` 语义，资源释放是停止流程中的唯一强制例外。

目标态中，workflow 的步骤状态、事件流、暂停恢复和资源兜底必须按真实执行链路落地。Lab4AI、SSH、文件写入、项目分析、论文分析和报告生成都必须走真实 executor；缺少管理员凭证、依赖缺失、平台 API 失败、网络不可达或远程命令失败时，直接进入结构化错误处理或 HITL，不允许用 mock 成功继续推进。

后端固定 executor 的定位需要收敛：它可以作为 Skill Workflow Runtime 的内置适配器实现某个 instruction 的语义，但不能在 skill step 内模型 tool-use 失败时无条件改走语义不同的固定流程。凡是 fallback，都必须证明仍在执行同一条 skill 契约；否则应标记 step failed / waiting_for_user，并暴露缺失的模板变量、工具适配器或执行上下文。

近期最小实现（已完成）：

- 新增 Python `SkillLoader`，支持扫描 `skills/*/SKILL.md`。
- 新增 `SkillDefinition` 数据结构，包含 `name / description / triggers / when_to_use / allowed_tools / body / base_dir`。
- `lab4ai-auto-reproduct` 执行时必须加载同目录 `project_reproduce.yaml`。
- `agent_loop.py` 不再只写“已选择 skill”，而要把选中 skill 的正文和工作流上下文注入模型请求。
- 暂不实现内嵌 Shell 语法；如未来支持，必须像 `claude-code-analysis` 一样经过统一权限和审计管线。

当前落地状态：

- 已新增 `backend/app/services/skills.py`，实现 `SkillDefinition`、`SkillLoader` 和 `select_skill`。
- 已在 `backend/app/services/agent_loop.py` 中接入 SkillLoader，复现任务会选择 `lab4ai-auto-reproduct` 并注入 skill 正文与 `project_reproduce.yaml`。
- 已新增 `backend/tests/test_skills.py` 覆盖 skill 解析、workflow 加载和任务选择。
- 已新增 `backend/app/services/workflow.py` 首版 `SkillWorkflowRunner`，可解析 `project_reproduce.yaml` 的 `tasks / depends_on / instruction / expected_output`，把 step 状态写入 `Conversation.metadata.workflow_steps`，并推送 `workflow_loaded / workflow_step_* / workflow_cleanup_*` 事件。
- Agent Loop 已在复现任务中接入 WorkflowRunner；用户确认后可从 `waiting_for_user` 恢复继续执行，同一轮执行继续沿用当前 `workflow_run_id`。
- 前端 `ChatPage` 和 `RightPanel` 已可展示 workflow 加载、step 执行、等待确认、失败和资源兜底释放事件。

### 5.6 Lab4AI 云实例管理

Lab4AI 云实例是真正消耗费用的资源，必须由后端统一管理。

设计要点：

- 管理员配置统一 Lab4AI 账号。
- 创建实例时后端记录 `server_id / user_id / conversation_id / start_time / status`。
- 查询实例时按用户过滤；管理员可查看全部。
- 关停实例前校验归属。
- Agent Loop 异常、用户停止任务或后端重启恢复时，必须检查并清理遗留实例。
- `lab4ai_create_instance / lab4ai_stop_instance / lab4ai_list_instances` 直接调用真实 Lab4AI REST API，并写入或更新 `CloudInstance` 归属记录；若管理员未配置 Lab4AI 凭证，ToolRegistry 触发 `lab4ai_credentials_required` 人工介入并暂停当前 `tool_call_id`，由前端弹出管理员凭证配置弹窗；若平台 API 返回失败，则返回结构化错误并进入重试、HITL 或失败处理，不再通过 Runner/mock 分支绕过真实执行。

### 5.7 算力限额

- 管理员为用户设置 GPU/CPU 累计使用时长上限。
- 后端根据云实例 `start_time / stop_time` 统计用量。
- 创建新实例前检查剩余额度。
- 前端展示用户当前额度和已用量。

### 5.8 WebSocket 事件流

WebSocket 推送内容：

- assistant 文本增量。
- tool start / result / error。
- skill selection。
- human confirmation request / answer。
- 任务状态变化。
- Lab4AI 实例状态变化。
- 错误类型和错误消息。

事件必须持久化，断线重连后可以通过 conversation history 回看。

事件流协议补充：

- 每个事件必须包含 `seq`，由后端按对话递增分配。前端使用 `seq` 去重，避免 WebSocket 重连回放导致重复追加。
- 每轮 Agent 执行必须包含 `run_id`，对应 `Conversation.metadata.workflow_run_id`。同一轮中的 assistant 文本、progress、tool 事件和状态变化都用同一个 `run_id` 串联。
- assistant 回复必须以同一条用户消息为边界聚合。规划、工具调用和总结属于同一轮执行轨迹，不应在主聊天区拆成多条互不关联的 assistant 回复。
- 模型最终回复使用 `assistant_started` / `assistant_delta` / `assistant_completed` 事件流式推送。`assistant_completed` 后再把完整文本持久化为一条 `ConversationMessage(role=assistant)`。
- 工具执行过程使用 `tool_started` / `tool_completed` / `tool_error` 表达，并持久化为 `ConversationMessage(role=tool)`；前端应在当前 assistant 回复下方以执行时间线展示，而不是完全隐藏。
- 模型驱动 tool-use 阶段，每个 `tool_started / tool_completed / tool_error / workflow_step_waiting / ask_user` 事件都必须携带 `tool_call_id`；如果事件属于某个 workflow step，还必须携带 `workflow_step_id`。
- HITL 审批事件必须携带 `run_id + tool_call_id + workflow_step_id`。用户确认后，后端只允许恢复同一 `workflow_run_id` 下同一个 `tool_call_id` 的调用，不能只按 tool name 或 step name 复用旧确认。
- Tool 审计信息第一阶段随 `ConversationMessage(role=tool).message_metadata` 落库，建议字段包括 `tool_call_id / workflow_step_id / risk_level / audit_category / confirmation_required / confirmed_by_user / confirmed_at / tool_input / ok / error`。
- `message` 事件只用于已完成并落库的历史消息兼容；实时渲染优先消费 `assistant_*` 和 `tool_*` 事件。
- 中间规划内容可以作为 `progress` / `progress_delta` 事件展示在执行时间线中，不作为独立 assistant 消息，避免“一问多答”的聊天体验。

### 5.9 对话记忆

每个对话都需要自己的结构化记忆，不只是保留原始消息历史。当前推荐做法是把记忆放在 `Conversation.metadata` 中，由后端统一读写，避免再引入额外存储面。

建议结构：

```json
{
  "memory": {
    "summary": "当前任务摘要",
    "facts": ["已确认事实"],
    "decisions": ["用户已确认的决策"],
    "open_questions": ["待用户回答的问题"],
    "artifacts": ["报告路径 / 远程实例 / 日志路径"],
    "last_compacted_at": "2026-05-19T00:00:00Z",
    "compacted_through_message_id": 123,
    "compaction_count": 1
  },
  "workflow_run_id": "每轮 Agent 执行的唯一 ID",
  "workflow_state": "idle | running | waiting_for_user | completed | failed | stopped",
  "pending_user_input": {
    "question": "需要用户确认的问题",
    "options": ["继续", "修改方案", "停止"],
    "step": "human_checkpoint",
    "tool_name": "lab4ai_create_instance",
    "tool_call_id": "toolu_01...",
    "workflow_step_id": "step_3_deploy_cpu",
    "tool_input": {},
    "run_id": "当前 workflow_run_id",
    "intervention": {
      "type": "lab4ai_credentials_required",
      "title": "需要配置 Lab4AI 平台账号",
      "admin_endpoint": "/api/admin/settings/lab4ai"
    }
  }
}
```

记忆更新原则：

- 新消息进入后，先追加原始消息，再更新结构化记忆。
- 重要事实、用户确认、远程实例 ID、报告路径必须写入 `memory`。
- Agent 请求模型时，使用“完整消息历史 + 最近窗口 + memory 摘要”三层上下文，而不是只依赖最近 12 条消息。
- 当对话过长时，后端把早期消息压缩为摘要写入 `memory.summary`，记录 `last_compacted_at / compacted_through_message_id / compaction_count`；完整原始消息仍保留在数据库和 JSONL 事件日志中。

下一阶段增加跨对话长期记忆，但第一阶段不引入向量库，采用数据库关键词检索：

- 新增 `UserMemory` 或等价持久化结构，按 `user_id` 隔离存储长期事实、偏好、常用环境、历史项目经验和重要决策。
- 记忆来源只来自明确完成的对话摘要、用户确认的决策和已完成产物，不把临时推测或失败中间状态自动写入长期记忆。
- 检索时使用关键词、任务类型、GitHub 仓库名、论文标题/URL、Tool 产物路径等结构化字段匹配，最多召回 3-5 条，注入 system prompt 的“长期记忆上下文”区块。
- 长期记忆必须支持用户级禁用、查看和删除；禁用后不再写入或召回，但不影响单个对话内部的 `Conversation.metadata.memory`。
- 召回内容必须带来源 `conversation_id / message_id / created_at`，便于审计和后续 UI 展示。

### 5.10 Human-in-the-loop

HITL 不是单独一个页面，而是对话流程中的“等待用户决策”状态。

适合触发人工参与的场景：

- 信息不足，无法安全继续，例如缺少仓库、论文链接、数据集许可信息。
- 动作会产生费用或影响远程资源，例如创建 GPU 实例、启动长训练、下载受限数据。
- 多个方案都可行，但需要用户确认优先级，例如“先 CPU 探索还是直接上 GPU”。
- 解析到高风险命令或可能破坏环境的操作。

推荐交互：

1. Agent 通过 `ask_user` 生成问题。
2. 后端把 `workflow_state` 置为 `waiting_for_user`，并写入 `pending_user_input`。
3. WebSocket 推送 `ask_user` 事件，前端展示问题和可选操作；需要明确人参与决策或配置时，同时弹出决策弹窗。
4. 输入框保持可用，用户直接回复文字、点击快捷按钮，或在专用弹窗中填写必要配置。
5. 用户回复后，`POST /api/conversations/{id}/messages` 继续推进流程。
6. 后端读取原始消息历史与 `memory`，从上次暂停点继续执行。

实现约束：

- `ask_user` 不应只是普通文本，它必须能暂停流程。
- `pending_user_input.intervention` 用于声明专用人工介入 UI，前端按 `type` 分发弹窗；普通确认走通用决策弹窗，`lab4ai_credentials_required` 走 Lab4AI 管理员凭证配置弹窗。
- Lab4AI 凭证缺失不得直接让 workflow 失败，应暂停当前 `tool_call_id`，提示管理员配置 `/api/admin/settings/lab4ai`，保存后再由用户确认“已完成配置，继续执行”。
- 被确认过的决策要写进 `memory.decisions`，但审批只对当前 `workflow_run_id + tool_call_id` 生效，避免新一轮对话或同一轮内另一个工具调用误用旧确认。
- HITL 审批绑定字段为 `workflow_run_id / tool_call_id / workflow_step_id / tool_name`。缺任一关键字段时，高风险或计费 Tool 不能继续执行。
- 第一阶段审计不新增独立表，确认请求、用户回复、审批结果和 Tool 执行结果写入 `ConversationMessage.message_metadata`；后续管理员审计检索需要增强时，再迁移到独立 `AuditLog`。
- 没有收到用户回复时，不得自动跳过需要确认的步骤。
- 发生中断、刷新页面或重新连接后，前端仍应通过 `pending_user_input` 恢复到等待态。

## 6. 数据模型

```text
User
├── id
├── username（手机号，用于登录和唯一身份标识）
├── institution（机构/学校，注册必填）
├── password_hash
├── role
├── is_active
└── quota fields

LLMConfig
├── id
├── user_id
├── provider
├── base_url
├── api_key_encrypted
├── model
└── updated_at

Conversation
├── id
├── user_id
├── task_type
├── title
├── status
├── metadata
├── log_file_path
├── created_at
└── updated_at

metadata 建议承载：

- `memory`
- `workflow_state`
- `workflow_run_id`
- `pending_user_input`
- `task_type / github_url / paper_url / intent_hint`

UserMemory
├── id
├── user_id
├── kind（fact / preference / decision / artifact / project）
├── content
├── keywords
├── source_conversation_id
├── source_message_id
├── enabled
├── created_at
└── updated_at

ConversationMessage
├── id
├── conversation_id
├── role
├── content
├── metadata
└── created_at

CloudInstance
├── id
├── user_id
├── conversation_id
├── server_id
├── instance_id
├── instance_type
├── gpu_count
├── ssh_host / ssh_port / ssh_user
├── status
├── start_time
├── stop_time
└── raw_payload
```

历史遗留的旧实例命名已迁移到 `Conversation` 和 `CloudInstance`。代码、API、测试和前端主链路不再保留 `claw-instances` 入口；涉及算力实例的公开接口统一使用 `cloud-instances`。

## 7. API 设计

### 7.1 Auth

- `POST /api/auth/register`
- `POST /api/auth/login`
- `GET /api/auth/me`

### 7.2 Conversations

- `POST /api/conversations`：创建新对话。
- `GET /api/conversations`：对话列表。
- `GET /api/conversations/{id}`：对话详情，含历史消息。
- `POST /api/conversations/{id}/messages`：发送消息并触发 Agent Loop。
- `POST /api/conversations/{id}/stop`：中断当前执行。
- `WS /api/conversations/{id}/stream`：实时事件流。

### 7.3 LLM Config

- `GET /api/llm-config`
- `PUT /api/llm-config`
- `POST /api/llm-config/test`

### 7.4 Lab4AI / Cloud Instances

- `GET /api/cloud-instances`
- `GET /api/cloud-instances/quota`
- `POST /api/cloud-instances/{id}/stop`

### 7.5 Admin

- `GET /api/admin/users`
- `PATCH /api/admin/users/{id}`
- `GET /api/admin/cloud-instances`
- `PUT /api/admin/settings/lab4ai`
- `GET /api/admin/usage`

## 8. 前端体验

核心页面：

- 登录 / 注册。
- WelcomePage：创建科研任务入口。
- ChatPage：多轮对话、Agent 回复 Markdown 渲染、每条消息的时间与复制按钮、停止按钮、结果回看。
- Sidebar：历史对话、配额展示、任务类型导航。
- RightPanel：Tool Events 流、当前对话详情、云实例、任务 metadata。
- ModelSettings：用户模型配置和连通性测试。
- Admin 页面：用户管理、云实例总览、Lab4AI 凭证、用量报表。

任务类型：

- `reproduce`：项目/论文复现。
- `search`：论文/资料检索。
- `paper_only`：仅论文分析。
- `experiments`：实验设计、消融、调参。
- `polish`：论文润色和表达优化。
- `general`：通用科研问答。

## 9. 当前状态

已完成：

- 用户注册 / 登录 / JWT。
- V2 `conversations` API。
- V2 Agent Loop 基础闭环。
- Anthropic-compatible 模型调用。
- 模型配置页面和连通性测试。
- WebSocket 流式事件。
- 对话历史持久化。
- 对话 memory 已可写入 `Conversation.metadata`，包含摘要、事实、决策、待答问题和产物列表。
- reproduce 任务已具备 Tool 策略驱动的 HITL：`lab4ai_create_instance` 必须确认，高风险 `ssh_execute` 条件确认，回复后按 `approved / needs_revision / rejected / stopped` 分类处理。
- 对话 memory 已支持长历史压缩，早期消息会压缩进 `memory.summary`，并记录 `compacted_through_message_id / compaction_count`。
- 前端对话入口、历史记录、模型设置页。
- ChatPage 已支持 Agent Markdown 渲染，消息底部显示时间和复制按钮；Tool Events 已移动到右侧栏展示。
- 配额查询和前端展示。
- SkillLoader 最小实现：扫描 `skills/*/SKILL.md`、解析 frontmatter、加载 `lab4ai-auto-reproduct/project_reproduce.yaml` 并注入 Agent Loop system prompt。
- Skill Workflow Runtime 首版：解析 `project_reproduce.yaml`，持久化 step 状态，推送 workflow step 事件，并在失败、异常或停止时根据 `workflow_resources` 兜底释放 CPU/GPU 实例。
- Lab4AI Tool 真实 API：`lab4ai_create_instance / lab4ai_stop_instance / lab4ai_list_instances` 直接调用真实 Lab4AI API，并写入 `CloudInstance` 归属记录；不再保留 Runner/mock 路径。
- Workflow 解析边界已将历史 `claw-workflow/*` 版本号归一化为 `lab4ai-workflow/*`，运行时 metadata 与 WebSocket 事件不再暴露旧 workflow 品牌命名。
- 已确认下一阶段的实现方向：采用 Workflow 强约束 + step 内模型 tool-use；高风险和计费 Tool 第一阶段可以接入，但必须经过 ToolRegistry、HITL 和审计管线；跨对话长期记忆先用数据库关键词检索，不引入向量库。
- Agent Loop 已接入 Anthropic-compatible `tool_use` blocks：模型可在 Workflow step 内按 allowlist 请求工具调用，后端执行 `ToolRegistry` 后把 `tool_result` 回流给模型；超过最大轮数会停止继续调用。
- ToolRegistry 已补齐 `risk_level / audit_category`、Anthropic tool schema 输出、`workflow_run_id + tool_call_id` 审批绑定，并新增保守模拟的 `file_write` Tool（不写本地文件，不允许指向 `skills/`）。
- Skill Workflow Runtime 已深化 step metadata：`attempts / allowed_tools / tool_calls / artifacts / progress / error` 会持久化到 `Conversation.metadata.workflow_steps[*]`，并推送 `workflow_step_progress`。
- 已新增 `UserMemory` 和 `long_term_memory` 服务，第一阶段按数据库关键词/内容检索召回跨对话长期记忆，不引入向量库。
- 已确认长期方向：新增 `SkillRuntime`，把 `tools.yaml`、`manifest.yaml` 和脚本入口注册为真实后端 Tool；所有 skill 能力必须通过 `ToolRegistry` 执行、审计和返回结构化结果。
- 已确认架构原则：`skills/` 内容是执行契约和铁律。后端运行时必须解析、渲染、适配并执行 skill，不得通过修改 `skills/` 或绕过 workflow instruction 来“修复”任务。
- P0/P1 旧 OpenClaw / vendor skill 适配首轮已落地：`claw_shell_run` 与 `ssh_essentials_execute` 会规范化到 `ssh_execute`；`sshpass ... ssh ... "<remote command>"` wrapper 会被编译为远程命令；`file_system_read / file_system_list / file_system_write` 映射到受控 workspace 或当前任务绑定实例的 SFTP 路径。

当前限制：

- Lab4AI 创建 / 停止 / 查询已走真实 API 代码路径，仍需要真实凭证与线上环境联调；缺少凭证时应触发 `lab4ai_credentials_required` 弹窗介入，不再自动模拟计费实例。
- SSH 执行已接入真实 executor：后端从 `CloudInstance` 读取 SSH 连接信息，通过 `paramiko` 执行命令；缺少实例、SSH 凭证、依赖、超时或非零退出码都会返回结构化错误。仍需要真实 Lab4AI 线上实例做端到端联调。
- Workflow 已接入 SkillRuntime 适配层：`tools.yaml` / `manifest.yaml` 中的关键能力已注册为可执行 Tool；`lab4ai-paper-analysis` 的声明入口虽仍指向缺失包装函数，但后端适配器会复用现有脚本函数完成真实论文分析，暂不修改 `skills/` 目录。
- `step_1_audit` 已同时执行仓库分析和论文分析真实脚本，不再使用固定审计值。
- Agent Loop 已具备 step 内模型 tool-use 基础能力，但当前仅在 Workflow 受控 step 中启用；真实效果仍依赖所配置模型是否支持 Anthropic-compatible `tool_use`。
- Skill Workflow Runtime 已补齐 P0/P1 首轮历史工具名适配和 `sshpass` wrapper 编译；仍需继续完善更完整的 step 输出别名映射、长脚本日志流和真实远程服务器集成测试。
- `api_key_encrypted` 字段尚未接入真实加密。
- `skills/` 目录已支持最小解析和注入，但仍需继续标准化元数据、`allowed_tools` 和任务类型映射。
- `Skill Workflow Runtime` 已补齐 step metadata、部分 step 内模型 tool-use，以及真实 SSH、受控文件写入、真实论文分析和真实报告生成 executor；仍需补充真实远程服务器集成测试。
- GitHub、arXiv、Hugging Face 等外部访问仍缺少统一代理/镜像配置；网络不可达时应结构化失败或进入 HITL，而不是继续模拟。
- memory 已新增数据库关键词检索的跨对话长期记忆基础服务，但用户级查看/删除/禁用 API 与前端入口仍待实现。
- HITL 已支持 `tool_call_id` 级审批绑定和 Tool 审计 metadata，但还不是独立管理员审计系统。
- `skills/` 原始模板仍包含历史 `claw-workflow` / `openclaw` / `claw-shell` 命名。根据当前协作约束，暂不直接修改 `skills/` 目录；若后续需要标准化模板，需要先确认迁移方案并同步更新 workflow 文档。

## 10. Workflow 强约束完成机制

Workflow step 的完成条件不能由模型自然语言或单次探活类工具调用决定。后端运行时必须把每个关键 step 编译为可验证合约，并在完成前校验以下内容：

- `required_tools`：该 step 必须出现并成功完成的真实 Tool，例如 `step_4_cpu_env_setup` 必须执行 `ssh_execute`。
- `required_effects`：该 step 必须产生的能力效果，例如远程执行、远程写入、实例生命周期管理或本地产物生成。
- `required_evidence`：该 step 必须写入 `workflow_steps[*].evidence` 的验收证据，例如远程 workspace 存在、Git 仓库可识别、依赖安装流程已尝试、报告文件路径已生成。
- `postconditions`：涉及远程状态的 step 必须在主命令后执行独立验收命令；只读探活、目录列表、模型总结不能替代后置验收。

当前落地规则：

- `step_4_cpu_env_setup` 在远程 CPU 实例执行项目准备命令后，必须再次通过 `ssh_execute` 验证 `/workspace/user-data/codelab/<repo>/code`、`data`、`model` 目录存在，且 `code` 是 Git 仓库。
- `step_7_gpu_execution` 在远程 GPU 实例执行 smoke test 后，必须再次通过 `ssh_execute` 验证共享项目 workspace 和 Git 仓库存在。
- `step_8_generate_report` 必须由 `repro_report` 返回真实 `report_path`，否则即使工具返回 `ok=true` 也不能标记为完成。
- 对于有固定 executor 的关键 step，模型 tool-use 只能提供辅助信息或提前发现错误，不能单独使 step 完成；固定 executor 和合约验收仍必须执行。

## 11. 下一步

1. 用真实 Lab4AI CPU/GPU 实例验证 P0/P1 适配：`claw_shell_run -> ssh_execute`、`sshpass` wrapper 编译、`remote_project_prep`、远程 SFTP 读写和 cleanup 都必须在真实环境中通过。
2. 继续按 [docs/skill-adapter-plan.md](skill-adapter-plan.md) 处理 P1 剩余 workflow：为 `lab4ai-auto-research` 和 `lab4ai-lf-data-preprocess` 增加专用 runner，复用已落地的安全 Tool 映射。
3. 收敛固定 executor fallback：只有当 fallback 仍执行同一条 skill 契约时才允许继续；否则返回结构化错误或 HITL，不再用语义不同的固定命令掩盖模板/适配器缺失。
4. 继续完善 `SkillRuntime`：扫描 `SKILL.md`、`tools.yaml`、`manifest.yaml`、`skill.json`，把 skill 入口注册为 `ToolRegistry` 中的真实 Tool，并提供启动健康检查。
5. 补齐 skill 入口与依赖：为 `lab4ai-paper-analysis` 增加 `analyze_paper_tool`，导入测试 `repo_audit / analyze_paper / run_remote_prep / generate_report`，并把 `requests / pyyaml / pymupdf / python-docx / paramiko 或 asyncssh` 写入后端运行依赖。
6. 完善真实 `ssh_execute`：从 `CloudInstance` 获取连接信息，使用后端 SSH 库执行命令，支持超时、日志流、退出码、SFTP、敏感信息脱敏和 `{{...}}` 未渲染模板兜底拦截。
7. 改造 Workflow step：`step_1_audit` 执行真实仓库分析与论文分析；`step_4_cpu_env_setup` 通过真实远程准备工具执行；`step_7_reproduce_on_gpu` 记录真实训练/推理日志；`step_8_generate_report` 生成真实报告 artifact。
8. 将 `file_write` 从保守模拟升级为受控 workspace 写入，支持本地任务 workspace 与当前任务绑定远程 workspace，不允许修改 `skills/`。
9. 增加外部网络配置：管理员可配置 GitHub、arXiv、Hugging Face 的代理或镜像；网络失败返回结构化错误并可触发 HITL。
10. 用真实 Lab4AI 凭证与线上环境联调 `lab4ai_create_instance / lab4ai_stop_instance / lab4ai_list_instances`，确认响应字段、错误码、计费实例释放和 `CloudInstance` 归属记录。
11. 增加自动化验收：skill entrypoint import 测试、Tool schema/权限测试、假 SSH server 集成测试，以及 PhotoDoodle dry-run，要求没有 `已模拟执行`、没有未渲染 `{{step_...}}`、没有固定 `score=75`。
12. 为长期记忆补齐用户级查看、删除、禁用 API 与前端入口。
13. 为 Tool 审计补齐管理员检索视图；如 `ConversationMessage.message_metadata` 不够用，再迁移到独立 `AuditLog`。
14. 为用户 LLM API Key 接入加密存储。
15. 完成管理员前端页面。
