# Skill 适配计划

更新日期：2026-05-21

本文记录 `skills/` 中旧 OpenClaw / vendor skill 与当前 LOBSTER 后端 ToolRuntime 的适配方案。`skills/` 目录仍作为只读执行契约；适配工作应落在后端 `SkillRuntime`、`SkillWorkflowRunner`、`ToolRegistry` 和测试中，不通过改写 skill 模板来绕过问题。

## 适配原则

- 模型可以阅读 `SKILL.md`、`project_reproduce.yaml`、`pipeline.yml` 和 step 文档，但模型输出的工具参数不是可信执行输入。
- 所有会创建资源、执行 SSH、写文件、下载数据或修改远程环境的动作必须经过后端 `ToolRegistry`，并保留 HITL、审计、配额、资源归属和失败清理。
- `claw-shell`、`sshpass`、`ssh`、`scp`、`sftp`、`rsync`、`tmux` 等历史 CLI 语义不能直接在 Web 后端逐字执行。后端只按其语义适配为受控 Tool。
- SSH 主机、端口、用户名和密码只能从 `CloudInstance` 或后端凭证服务读取，不进入模型上下文、WebSocket 事件、普通日志或前端展示。
- 模板变量必须在 Tool 调用前完成渲染。任何 `{{...}}` 残留都应返回结构化失败，不能继续下发远程命令。
- 无法安全适配的能力应返回 `ok=false` 与明确 `error_code`，或进入 HITL；不得伪造成已成功执行。

## 后端映射约定

| 历史名称 / 语义 | 后端 Tool | 适配要求 |
|---|---|---|
| `claw-shell` / `claw_shell_run` | `ssh_execute` 或受控 workspace shell | 远程命令走 `ssh_execute`；不直接执行 vendor `handler.js` / `tmux` |
| `sshpass ... ssh ... "<remote command>"` | `ssh_execute` | 提取远程命令；连接信息从 `CloudInstance` 读取；探活用 `connect_retries` |
| `lab4ai-instance-manage (创建)` | `lab4ai_create_instance` | 走真实 Lab4AI API，创建后写入 `CloudInstance` 与 `workflow_resources` |
| `lab4ai-instance-manage (关闭)` | `lab4ai_stop_instance` | 只能释放当前用户 / 当前对话绑定实例；cleanup 可跳过二次确认 |
| `lab4ai-project-prep` | `remote_project_prep` | 不传 `ssh_password` 给模型；通过 `ssh_execute` / SFTP 上传和执行脚本 |
| `file-system` 读写语义 | workspace read/list/write、`file_write` | 限定任务 workspace 或当前远程 workspace；禁止写 `skills/` |
| `ssh-essentials` 中 scp/sftp 语义 | SFTP 上传/下载 Tool | 只允许当前任务绑定实例和受控路径 |
| `ssh-essentials` 中 tunnel/X11/jump host | 暂不支持 | 返回结构化错误或 HITL，不开放任意隧道能力 |

## P0：复现 workflow 安全闭环

P0 是 `lab4ai-auto-reproduct` 跑通且不泄露 SSH 密码的硬前提。

| 项 | 文件 | 当前风险 | 适配动作 | 状态 |
|---|---|---|---|---|
| `claw_shell_run` vendor 入口 | `skills/lab4ai-auto-reproduct/vendor/claw-shell/handler.js` | 直接执行本机 `tmux`，绕过审计 | 注册兼容 alias；底层转 `ssh_execute` 或受控 workspace shell | 已落地 |
| Step 4 CPU 探活 + clone | `skills/lab4ai-auto-reproduct/project_reproduce.yaml` | `sshpass -p {{step_3.ssh_pass}}` 会暴露密码 | 编译为 `ssh_execute(server_id=cpu, connect_retries=30, command=<clone>)` | 已落地 |
| Step 7 GPU 探活 + bash | `skills/lab4ai-auto-reproduct/project_reproduce.yaml` | `sshpass -p {{step_6.ssh_pass}}` 与长脚本直接拼接 | 编译为 `ssh_execute(server_id=gpu, connect_retries=30, command=<gpu_script>)` | 已落地 |
| `lab4ai-project-prep` | `skills/lab4ai-project-prep/prep_runner.py` | 直接调用 `sshpass`，入参包含 SSH 密码 | 后端 `remote_project_prep` 生成脚本并走 `ssh_execute` / SFTP | 已落地 |
| `lab4ai-instance-manage` | `skills/lab4ai-instance-manage/tools.yaml` | 旧脚本读取 `/root/.openclaw/.env`，会动态装依赖 | 映射为 `lab4ai_create_instance / lab4ai_stop_instance / lab4ai_list_instances` | 已落地 |

