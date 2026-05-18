# Step 2: Core policies, Gate protocol, execution order

Global rules apply to **every** step skill (`skill_01` … `skill_08` Markdown 文件). **Source of truth** for behavior: this file plus the step skills; **`../pipeline.yml`** (bundle root, sibling of `scripts/`) lists stages and gates.

**技能流程与管线 `stages` 顺序（`scripts/` 下 skill_01→skill_08，与 `pipeline.yml` 一致）：**  
`skill_01lab_instance.md` → `skill_02policies.md`（本文件）→ `skill_03setup.md` → `skill_04environment.md` → `skill_05experiment_logging.md` → `skill_06loop.md` → `skill_07report.md` → `skill_08stop_instance.md`

Lab=yes 时 **先** `skill_01` 建机（文档 **Step 1**），**再** 本文件补 Gate 与全局规则（文档 **Step 2**），**再** `skill_03setup`（文档 **Step 3**；Gate Step 1）；Gate log 中 **Step 1 / Step 2 可非时间序填写为 yes**，但进入 **Step 2.5** 前两者在适用时均须为 **yes**。

- **`skill_01lab_instance.md`（文档首行 **Step 1**，对应 Gate log **Step 2** 实验室实例）：** 仅当 Gate log **Lab instance flow = yes** 时执行；**no** 时整阶段跳过（Gate log 中 `Step 2 done?` 填 **skipped**）。**yes** 时按 **`lab4ai-instance-manage/SKILL.md`** 创建实例。  
- **`skill_08stop_instance.md`（文档首行 **Step 8**，对应 Gate **Step 7** 关实例）：** 仅当曾成功执行 Gate **Step 2**（实验室建实例）时在 Gate **Step 6** 报告**之后**执行；否则整阶段跳过。

### 与 `pipeline.yml` 的配合

| 文件 | 角色 |
|------|------|
| **`skill_02policies.md`（本文件）** | 门禁、执行顺序、命令展示、确认策略 |
| **`skill_01` … `skill_08`**（本文件为 **`skill_02policies.md`**） | 各 Step 细则与可复制命令 |
| **`../pipeline.yml`** | 结构化阶段、`gates`、`command_templates`；**冲突时以各 Step 正文为准** |

**推荐用法：** 每进入一阶，打开 `stages[].skill_file` 对应的 Markdown（通常为 `scripts/*.md`）；对照 **`../pipeline.yml`** 中同名 `stages[].id` 的 `gates` / `completion_criteria`；命令模板以 YAML 为骨架，**细则以 Step 文档为准**。

## Gate protocol（强制执行：未做 = 未按本 skill 执行）

仅靠「建议按序」不足以约束自动化。**本 skill 要求：在开展下一阶段任何实质工作之前，必须先完成并展示 Gate log。** 若跳过下列任一条即开始训练、改实验代码、写报告或关实例，则视为 **未按文档执行**，须**回退补做**，不得宣称本 skill 已完整执行。

### 何时必须输出 Gate log（缺一不可）

1. **会话开始后第一次**准备执行项目内命令（含 `git`、`conda`、训练）之前。
2. **每一次阶段切换**之前：Lab=yes 时 Step 2（实验室）与 Step 1（Setup）须在 **Step 2.5** 前均达标（管线顺序下可先 Step 2 后 Step 1）；以及 2.5→预循环确认、进入 Step 5 循环、循环结束→Step 6、Step 6→Step 7（若适用）。

### Gate log 模板（复制输出并逐项填写；禁止留空或全写「已完成」而无证据）

