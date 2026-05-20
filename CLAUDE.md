# CLAUDE.md

本文件是 Claude Code 协作时的项目指引。请在每次会话开始时阅读此文件以了解项目背景、协作规则和当前状态。

---

## 1. 项目概述

本项目是一个 **LOBSTER 自建 Agent Loop 科研助手 Web 应用**，目标是让多用户通过浏览器使用同一个 Lab4AI 账号的算力资源，各自管理自己的对话式科研任务，完成自动化科研工作流（以论文/项目复现为主）。

完整的需求和设计方案见：[docs/proposal.md](docs/proposal.md)

当前开发进度见：[docs/progress.md](docs/progress.md)

### 核心定位

- **Agent Loop**：后端自建的智能核心，直接调用用户配置的模型并调度 Tool
- **Web 应用**：对话壳和任务编排入口，负责状态记录、日志转发和历史回看
- **Lab4AI 平台**：远程算力资源（GPU/CPU 云实例），由后端 Tool 调用 REST API 管理
- **claude-code-analysis 参考边界**：仅借鉴其中 Agent Loop、Tool、Skill、Memory 的设计，不直接复用其 CLI/TUI、bridge、sandbox 和本地代码 Agent 运行时。

### 两层实例模型（重要）

理解这一点是项目架构的关键：

1. **第一层：Agent Loop**（后端，直接运行）
   - 组装 system prompt、对话历史和技能上下文
   - 调用用户配置的 LLM
   - 通过 Tool 系统执行创建实例、SSH、分析仓库等动作

2. **第二层：Lab4AI 云实例**（远程，按时计费）
   - 由后端 Tool 创建/释放
   - 多用户共享同一个 Lab4AI 账号，需要后端记录归属关系实现逻辑隔离
   - 异常退出时需自动清理，防止空转烧钱

---

## 2. 技术栈

| 层 | 技术 |
|---|---|
| 后端 | Python 3.13 + FastAPI（包管理用 uv） |
| 前端 | React + TypeScript |
| 数据库 | SQLite（开发）→ PostgreSQL（生产） |
| 进程管理 | subprocess + asyncio（不使用 Docker） |
| 实时日志 | WebSocket + xterm.js |
| 认证 | JWT |

---

## 3. 目录结构

```
aaa/
├── CLAUDE.md              # 本文件
├── README.md
├── pyproject.toml         # Python 项目配置（uv）
├── uv.toml                # uv 配置
├── uv.lock
├── docs/
│   ├── proposal.md        # 完整设计方案（需求、架构、API、数据模型）
│   └── agent-loop-setup.md # Agent Loop 配置指南
├── skills/                # Skills 任务模板集合
│   └── ...
├── backend/               # FastAPI 后端
│   ├── app/
│   │   ├── api/           # 路由
│   │   ├── core/          # 配置、安全、数据库
│   │   ├── models/        # SQLAlchemy 模型
│   │   ├── schemas/       # Pydantic schema
│   │   ├── services/      # 业务逻辑
│   │   │   ├── agent_loop/ # Agent Loop 核心实现
│   │   │   └── lab4ai/    # Lab4AI API 代理与归属管理
│   │   └── main.py
│   └── tests/
├── frontend/              # React + Vite + TypeScript
│   ├── src/
│   └── package.json
├── runtime/               # 运行时数据（gitignore）
│   ├── workspaces/        # 每任务一个 workspace：runtime/workspaces/<task_id>/
│   ├── logs/              # Agent Loop 与 Tool 日志归档
│   └── app.db             # SQLite 开发数据库
└── main.py
```

---

## 4. 开发命令与环境

### 后端

```bash
# 安装依赖
uv sync

# 启动开发服务器（自动 reload）
uv run uvicorn app.main:app --reload --app-dir backend --host 127.0.0.1 --port 8000

# 冒烟测试（端到端：注册→登录→创建任务→等 mock 完成）
uv run python backend/tests/smoke.py

# 运行测试
uv run pytest

# 代码格式化 + lint
uv run ruff check backend/ --fix
uv run ruff format backend/
```

### 前端

```bash
cd frontend
npm install
npm run dev    # Vite dev server → http://localhost:5173
```

### 环境配置

