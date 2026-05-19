# AGENTS.md

本文件是面向 Codex、OpenAI Agents 以及其他代码协作代理的项目入口说明。

## 必读上下文

开始处理本项目中的任何任务前，请先阅读并遵循：

- [CLAUDE.md](CLAUDE.md)：项目背景、协作规则、当前进度和关键文件索引
- [docs/proposal.md](docs/proposal.md)：完整需求与架构设计方案
- [README.md](README.md)：项目运行和基础说明

其中，`CLAUDE.md` 是本项目当前最完整的协作上下文。若本文件与 [CLAUDE.md](CLAUDE.md) 存在冲突，请优先以 [CLAUDE.md](CLAUDE.md) 为准，并在回复中指出冲突点。

## 协作规则

- 默认使用简体中文交流，命令、代码标识符和日志原文保持原样。
- 修改需求、架构或跨模块设计前，先更新或确认 [docs/proposal.md](docs/proposal.md)。
- 不要擅自回滚用户或其他代理已经做出的改动。
- 运行测试、格式化或开发服务时，优先使用项目现有命令和工具链。
- 涉及 Agent Loop、Lab4AI、任务 workspace、运行时目录等内容时，先确认 `CLAUDE.md` 中的约定。

## Codex 说明

Codex 在处理当前仓库任务时，会优先查找并读取适用范围内的 `AGENTS.md`。因此，本文件可以作为 Codex 每次进入项目时的稳定指引。

不过，是否“每次都会看”也取决于具体运行环境是否把该文件加载到会话上下文中。为稳妥起见，本文件明确要求继续阅读 `CLAUDE.md`，避免两个入口文档内容分叉。