```text
=== Gate log (autoresearch skills) ===
Lab instance flow? [ yes | no ]   # 本会话最先明确询问并记录；禁止默认 no。若用户尚未明确回答，此行保持未决并阻塞后续阶段
Step 1 (Project setup) done? [ yes | no ]   # 证据：项目路径已确认；入口已确认；results.tsv 表头已创建
Step 2 (Lab instance provision) done? [ skipped | yes | no ]   # 若 Lab=yes：须 yes，且 serverId 已保存、SSH 可用；Lab=no 填 skipped
Step 2.5 (Environment ready) done? [ yes | no ]   # 证据：环境就绪——已展示当前 python 可执行路径（须为 conda 新建或用户确认复用的环境；新建根仅 conda；且已给出镜像检查结论 image_available / image_unavailable / user_declined_image；Lab=yes 时在 SSH 会话内的实例上完成）
Step 5 (Pre-loop confirmation) done? [ yes | no ]   # 证据：停止条件与单轮时限已由用户明确确认（非默认臆测）
Loop status (Step 5 loop)? [ not_started | running | ended ]
Step 6 (Final report) done? [ yes | no ]   # 证据：autoresearch_report.md（或约定路径）已写入
Step 7 (Stop lab instance) done? [ not_applicable | yes | no ]   # Step 2=yes 时禁止填 not_applicable，必须先询问是否关机；yes 可为用户确认立即关机或“询问后 10 分钟无回复触发 timeout auto-stop”；仅当 Step 2=skipped 才可填 not_applicable
Next action (one sentence, must match first incomplete row above):
=== end ===
```

### Gate log 看板模板（可选，更易读）

> 状态图例（推荐统一）：`✅ 已完成` / `⏳ 未开始` / `🔄 进行中` / `⛔ 阻塞` / `⏸ 待定`
>
> 取值与状态建议映射：
> - `yes` → `✅ 已完成`
> - `no` → `⏳ 未开始`（若受前置门禁限制可标 `⛔ 阻塞`）
> - `running` / `STARTING` → `🔄 进行中`
> - `skipped` / `not_applicable` → `⏸ 待定`（仅在规则允许时使用）

```text
=== Gate log (autoresearch skills | Kanban view) ===
Lab instance flow? [ yes | no | unresolved ] : ⛔ 阻塞   # unresolved 表示用户尚未明确答复

[⏳ 未开始] Step 1  Project setup
     - value: [ yes | no ]
     - evidence: <path/entrypoint/results.tsv header>

[⏳ 未开始] Step 2  Lab instance provision
     - value: [ skipped | yes | no ]
     - evidence: <serverId/ssh ready>

[⏳ 未开始] Step 2.5 Environment ready
     - value: [ yes | no ]
     - evidence: <python path/image check/env name>

[⏳ 未开始] Step 5  Pre-loop confirmation
     - value: [ yes | no ]
     - evidence: <max rounds/per-run limit confirmed>

[🔄 进行中] Step 5  Experiment loop
     - loop status: [ not_started | running | ended ]
     - progress: <round x/y>

[⏳ 未开始] Step 6  Final report
     - value: [ yes | no ]
     - evidence: <autoresearch_report.md path>

[⏸ 待定] Step 7  Stop lab instance
     - value: [ not_applicable | yes | no ]
     - evidence: <stop decision branch or reason>

Next action (one sentence, must match first incomplete/blocked step above):
<action + required user input in one line>
=== end ===
```

填写规则（与标准模板一致）：
- `Step 2 = yes` 时，`Step 7` 不得填 `not_applicable`。
- `Lab instance flow = unresolved` 时，后续步骤默认标 `⛔` 或 `⏳`，并把 Next action 写为“先确认是否创建实例”。
- 仅当对应 gate 证据齐全时，状态才可改为 `✅`。
- 优先让每个步骤都包含 `value + evidence` 两行，避免只给状态不给证据。

### Gate log 表格模板（默认模板，优先使用）

> 默认优先使用该表格版向用户展示 Gate log。仅在用户明确要求纯文本/看板样式时，才切换为其他模板；字段语义必须保持一致。

