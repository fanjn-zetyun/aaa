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
| LLM 调用 | 后端直接调用，用户配置 `base_url / api_key / model / max_tokens` |
| Tool 执行 | 后端 Tool 系统统一调度 |
| 任务编排 | 先 MVP 固定工具链，后续升级为模型驱动 tool-use 循环 |
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
    max_tokens: int
```

要求：

- 支持 `GET /api/llm-config` 和 `PUT /api/llm-config`。
- 支持 `POST /api/llm-config/test` 测试当前表单配置连通性。
- `api_key` 必须加密存储；当前 MVP 尚未完成真正加密，后续需要补齐。
- 模型需支持 tool use；不支持时可降级为固定工具链或纯对话模式。

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

MVP 当前允许用固定工具链模拟闭环：

1. 选择 skill / 任务类型。
2. 模拟或调用 `lab4ai_create_instance`。
3. 模拟或调用 `ssh_execute`。
4. 模拟或调用 `lab4ai_stop_instance`。
5. 调用模型生成总结。

后续目标是升级为真正由模型返回 `tool_use`，后端执行后继续循环。

### 5.4 Tool 系统

每个 Tool 是结构化对象：

```python
class Tool:
    name: str
    description: str
    input_schema: dict

    async def call(self, input: dict, context: ToolContext) -> ToolResult: ...
    def is_read_only(self) -> bool: ...
    def requires_confirmation(self) -> bool: ...
```

MVP Tool：

| Tool | 功能 |
|---|---|
| `lab4ai_create_instance` | 创建 Lab4AI 云实例并记录归属 |
| `lab4ai_stop_instance` | 停止 Lab4AI 云实例并记录结束时间 |
| `lab4ai_list_instances` | 查询当前用户可见云实例 |
| `ssh_execute` | 在远程实例执行命令 |
| `analyze_repo` | 分析 GitHub 仓库结构 |
| `read_url` | 读取网页、论文或文档内容 |
| `web_search` | 检索论文或资料 |
| `file_write` | 写入远程文件 |
| `ask_user` | 信息不足时向用户追问 |

所有会影响远程资源或产生费用的 Tool 必须：

- 校验用户权限和配额。
- 写入审计日志。
- 绑定 `conversation_id`。
- 失败时返回结构化错误，便于模型继续处理。

### 5.5 Skill 系统

保留 `skills/` 目录作为任务模板和工具组合定义，但不再要求兼容任何外部 CLI。

参考 `claude-code-analysis` 的 Skill 机制时，需要明确：**Skill 不是直接执行器**。Skill 的职责是声明领域流程、触发条件、上下文模板和允许使用的工具；真正创建实例、执行 SSH、写文件、检索资料等动作，必须通过后端 Tool 完成。

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
4. 把 skill 摘要注入 system prompt，用于模型选择。
5. 根据用户输入、前端 intent hint、`triggers` / `when_to_use` 选择 skill。
6. 将选中 skill 的正文、工作流文件摘要和 `allowed_tools` 注入 Agent Loop。
7. Agent Loop 驱动模型规划，模型通过 Tool 调用落地执行动作。

Skill 执行链路：

```text
用户消息
  -> SkillLoader 扫描并解析 skills/<name>/SKILL.md
  -> SkillSelector 选择合适 skill
  -> SkillContext 注入 system prompt
  -> LLM 根据 skill 流程产生计划或 tool_use
  -> ToolRegistry 执行具体 Tool
  -> tool_result 回流到 Conversation
  -> LLM 继续下一轮或总结完成
```

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

### 5.6 Lab4AI 云实例管理

Lab4AI 云实例是真正消耗费用的资源，必须由后端统一管理。

设计要点：

- 管理员配置统一 Lab4AI 账号。
- 创建实例时后端记录 `server_id / user_id / conversation_id / start_time / status`。
- 查询实例时按用户过滤；管理员可查看全部。
- 关停实例前校验归属。
- Agent Loop 异常、用户停止任务或后端重启恢复时，必须检查并清理遗留实例。

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
- 任务状态变化。
- Lab4AI 实例状态变化。
- 错误类型和错误消息。

事件必须持久化，断线重连后可以通过 conversation history 回看。

## 6. 数据模型

```text
User
├── id
├── username
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
├── max_tokens
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
├── name
├── status
├── gpu_type
├── start_time
├── stop_time
└── raw_payload
```

旧的 `ClawInstance` 命名属于历史遗留。后续迁移时应改为 `Conversation` 和 `CloudInstance`，旧接口只作为兼容层保留或删除。

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
- ChatPage：多轮对话、执行事件、停止按钮、结果回看。
- Sidebar：历史对话、配额展示、任务类型导航。
- RightPanel：当前对话详情、云实例、任务 metadata。
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
- 前端对话入口、历史记录、模型设置页。
- 配额查询和前端展示。
- SkillLoader 最小实现：扫描 `skills/*/SKILL.md`、解析 frontmatter、加载 `lab4ai-auto-reproduct/project_reproduce.yaml` 并注入 Agent Loop system prompt。
- MVP 模拟 Tool：创建实例、SSH 执行、停止实例。

当前限制：

- Lab4AI 创建 / 停止实例仍未接入真实 API。
- SSH 执行仍是模拟。
- Agent Loop 仍以固定工具链为主，尚未升级为完整 tool-use 循环。
- `api_key_encrypted` 字段尚未接入真实加密。
- `skills/` 目录已支持最小解析和注入，但仍需继续标准化元数据、`allowed_tools` 和任务类型映射。
- 旧 `claw-instances` 接口和相关命名仍有历史遗留，后续需要迁移或删除。

## 10. 下一步

1. 接入真实 Lab4AI API，完成实例创建、停止、查询和归属记录。
2. 实现真实 `ssh_execute`，支持凭证、超时、日志流和失败处理。
3. 将 Agent Loop 升级为模型驱动的 tool-use 循环。
4. 继续标准化 `skills/` 元数据、`allowed_tools` 和 prompt 模板。
5. 为用户 LLM API Key 接入加密存储。
6. 清理旧 `claw-instances` API、模型命名和测试。
7. 完成管理员前端页面。
