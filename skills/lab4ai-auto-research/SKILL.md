---
name: lab4ai-auto-research
description: >
  通过读取并遵循 lab4ai-auto-research/pipeline.yml 执行完整自动化训练实验流程：按 stages 顺序打开对应
  Step Markdown、满足 gates、使用 command_templates 与 placeholders。与 scripts/skill_02policies.md 的 Gate log
  与执行顺序强制一致。适用于需按管线推进的超参/策略实验自动化。
triggers:
  - "lab4ai-auto-research"
  - "自动化训练实验"
  - "自动化实验"
  - "自动跑实验"
  - "自动做实验"
  - "自动调参"
  - "自动化调参"
  - "自动化超参搜索"
  - "批量实验"
  - "批量跑实验"
  - "自动复现实验"
  - "自动化复现实验"
  - "自动实验管线"
  - "实验自动化"
  - "实验室训练实验"
  - "Lab4AI 实验室"
  - "Lab4AI 实验管线"
  - "Lab4AI 自动化实验"
  - "Lab4AI 自动调参"
  - "超参实验自动化"
  - "超参数搜索自动化"
  - "策略实验自动化"
  - "实验循环 LOOP"
  - "自动化实验室"


metadata:
  language: zh-CN
  pipeline_file: lab4ai-auto-research/pipeline.yml
---

## 前置条件
- `/root/.openclaw/.env` 中配置了 `LAB4AI_PHONE` 和 `LAB4AI_PASSWORD`
- **`httpx`**：执行 **`lab4ai-instance-manage`** 的 `create.py` / `stop.py` 时，若未安装会在首次运行时自动 `pip install httpx`；也可事先执行：`pip install httpx`
- **`install.sh`**：将本技能、`vendor/` 内第三方 skill（与 **`lab4ai-auto-reproduct/vendor`** 同源：`claw-shell`、`file-system`、`ssh-essentials`）及兄弟目录 `lab4ai-instance-manage` / `lab4ai-image-manage` 软链到 `OPENCLAW_SKILLS`（默认 `~/.openclaw/skills`），供 Agent 调用远程命令与读文件。
- **对话语言默认中文**：除用户明确要求其他语言，或命令/日志原文必须原样展示外，面向用户的叙述默认使用简体中文。

# 通过 `pipeline.yml` 驱动自动化实验（Autoresearch）

本目录布局与 **`lab4ai-skills-master`** 对齐：**入口文件为 `SKILL.md`**（不再使用 `skill.md`），并补充 **`skill.json`**、**`manifest.yaml`** 便于与 OpenClaw / 技能市场一致索引；编排真源仍为 **`pipeline.yml`**（角色上对应复现仓的 `project_reproduce.yaml`，字段名刻意保留以兼容现有引用）。

本技能说明**智能体如何以 `lab4ai-auto-research/pipeline.yml` 为控制面**，结合 **各 Step Markdown**（如 `scripts/skill_03setup.md`、`scripts/skill_06loop.md`）正文，完成端到端自动化实验（含门禁、循环、终稿报告、可选实验室开关机）。

## 适用场景

- 用户要求「按 autoresearch / 自动化实验管线」执行任务
- 需要**可核对**的阶段清单（`stages`）、门禁（`gates`）与命令模板（`command_templates`）
- 多份 Step Markdown 已拆分，需**单一入口**决定「下一步读哪份、做什么」

## 管线文件位置（必须）

- **优先探测当前 bundle 根目录**（即 `SKILL.md` 同级目录）下的 `pipeline.yml`。
- 若当前工作目录不在 bundle 根，再回退探测 `lab4ai-auto-research/pipeline.yml`（相对仓库根）。
- `pipeline.yml` 中 `root: lab4ai-auto-research` 仅用于解释 `skill_file` 的相对路径；实际执行时以已探测到的 bundle 根为拼接基准。

## 执行协议（智能体必须遵守）

### 1. 加载管线

1. **读取** `lab4ai-auto-research/pipeline.yml` 全文（或至少 `global_policies`、`placeholders`、`stages`）。
2. 记下 **`global_policies.policies_skill`**（当前为 `scripts/skill_02policies.md`）— 在按 `stages` 推进前须已理解其中的 **Gate protocol** 与 **Execution order**（首段 `skill_file` 可为 **`instance_provision`**）。

### 2. Gate 与政策技能（`policies_skill`）

加载 `pipeline.yml` 后**随即**打开 **`lab4ai-auto-research/` + `global_policies.policies_skill`**（即 `lab4ai-auto-research/scripts/skill_02policies.md`）通读 Gate 与全局规则；随后**严格按 `stages` 顺序**执行各段（首段可能为 **`instance_provision`**，不等同于「先完成 Step 1」）。并遵守：

- 在**第一次**要跑项目内命令前，输出 **Gate log**（模板见该文件）。
- 在**每次阶段切换**前，更新并再次输出 Gate log。
- **对用户说明**：以 Gate log、命令与可核对证据为主，**少空话套话**；**减少**泛问「是否继续 / 可以吗」（Gate 已允许、仅顺序推进时**默认不问**；细则见 `skill_02policies.md`「对话与对用户输出」与 **Confirmation policy**）。
- **多数据集（强制询问）**：若 README / 脚本 / 配置表明需要**下载或选用多个不同数据集**（多 benchmark、多可选 `download_*`、多数据源等），**必须先列出选项并询问用户要哪一个或哪几个**，**在得到明确选择前禁止**批量下载或擅自选定默认集；细则见 `scripts/skill_03setup.md` Step 1 第 8 条与 `scripts/skill_02policies.md`「明确禁止的跳步」表。