```text
=== Gate log (autoresearch skills | Table view) ===
| 项目 | 状态 | value | evidence |
|---|---|---|---|
| Lab instance flow | ⛔ 阻塞 / ✅ 已完成 | yes / no / unresolved | 用户是否明确答复 |
| Step 1 Project setup | ✅ 已完成 / ⏳ 未开始 / ⛔ 阻塞 | yes / no | project_root、entrypoint、results.tsv 表头 |
| Step 2 Lab instance provision | ✅ 已完成 / ⏳ 未开始 / ⏸ 待定 | yes / no / skipped | serverId、SSH 就绪 |
| Step 2.5 Environment ready | ✅ 已完成 / ⏳ 未开始 / ⛔ 阻塞 | yes / no | env 名称、python 路径、镜像结论 |
| Step 5 Pre-loop confirmation | ✅ 已完成 / ⏳ 未开始 / ⛔ 阻塞 | yes / no | 最大轮数、总时长、单轮时限 |
| Step 5 Experiment loop | 🔄 进行中 / ⏳ 未开始 / ✅ 已完成 | not_started / running / ended | round x/y、当前最佳指标 |
| Step 6 Final report | ✅ 已完成 / ⏳ 未开始 | yes / no | autoresearch_report.md 路径 |
| Step 7 Stop lab instance | ✅ 已完成 / ⏸ 待定 / ⏳ 未开始 | yes / no / not_applicable | 关机决策分支与结果 |

Next action (one sentence, must match first incomplete/blocked row above):
<action + required user input in one line>
=== end ===
```

表格版填写约束（与其他模板一致）：
- `Step 2 = yes` 时，`Step 7.value` 不得为 `not_applicable`。
- `Lab instance flow = unresolved` 时，优先将后续相关行状态标记为 `⛔ 阻塞` 或 `⏳ 未开始`，并在 `Next action` 中先收敛用户回答。
- `Step 5 Experiment loop` 行建议在 `evidence` 中固定写 `round x/y`，便于跨轮次追踪。
- 阶段切换、关键执行前的 Gate log 输出，默认都使用该表格模板。

**与 `pipeline.yml` 一致：** 若 **Lab=yes**，可能在 **Step 1 = yes** 之前先将 **Step 2** 标为 `yes`（先建机后 Setup）；进入 **Step 2.5** 前仍须两行在适用时均为 `yes`。

**允许的下一步**只能是 Gate log 里 **第一个仍为 `no` 或未覆盖** 的阶段所对应动作；**不得**在上一行仍为 `no` 时执行下一阶段的训练或大规模编辑。

### 明确禁止的「跳步」（出现即违规）

| 禁止行为 | 须先满足 |
|----------|----------|
| 未先询问“是否创建实例（Lab instance flow）”就直接调用 `instance_create` | 先得到用户 yes/no 明确答复并记录到 Gate log（Lab=no 时 Step 2 应为 skipped） |
| 未经用户明确答复就把 Lab 当作 no 并跳过 `skill_01lab_instance.md` | 先询问并记录 `Lab instance flow? [yes|no]`；未明确答复前不得跳过 Step 2，也不得进入后续阶段 |
| Step 2 已执行却将 Step 7 标为 `skipped`/`not_applicable` 并自动跳过关机询问 | 若 Step 2=yes，Step 7 必须先询问用户是否关机（yes 立即执行；no 保持待处理；10 分钟无回复 timeout auto-stop）；不得自动跳过 |
| **存在多个可选数据集时**自行批量下载、或默认选其中一个而不问用户 | 已按 `skill_03setup.md` Step 1 第 8 条：**列出可选数据集**并**询问用户要下载/使用哪一个或哪几个**，得到**明确答复**后再执行下载或指向数据路径 |
| 在未询问并确认实验停止条件前继续往下执行（训练/循环） | 已完成 Step 5 pre-loop 的停止条件确认：必须明确询问并得到用户确认（最大轮数/总时长/截止时间/manual-only/单轮时限等）；未确认前不得进入任何训练命令或 `LOOP FOREVER` |
| 运行 `<training_command>` 或进入 Step 5 循环 | Step 1 与（若 Lab=yes）Step 2 均完成（顺序可与管线 stages 一致）；Step 2.5 完成；若 Lab=no 则 Step 2.5 完成（Step 2 为 skipped）；且 Step 5 **预循环**已确认 |
| 用户说「直接训练 / 别管环境」 | 仍须用 Gate log 标出缺口；至少确认路径、解释器、停止条件，否则不开始训练 |
| 撰写或宣称完成 Step 6 | 循环已结束或已达成停止条件/用户中断，且具备 `results.tsv` 或诚实说明为空 |
| 执行 Step 7 `instance_stop` | Step 6 已完成（若 Step 2 实验室曾执行）；且已先询问用户是否关机（用户 yes 可立即执行；用户 no 则不得执行；10 分钟无回复可按 timeout auto-stop 执行） |

