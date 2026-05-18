# Step 6: The experiment loop (Gate Step 5)

**Prerequisites:** 管线 **skill_01→skill_04** 已按 Gate 完成：`skill_01lab_instance.md`（Lab=no 为 skipped）、`skill_02policies.md`、`skill_03setup.md`、`skill_04environment.md`；并阅读 `skill_05experiment_logging.md` 的 Step 3–4 规则。

> **STOP — 前置条件：** 未在 Gate log 中将 Step 1、（**Step 2** 若 Lab）、**Step 2.5** 标为 `yes`（Lab=no 时 Step 2 为 skipped），且 **Step 5 pre-loop done = yes**（用户已明确确认停止条件与单轮时限）之前，**不得**执行 `LOOP FOREVER` 或任何训练命令。这是最常见的被跳过的关键步骤。

Run experiments continuously on a dedicated branch:

Before starting the loop, you **must** obtain **explicit user confirmation** of stop conditions (ask once, list clearly). Examples:
- Maximum number of experiment iterations (e.g., stop after N runs)
- Total automation duration (e.g., stop after X hours)
- Specific wall-clock stop time (e.g., stop at 07:30 local time)
- Manual-stop only mode (run until user interrupts)
- **Per-run wall-clock limit** (a.k.a. observation window): maximum time a single training run is allowed before you treat it as stuck or failed (must align with the real task—minutes for short jobs, hours for large pretraining).

If the user does not propose values, **you may infer** reasonable limits from the README, training time budget, or prior `run.log` behavior—then **present that proposal to the user and require explicit confirmation** before starting `LOOP FOREVER`. **Do not** start the loop until the user confirms (or edits) these limits.

**Per-run timeout (do not use a one-size-fits-all number):** Derive the limit from, in order of priority:
1. User-confirmed per-run / observation duration (if given).
2. README or config (fixed epoch count, wall-clock training budget, `max_steps`, scheduler, etc.).
3. A **baseline run**: after the first successful training, read wall time from logs (e.g. `training_seconds`, `total_seconds`, or timestamps) and set subsequent limits to a **reasonable multiple** of that (e.g. 1.5×–2×) plus a small buffer for startup and evaluation—**not** an arbitrary short default that would kill long-running jobs.
4. If nothing is known yet, use a conservative cap only for the **first** exploratory run to avoid infinite hangs; then replace it using (3).

Do **not** assume a fixed duration such as “10 minutes” for every project: CV/NLP small loops may finish in minutes; large-scale training may legitimately run for hours.

**Autonomous loop (no per-round confirmation):** **After** the user has confirmed all pre-loop gates (including stop conditions above), **proceed on your own** from one experiment to the next. Do **not** ask the user to confirm each round, each change, or whether to continue. Only stop when the **user-confirmed** stop conditions are met, or when the user explicitly interrupts.

**User may stop at any time:** While the loop is running, the user **may choose to stop** the automation at any moment (e.g. explicit interrupt, “stop experiment” instruction, or platform stop signal). When the user stops: do **not** start another training round; terminate any in-flight training job safely if possible; leave the repo in a consistent state; then **must** complete **Step 6** (final report), noting that the run ended due to **user stop**.

LOOP FOREVER:

1. Check git state (current branch, start commit, current best result)
2. Make one round of changes (based on a single hypothesis)
3. Commit changes
4. Activate the selected virtual environment first, verify it is active (`python -c "import sys; print(sys.executable)"`), then run training and redirect logs: `(<training_command>) > run.log 2>&1`
5. Extract primary metric and memory from `run.log`
6. If extraction is empty, treat as crash: inspect `tail -n 50 run.log`, then decide to fix or skip
7. Write to `results.tsv`
8. If the metric improves (by the defined direction), keep the commit and advance
9. If not improved, revert to the round start commit or current best commit

**Example commands for one loop iteration (show a filled-in block before each run; adjust metric grep to the project):**

```bash
cd "<project_root>"
# MUST use conda env (or user-confirmed reused env) per Step 2.5; new env roots = conda only. Verify interpreter path:
python -c "import sys; print(sys.executable)"
git status
git rev-parse HEAD   # record round-start SHA if needed

# After code edits:
git add -A
git commit -m "autoresearch: <short hypothesis>"

(<training_command>) > run.log 2>&1

grep -E "val_|acc|bleu|mAP|loss|peak_vram_mb|max_memory|val_bpb" run.log | tail -n 20
# If empty: tail -n 50 run.log

# On discard / revert to round start:
# git reset --hard <round_start_sha>
```

The idea is that you are a completely autonomous researcher trying things out. If they work, keep. If they don't, discard. And you're advancing the branch so that you can iterate. If you feel like you're getting stuck in some way, you can rewind but you should probably do this very very sparingly (if ever).

**Timeout**: If a run exceeds the **current** per-run limit (from the rules above), terminate the process, record as failure or `crash` in `results.tsv`, and continue the loop. Refresh the limit when the README, user, or baseline logs give you a better estimate.

**Crashes**: If a run crashes (OOM, or a bug, or etc.), use your judgment: If it's something dumb and easy to fix (e.g. a typo, a missing import), fix it and re-run. If the idea itself is fundamentally broken, just skip it, log "crash" as the status in the tsv, and move on.

**NEVER STOP (agent-side only):** Once the experiment loop has begun (after the initial setup), do NOT pause to ask the human if you should continue. Do NOT ask "should I keep going?" or "is this a good stopping point?". The human might be asleep, or gone from a computer and expects you to continue working *indefinitely* until stop conditions are met or the user explicitly interrupts—no intermediate confirmation required. **The user may still stop the run at any time** (see **User may stop at any time** above); this rule only forbids *you* from idling while waiting for permission to continue. You are autonomous. If you run out of ideas, think harder — read papers referenced in the code, re-read the in-scope files for new angles, try combining previous near-misses, try more radical architectural changes. The loop runs until the human interrupts you, period.

**Autonomy**: Once in the loop, continue autonomously until stop conditions are met or the user explicitly interrupts—no intermediate confirmation required.

**Before exiting the automation session:** you **must** complete **Step 6** and deliver the final report artifact. Ending without a written report is **not allowed** (even if the loop ran zero experiments or crashed early—then write a minimal report explaining why). If **Step 2** (lab instance) ran, **then** run **Step 7** to stop the instance (after the report is written).

---

**Previous:** `skill_05experiment_logging.md` — **Next:** `skill_07report.md`
