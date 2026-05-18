# Step 4: Environments (Gate Step 2.5)

**Prerequisites:** `skill_02policies.md`、`skill_03setup.md` 已完成（Gate log: Step 1 = yes）。若 **Lab instance flow = yes**，**`skill_01lab_instance.md`（Gate Step 2；文档 Step 1）** 须已完成（`instance_create` 成功、`serverId` 已保存、SSH 已可用），本步在 **SSH 后的实验室实例** 上执行环境与依赖；若 **Lab = no**，在本机/当前工作区执行即可。

> **STOP — 前置条件：** 未在 **Gate log** 中将 Step 1 标为 `yes` 之前，**不得**创建/激活环境或安装依赖。若 **Lab = yes**，还须先将 **Step 2** 标为 `yes`（再在本步完成 **Step 2.5**）。

### 构建环境之前（强制）

在**任何**会新建、重建或实质填充虚拟环境的行为之前（包括但不限于 `conda create`、`conda env create`、`mamba create`（与 conda 同类）、为「搭环境」而执行的大批量 `pip install` / `conda install`），**必须先向用户发问并得到明确答复**：是否已有**可直接用于本项目**的虚拟环境（请用户说明环境名、路径，或是否使用 `/workspace/envs` 下已有目录、是否复用镜像/模板等）。**未得到用户关于「有无现成环境」的明确答复前，禁止开始构建新环境。** 只读检查（如查看 README、`conda env list` 列出名称）允许；一旦会写入磁盘或触发下载，即视为「构建」须已满足本段。

**镜像检查（必须在新建前完成并留痕）：**
1. 明确询问：是否存在可复用的环境镜像/模板（image/snapshot/base env）。
2. 给出检查结论之一：`image_available` / `image_unavailable` / `user_declined_image`。
3. 仅当结论为 `image_unavailable` 或 `user_declined_image` 时，才允许执行 `conda create` / `conda env create`。
4. 若 `image_available`，优先复用镜像方案，**不得**直接跳到新建环境。

A virtual environment is mandatory. **新建环境（从 0 创建或等价重建）仅允许 Conda 系**：只可用 `conda` / `mamba` 的 `conda create`、`conda env create`、`mamba env create` 等创建环境根；**禁止**用 `python -m venv`、`virtualenv`、`poetry env`、`pipenv` 等创建新的独立 Python 环境根。若用户已有非 conda 环境且仅**复用**之，可继续用该解释器；一旦需要**新建**，必须走 Conda。After the mandatory question above, if you still need to create or select tooling, use this file priority:

1. `environment.yml` / `conda.yml`
2. `requirements*.txt`

If the user confirms an existing env: use/activate it (or `conda run` / explicit interpreter path); **do not recreate** an equivalent.

**首轮询问须一并覆盖：** 除「是否已有可直接用于本项目的虚拟环境」外，是否使用 **`/workspace/envs`** 下某路径、是否存在可复用的环境镜像/模板。用户指明路径后，在提出 `conda create` / 新建目录等命令前**核实**该路径是否存在且可用。

若已确认有可用的本地或镜像环境：**直接选用**，**禁止**再创建等价新环境。仅当用户明确没有可用环境时，再严格按项目说明（尤其 README）并 **遵循 `create_env.md`** 新建；**不要**自行拼凑安装命令。**凡是“需要新建环境”的场景，必须委托并执行 `scripts/create_env.md`；不得绕过该文档直接自行设计安装流程。**



Requirements:
- **新建环境仅 Conda**：创建环境根只用 `conda`/`mamba`；禁止 `python -m venv`、`poetry env`、`pipenv` 等新建独立环境。
- **须先满足**上文「### 构建环境之前（强制）」：未完成「是否已有可用虚拟环境」的询问与明确答复前，不得执行会写入磁盘或触发下载的环境构建。
- **须先完成镜像检查结论**（`image_available` / `image_unavailable` / `user_declined_image`）并在对话中明确记录；无结论不得新建环境。
- **需要新建环境时必须使用** `scripts/create_env.md`：创建策略、GPU 校验、回退逻辑以该文档为准，不得在本文件中另起一套流程。
- 若新建环境阶段出现 PyTorch 下载超时，按 `scripts/create_env.md` 的「PyTorch 安装防超时（强制策略）」执行（重试参数、分步安装、wheel 离线路径）。
- Before any install, **show the full command block** you will run (see **Command display policy** in `skill_02policies.md`).
- Before creating any new environment, **ask for the target env name/path** and verify `/workspace/envs/<user_env_name>` (when applicable) **after** the mandatory availability question is resolved.
- Never install packages into the system/global environment (system Python, base env, user site-packages).
- Only install packages inside an allowed virtual environment that the user has confirmed (conda env environment), and only as required by the project.
- The virtual environment must be created according to project requirements (especially README instructions)
- Python version must follow explicit project configuration (e.g., `environment.yml`, `.python-version`, `pyproject.toml`)
- If README explicitly mandates one method , follow README
- No explicit shell activation is required; run commands via the selected environment's executable path (prefer `conda run -n <env_name> ...` / `conda activate`；若仅**复用**用户已有非 conda 环境，可用其解释器路径，但**不得**为此新建 venv/Poetry/pipenv 根)。
- Do not run training, evaluation, or experiment-loop commands before selecting a confirmed virtual environment.

---

**Previous:** `skill_03setup.md` — **Next:** `skill_05experiment_logging.md`（Step 3–4 规则）→ `skill_06loop.md` 预循环与循环（见 `skill_02policies.md` 阶段图）
