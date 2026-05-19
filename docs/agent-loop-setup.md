# 自建 Agent Loop 配置指南

本文档说明 LOBSTER 后端 Agent Loop 的本地配置方式。项目已确认不再接入外部 Agent CLI，后端会直接负责模型调用、Tool 调度、Lab4AI 资源归属和事件流推送。

## 1. 环境要求

| 依赖 | 说明 |
|---|---|
| Python | 3.13+ |
| uv | Python 包管理 |
| Node.js | 前端 Vite 开发环境 |
| Lab4AI 账号 | 由管理员统一配置 |
| LLM API | 用户自行配置 Anthropic-compatible `base_url / api_key / model` |

## 2. 后端配置

从示例文件复制配置：

```bash
cp backend/.env.example backend/.env
```

核心配置项：

```env
DATABASE_URL=sqlite+aiosqlite:///./runtime/app.db
SECRET_KEY=change-me
```

模型配置不写入全局 `.env`，而是用户登录后在「模型设置」页面填写：

- `provider`
- `base_url`
- `api_key`
- `model`
- `max_tokens`

页面会调用 `POST /api/llm-config/test` 做连通性测试。

## 3. Lab4AI 凭证

Lab4AI 平台账号由管理员统一配置，后端加密保存。Agent Loop 执行以下 Tool 时会使用该凭证：

- `lab4ai_create_instance`
- `lab4ai_stop_instance`
- `lab4ai_list_instances`

所有云实例创建都必须写入后端数据库，记录：

- `server_id`
- `user_id`
- `conversation_id`
- `start_time`
- `status`
- Lab4AI 原始响应

## 4. Skills 目录

`skills/` 目录保留为 LOBSTER 的任务模板集合。推荐格式：

```yaml
---
name: lab4ai-auto-reproduct
description: 自动复现 GitHub 项目的实验结果
task_type: reproduce
allowed_tools:
  - lab4ai_create_instance
  - ssh_execute
  - lab4ai_stop_instance
---

你是一个科研复现助手...
```

Agent Loop 启动时读取 skill 元数据，用于：

- 选择任务类型。
- 组装 system prompt。
- 限制可用 Tool。
- 生成可观测的 `skill_selection` 事件。

## 5. 开发启动

后端：

```bash
uv sync
uv run uvicorn app.main:app --reload --app-dir backend --host 127.0.0.1 --port 8000
```

前端：

```bash
cd frontend
npm install
npm run dev
```

验证：

```bash
uv run python backend/tests/smoke_v2.py
uv run pytest
cd frontend && npm run build
```

## 6. 当前未完成项

- Lab4AI Tool 仍需接入真实 API。
- `ssh_execute` 仍需接入真实 SSH。
- Agent Loop 仍需升级为完整 tool-use 循环。
- 用户 API Key 仍需接入真正加密存储。
- 旧接口和旧命名仍需逐步迁移清理。