- 后端配置文件：`backend/.env`（从 `backend/.env.example` 复制）
- 默认管理员：admin / admin123（首次启动自动创建）
- 数据库：SQLite 存储在 `runtime/app.db`（自动创建）

---

## 5. Claude 协作规则（重要）

以下规则是和我协作的硬性要求，请严格遵守：

### 5.1 必须提问确认

- 遇到任何不明确的需求或设计点，**必须使用提问的方式向我确认**，禁止自行猜测意图
- 优先使用 `AskUserQuestion` 工具发起多选题，让我快速回答
- 即使你认为答案很显然，也要确认一次再行动
- 一次最多问 4 个问题，问题之间互相独立

### 5.2 中文交流

- 所有面向我的对话、文档、注释默认使用简体中文
- 命令、代码标识符、日志原文按原样保留
- proposal.md 等设计文档用中文撰写

### 5.3 先设计后编码

- 重要的需求或架构决策，先在 [docs/proposal.md](docs/proposal.md) 中写清方案，确认后再写代码
- 不要跳过设计阶段直接动手实现
- 涉及多个模块的改动前，先讨论思路

### 5.4 同步更新 proposal

- 当需求或架构发生变化时（包括我口头确认的新决策），**必须同步更新 [docs/proposal.md](docs/proposal.md)**
- proposal 是项目的单一真源（single source of truth），不应与实际实现脱节
- 如果发现 proposal 与代码现状不一致，主动指出并询问是修代码还是改文档

### 5.5 不要猜测我的知识背景

- 我不了解多实例管理和系统架构设计的相关知识
- 涉及技术决策时，先解释清楚选项的利弊，再让我决定，不要直接推进
- 如果我说「不确定，帮我分析」，给出明确的推荐意见和理由

### 5.6 通用编码行为准则

以下准则来自 [AKclaude.md](AKclaude.md)，用于减少 LLM 协作编码中的常见错误。它们默认与本项目规则合并使用；如果和项目特定规则存在冲突，以本文件前文的项目规则为准。

**权衡取向：** 这些准则更偏向谨慎而不是速度。对于非常简单的任务，可以结合实际情况判断。

#### 5.6.1 编码前先思考

**不要假设，不要隐藏困惑，主动暴露取舍。**

实现前需要做到：

- 明确说出你的假设。如果不确定，就提问。
- 如果存在多种理解方式，要把它们列出来，不要悄悄选择其中一种。
- 如果存在更简单的方案，要说明。必要时可以提出反对意见。
- 如果有不清楚的地方，先停下来，说明哪里不清楚，再提问。

#### 5.6.2 简洁优先

**用能解决问题的最少代码，不做 speculative work。**

- 不添加需求之外的功能。
- 不为只使用一次的代码抽象。
- 不添加未被要求的“灵活性”或“可配置性”。
- 不为不可能发生的场景添加错误处理。
- 如果写了 200 行但本来可以 50 行解决，就重写并简化。

自检问题：如果一位资深工程师会认为这段实现过度复杂，那就应该简化。

#### 5.6.3 外科手术式修改

**只改必须改的地方，只清理自己造成的问题。**

编辑已有代码时：

- 不要顺手“优化”相邻代码、注释或格式。
- 不要重构没有坏掉的东西。
- 匹配已有代码风格，即使你个人会用另一种写法。
- 如果发现无关的死代码，可以提出来，但不要直接删除。

当你的改动产生了孤立代码时：

- 删除由你的改动导致的未使用 import、变量或函数。
- 不要删除原本就存在的死代码，除非用户明确要求。

判断标准：每一行改动都应该能直接追溯到用户请求。

#### 5.6.4 目标驱动执行

**定义成功标准，循环推进直到验证通过。**

把任务转化为可验证的目标：

- “添加校验” → “为无效输入写测试，再让测试通过”
- “修复 bug” → “先写出能复现 bug 的测试，再让测试通过”
- “重构 X” → “确保重构前后测试都通过”

对于多步骤任务，先给出简短计划：

```text
1. [步骤] → 验证：[检查项]
2. [步骤] → 验证：[检查项]
3. [步骤] → 验证：[检查项]
```

清晰的成功标准可以让你独立循环推进；模糊标准（例如“让它能用”）则需要持续向用户确认。