## P1：阻断任意 shell 与文件越界

P1 是防止模型读到 vendor skill 后回退到任意本机 shell、任意 SSH 或任意文件操作。

| 项 | 文件 | 当前风险 | 适配动作 | 状态 |
|---|---|---|---|---|
| `ssh-essentials` | `skills/*/vendor/ssh-essentials/SKILL.md` | 文档含 `ssh/scp/sftp/rsync/tunnel` 示例 | 仅允许映射到 `ssh_execute` 和 SFTP 受控操作；隧道/X11/jump host 拒绝 | 基础映射已落地，隧道类仍不支持 |
| `file-system` | `skills/*/vendor/file-system/SKILL.md` | 文档含 `find/cp/mv/sed` 等本机文件命令 | 映射到 workspace read/list/write；禁止任意本机 shell | 已落地 |
| `lab4ai-auto-research` 管线 | `skills/lab4ai-auto-research/pipeline.yml` | 也包含 `sshpass`、远程训练命令模板 | 后续单独实现 `AutoResearchWorkflowRunner`，共用 P0/P1 Tool 适配 | 待实施 |
| `lab4ai-lf-data-preprocess` | `skills/lab4ai-lf-data-preprocess/SKILL.md` | 创建实例、实例内执行脚本、关闭实例 | 编译为 create -> ssh/file tools -> stop 的 workflow | 待实施 |

## P2：旧路径与脚本入口收敛

P2 不阻塞当前复现主链路，但需要逐步消除旧 OpenClaw 路径、动态安装依赖和脚本式凭证读取。

| 项 | 文件 | 当前风险 | 适配动作 | 状态 |
|---|---|---|---|---|
| `lab4ai-instance-list` | `skills/lab4ai-instance-list/scripts/list.py` | 读取 `/root/.openclaw/.env` | 映射到 `lab4ai_list_instances` | 待实施 |
| `lab4ai-image-manage` | `skills/lab4ai-image-manage/scripts/*.py` | 旧凭证路径与脚本式镜像查询 | 映射为 `lab4ai_image_list / lab4ai_image_choose` | 待实施 |
| `lab4ai-repro-report` | `skills/lab4ai-repro-report/report_generator.py` | 动态安装 `python-docx`，输出旧路径 | 后端依赖健康检查；输出到 `runtime/workspaces` | 部分已落地，待补健康检查 |
| `lab4ai-paper-analysis` | `skills/lab4ai-paper-analysis/scripts/analyze_paper.py` | 默认 `/root/.openclaw/workspace`，动态安装依赖 | 后端包装输出路径；依赖提前声明和健康检查 | 部分已落地，待补健康检查 |

## 验收标准

- P0/P1 适配后，模型在 step 内看到 `claw-shell`、`sshpass` 或 vendor `file-system` 语义时，最终只能触发后端 allowlist 中的 Tool。
- Tool 输入中不得出现 `{{step_...}}`、`{{parameters...}}` 等未渲染模板。
- Tool 输入、Tool 结果、WebSocket 事件、对话消息中不得包含 SSH 密码或 Lab4AI 平台密码。
- 复现主链路失败时必须进入 cleanup，释放 `workflow_resources` 中未释放的 CPU/GPU 实例。
- 自动化测试至少覆盖：alias 映射、`sshpass` wrapper 编译、未渲染模板拒绝、受控 file write、cleanup 释放。
- dry-run 验收不得出现“已模拟执行”、固定 `score=75` 或静默跳过 `project_reproduce.yaml` step 的情况。