**Final deliverable:** every automation run **must** end with the **Step 6** written experiment report (`autoresearch_report.md` or equivalent); no run is complete without it. If **Step 2** (lab instance flow) created an instance, you **must** also run **Step 7** (`instance_stop` with the saved `serverId`) after Step 6—do not leave the instance running after automation finishes.

## Execution order（强制按序，禁止跳步）

Steps are **sequential phases**. Treat later steps as **blocked** until the previous phase’s **gates** and **deliverables** (below) are satisfied. If the user asks to skip ahead, **refuse unless** they explicitly accept the risk; still complete any **mandatory** gates (e.g. Step 1 detection, Step 5 pre-loop limits) before training.

**Phase map (single path):**

```text
Step 1 (setup + branch + results.tsv header + confirmed detection)
    → Step 2 (optional only if this skill’s lab flow applies: instance + SSH + serverId saved)
        → Step 2.5 (conda env active / env confirmed — on lab host if Lab=yes, else local; new roots: conda only)
            → Step 5 pre-loop gate (stop conditions + per-run limits — user confirms once)
                → Step 5 LOOP FOREVER (each round: Step 3-style edits + train + Step 4 logging)
                    → Step 6 (final report file written)
                        → Step 7 (only if Step 2 ran: instance_stop)
```

**“Done with phase” checklist (agent must verify before leaving the phase):**

| Phase | You may leave this phase only when… |
|-------|-------------------------------------|
| **1** | Project path and (if applicable) single entrypoint are **user-confirmed**; `results.tsv` header exists; detection summary (step 7 in Step 1) is confirmed; **if multiple datasets apply**, user has **explicitly chosen** which to download/use (step 8 in Step 1). |
| **2** | `instance_create` returned `code == 0`; SSH to instance works; **`serverId` persisted** for Step 7. *(Skip entire Step 2 if not using the lab instance flow.)* |
| **2.5** | A project-approved interpreter is active (`conda activate` / equivalent) and user confirmed env/image choice — **on the lab instance via SSH when Lab=yes**, otherwise on the local workspace; **no training** has started yet except what Step 5 allows later. |
| **5 (enter loop)** | **Step 5** stop conditions and per-run limits are **explicitly user-confirmed**; Step **1** loop prerequisites are also confirmed. |
| **5 (each round)** | That round’s train+log+`results.tsv` row (Step **4**) is done or recorded as `crash`; then next round or exit loop when stop conditions hit. |
| **6** | `autoresearch_report.md` (or agreed name) exists at project root (or agreed path) with required sections. |
| **7** | If Step 2 ran (lab instance): ask user whether to stop instance first; if user says **yes**, run `instance_stop`; if user says **no**, keep pending; if no reply for **10 minutes**, run timeout auto-stop with saved `serverId`. Non-zero `code` is surfaced, not ignored. |

**Progress discipline (mandatory):** At each phase boundary you **must** output the **Gate log** block above (filled in), not only a one-liner. A single-line summary is optional *after* the Gate log. Example after log: `Next: Step 2 instance_create` or `Next: Step 2.5 environment on lab host after SSH`.

### 对话与对用户输出（避免空话、套话）

