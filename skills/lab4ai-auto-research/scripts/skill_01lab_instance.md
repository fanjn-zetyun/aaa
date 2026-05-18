# Step 1: Provision compute instance (mandatory before Gate Step 2.5 environment work on the lab when Lab=yes)

**Prerequisites:** Gate log 已初始化；在本阶段任何创建动作前，**必须先询问用户是否创建实例（Lab instance flow: yes/no）**并记录结果；仅当 **Lab instance flow = yes** 时继续本阶段创建（本阶段为管线 **`stages` 首段**，先于 **`skill_02policies.md`** / **`skill_03setup.md`**）。

> **STOP — 前置条件：** 首先必须问清「是否创建实例」。**未经用户明确回答（yes/no）时，禁止跳过本阶段，且不得进入 `skill_02policies.md` 或任何后续阶段。** 若用户答 **Lab = no**：本整节 **skipped**，须在 Gate log 标明 **`Step 2 skipped`**，并进入下一阶段 **`skill_02policies.md`**。若用户答 **Lab = yes**：可按 **`lab4ai-instance-manage`** 创建实例并 SSH；**不要求** Gate log 中 Step 1 已先于本阶段完成（与 `pipeline.yml` 中 **instance_provision → policies → setup** 一致）。**须**在进入 **`skill_02policies.md`** 前补全 Gate log 中 Lab 与 Step 2 相关行。


### 1.1 Create instance via dedicated skill

Use **`lab4ai-instance-manage`**（创建 + 关闭由同一技能文档覆盖；本步只做 **创建**）：

- **Skill 路径（与 `pipeline.yml` 的 `root: lab4ai-auto-research` 一致时，优先用这条）：** `../lab4ai-instance-manage/SKILL.md`  
  （从 **`lab4ai-auto-research/`** 向上一级到 `autoresearch/`，再进入 `lab4ai-instance-manage/`。）
- **若工具只能按本文件所在目录解析**（`scripts/skill_01lab_instance.md`）：`../../lab4ai-instance-manage/SKILL.md`
- **若当前工作目录已是 `autoresearch/` 仓库根：**`lab4ai-instance-manage/SKILL.md`

勿使用 `../../` 从 **`lab4ai-auto-research/`** 作为当前目录去解析——会跳到 `autoresearch` 的父级，从而找不到 `lab4ai-instance-manage`。

按该 SKILL **第一节「创建实例」** 与 `scripts/create.py` 执行：参数、调用方式、成功条件与错误处理均以该文档为准。可选地在自然语言意图中使用 `image=...` 指定 `imageTag`（解析规则见 **`lab4ai-instance-manage/SKILL.md`**）；未指定时使用脚本内默认镜像。

**Persist `serverId` for teardown:** After a successful create, save the returned `serverId` in automation state (environment variable, ephemeral local file outside git, or agent memory) — **Step 7** requires this exact value for `instance_stop`. Do not rely on recalling it from logs alone if the session may reset.

### 1.2 SSH login using returned fields

从 **`create.py` 打印的一行 JSON**（根对象）读取：

- `ssh_host`, `ssh_port`, `ssh_user`, `ssh_pass`

（若你解析的是原始 HTTP 响应里的 `data` 对象，则对应 `sshHost` / `sshPort` / `sshUser` / `sshPwd`。）

**Interactive (manual password entry):**

```bash
ssh -p <ssh_port> <ssh_user>@<ssh_host>
# When prompted, paste the value of ssh_pass from the create script JSON.
```

**Non-interactive automation (only if your environment allows it; avoid committing passwords):**

Prefer reading password from a **runtime variable** populated from the create response, not hardcoding in repo docs.

```bash
# Example with sshpass (must be installed): NEVER log or commit SSHPASS
export SSHPASS='<paste_ssh_pass_from_response>'
sshpass -e ssh -o StrictHostKeyChecking=accept-new -p '<ssh_port>' '<ssh_user>@<ssh_host>'
unset SSHPASS
```

**Security:** Do not store lab passwords or `ssh_pass` in git-tracked files; rotate credentials if they were ever committed.

**推进：** SSH 就绪且 Gate 允许进入 2.5 时，**不要**再泛问「是否继续」；按 `skill_02policies.md`「对话与对用户输出」与 **Confirmation policy** 处理。环境等**实质**未定的问题仍按 **`skill_04environment.md`** 询问。

### 1.3 Gate

- Confirm the create skill reports success (`status` == `success` / API `code == 0` per instance-manage SKILL).
- Confirm SSH session is active on the instance before marking **Step 2** done in the Gate log.
- **Step 2.5 is after Step 2 when Lab=yes:** on the SSH session, run **`skill_04environment.md`** end-to-end (ask existing env, `/workspace/envs`, create/activate as approved). Step 2 does **not** replace Step 2.5; it only delivers instance + SSH + persisted `serverId`.

---

**Previous:** 无（管线首阶段）— **Next:** `skill_02policies.md`
