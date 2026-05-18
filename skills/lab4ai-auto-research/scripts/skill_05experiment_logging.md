# Step 5: Experimentation scope, output format, logging results (Gate Steps 3–4)

**Prerequisites:** `skill_02policies.md`；**`skill_03setup.md`（Gate Step 1；文档 Step 3）** 与 **`skill_04environment.md`（Gate Step 2.5；文档 Step 4）** 已完成（Lab=yes 时在 SSH 后的实例上做 2.5）。当 Lab=yes 时，**Step 2** 须先于 Step 2.5；管线顺序下 **Step 1 可在 Step 2 之后**完成，但进入训练前 Gate log 须均已达标。

## Step 3: Experimentation

> **STOP — 前置条件：** 若 Lab=yes：须 **Step 2**（含 `serverId`、SSH）与 **Step 2.5**（环境）均已满足；若 Lab=no：须 **Step 2.5** 满足（Gate log 中 Step 2 为 skipped）。在此之前**不得**为实验目的修改训练相关代码或配置。Step 3 的实质工作发生在 **Step 5 循环内**；不要在没有 Step 5 预循环确认的情况下单独「先跑一轮训练」。

Each experiment should focus on one clear hypothesis (hyperparameters, architecture, optimizer, training strategy, etc.).

**Allowed:**
- Modify training-related code/config within project-allowed scope (typically training entrypoint, model, optimizer, hyperparameter config files).

**Not allowed:**
- Modify files explicitly forbidden by README.
- Break evaluation protocol (metric definition or validation flow), making results incomparable.
- Modify environment configuration files (e.g., `environment.yml`, `conda.yml`, `requirements*.txt`, `pyproject.toml`).

**Goal:**
- Optimize the primary project metric (based on direction defined in README).
- When results are close, prefer simpler and more maintainable solutions.

**First run:**
- Run a baseline first (ideally without code changes) to establish a comparison point.

## Output format

Log formats vary by project. Standardize by redirecting training output to `run.log`, then extract:

- Primary metric (e.g., `val_loss`, `accuracy`, `bleu`, `mAP`, `val_bpb`)
- Peak memory/VRAM (if available)

Example (adjust by project fields):

```bash
grep -E "val_|acc|bleu|mAP|loss|peak_vram_mb|max_memory" run.log
```

## Step 4: Logging results

After each run, record in `results.tsv` (tab-separated, not comma-separated):

```tsv
commit	<primary_metric>	memory_gb	status	description
```

Field definitions:
1. `commit`: short hash of the experiment commit (`none` if git is unavailable)
2. `<primary_metric>`: metric value (`nan` or `0` for crashes)
3. `memory_gb`: peak memory/VRAM (`0.0` if unavailable)
4. `status`: `keep` / `discard` / `crash`
5. `description`: short note of hypothesis or change

`results.tsv` is recommended to stay untracked and not committed (unless the project requires it).

**Example: append one experiment row (tabs between fields; show the exact line you will run):**

```bash
# After each run, one line (example—replace values with real commit hash, metric, etc.)
printf '%s\t%s\t%s\t%s\t%s\n' "<short_commit>" "<metric_value>" "<memory_gb>" "keep|discard|crash" "one-line description" >> results.tsv
```

---

**Previous:** `skill_04environment.md` — **Next:** `skill_06loop.md`
