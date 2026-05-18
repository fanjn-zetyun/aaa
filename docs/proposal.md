# OpenClaw 多实例管理 Web 应用 — 设计提案

## 1. 项目概述

构建一个 Web 应用，让多用户通过浏览器使用同一个 Lab4AI 账号的算力资源，各自管理自己的 OpenClaw Agent 实例，完成自动化科研任务（以论文/项目复现为主）。

系统核心能力：
- 在 Web 页面上配置和加载 skills
- 启动 openclaw 实例执行任务
- 管理两层实例：本地 openclaw Agent 进程 + 远程 Lab4AI 云实例（GPU/CPU）
- 实时查看运行日志
- 按用户隔离资源视图，限制算力使用额度

## 2. 需求确认摘要

| 维度 | 决策 |
|------|------|
| OpenClaw 形态 | CLI Agent 进程（类似 Claude Code），本地运行 |
| 多实例原因 | 多用户各自管理自己的实例 |
| 用户体系 | 多角色：普通用户 + 管理员 |
| 主要任务类型 | 论文/项目复现（lab4ai-auto-reproduct） |
| 实例启动方式 | 子进程（subprocess），不使用 Docker |
| Lab4AI 凭证 | 平台统一一个账号，所有用户共享算力池 |
| 算力限额 | 按用户累计使用时长限制 |
| 云实例归属 | 后端记录 serverId → 用户映射，按用户过滤展示 |
| 后端技术栈 | Python（FastAPI） |
| 前端技术栈 | React |
| 日志体验 | 实时流式输出（WebSocket） |
| 部署环境 | 先本地开发，后续再考虑远程部署 |
| 大模型使用 | 仅在 openclaw 内部，Web 后端不调用大模型 |
| Skills 加载 | 全量加载，由 openclaw Agent 自行决定使用哪些 |
| 用户输入 | GitHub URL（必填）+ 论文 URL（可选）+ 自然语言指令（可选） |
| 开发策略 | 先完成设计方案，再确定实现范围 |

## 3. 两层实例模型

本系统管理两层实例，理解它们的关系是架构设计的关键：

```
┌─────────────────────────────────────────────────────────────┐
│ 第一层：OpenClaw Agent 进程（本地）                           │
│                                                             │
│ - Web 后端通过 subprocess 启动                               │
│ - 负责编排 skills 工作流（读 pipeline.yml、执行各 step）       │
│ - 通过 lab4ai-instance-manage skill 调用 Lab4AI API          │
│ - 通过 SSH 连接远程实例执行代码                               │
│ - 占用资源少，主要是编排和协调角色                             │
└──────────────────────────────┬──────────────────────────────┘
                               │ 调用 Lab4AI REST API
                               │ SSH 连接
┌──────────────────────────────▼──────────────────────────────┐
│ 第二层：Lab4AI 云实例（远程，花钱的）                          │
│                                                             │
│ - GPU/CPU 云服务器，按时计费                                  │
│ - 由 openclaw 通过 lab4ai-instance-manage/create.py 创建     │
│ - 由 openclaw 通过 lab4ai-instance-manage/stop.py 释放       │
│ - 实际跑训练代码、下载数据、执行实验的地方                     │
│ - 风险点：openclaw 异常退出后可能遗留未释放的云实例             │
└─────────────────────────────────────────────────────────────┘
```

### 为什么不用 Docker

| 考虑因素 | 结论 |
|----------|------|
| 真正需要隔离的资源 | Lab4AI 云实例（通过后端记录归属关系实现逻辑隔离） |
| 本地 openclaw 进程 | 轻量编排器，子进程管理足够 |
| 开发复杂度 | 子进程方案显著更简单，加快第一版交付 |
| 后续扩展 | 如需物理隔离可后续引入 Docker，架构预留接口 |

## 4. 系统架构