在已满足 **Gate log** 与 **Command display** 的前提下，**自然语言说明须短、可核对、信息密度高**：

- **默认使用中文回答**（简体中文）。除用户明确要求其他语言，或必须保留的命令/日志原文外，不切换英文叙述。
- **禁止**长篇套路寒暄、空洞表态（如反复「我会尽力」而无路径/命令/证据），以及**同义复述**用户已可见的整段正文。
- **默认结构**：完整 **Gate log** →（可选）**一句** `Next: …` + 关键证据（路径、将执行命令、一行关键输出）→ 若需用户决策则 **逐条列出待选/待填项**。
- **一次性提问优先**：同一阶段若存在多个待确认项（如项目路径、入口选择、数据集选择、环境方案、停止条件），应在**一条消息**中集中列出并一次性询问；除非用户回答后出现新分叉，否则不要拆成多轮零碎追问。
- **同一轮回复**不堆多段总结；细节仅在用户追问或排错时展开。
- 若用户要求「少废话 / 只要结论」：**仅** Gate log + 命令块 + 待确认项，省略叙事段落。
- **减少「是否继续 / 可以吗 / 要不要往下做」等元推进询问**：下一步已由 **`pipeline.yml` 的 `stages`** 与 **Gate log** 决定、且当前阶段门禁已满足时，**默认不问**泛用「是否继续」— 用 **Gate log（更新后）+ `Next: …` + 将执行命令** 直接推进。**仅当**仍存在 **Confirmation policy** 所指**未决的实质选择**（路径、入口、环境方案、停止条件等）时，才发问；**同一类**「无新信息的是否继续」**每阶段至多一次**，且避免在相邻两轮回复里重复。
- **禁止**固定话术式串联：「确认后我将 A，然后 B，再 C，**是否继续？**」— 若 A→B→C 均为文档与 Gate 已规定的顺序、且无新的分叉，则**不得**为此套一层全体「是否继续」。

## 执行规则（必须遵守）

1. **前置确认**：对**实质性写操作或高风险动作**（如分支切换、批量改动、训练循环启动、实例开关机）必须先获得用户明确授权；若同一阶段已获授权且无新增分叉，不要求每轮重复确认
2. **操作透明**：向用户展示即将执行的具体操作清单（须含**可执行命令**，见 **Command display policy**）
3. **回滚准备**：确认前先生成操作快照以便回滚
4. **阶段阶序**：未完成上一阶段的门禁与交付物，不得进入下一阶段；**禁止**在未满足 Step 1 与 Step 5 预循环确认的情况下进入 `LOOP FOREVER`；**禁止**在循环未结束（或未满足停止条件/用户中断）时跳过 Step 6；若执行过 **Step 2**（实验室建实例），**禁止**在 Step 6 完成前执行 Step 7，也**禁止**只做 Step 7 而不写报告
5. **Gate log**：在 **Gate protocol** 规定的时点 **必须**输出已填写的 Gate log；**禁止**在 Gate log 显示前置阶段仍为 `no` 时执行下一阶段关键操作（训练、循环、终稿报告、关实例）
6. **对话输出**：遵守上文「对话与对用户输出」— **先事实（Gate log / 命令 / 结果）后短评**，不写空话套话；**少问**泛用「是否继续」，多问**具体选项/参数**（见该节与 **Confirmation policy**）。
7. **推进方式**：能执行则**展示命令后执行**；阶段内无新增实质分叉时默认连续推进，不得用重复的「是否继续」代替实质进展。

## Command display policy (mandatory)

For **every key operational step**, you **must show the exact shell commands** (or exact `git`/equivalent invocations) you will run—**before** execution—with project-specific values filled in wherever already known (`<project_root>`, `<env_name>`, `<training_command>`, etc.). Do **not** describe steps only in prose; the user must be able to copy-paste or audit the command block.

**Key steps that always require an explicit command listing:**

