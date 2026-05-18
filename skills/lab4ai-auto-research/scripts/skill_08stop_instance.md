# Step 8: Stop lab instance (mandatory after Gate Step 6 when Gate Step 2 ran)

**Prerequisites:** `skill_02policies.md`, `skill_07report.md` complete if an instance was created.

> **STOP — 前置条件：** 若曾执行 **Step 2**（实验室建实例）：未在 Gate log 中将 **Step 6 report = yes** 之前，**不得**调用 `instance_stop`。

Run **after** Step 6 is complete (final report written). Skip this step only if **no** instance was created in **Step 2**.

If Step 2 created an instance, **do not mark this step as skipped/not_applicable by default**. You must ask the user whether to stop now, then follow yes/no/timeout policy below.

Before calling `instance_stop`, explicitly ask the user whether to stop the instance now.

**Timeout fallback (mandatory):**
- If the user explicitly replies "yes", stop immediately.
- If the user explicitly replies "no", keep the instance and record that Step 8 is pending by user choice.
- If there is **no user reply for 10 minutes** after the stop-instance question is sent, automatically execute `instance_stop` to avoid resource leakage, and record in output/Gate log that this was a **timeout auto-stop**.

**`serverId`** must be the **same** value returned when the instance was created in **Step 2.1** (`create.py`); Step 7 is only for stopping that Step 2-created instance (not any other serverId, and never hardcoded per run).

Use **`lab4ai-instance-manage`**（与 **Step 2** 创建为同一技能；本步只做 **关闭**）：

- **优先（与 `lab4ai-auto-research/` 为当前目录时）：** `../lab4ai-instance-manage/SKILL.md`
- **从 `scripts/skill_08stop_instance.md` 解析：** `../../lab4ai-instance-manage/SKILL.md`
- **从 `autoresearch/` 仓库根：** `lab4ai-instance-manage/SKILL.md`

勿在 **`lab4ai-auto-research/`** 下误用 `../../` 指向 `lab4ai-instance-manage`（会跳到仓库根之上）。

按该 SKILL **第二节「关闭实例」** 与 `scripts/stop.py` 执行：调用方式、成功条件与失败处理均以该文档为准。

**Security:** Prefer loading `phone` / `password` from secrets or environment variables instead of committing them to tracked files.

---

**Previous:** `skill_07report.md`