```
┌─────────────────────────────────────────────────────────────┐
│                      浏览器 (React)                           │
│  ┌────────┐ ┌──────────────┐ ┌────────────┐ ┌───────────┐  │
│  │用户登录 │ │openclaw 实例 │ │Lab4AI 云实例│ │实时日志(WS)│  │
│  └────────┘ └──────────────┘ └────────────┘ └───────────┘  │
└────────────────────────┬────────────────────────────────────┘
                         │ HTTP / WebSocket
┌────────────────────────▼────────────────────────────────────┐
│                  Web 后端 (FastAPI)                           │
│                                                              │
│  ┌──────────────┐  ┌───────────────────┐  ┌─────────────┐   │
│  │ 用户认证(JWT) │  │ openclaw 进程管理  │  │ 日志流转发   │   │
│  └──────────────┘  └────────┬──────────┘  │ (WebSocket)  │   │
│                             │              └─────────────┘   │
│  ┌──────────────┐  ┌───────▼───────────┐                    │
│  │ 算力限额管理  │  │ Lab4AI 云实例代理  │                    │
│  │ (时长配额)   │  │ (归属记录+过滤)   │                    │
│  └──────────────┘  └───────────────────┘                    │
│                                                              │
│  ┌───────────────────────────────────────────────────────┐   │
│  │              数据持久层 (SQLite → PostgreSQL)           │   │
│  │  用户表 / openclaw实例 / 云实例归属 / 用量记录 / skills │   │
│  └───────────────────────────────────────────────────────┘   │
└──────────────────────────────────────────────────────────────┘
         │                                    │
         │ subprocess                         │ REST API (代理)
         ▼                                    ▼
┌─────────────────────┐           ┌─────────────────────────┐
│ openclaw CLI Agent  │ × N       │     Lab4AI 云平台        │
│ (子进程)            │──SSH──→   │  GPU/CPU 实例 (统一账号)  │
│ + skills 目录       │           │                         │
│ + Lab4AI 凭证       │           │  instance-list API      │
└─────────────────────┘           │  instance-create API    │
                                  │  instance-stop API      │
                                  └─────────────────────────┘
```

## 5. 核心模块设计

### 5.1 用户认证模块

- 注册/登录（JWT Token）
- 角色：`user`（普通用户）、`admin`（管理员）
- 普通用户：只能看到和管理自己的 openclaw 实例和云实例
- 管理员：查看所有用户的实例、管理用户账号、配置平台设置

### 5.2 大模型能力定位

大模型（LLM）在本系统中的位置：

| 层级 | 是否使用大模型 | 说明 |
|------|--------------|------|
| Web 前端 | 否 | 纯 UI 展示和交互 |
| Web 后端 | 否 | 只做进程管理、状态记录、日志转发，不需要理解任务内容 |
| OpenClaw Agent | **是** | 核心智能层，负责分析仓库、选择 skills、编排执行、与用户交互 |

Web 后端是一个「无脑管理壳」——它不关心任务内容是什么，只负责：
- 启动/停止 openclaw 进程
- 记录实例状态和云实例归属
- 转发日志流
- 管理用户和算力配额

所有「智能」决策（分析 README、判断用哪些 skills、决定执行步骤）都由 openclaw 内部的大模型完成。

### 5.3 Skills 加载与自动选择

**加载方式：** 启动 openclaw 时将整个 `skills/` 目录全量加载（通过 OPENCLAW_SKILLS 环境变量或参数指定路径）。

**自动选择逻辑（由 openclaw 内部完成）：**
1. openclaw 启动后拿到用户输入（GitHub URL + 可选论文 URL + 可选指令）
2. 分析仓库内容（README、代码结构、依赖文件）
3. 根据 skills 的 SKILL.md 中的 `triggers` 和 `description` 自动匹配合适的 skill
4. 按对应 skill 的 pipeline 执行任务

**用户无需手动选择 skills，整个过程完全自动。**

### 5.4 任务提交（用户输入）

用户在 Web 上发起任务时只需填写：

