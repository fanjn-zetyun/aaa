# 当前开发进度

更新日期：2026-05-19

## 已完成

- 项目级协作入口已补充：根目录新增 `AGENTS.md`，用于 Codex / Agents 进入项目时读取，并指向 `CLAUDE.md`、`docs/proposal.md`、`README.md`。
- 历史遗留的 `claw-instances` 接口和旧版 Runner 已进入迁移清理阶段，当前主链路以 `conversations` 为准。
- V2 数据模型已落地：
  - `LLMConfig`：按用户保存 `provider / base_url / api_key / model / max_tokens`。
  - `Conversation`：保存对话/任务、任务类型、状态、metadata、JSONL 日志路径。
  - `ConversationMessage`：保存 user / assistant / tool / system 消息。
- V2 API 已实现：
  - `POST /api/conversations`
  - `GET /api/conversations`
  - `GET /api/conversations/{id}`
  - `POST /api/conversations/{id}/messages`
  - `POST /api/conversations/{id}/stop`
  - `WS /api/conversations/{id}/stream`
  - `GET /api/llm-config`
  - `PUT /api/llm-config`
- V2 Agent Loop 已实现基础闭环：
  - 支持读取对话历史和 metadata。
  - 支持 system prompt 组装。
  - 支持调用 Anthropic-compatible `/v1/messages` 真实模型接口。
  - 未配置 API Key 或模型调用失败时，会降级为本地 fallback，保证 MVP 可运行。
  - 支持 tool event 流式推送和对话消息持久化。
- 前端已切换到 V2 对话入口：
  - WelcomePage 创建 `/api/conversations`。
  - ChatPage 展示多轮消息、tool events、停止执行按钮。
  - Sidebar 历史记录读取 `/api/conversations`。
  - RightPanel 展示 V2 conversation 详情。
  - 新增 `/model-settings` 模型设置页，可配置真实模型 `base_url / api_key / model / max_tokens`。
- WebSocket 稳定性已优化：
  - 前端仅在对话 `active/running` 且 token 存在时建立 WS。
  - 后端避免在断开后重复 `close()`，减少 Vite `ECONNABORTED` 代理噪音。
- 验证脚本已补充：
  - 新增 `backend/tests/smoke_v2.py`，覆盖登录、LLM 配置、创建 V2 对话、Agent Loop 执行、消息回看。
- Skill 系统最小闭环已落地：
  - 新增 `backend/app/services/skills.py`，实现 `SkillDefinition`、`SkillLoader` 和 `select_skill`。
  - 支持扫描 `skills/*/SKILL.md`，解析 frontmatter 中的 `name / description / triggers / when_to_use / allowed_tools`。
  - `lab4ai-auto-reproduct` 会自动加载同目录 `project_reproduce.yaml`，作为 workflow context 注入模型请求。
  - `backend/app/services/agent_loop.py` 已接入 SkillLoader，不再只记录“已选择 skill”，而是把选中 skill 正文和工作流上下文注入 system prompt。
  - 新增 `backend/tests/test_skills.py`，覆盖 skill 解析、workflow 加载和 reproduce 任务选择。

## 当前验证结果

已通过以下检查：

```bash
uv run python backend/tests/smoke_v2.py
uv run pytest
uv run ruff check backend/app
cd frontend && npm test -- --run
cd frontend && npm run build
```

前后端联调结果：

- 后端 API 文档页 `GET /docs` 通过。
- 前端 Vite 页面访问通过。
- V2 对话创建、Agent Loop 执行、tool event 和历史回看通过。
- 本次本地服务端口：后端 `http://127.0.0.1:8000`；前端因 `5173` 被占用，Vite 自动使用 `http://127.0.0.1:5174`。

## 当前限制

- V2 Agent Loop 已能调用真实模型，但工具层仍是 MVP 模拟：
  - `lab4ai_create_instance` 当前仅模拟创建实例。
  - `ssh_execute` 当前仅模拟 SSH 命令执行。
  - `lab4ai_stop_instance` 当前仅模拟释放实例。
- `api_key` 当前存储在 `LLMConfig.api_key_encrypted` 字段中，但实现上尚未做真正加密；后续需要接入统一加密方案。
- V2 Agent Loop 目前是“模型规划 + 后端顺序执行固定工具链 + 模型总结”，还不是完整 LLM tool-use 自动循环。
- Skills 目录仍保留原 `SKILL.md` 形态；当前已支持 frontmatter 解析和 workflow 注入，但尚未完全标准化为统一 `SKILL.yaml` + allowed tools 规范。
- 管理员前端页面仍未完整实现。
- 真实 Lab4AI API 和真实 SSH 仍未接入。

## 下一步建议

1. 将 `lab4ai_create_instance / lab4ai_stop_instance` 接到真实 Lab4AI API，并写入 `CloudInstance` 归属记录。
2. 实现真实 `ssh_execute`，包括 SSH 凭证、命令超时、输出流式回传和失败处理。
3. 将 Agent Loop 从固定工具链升级为模型驱动的 tool-use 循环。
4. 继续标准化 `skills/` 元数据和 prompt 模板，补齐 `allowed_tools` 与任务类型映射。
5. 为用户 LLM API Key 接入加密存储。
6. 补充 V2 API 的单元测试和前端测试。
7. 清理旧 `claw-instances` 相关接口与文档。
