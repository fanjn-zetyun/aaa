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

MVP 当前允许用固定工具链推进闭环：

1. 选择 skill / 任务类型。
2. 调用 `lab4ai_create_instance` 创建真实 Lab4AI 实例。
3. 调用 `ssh_execute` 执行远程命令（当前 executor 仍待接入真实 SSH）。
4. 调用 `lab4ai_stop_instance` 释放真实 Lab4AI 实例。
5. 调用模型生成总结。

后续目标是升级为真正由模型返回 `tool_use`，后端执行后继续循环。

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

确认策略约定：

- `never`：只读或安全动作，不触发 HITL。
- `always`：创建算力实例等会产生费用或占用资源的动作，必须先确认。
- `risky`：如 SSH 命令，只有命中高风险模式时才确认。

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

### 5.5.1 Skill Workflow Runtime（已确认实施）

针对 `lab4ai-auto-reproduct` 这类强流程任务，不能只把 `SKILL.md` 和 `project_reproduce.yaml` 注入模型上下文后让模型自由发挥。后端需要把 workflow 文件解析为可追踪、可恢复、可展示的执行状态机。

用户在页面选择「论文与代码复现」并输入 GitHub URL、论文 URL 后，系统默认选择 `lab4ai-auto-reproduct`，加载同目录 `project_reproduce.yaml`，并按 YAML 中 `tasks` 数组逐步执行。

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
      "output": "score=75；已完成仓库与论文审计"
    }
  ],
  "workflow_resources": {
    "cpu": {"server_id": "xxx", "released": true},
    "gpu": {"server_id": "yyy", "released": false}
  },
  "workflow_results": {
    "repo_name": "PhotoDoodle",
    "score": 75,
    "audit_report_path": "",
    "word_report_path": ""
  }
}
```

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

短期实现中，workflow 的步骤状态、事件流、暂停恢复和资源兜底必须按真实执行链路落地。Lab4AI Tool 不再提供 Runner/mock 开关；缺少管理员凭证或平台 API 调用失败时直接失败并进入错误处理。SSH executor 仍需后续接入真实远程执行。

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
- `lab4ai_create_instance / lab4ai_stop_instance / lab4ai_list_instances` 直接调用真实 Lab4AI REST API，并写入或更新 `CloudInstance` 归属记录；若管理员未配置 Lab4AI 凭证或平台 API 返回失败，ToolRegistry 直接返回失败，不再通过 Runner/mock 分支绕过真实执行。

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
    "tool_input": {},
    "run_id": "当前 workflow_run_id"
  }
}
```

记忆更新原则：

- 新消息进入后，先追加原始消息，再更新结构化记忆。
- 重要事实、用户确认、远程实例 ID、报告路径必须写入 `memory`。
- Agent 请求模型时，使用“完整消息历史 + 最近窗口 + memory 摘要”三层上下文，而不是只依赖最近 12 条消息。
- 当对话过长时，后端把早期消息压缩为摘要写入 `memory.summary`，记录 `last_compacted_at / compacted_through_message_id / compaction_count`；完整原始消息仍保留在数据库和 JSONL 事件日志中。

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
3. WebSocket 推送 `ask_user` 事件，前端展示问题和可选操作。
4. 输入框保持可用，用户直接回复文字或点击快捷按钮。
5. 用户回复后，`POST /api/conversations/{id}/messages` 继续推进流程。
6. 后端读取原始消息历史与 `memory`，从上次暂停点继续执行。

实现约束：

- `ask_user` 不应只是普通文本，它必须能暂停流程。
- 被确认过的决策要写进 `memory.decisions`，但审批只对当前 `workflow_run_id` 生效，避免新一轮对话误用旧确认。
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

当前限制：

- Lab4AI 创建 / 停止 / 查询已走真实 API 代码路径，仍需要真实凭证与线上环境联调；缺少凭证时会失败，不再自动模拟计费实例。
- SSH 执行仍是模拟。
- Agent Loop 仍以固定工具链为主，尚未升级为完整 tool-use 循环。
- `api_key_encrypted` 字段尚未接入真实加密。
- `skills/` 目录已支持最小解析和注入，但仍需继续标准化元数据、`allowed_tools` 和任务类型映射。
- `Skill Workflow Runtime` 仍是首版状态机：step executor 目前按已知 9 步映射到后端 Tool，后续需要把更多 step 内部逻辑替换为真实 SSH、文件写入、报告生成和更细粒度进度。
- memory 仍是基于 `Conversation.metadata` 的轻量结构化实现，尚未接入向量检索或跨对话长期记忆。
- HITL 已接入统一 Tool 确认管线，但还不是完整权限系统，后续需要覆盖真实 Lab4AI、真实 SSH、文件写入等更多动作。
- `skills/` 原始模板仍包含历史 `claw-workflow` / `openclaw` / `claw-shell` 命名。根据当前协作约束，暂不直接修改 `skills/` 目录；若后续需要标准化模板，需要先确认迁移方案并同步更新 workflow 文档。

## 10. 下一步

1. 用真实 Lab4AI 凭证与线上环境联调 `lab4ai_create_instance / lab4ai_stop_instance / lab4ai_list_instances`，确认响应字段、错误码、计费实例释放和 `CloudInstance` 归属记录。
2. 实现真实 `ssh_execute`，支持凭证、超时、日志流和失败处理。
3. 将 Agent Loop 升级为模型驱动的 tool-use 循环。
4. 深化 `Skill Workflow Runtime`：把 step 内部的 SSH、文件写入、报告生成和更细粒度 `workflow_step_progress` 接到真实 executor。
5. 把 HITL 权限系统扩展到真实 Lab4AI、真实 SSH、文件写入等高风险 Tool，并补齐审计记录。
6. 为对话 memory 增加跨对话长期记忆和检索策略。
7. 为用户 LLM API Key 接入加密存储。
8. 完成管理员前端页面。
