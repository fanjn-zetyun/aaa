# Autoresearch skill bundle

自动化训练实验技能包：按阶段拆分的 Markdown 技能文档 + **`pipeline.yml`** 集成索引。

## 用管线驱动全流程（推荐智能体入口）

- **[`SKILL.md`](SKILL.md)**：说明如何**读取 `pipeline.yml`**、按 `stages` 打开对应 `skill_file`、满足 `gates`、填写 `placeholders` 并执行 `command_templates`（含 Lab 分支与完成条件）。

## 技能流程（文件名 skill_01→skill_08）

`skill_01lab_instance.md`、`skill_02policies.md`、`skill_03setup.md`、`skill_04environment.md`、`skill_05experiment_logging.md`、`skill_06loop.md`、`skill_07report.md`、`skill_08stop_instance.md`

## 管线执行顺序（Gate / `pipeline.yml` 的 `stages`）

以 **`pipeline.yml` 的 `stages` 数组顺序** 作为唯一运行时序真源；`scripts/skill_01` 到 `scripts/skill_08` 仅作为分步说明文档。  

维护时建议遵循：
- 新增/调整阶段时，先改 `pipeline.yml`（`stages`、`gates`、`skill_file`）；
- 再同步对应 `scripts/*.md` 的正文细则；
- `README.md` 与 `SKILL.md` 仅保留入口说明，不重复维护完整映射表。

说明：`scripts/skill_0N*.md` 标题中的 Step N 与 Gate log 的 Step 1/2/2.5/... 属于两套编号；Gate 判断以 `scripts/skill_02policies.md` 为准。

**实验室算力（Lab4AI）：** **Step 2**（建实例）与 Step 7（关实例）均使用仓库内 **`lab4ai-instance-manage`**（相对 bundle 根目录 `lab4ai-auto-research/` 为 **`../lab4ai-instance-manage/SKILL.md`**），对应 SKILL 第一节「创建实例」、第二节「关闭实例」及 `scripts/create.py`、`scripts/stop.py`。

## Pipeline 集成

- **机器可读索引：** [`pipeline.yml`](pipeline.yml)  
  - `skill_documents`：每个 `stages[].id` 对应 `skill_file` 路径（相对 bundle 根目录 `lab4ai-auto-research/`，一般为 `scripts/*.md`）。  
  - `global_policies` 中的 `document_section` 指向 **`scripts/skill_02policies.md`** 中的章节标题。  
- **冲突处理：** 以 **各 Step Markdown 正文** 为准；更新流程时同步改 `pipeline.yml` 中的 `skill_file` / 描述。

## 仓库根目录的 `program.md`

项目根目录的 `program.md` 仅作**入口跳转**；完整内容在本 **`lab4ai-auto-research/`** 目录。