### 3. 按 `stages` 顺序推进（不要按 `skill_documents` 单独排序）

`pipeline.yml` 里 **`stages`** 数组的顺序即为**运行时序**。对每个 `stages[]` 条目：

| 动作 | 说明 |
|------|------|
| **打开 `skill_file`** | 路径 = `lab4ai-auto-research/` + `stages[].skill_file`（与条目内 `skill_file` 一致） |
| **对照 `gates`** | 全部满足前，**不得**进入下一 `stage` |
| **执行 `tasks`** | 按技能正文与 `tasks` 描述完成；`confirm_required: true` 的须用户明确确认 |
| **拼命令** | 使用该 stage 下 **`command_templates`**，将 **`placeholders`** 中键（如 `<project_root>`）替换为会话中已确认的真实值 |
| **委托技能** | 若 stage 含 **`delegated_skill`**，则打开 **`lab4ai-auto-research/` + `delegated_skill.file`**（相对 bundle 根；当前多为 `scripts/create_env.md`），仍须满足本管线的 gates |

**实验室实例分支：**

- **`instance_provision`（`skill_01`，文档首行 **Step 1**；Gate log **Step 2**）**：在 `stages` 中位于 **`policies`、`setup`、`environments`（Gate **Step 2.5**）之前**（当前管线为首段）；仅当 Gate log 中 **Lab instance flow = yes** 时执行。若为 **no**，该 stage **整段跳过**（在 Gate log 标 **`Step 2 skipped`**），且**不得**执行 `instance_teardown` 中的关实例逻辑（或标为 `N/A`）。**禁止默认 Lab=no 自动跳过**：必须先明确询问并拿到用户 yes/no，再允许执行或跳过。**Gate Step 2.5** 仍须在 Gate Step 2（若适用）之后；Gate log 允许 **Gate Step 1 在 Gate Step 2 之后**补齐（见 `skill_02policies.md`）。
- **`instance_teardown`（`skill_08`，文档首行 **Step 8**；Gate **Step 7**）**：仅当曾成功执行 Gate **Step 2**（实验室建实例）且需释放资源时执行；须在 Gate **Step 6** 报告完成后。

**`experimentation` 与 `output_and_logging`：** 二者可能指向同一 `skill_file`（`skill_05`，文档首行 **Step 5**）；**实验性编辑 + 每轮日志**在 **`experiment_loop`**（`skill_06`，文档 **Step 6**）内循环执行，不要在没有完成 **Gate Step 5 `pre_loop_gates`** 的情况下单独「只跑一轮训练」。

### 4. 与 `skill_documents` 的关系

YAML 顶部 **`skill_documents`** 为 **stage_id → skill_file** 的索引表，便于校验；**执行时以 `stages` 为准**。若 `stages[].skill_file` 与 `skill_documents` 不一致，**以 `stages[].skill_file` 为准**并应修正 YAML。

### 5. 完成条件

对照文件末尾 **`completion_criteria`**：全部满足后，本自动化实验任务视为**规范完成**；其中 **`final report`** 与（若适用）**`instance_stop`** 为硬条件。

### 6. 冲突处理

**各 Step Markdown 正文优先于 YAML 中的简短描述。** `description`、`rule` 字段是摘要；细则、示例命令、STOP 块以对应 **Step 文件**为准。

## 最小伪代码（逻辑顺序）

```text
read lab4ai-auto-research/pipeline.yml
read lab4ai-auto-research/scripts/skill_02policies.md
emit Gate_log (initial)

for each stage in pipeline.stages (in array order):
  if stage.id == instance_provision:
    ask user explicitly: "是否创建实验室实例（Lab instance flow）？[yes/no]"
    if Lab choice unresolved: block here (do not enter next stage)
    if Lab == no: continue
  if stage.id == instance_teardown and Lab == no: continue

  read lab4ai-auto-research/{stage.skill_file}
  until all stage.gates satisfied (per skill + user confirm):
    run stage.tasks using skill text
    show command_templates with placeholders resolved
  emit Gate_log (updated)

# Gate Step 5 loop: follow scripts/skill_06loop.md (document Step 6) until stop / interrupt
# Then final_report (skill_07, document Step 7), then instance_teardown (skill_08, document Step 8) if Lab

assert completion_criteria from pipeline.yml
```

## 相关文件

**执行顺序与映射真源：** 统一以 `pipeline.yml` 的 `stages` 与 `skill_file` 为准；`scripts/skill_01` 到 `scripts/skill_08` 仅承载分步细则，不在本文件重复维护完整映射表。

| 文件 | 用途 |
|------|------|
| `lab4ai-auto-research/SKILL.md` | 本文件：驱动协议与伪代码 |
| `lab4ai-auto-research/pipeline.yml` | 阶段、门禁、占位符、命令模板 |
| `lab4ai-auto-research/manifest.yaml` | 管线元数据（对齐 lab4ai-skills `manifest.yaml` 角色） |
| `lab4ai-auto-research/skill.json` | 触发词与版本（对齐 `skill.json` 角色） |
| `lab4ai-auto-research/scripts/skill_02policies.md` | Gate log、执行顺序、全局规则 |
| `lab4ai-auto-research/README.md` | 人类可读的技能阅读顺序 |
| `lab4ai-auto-research/scripts/*.md` | 分步细则（见 `pipeline.yml` 的 `stages[].skill_file`） |

---

**提示：** 若工具链支持「只附加一个文件」，可同时附加 **`lab4ai-auto-research/pipeline.yml`** 与 **`lab4ai-auto-research/scripts/skill_02policies.md`**，并声明「后续每阶段按 pipeline 的 `stages[].skill_file` 打开对应 Step 文档」。