| 字段 | 必填 | 说明 |
|------|------|------|
| GitHub URL | 是 | 要复现的项目地址 |
| 论文 URL/PDF | 否 | 对应论文，帮助 Agent 理解实验细节 |
| 自然语言指令 | 否 | 额外指示，如「只复现 Table 1 的结果」「用 A100 跑」 |

### 5.5 OpenClaw 进程管理（第一层）

| 操作 | 实现方式 |
|------|----------|
| 创建 | `subprocess.Popen` 启动 openclaw CLI，传入 skills 和任务参数 |
| 监控 | 后端持有进程句柄，轮询 `poll()` 检测状态 |
| 日志 | 捕获 stdout/stderr pipe，异步读取 |
| 停止 | 发送 SIGTERM，超时后 SIGKILL |
| 清理 | 进程退出后触发孤儿云实例检查 |

**OpenClaw 实际形态（来自官方 README）：**
- Node.js 项目，需 Node 22.19+ 或 24
- 安装方式：`npm install -g openclaw@latest`
- 关键命令：`openclaw agent --message "<用户输入>"` —— 一次性运行 Agent 完成任务后退出，契合 subprocess 方案
- Skills 默认目录：`~/.openclaw/workspace/skills/<skill>/SKILL.md`

**Skills 加载策略（按任务隔离 workspace）：**

每次任务启动一个独立 workspace，避免多用户/多任务相互干扰：

```
项目根目录/
└── runtime/
    └── workspaces/
        └── <task_id>/                  ← 每个任务一个独立 workspace
            ├── skills/                 ← 软链到项目根 skills/
            ├── .openclaw/
            │   └── .env                ← 注入 Lab4AI 凭证
            └── ...                     ← openclaw 运行时产物
```

启动时通过 `OPENCLAW_WORKSPACE` 环境变量或 `--workspace` 参数指定该任务的 workspace 路径。

**接口抽象（OpenclawRunner）：**

为支持 mock 与真实 openclaw 的切换，后端定义统一接口：

```python
class OpenclawRunner(Protocol):
    async def start(self, task_id: str, user_input: TaskInput) -> ProcessHandle: ...
    async def stop(self, handle: ProcessHandle, timeout: int = 30) -> None: ...
    async def stream_logs(self, handle: ProcessHandle) -> AsyncIterator[str]: ...
```

实现：
- `MockOpenclawRunner`：开发阶段使用，跑一个假脚本输出模拟日志
- `RealOpenclawRunner`：调用真实 `openclaw agent` 命令

状态机：

```
pending → running → completed
                  → stopped (用户手动)
                  → failed (异常退出 → 触发云实例清理)
```

### 5.6 Lab4AI 云实例代理（第二层）

这是本系统的关键设计——Web 后端作为 Lab4AI API 的代理层：

**问题：** Lab4AI 的 instance-list API 返回整个账号下所有实例，无法区分是哪个用户创建的。

**解决方案：**

1. **拦截创建请求：** openclaw 创建云实例时，后端记录 `serverId → user_id` 映射
2. **过滤查询结果：** 调用 Lab4AI instance-list API 获取全量列表，根据数据库记录过滤出当前用户的
3. **代理关停操作：** 用户只能关停自己的云实例（后端校验归属）
4. **孤儿实例清理：** openclaw 异常退出时，后端自动检测并关停该用户遗留的云实例

**拦截方式（两种可选）：**
- 方案 A：修改 openclaw 的 skills 脚本，创建/关停时回调 Web 后端 API
- 方案 B：后端定时轮询 Lab4AI instance-list，对比数据库发现新实例自动归属

### 5.7 算力限额管理

- 管理员为每个用户设置 GPU/CPU 累计使用时长上限（如：每月 100 小时 GPU）
- 后端记录每个云实例的 startTime 和 stopTime，累计计算用量
- 用户发起新任务时检查剩余额度，不足则拒绝
- 管理员可查看所有用户的用量统计

### 5.8 实时日志模块

