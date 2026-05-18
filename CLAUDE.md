# CLAUDE.md

本文件是 Claude Code 协作时的项目指引。请在每次会话开始时阅读此文件以了解项目背景、协作规则和当前状态。

---

## 1. 项目概述

本项目是一个 **OpenClaw 多实例管理 Web 应用**，目标是让多用户通过浏览器使用同一个 Lab4AI 账号的算力资源，各自管理自己的 OpenClaw Agent 实例，完成自动化科研任务（以论文/项目复现为主）。

完整的需求和设计方案见：[docs/proposal.md](docs/proposal.md)

### 核心定位

- **OpenClaw**：本地运行的 LLM Agent CLI（Node.js 项目，`npm install -g openclaw@latest`），是系统的智能核心
- **Web 应用**：管理壳，不调用大模型，只做进程管理、状态记录、日志转发
- **Lab4AI 平台**：远程算力资源（GPU/CPU 云实例），由 openclaw 通过 skills 调用 REST API 管理

### OpenClaw 集成要点

- 启动命令：`openclaw agent --message "<用户输入>"`（一次性运行 Agent 完成任务后退出，契合 subprocess 方案）
- Skills 默认路径：`~/.openclaw/workspace/skills/<skill>/SKILL.md`
- **按任务隔离 workspace**：每个任务在 `runtime/workspaces/<task_id>/` 下创建独立 workspace（软链 `skills/` + 注入 `.env`），通过 `OPENCLAW_WORKSPACE` 或 `--workspace` 指定
- 后端通过 **`OpenclawRunner` 抽象接口**调用，提供 mock 和真实两种实现（开发阶段先用 mock）

### 两层实例模型（重要）

理解这一点是项目架构的关键：

1. **第一层：openclaw Agent 进程**（本地，子进程方式启动）
   - 编排 skills 工作流
   - 通过 LLM 分析任务、自动选择合适的 skill
   - 通过 SSH 连接远程 Lab4AI 实例执行代码

2. **第二层：Lab4AI 云实例**（远程，按时计费）
   - 由 openclaw 通过 `lab4ai-instance-manage` skill 创建/释放
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
│   └── openclaw-setup.md  # OpenClaw 安装与配置指南
├── skills/                # OpenClaw skills 集合（lab4ai-* 系列，软链到 workspace）
│   └── ...
├── backend/               # FastAPI 后端
│   ├── app/
│   │   ├── api/           # 路由
│   │   ├── core/          # 配置、安全、数据库
│   │   ├── models/        # SQLAlchemy 模型
│   │   ├── schemas/       # Pydantic schema
│   │   ├── services/      # 业务逻辑
│   │   │   ├── openclaw/  # OpenclawRunner（mock + real 实现）
│   │   │   └── lab4ai/    # Lab4AI API 代理与归属管理
│   │   └── main.py
│   └── tests/
├── frontend/              # React + Vite + TypeScript
│   ├── src/
│   └── package.json
├── runtime/               # 运行时数据（gitignore）
│   ├── workspaces/        # 每任务一个 workspace：runtime/workspaces/<task_id>/
│   ├── logs/              # openclaw 进程日志归档
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
- OpenClaw 模式：`OPENCLAW_RUNNER=mock`（开发阶段）
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

---

## 6. 当前进度

- [x] 需求梳理与架构设计（见 [docs/proposal.md](docs/proposal.md)）
- [x] 关键决策已确认：
  - 不使用 Docker，用 subprocess 管理 openclaw 进程
  - 多用户共享一个 Lab4AI 账号，后端记录云实例归属关系
  - Web 后端不调用大模型，所有智能能力在 openclaw 内部
  - Skills 全量加载，由 Agent 自行选择
  - 用户输入：GitHub URL（必填）+ 论文 URL（可选）+ 自然语言指令（可选）
  - OpenClaw 集成：先 mock 后真实，按任务隔离 workspace
  - 前端工具链：Vite + React + TypeScript
  - Lab4AI 凭证：通过管理员后台页面配置
  - 前端交互模式：对话式 AI 科研助手（产品名 LOBSTER），非传统管理后台
- [x] 项目目录结构初始化（backend/、frontend/、runtime/）
- [x] OpenClaw 安装配置指南（docs/openclaw-setup.md）
- [x] OpenclawRunner 接口定义 + mock 实现
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
- [x] 后端单元测试（pytest，35 个用例全部通过）
  - auth 模块：注册/登录/me/参数校验/重复用户名/禁用账号
  - claw-instances 模块：创建/列表/查询/停止/用户隔离/配额查询
  - services 层：workspace 创建/环境变量写入/OpenclawManager 生命周期
- [x] 前端单元测试（Vitest + React Testing Library，12 个用例全部通过）
  - LoginPage：登录/注册切换、错误提示
  - WelcomePage：表单提交、URL 校验、路由导航
  - API 层：token 管理
- [x] 冒烟测试验证通过（注册→登录→创建任务→mock 执行完成→状态 completed）
- [ ] 管理员前端页面（用户管理、云实例总览、平台设置、用量报表）
- [ ] RealOpenclawRunner 实现（真实 openclaw CLI 调用）
- [ ] 前端 build 产物部署配置

---

## 7. 关键文件索引

| 文件 | 用途 |
|------|------|
| [docs/proposal.md](docs/proposal.md) | 完整设计方案（架构、API、数据模型、MVP 范围） |
| [docs/openclaw-setup.md](docs/openclaw-setup.md) | OpenClaw 安装与配置指南 |
| [skills/lab4ai-auto-reproduct/SKILL.md](skills/lab4ai-auto-reproduct/SKILL.md) | 项目复现主流程定义 |
| [skills/lab4ai-instance-manage/SKILL.md](skills/lab4ai-instance-manage/SKILL.md) | Lab4AI 云实例 API 调用规范 |
| [skills/lab4ai-instance-list/SKILL.md](skills/lab4ai-instance-list/SKILL.md) | Lab4AI 云实例列表查询 |
| [pyproject.toml](pyproject.toml) | Python 项目依赖配置 |
