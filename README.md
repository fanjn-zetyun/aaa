# OpenClaw 多实例管理平台

多用户共享 Lab4AI 算力资源的 Web 应用，通过 OpenClaw Agent 自动化完成论文/项目复现任务。

## 它能做什么

- 用户提交 GitHub URL，系统自动启动 OpenClaw Agent 进行项目复现
- Agent 自动分析仓库、选择合适的 skill pipeline、创建远程 GPU/CPU 实例、执行实验
- Web 页面实时查看 Agent 运行日志（WebSocket 流式推送）
- 管理员统一管理 Lab4AI 账号、分配算力配额、监控所有实例
- 异常保护：Agent 崩溃后自动清理遗留的云实例，防止空转烧钱

## 技术栈

| 层 | 技术 |
|---|---|
| 后端 | Python 3.13 + FastAPI + SQLAlchemy 2.0 (async) |
| 前端 | React + TypeScript + Vite |
| 数据库 | SQLite（开发）/ PostgreSQL（生产） |
| Agent | OpenClaw CLI（Node.js） |
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
│   └── openclaw-setup.md  # OpenClaw 安装与对接指南
├── skills/                # OpenClaw skills（lab4ai-* 系列）
├── backend/               # FastAPI 后端
│   ├── app/
│   │   ├── api/           # 路由（auth、实例管理、WebSocket、管理员）
│   │   ├── core/          # 配置、数据库、安全
│   │   ├── models/        # ORM 模型
│   │   ├── schemas/       # Pydantic schema
│   │   └── services/      # 业务逻辑（OpenclawRunner、Lab4AI 代理）
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

1. **OpenClaw Agent 进程**（本地）— 编排 skills 工作流，通过 LLM 分析任务并自动选择执行路径
2. **Lab4AI 云实例**（远程）— 实际跑代码的 GPU/CPU 机器，由 Agent 通过 API 创建和释放

**Skills 全量加载：** 用户无需手动选择 skills，Agent 启动后自动分析仓库内容并决定使用哪些 skill。

## 开发状态

当前处于 MVP 开发阶段，OpenClaw 集成使用 mock 实现（模拟日志输出），后续接入真实 OpenClaw CLI。

详细设计方案和待办事项见 [docs/proposal.md](docs/proposal.md)。

## License

Private
