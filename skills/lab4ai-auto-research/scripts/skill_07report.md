# Step 7: Final automation experiment report (mandatory; Gate Step 6)

**Prerequisites:** `skill_02policies.md`; experiment loop ended or user interrupted (no new rounds). See `skill_06loop.md`.

> **STOP — 前置条件：** 未在 Gate log 中将 **Loop status = ended**（或用户中断且不再开新轮）之前，**不得**把 Step 6 标为完成或省略报告。零轮实验也须写**最小报告**说明原因。

Producing the experiment report is **required** for every automation run. There is **no** optional skip.

When the automation **ends** (stop conditions satisfied, limits reached, or user interrupt), you **must** produce a **single final report** for the user. This step is **obligatory** before the task is considered complete.

**Artifact (required):** write `autoresearch_report.md` (or `experiment_report.md`) in the **project root**, unless the user or README specifies another path or name. The file **must** be created (or overwritten) so the user always has a durable record.

**Example (if creating via shell; otherwise state the exact file path and use your editor tool—still show the user the path):**

```bash
cd "<project_root>"
# e.g. touch + edit, or heredoc—show the real command you use
ls -la autoresearch_report.md
```

**Report must include (adjust labels to the project’s primary metric):**

1. **Metadata**
   - Project path (confirmed root), experiment branch name (e.g. `autoresearch/<tag>`), report generation time (wall-clock).
   - Reason the run ended (e.g. max iterations, time limit, wall-clock stop, user interrupt).

2. **Summary of outcomes**
   - Primary metric name and direction (higher vs lower is better).
   - **Best result**: best `<primary_metric>` value, corresponding `commit` short hash, and one-line **description** from `results.tsv`.
   - Optional: baseline (first `keep` or first valid run) vs best, if comparable.

3. **Full table (or excerpt)**
   - Copy or summarize `results.tsv` (all rows, or last N rows if very long), so the user can audit every round.

4. **Counts**
   - Number of runs with `status` = `keep` / `discard` / `crash` (if recorded).

5. **Notable failures**
   - Brief list of recurring errors or OOM patterns (from `run.log` / `description` columns), without dumping huge logs.

6. **Next steps (short)**
   - 1–3 concrete suggestions (e.g. follow-up hypotheses, config to try, or “revert branch to best commit”).

**If `results.tsv` is missing or empty:** state that clearly, list what was attempted, and point to any partial logs (`run.log` paths) if available.

---

**Previous:** `skill_06loop.md` — **Next:** `skill_08stop_instance.md` (if Step 2 lab instance ran)