**这些准则生效的表现是：** diff 中不必要的改动更少，因过度复杂导致的返工更少，澄清问题发生在实现之前，而不是出错之后。

---

## 6. 当前进度

- [x] 需求梳理与架构设计（见 [docs/proposal.md](docs/proposal.md)）
- [x] 关键决策已确认：
  - 不使用 Docker，后端直接运行 Agent Loop
  - 多用户共享一个 Lab4AI 账号，后端记录云实例归属关系
  - Web 后端直接调用大模型，所有智能能力在后端 Agent Loop 内部
  - Skills 由后端加载并注入 system prompt
  - 用户输入：GitHub URL（必填）+ 论文 URL（可选）+ 自然语言指令（可选）
  - Agent Loop：先 MVP 固定工具链，后续升级为完整 tool-use 循环
  - 前端工具链：Vite + React + TypeScript
  - Lab4AI 凭证：通过管理员后台页面配置
  - 前端交互模式：对话式 AI 科研助手（产品名 LOBSTER），非传统管理后台
- [x] 项目目录结构初始化（backend/、frontend/、runtime/）
- [x] FastAPI 后端骨架（配置、数据库、依赖注入）
- [x] 用户认证模块（注册/登录/JWT）
- [x] 实例与云实例 API + 数据模型
- [x] WebSocket 实时日志流
- [x] Lab4AI 代理层 + 管理员 API
- [x] React + Vite 前端骨架（AppLayout + Sidebar + 路由）
- [x] 前端核心页面：登录、复现任务输入（WelcomePage）、任务对话（ChatPage）、右侧面板
- [x] 前端其他任务类型页面（search / paper-only / experiments / polish）独立路由 + basePath 导航
- [x] 算力限额后端接口（GET /api/claw-instances/quota）+ 创建任务时配额校验
- [x] 算力限额前端展示（Sidebar 配额进度条）+ 超额拦截
- [x] SkillLoader 最小闭环：扫描 `skills/*/SKILL.md`、解析 frontmatter、为 `lab4ai-auto-reproduct` 加载 `project_reproduce.yaml`，并注入 Agent Loop system prompt
- [x] 对话 memory + HITL 闭环：结构化 memory 存入 `Conversation.metadata`，ToolRegistry 统一声明确认策略，reproduce 任务在创建资源前暂停等待用户确认，用户回复后按 approved / needs_revision / stopped 分类处理，并支持长对话摘要压缩
- [x] 后端单元测试（pytest，46 个用例全部通过）
  - auth 模块：注册/登录/me/参数校验/重复用户名/禁用账号
  - cloud-instances 模块：创建/列表/查询/停止/用户隔离/配额查询
  - services 层：Conversation / Agent Loop / Tool / Skill / Memory 生命周期
- [x] 前端单元测试（Vitest + React Testing Library，12 个用例全部通过）
  - LoginPage：登录/注册切换、错误提示
  - WelcomePage：表单提交、URL 校验、路由导航
  - API 层：token 管理
- [x] 冒烟测试验证通过（注册→登录→创建任务→HITL 等待确认→用户回复→mock 执行完成→状态 completed）
- [x] 前端 build 验证通过（`npm run build`）
- [ ] 管理员前端页面（用户管理、云实例总览、平台设置、用量报表）
- [ ] 前端 build 产物部署配置

---

## 7. 关键文件索引

| 文件 | 用途 |
|------|------|
| [docs/proposal.md](docs/proposal.md) | 完整设计方案（架构、API、数据模型、MVP 范围） |
| [docs/agent-loop-setup.md](docs/agent-loop-setup.md) | Agent Loop 配置指南 |
| [skills/lab4ai-auto-reproduct/SKILL.md](skills/lab4ai-auto-reproduct/SKILL.md) | 项目复现主流程定义 |
| [skills/lab4ai-instance-manage/SKILL.md](skills/lab4ai-instance-manage/SKILL.md) | Lab4AI 云实例 API 调用规范 |
| [skills/lab4ai-instance-list/SKILL.md](skills/lab4ai-instance-list/SKILL.md) | Lab4AI 云实例列表查询 |
| [pyproject.toml](pyproject.toml) | Python 项目依赖配置 |