| Phase | Examples of what to display |
|-------|-----------------------------|
| Step 1 | `cd`, `git fetch`/`checkout`/`checkout -b`, creating `results.tsv` header |
| Step 2.5 | `conda activate …` or `conda run -n …`（新建环境仅 `conda create` / `conda env create`）；展示将执行的 `conda`/`pip` 命令行（Lab=yes 时在 SSH 后实例上） |
| Baseline / Step 5 | Full `(<training_command>) > run.log 2>&1`, metric `grep`/`rg` lines, `git add`/`commit`, `git reset --hard` when reverting |
| Step 4 | How one result row is appended to `results.tsv` (tab-safe, e.g. `printf` or documented paste) |
| Step 6 | Path to `autoresearch_report.md` and any shell used to create it (if applicable) |
| Step 7 | Exact Python (or shell) used to call `instance_stop` with `serverId` from Step 2.1 / `create.py` output (if Step 2 ran) |

If a step uses only an editor/tool API and no shell, still **list the equivalent concrete actions** (exact file path + operation) in the same spirit.

## Confirmation policy (mandatory)

**Every step in this document that requires user confirmation—or any material choice (paths, which entrypoint, environment plan, stop limits)—must receive explicit user confirmation before you proceed.** If the user has not confirmed, **stop and ask**; do not assume consent or skip the gate.

**Batch-first rule（强制）:** when multiple confirmations are pending in the same phase, ask them in one consolidated checklist message and wait for a single combined reply; do not split into repeated one-question turns unless the user explicitly asks to answer step-by-step.

**run_tag exception（强制）:** experiment tag (`run_tag`, e.g. `autoresearch/<tag>`) does **not** require user confirmation by default. Auto-generate it directly unless the user explicitly provides a preferred tag value.

**与泛问「是否继续」的界限：** 上列**实质门**未满足时，**必须**问清或列出待填项。**不得**在「仅执行文档规定的下一阶段、Gate 已允许」时，反复用「是否继续」「可以吗」「要不要往下」替代 **Command display + 执行**；此类泛问视为**过多询问**，应删减。

**Checklist-style gates** (non-exhaustive; follow the exact wording in each Step skill below):

- Step 1: project path; if multiple training entrypoints, which one; detection summary (entrypoint + config + how passed in); readiness to enter loop only after this batch is confirmed.
- Step 2: `instance_create` 成功（`create.py` 的 `status == success` / API `code == 0`），SSH 到返回的 host/port/user 已建立 **before Step 2.5 env work when Lab=yes** and before any Step 3 work; **`serverId` 从 `create.py` 一行 JSON 根字段** 持久化供 Step 7 关机。
- Step 2.5: **must explicitly ask** whether an existing env is available; **must resolve image availability first** (`image_available` / `image_unavailable` / `user_declined_image`); **first check `/workspace/envs` for the user-specified env**; if building new, that the planned approach matches `create_env.md` and user confirms before running `conda create` /etc. If `image_available`, prefer image reuse and do not jump directly to new env creation.
- Step 7 (when Step 2 was used): after Step 6, **must ask user whether to stop now**. User `yes` → execute immediately; user `no` → keep pending by user choice; **no reply for 10 minutes** → execute timeout auto-stop. In all execution branches, `instance_stop` result (`code == 0` or failure) must be surfaced—automation is not “cleanly finished” while the instance remains provisioned unintentionally.
- Step 5 (before `LOOP FOREVER`): stop conditions and per-run limits—**must explicitly ask and get user confirmation** of proposed values (you may **suggest** defaults inferred from README/logs, but **must not** start the loop or any training until the user explicitly confirms or adjusts them).

**Exception (narrow):** After the user has confirmed **entry into the experiment loop** as above, individual iterations inside `LOOP FOREVER` run **without** re-confirming each round (unless the user stops the run)—see `skill_06loop.md`.

---

**Previous（管线顺序）:** `skill_01lab_instance.md`（Lab=no 且跳过建机时，上一阶段视为未执行建机，直接进入本文件）  
**Next skill:** `skill_03setup.md`