- 后端通过 subprocess pipe 捕获 openclaw 的 stdout/stderr
- 异步读取，通过 WebSocket 实时推送到前端
- 前端以终端风格渲染（xterm.js）
- 日志持久化到数据库/文件，任务结束后仍可回看

### 5.9 Lab4AI 凭证管理

- 管理员在后台配置统一的 Lab4AI 账号（phone + password）
- 加密存储在数据库中
- 启动 openclaw 子进程时通过环境变量注入
- 所有用户共享同一算力池，通过限额机制分配

## 6. 数据模型

```
User
├── id
├── username
├── password_hash
├── role (user | admin)
├── gpu_quota_hours       -- GPU 累计时长上限（小时）
├── cpu_quota_hours       -- CPU 累计时长上限（小时）
└── created_at

ClawInstance (openclaw 进程)
├── id
├── user_id (FK → User)
├── pid (操作系统进程 ID)
├── status (pending | running | completed | stopped | failed)
├── skills (JSON: 加载的 skills 列表)
├── task_config (JSON: github_url, paper_url, user_prompt)
├── created_at
├── started_at
└── finished_at

CloudInstance (Lab4AI 云实例)
├── id
├── user_id (FK → User)
├── claw_instance_id (FK → ClawInstance, 哪个 openclaw 创建的)
├── server_id (Lab4AI 返回的 serverId)
├── instance_type (CPU | GPU)
├── gpu_count
├── ssh_host
├── ssh_port
├── status (running | stopped)
├── started_at
└── stopped_at

UsageRecord (用量记录)
├── id
├── user_id (FK → User)
├── cloud_instance_id (FK → CloudInstance)
├── instance_type (CPU | GPU)
├── duration_seconds
├── recorded_at
└── billing_month (如 "2026-05")
```

## 7. API 设计

### 认证
- `POST /api/auth/register` — 注册
- `POST /api/auth/login` — 登录，返回 JWT

### Skills
- `GET /api/skills` — 获取已加载的 skills 列表（名称、描述，仅供展示）

### OpenClaw 实例管理
- `POST /api/claw-instances` — 创建任务（GitHub URL + 可选论文 URL + 可选指令）→ 启动 openclaw 进程
- `GET /api/claw-instances` — 获取当前用户的 openclaw 实例列表
- `GET /api/claw-instances/{id}` — 获取实例详情
- `POST /api/claw-instances/{id}/stop` — 停止 openclaw 进程
- `DELETE /api/claw-instances/{id}` — 删除实例记录

### Lab4AI 云实例管理
- `GET /api/cloud-instances` — 获取当前用户的云实例列表（后端过滤）
- `POST /api/cloud-instances/{id}/stop` — 手动关停云实例（校验归属）

### 实时日志
- `WS /api/claw-instances/{id}/logs` — WebSocket 实时日志流

### 算力用量
- `GET /api/usage` — 当前用户的用量统计
- `GET /api/usage/quota` — 当前用户的剩余额度

### 管理员
- `GET /api/admin/claw-instances` — 所有用户的 openclaw 实例
- `GET /api/admin/cloud-instances` — 所有云实例（直接调 Lab4AI API）
- `GET /api/admin/users` — 用户管理
- `PUT /api/admin/users/{id}/quota` — 设置用户算力配额
- `GET /api/admin/usage` — 全平台用量统计
- `PUT /api/admin/settings/lab4ai` — 配置 Lab4AI 凭证

## 8. 前端页面结构

```
/login                  — 登录页
/register               — 注册页
/dashboard              — 概览（我的 openclaw 实例 + 云实例状态 + 用量）
/tasks/new              — 创建新任务（填 GitHub URL、可选论文 URL、可选指令）
/tasks/:id              — 任务详情 + 实时日志终端
/cloud-instances        — 我的 Lab4AI 云实例列表（可手动关停）
/usage                  — 我的算力用量统计
/admin/instances        — [管理员] 所有 openclaw 实例
/admin/cloud-instances  — [管理员] 所有云实例
/admin/users            — [管理员] 用户管理 + 配额设置
/admin/settings         — [管理员] 平台设置（Lab4AI 凭证）
/admin/usage            — [管理员] 全平台用量报表
```

