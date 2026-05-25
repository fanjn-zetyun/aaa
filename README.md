# AutoResearch24 科研助手平台

多用户共享 Lab4AI 算力资源的 Web 应用，通过自建 Agent Loop 自动化完成论文/项目复现任务。

## 它能做什么

- 用户提交 GitHub URL，系统自动启动 Agent Loop 进行项目复现
- Agent 自动分析仓库、选择合适的 skill、创建远程 GPU/CPU 实例、执行实验
- Web 页面实时查看执行日志（WebSocket 流式推送）
- 管理员统一管理 Lab4AI 账号、分配算力配额、监控所有实例
- 异常保护：Agent 崩溃后自动清理遗留的云实例，防止空转烧钱

## 技术栈

| 层 | 技术 |
|---|---|
| 后端 | Python 3.13 + FastAPI + SQLAlchemy 2.0 (async) |
| 前端 | React + TypeScript + Vite |
| 数据库 | SQLite（开发）/ PostgreSQL（生产） |
| Agent | 后端自建 Agent Loop |
| 算力平台 | Lab4AI（GPU/CPU 云实例） |

## 快速开始

### 环境要求

- Python 3.13+
- Node.js 22.19+ 或 24
- [uv](https://docs.astral.sh/uv/)（Python 包管理）

### 后端

```bash
# 安装依赖
uv sync

# 复制配置文件并按需修改
cp backend/.env.example backend/.env

# 启动（首次启动会自动建表 + 创建默认 admin 账号）
uv run uvicorn app.main:app --reload --app-dir backend
```

默认管理员：`admin` / `admin123`

### 前端

```bash
cd frontend
npm install
npm run dev
```

访问 http://localhost:5173，前端已配置 API 代理到后端 8000 端口。

## 目录结构

```
├── CLAUDE.md              # Claude Code 协作指引
├── docs/
│   ├── proposal.md        # 完整设计方案（架构、API、数据模型）
│   └── agent-loop-setup.md # Agent Loop 配置指南
├── skills/                # Skills 任务模板
├── backend/               # FastAPI 后端
│   ├── app/
│   │   ├── api/           # 路由（auth、实例管理、WebSocket、管理员）
│   │   ├── core/          # 配置、数据库、安全
│   │   ├── models/        # ORM 模型
│   │   ├── schemas/       # Pydantic schema
│   │   └── services/      # 业务逻辑（Agent Loop、Tool、Lab4AI 代理）
│   └── tests/
├── frontend/              # React + Vite
│   └── src/
│       ├── pages/         # 页面组件
│       ├── components/    # 通用组件
│       └── lib/           # API 客户端等工具
└── runtime/               # 运行时数据（gitignore，自动生成）
    ├── workspaces/        # 每任务独立 workspace
    └── app.db             # SQLite 开发数据库
```

## 核心概念

**两层实例模型：**

1. **Agent Loop**（后端）— 编排 skills、Tool 和模型调用，通过 LLM 分析任务并自动选择执行路径
2. **Lab4AI 云实例**（远程）— 实际跑代码的 GPU/CPU 机器，由后端通过 API 创建和释放

**Skills 全量加载：** 用户无需手动选择 skills，Agent 启动后自动分析仓库内容并决定使用哪些 skill。

**参考实现边界：** [claude-code-analysis/](claude-code-analysis/) 只作为 Agent Loop、Tool、Skill、Memory 机制的架构参考，不作为直接底座。AutoResearch24 仍以 FastAPI 后端和 React Web UI 为主。

## 当前开发状态

当前 V2 MVP 已跑通：后端已支持 `conversations` 对话式任务、真实模型配置与 Anthropic-compatible 模型调用，前端已支持对话页、历史记录、模型设置页和 WebSocket 流式事件。Skill Loader 最小闭环已接入，复现任务会加载 `lab4ai-auto-reproduct` 及其 `project_reproduce.yaml` 并注入 Agent Loop。每个对话已具备轻量结构化 memory，复现任务会在创建资源前进入 human-in-the-loop 确认，用户回复后继续执行。

目前 Lab4AI 实例创建、查询和释放已改为直接走真实 API；缺少管理员凭证时会进入 human-in-the-loop 管理员配置弹窗，不再通过 mock Runner 模拟计费实例。SSH、文件写入、仓库/论文分析和报告生成已接入后端真实 executor；缺少实例、依赖、网络或远程命令失败时返回结构化错误，不伪造成功。详细进度见 [docs/progress.md](docs/progress.md)，完整设计方案见 [docs/proposal.md](docs/proposal.md)。

## 当前实现补充（2026-05-19）

- 后端 Tool 层已从硬编码方法升级为声明式 `ToolRegistry`，每个 Tool 统一声明 `description / input_schema / confirmation_policy / executor`。
- HITL 现在由 Tool 确认策略统一触发：创建 Lab4AI 算力实例必须确认，高风险 SSH 命令按策略确认，用户回复会被分类为 `approved / needs_revision / rejected / stopped`。
- 每轮 Agent 执行都有 `workflow_run_id`，用户确认只对当前运行生效，避免后续新一轮对话误用旧确认。
- 对话 memory 已支持摘要压缩，长历史会汇总进 `memory.summary`，完整原始消息仍保留在数据库和 JSONL 事件日志中。
- 当前验证通过：`uv run pytest` 46 个后端用例、`uv run python backend/tests/smoke_v2.py`、`uv run ruff check backend/app`、前端 12 个 Vitest 用例和 `npm run build`。

## License

Private
