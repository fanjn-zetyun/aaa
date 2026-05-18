# OpenClaw 安装与配置指南

本文档说明如何在服务器上安装 OpenClaw 并与本 Web 应用对接。开发阶段后端会使用 `MockOpenclawRunner` 模拟 openclaw 行为，正式联调时再切换到 `RealOpenclawRunner`。

---

## 1. 系统要求

| 项 | 要求 |
|---|---|
| 操作系统 | macOS / Linux / Windows（推荐 WSL2） |
| Node.js | 24（推荐）或 22.19+ |
| 包管理器 | npm / pnpm / bun（任选其一） |
| Python | 3.13+（用于本 Web 应用后端） |
| 网络 | 可访问 GitHub、npm registry、Lab4AI 平台 |

---

## 2. 安装 OpenClaw

### 2.1 全局安装（推荐）

```bash
npm install -g openclaw@latest
# 或
pnpm add -g openclaw@latest
```

### 2.2 验证安装

```bash
openclaw --version
openclaw doctor      # 自检各项配置
```

### 2.3 首次配置（onboard）

```bash
openclaw onboard --install-daemon
```

按提示完成：

1. **登录模型提供商**（推荐 OpenAI 或其他 OAuth 方式）
2. **配置 Gateway 守护进程**（macOS/Linux 通过 launchd/systemd 注册）
3. **跳过通道配置**（本项目不需要 WhatsApp/Slack 等通道，CLI 调用即可）

> 注意：本 Web 应用通过 `openclaw agent` 命令一次性触发 Agent 任务，不依赖 Gateway 的常驻通道功能。

---

## 3. 与本 Web 应用对接

### 3.1 Skills 同步

本项目的 `skills/` 目录是任务执行所需的核心 skill 集合。后端在每次启动 openclaw 任务时，会为该任务创建独立 workspace，并把项目根目录的 `skills/` 软链或复制进去：

```
runtime/workspaces/<task_id>/
├── skills/                          ← 软链到 ../../../skills
├── .openclaw/
│   └── .env                          ← 注入 Lab4AI 凭证（LAB4AI_PHONE / LAB4AI_PASSWORD）
└── ...
```

### 3.2 Lab4AI 凭证注入

Lab4AI 凭证通过 Web 后台的「管理员设置」页面配置，存储在数据库中（加密）。任务启动时后端会写入 workspace 内的 `.openclaw/.env`：

```
LAB4AI_PHONE=<手机号>
LAB4AI_PASSWORD=<密码>
```

`lab4ai-instance-manage` 等 skill 会从该 `.env` 读取凭证。

### 3.3 启动方式

后端通过 subprocess 调用：

```bash
openclaw agent \
  --workspace runtime/workspaces/<task_id> \
  --message "复现这个项目: <github_url> 论文: <paper_url> 指令: <user_prompt>"
```

> 具体参数（如 `--workspace` 是否被支持，是否需要环境变量 `OPENCLAW_WORKSPACE`）需要在真实 openclaw 联调时确认并补充到 `RealOpenclawRunner` 实现。

---

## 4. 开发模式（Mock）

开发阶段后端默认使用 `MockOpenclawRunner`，无需安装真实 openclaw。

切换方式：在 backend 的 `.env` 中设置：

```
OPENCLAW_RUNNER=mock      # 默认值，使用模拟实现
# OPENCLAW_RUNNER=real    # 切换到真实 openclaw 命令
OPENCLAW_BIN=openclaw     # 真实模式下的可执行文件路径
```

Mock 实现会：

- 启动一个内置的 Python 脚本，模拟 openclaw 的输出（按时间间隔打印日志）
- 模拟创建/释放 Lab4AI 云实例的回调（写入数据库）
- 支持 SIGTERM 优雅退出

---

## 5. 联调切换清单

从 mock 切到真实 openclaw 时需要做：

- [ ] 服务器安装 Node 24 + openclaw
- [ ] 完成 `openclaw onboard`，配置模型 API key
- [ ] 验证 `openclaw doctor` 输出正常
- [ ] 确认 `openclaw agent` 命令的实际参数（`--workspace` / `--message` / 环境变量等）
- [ ] 后端 `.env` 设置 `OPENCLAW_RUNNER=real`
- [ ] 配置好 Lab4AI 凭证（管理员页面）
- [ ] 跑一个简单的 GitHub URL 任务做端到端验证

---

## 6. 故障排查

| 问题 | 排查 |
|------|------|
| `openclaw: command not found` | 检查 npm 全局 bin 是否在 PATH |
| Skills 找不到 | 检查 workspace 内 `skills/` 软链是否生效 |
| Lab4AI 401 错误 | 检查 `.openclaw/.env` 是否正确写入凭证 |
| 进程僵尸 | 后端 `OpenclawRunner.stop()` 应先 SIGTERM，超时再 SIGKILL |
| 云实例未释放 | 检查后端的孤儿实例清理逻辑是否触发（见 proposal 10.2） |

---

## 7. 参考链接

- OpenClaw GitHub: https://github.com/openclaw/openclaw
- OpenClaw 官方文档: https://docs.openclaw.ai
- Skills 文档: https://docs.openclaw.ai/tools/skills
- Lab4AI 平台: https://tools.lab4ai.cn