## 9. 关键技术决策

| 决策点 | 选择 | 理由 |
|--------|------|------|
| 后端框架 | FastAPI | 异步支持好，WebSocket 原生支持，与 Python skills 生态一致 |
| 前端框架 | React + TypeScript | 组件化开发，生态丰富 |
| 进程管理 | subprocess + asyncio | 轻量，无需 Docker 依赖，本地开发零配置 |
| 大模型调用 | 仅 openclaw 内部 | Web 后端无需 LLM，降低成本和复杂度 |
| Skills 加载 | 全量加载，Agent 自选 | 用户无需理解 skills 体系，体验更简洁 |
| 实时日志 | WebSocket + xterm.js | 真正的实时流式体验 |
| 数据库 | SQLite（开发）→ PostgreSQL（生产） | 本地开发零配置，后续可平滑迁移 |
| 认证 | JWT | 无状态，前后端分离友好 |
| 云实例归属 | 后端数据库记录 serverId→user 映射 | 解决 Lab4AI API 无法区分用户的问题 |

## 10. 关键流程

### 10.1 用户发起复现任务

```
用户在 Web 上填写 GitHub URL（+ 可选论文 URL / 自然语言指令）→ 提交
    ↓
后端检查用户算力额度是否充足
    ↓
后端为该任务创建独立 workspace（runtime/workspaces/<task_id>/，软链 skills/ + 注入 .env）
    ↓
后端启动 openclaw 子进程（OpenclawRunner，传入 workspace + 用户输入）
    ↓
openclaw 内部大模型分析 GitHub 仓库，自动选择合适的 skill pipeline
    ↓
openclaw 按 pipeline 执行：
  1. 调用 lab4ai-instance-manage/create.py 创建云实例
     → 后端拦截/感知，记录 serverId → user_id
  2. SSH 连接云实例，执行环境准备、代码克隆、训练...
  3. 调用 lab4ai-instance-manage/stop.py 释放云实例
     → 后端更新云实例状态，计算用量
    ↓
任务完成，openclaw 进程退出
```

### 10.2 异常保护流程

```
openclaw 进程异常退出（crash / 被 kill）
    ↓
后端检测到进程退出码非 0
    ↓
查询数据库：该 openclaw 实例关联的云实例是否仍在运行？
    ↓
若有未释放的云实例 → 调用 lab4ai-instance-manage/stop.py 强制关停
    ↓
记录告警，通知用户
```

## 11. 待确认 / 后续迭代项

- [ ] 云实例创建的拦截方式（回调 vs 轮询）具体选哪种
- [ ] 每用户并发 openclaw 实例数限制
- [ ] 自动化实验（lab4ai-auto-research）任务类型支持
- [ ] 自定义工作流编排
- [ ] 任务结果/产物的下载和展示
- [ ] 远程部署方案（HTTPS、域名、反向代理）
- [ ] 算力额度的重置周期和告警阈值

## 12. 建议的 MVP 范围

**必须有：**

1. 用户登录/注册 + 角色区分
2. 创建复现任务（输入 GitHub URL + 可选论文/指令）→ 启动 openclaw 进程（全量加载 skills）
3. OpenClaw 实例列表 + 状态展示
4. 停止 openclaw 实例
5. 实时日志查看（WebSocket）
6. Lab4AI 云实例列表（按用户过滤）+ 手动关停
7. 异常退出时自动清理云实例
8. 管理员查看所有实例
9. 基础算力用量记录

**可以后做：**

- Skills 列表展示页面（非必须，因为用户不需要手动选择）
- 算力限额的精细化管理（告警、自动停机）
- 任务结果展示/下载
- 用量报表和可视化
- 多种任务类型支持
