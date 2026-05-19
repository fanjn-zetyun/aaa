---
name: python_venv_from_project
description: >
  Build isolated Python environments from repository files (environment.yml, requirements.txt,
  pyproject.toml, Pipfile, poetry.lock, etc.). For **autoresearch / lab4ai-auto-research**, **new**
  environment roots must be **Conda (or mamba)** only; use pip/poetry export flows **inside** that conda env
  when needed—never create a new venv/Poetry/pipenv root. Enforce unique env names; never install into system Python.
  Invoke when onboarding a repo or when the user has no usable env and must rebuild.
metadata:
  agent_loop:
    language: zh-CN
---

# 根据项目文件构建 Python 虚拟环境

本技能指导智能体在**任意代码仓库**中，依据项目内已有文件选择正确方式，在**隔离环境**中安装依赖，**禁止**向系统 Python 或用户全局 site-packages 安装包。

**与本仓库 `skill_04environment.md` 一致：新建环境只能使用 Conda 系**（`conda` / `mamba` 的 `conda create`、`conda env create`、`mamba create` 等）。**禁止**用 `python -m venv`、`virtualenv`、`poetry env`、`pipenv --python` 等创建新的独立环境根。若仅有 `requirements.txt` / `pyproject.toml` / `Pipfile`：先 `conda create` 或 `conda env create` 得到命名环境，再在该环境内用 `pip install`（或经用户同意的 `pip install -e .`）满足依赖；**不得**为此另建 venv/Poetry/pipenv 根。若本机无 conda：先与用户确认安装 conda/mamba 或使用实验室已带 conda 的镜像，**不要**退回到 venv 作为「新建」方案。

## 适用场景

- 新克隆仓库后需要可复现的运行环境
- README 未写全，需从 `pyproject.toml`、`requirements.txt` 等推断安装方式
- 需在 **Conda 命名环境** 内落地依赖（可配合 pip；创建根只能是 conda）

## 前置确认（必须）

在执行任何安装命令前：

1. **项目路径（必须询问）**：构建虚拟环境前**必须**向用户询问并确认**项目根目录的绝对路径或经用户认可的路径**（不可默认假定当前目录即项目根）。若用户未明确给出或确认，**不得**扫描 `pyproject.toml`、`environment.yml` 或执行任何创建/安装命令。
2. **确认是否已有可用环境**：询问用户是否已有可用的虚拟环境或环境镜像/模板；若可复用，优先使用。
3. **禁止**：在未进入 **conda 环境**（或用户确认复用的已有环境）、未确认**项目路径**前，执行 `pip install`、`conda install` 等会改动依赖的操作；**禁止**用 `poetry install` / `pipenv install` 去**新建**独立环境根（可在 conda 内用 pip 满足同等依赖）。
4. **环境名称不得冲突**：新建 **conda** 环境前，务必核对本机**已有**的 conda 环境名（如 `conda env list`）、用户已声明占用的**虚拟环境镜像/模板**名称。**新 conda 环境名不得与上述任一已有名称相同**；若重名则换名（如加项目名+日期后缀）或由用户指定唯一名称。

## GPU 前置体检（面向 GPU 训练时强制）

若本次任务是 GPU 训练/推理（默认 autoresearch 场景通常属于此类），在安装依赖前先完成以下检查并记录结论：

```bash
nvidia-smi
conda run -n <env_name> python -c "import torch; print(torch.cuda.is_available())"  # 若 torch 尚未安装可先跳过此条
```

当 `torch` 已安装后，补充：

```bash
conda run -n <env_name> python -c "import torch; print(torch.__version__, torch.version.cuda)"
conda run -n <env_name> python -c "import torch; print(torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'no-cuda')"
```

判定规则：
- `nvidia-smi` 不可用：先修复驱动/运行时，不应继续宣称“GPU 环境就绪”。
- `torch.cuda.is_available() = False`：视为 GPU 未就绪，需回到 CUDA/依赖匹配步骤排查。
- 仅当驱动可见且框架可见 GPU，才可进入训练阶段。

## 第一步：扫描项目中的环境定义文件（按优先级）

在**项目根目录**及常见子目录（如 `deploy/`、`conda/`）中查找，并按下列顺序决定**主策略**（README 若与文件冲突，以 README 为准）。

| 优先级 | 文件 | 典型含义 |
|--------|------|----------|
| 1 | `README.md` / `CONTRIBUTING.md` | 官方推荐的 Python 版本与安装命令 |
| 2 | `environment.yml` / `conda.yml` | 使用 **Conda** 创建环境 |
| 3 | `Pipfile` | **先建 conda 环境**，再在 conda 内用 `pip install`（或 `pipenv requirements` 导出后 pip）；**禁止** `pipenv` 创建独立 env 根 |
| 4 | `poetry.lock` + `pyproject.toml` | **先建 conda 环境**，再在 conda 内 `pip install` / `pip wheel` 等满足依赖；**禁止** `poetry env` 新建根（除非用户仅复用已有 poetry env，本表指「新建」） |
| 5 | `requirements.txt` / `requirements-*.txt` | **conda + pip**：`conda create -n …` 后 `pip install -r`；**禁止** `python -m venv` 作为新建根 |
| 6 | 仅 `pyproject.toml`（无 lock） | 阅读 `[project]` 依赖，用 `pip install -e .` |

辅助信息（用于确定 Python 版本）：

- `.python-version`（pyenv）
- `runtime.txt`（部分 PaaS）
- `pyproject.toml` 中 `requires-python`

## 第二步：选择虚拟环境形态（新建根 = 仅 Conda）

| 形态 | 何时选用 | 备注 |
|------|----------|------|
| **Conda / mamba** | **任何需要新建环境根时** | 唯一允许的创建方式；与系统 Python 隔离 |
| **venv / Poetry / Pipenv 新建根** | — | **禁止**作为 autoresearch 流程中的新建方案 |
| **复用用户已有非 conda 环境** | 用户明确声明且路径可用 | 仅**选用**，不新建；若后续必须新建，仍须 conda |

**原则**：以 README 为准；README 若要求 venv-only 新建，须与用户确认是否改为 conda 等价方案或中止本技能路径。**新建环境根只能 Conda。**

## 第三步：落地命令（示例模板）

以下命令均在**已 `cd` 到项目根**的前提下执行。将 `<env_name>` 替换为项目相关名称（如 `myproj`）。

**命名约束（必须）**：执行 `conda create` / `conda env create` / `mamba create` 等会**新建** conda 环境的命令前，先确认 `<env_name>` **不与已有 conda 环境、已有虚拟环境镜像名、本仓库已有环境目录**重名；**务必保证新名称全局唯一**（至少在本机当前命名空间内不与现有一致）。

### 3.1 Conda + `environment.yml`

**默认推荐：从 `environment.yml` 纯净创建（更可复现）**：

```bash
conda env create -f environment.yml -n <env_name>
conda run -n <env_name> python -c "import sys; print(sys.executable)"
```

**仅在用户确认后作为 fallback：clone `base` 再按 yml 更新**（用于特殊网络/工具链场景，不作为默认）：

```bash
conda create -n <env_name> --clone base
conda activate <env_name>
conda env update -f environment.yml --prune
```

**说明**：`--clone base` 会复制当前 `base` 环境中的包，体积可能较大；与 yml 中 Python 版本或 channel 冲突时，以 `conda env update` 结果为准。

更新已有环境：

```bash
conda env update -f environment.yml --prune
```

### 3.2 仅 `requirements.txt`

**优先（Conda）**：与本技能「优先使用 Conda」一致——先建 conda 环境再 pip：

```bash
conda create -n <env_name> python=3.10 -y
conda activate <env_name>
pip install -r requirements.txt
```

**禁止**：不得以「备选」为由使用 `python -m venv` 新建环境；无 conda 时见上文「若本机无 conda」。

### 3.3 `pyproject.toml`（可编辑安装）

在已激活的 **conda** 环境中：

```bash
pip install -e .
```

### 3.4 国内镜像（可选）

- **pip**：设置 `PIP_INDEX_URL` 为清华等镜像的 `simple` 地址，或 pip 配置 `index-url`。
- **conda**：在 `environment.yml` 或 `.condarc` 中配置 channel 镜像。

安装 **PyTorch CUDA** 等需额外 wheel 源时，按项目 `pyproject.toml` / README 中的 `extra-index-url` 执行，勿默认改写成与项目不一致的源。

### 3.5 GPU 框架与 CUDA 匹配（关键）

选择 GPU 依赖版本时使用以下优先级：
1. 项目 README / 锁文件（`environment.yml`、`poetry.lock`、`requirements*.txt`）明确指定版本；
2. 若项目未写明，使用框架官方兼容矩阵（如 PyTorch CUDA 对应关系）选最接近驱动可支持版本；
3. 不要“拍脑袋”升级到最新 CUDA/torch 组合。

最小执行建议：
- 先确认驱动可见（`nvidia-smi`）；
- 再安装与项目匹配的框架版本；
- 最后做 GPU 冒烟验证（见第四步）。

若出现不兼容（常见为 `CUDA driver version is insufficient`、找不到对应 wheel）：
- 优先回退框架版本到项目文档建议值；
- 其次调整 CUDA 变体；
- 仍失败时，记录失败组合，向用户明确说明并请求选择（换镜像/换实例/降版本）。

### 3.6 PyTorch 安装防超时（强制策略）

当项目依赖 PyTorch 且网络不稳定/离线受限时，按以下顺序执行（不要一次性把所有依赖混在同一条命令）：

1. **先装 PyTorch 主包，再装其余依赖**，避免长链路失败后整批回滚。
2. **强制开启超时与重试参数**（pip 默认超时偏短，易失败）。
3. **优先使用二进制 wheel**（避免源码编译导致超时或卡住）。
4. 若在线安装失败，切到 **wheel 预下载 + 离线安装** 路径。

在线安装（示例，按项目 README 的 CUDA 变体替换）：

```bash
# 仅示例：根据项目要求选择 cu118/cu121/cu124 等，不要拍脑袋替换
conda run -n <env_name> python -m pip install --upgrade pip
conda run -n <env_name> python -m pip install \
  --timeout 120 --retries 8 --prefer-binary --no-cache-dir \
  torch torchvision torchaudio \
  --index-url https://download.pytorch.org/whl/cu121
```

再安装项目其余依赖（与 torch 分开）：

```bash
conda run -n <env_name> python -m pip install \
  --timeout 120 --retries 8 --prefer-binary --no-cache-dir \
  -r requirements.txt
```

离线/半离线路径（推荐用于实验室无外网）：

```bash
# 有网机器：预下载 wheel
python -m pip download \
  --dest /tmp/torch_wheels \
  torch torchvision torchaudio \
  --index-url https://download.pytorch.org/whl/cu121

# 将 /tmp/torch_wheels 复制到目标机器后离线安装
conda run -n <env_name> python -m pip install \
  --no-index --find-links /path/to/torch_wheels \
  torch torchvision torchaudio
```

执行约束：
- PyTorch 相关安装命令必须展示完整参数（`--timeout`、`--retries`、索引源）后再执行。
- 若出现超时，不要直接改成“无限重试”；应记录失败索引源与 CUDA 变体，再按兼容矩阵回退。
- 若日志提示无法访问 `huggingface.co`/`download.pytorch.org`，优先判断为网络或离线限制，并转离线路径。

## 第四步：校验环境是否就绪

1. 打印 Python 解释器路径，确认**不在**系统目录：

   ```bash
   python -c "import sys; print(sys.executable)"
   ```

2. 尝试导入核心依赖（按项目而定），例如：

   ```bash
   python -c "import torch; print(torch.__version__)"
   ```

3. **GPU 冒烟测试（GPU 场景必须）**：

   ```bash
   conda run -n <env_name> python -c "import torch; assert torch.cuda.is_available(); x=torch.randn(2,2,device='cuda'); print(x.device, torch.cuda.get_device_name(0))"
   ```

4. 若项目提供 `Makefile` / `nox` / `tox` 中的 `lint` 或 `test`，可在用户同意下轻量运行以验证。

**GPU 环境就绪判定（建议写入日志/回执）**：
- 解释器路径位于目标 conda 环境；
- `nvidia-smi` 可用且识别 GPU；
- 框架可识别 CUDA（如 `torch.cuda.is_available() == True`）；
- 最小 GPU 张量计算成功。

## 禁止事项（必须遵守）

- 禁止 `sudo pip install`、禁止向系统 Python 安装包。
- 禁止**未询问并确认项目路径**就创建 conda 环境或安装依赖。
- 禁止在未确认项目路径与用户是否复用已有环境时，擅自执行全量安装。
- 禁止使用与**已有 conda 环境名或已有虚拟环境镜像名**相同的新环境名，未核对就 `conda create -n …`。
- **禁止** `python -m venv` / `poetry env` / `pipenv` 等创建新的非 conda 环境根（与本技能「仅 conda 新建」一致）。
- 若项目约定**不得修改** `environment.yml`、`requirements*.txt`、`pyproject.toml`、`poetry.lock`、`Pipfile.lock` 等锁文件，则只**读取**这些文件来安装，不擅自改写。

## 故障排查简表

| 现象 | 可能原因 | 处理方向 |
|------|----------|----------|
| Python 版本不符 | `requires-python` 与当前解释器不一致 | 用 conda/pyenv 指定版本重建 |
| 某包找不到 | 私有源、额外 index、可选依赖组 | 读 `pyproject.toml` 的 `[project.optional-dependencies]` |
| CUDA 版 PyTorch 装错 | 未使用官方/镜像的 cu 索引 | 按 README 或项目文档补全安装命令 |
| PyTorch 安装超时 | 网络抖动、默认超时过短、一次装包过多 | 拆分 torch/其余依赖；加 `--timeout --retries`；必要时改用 wheel 离线安装 |
| `torch.cuda.is_available()==False` | 驱动不可见、CUDA 变体不匹配、CPU 版 torch | 先 `nvidia-smi`，再核对 torch+cuda 版本组合并重装 |
| 权限错误 | 误用系统 pip | 确认已 `conda activate`（或 `conda run`）后再 `pip install` |

## 小结

1. **必须先询问并确认项目根路径**，再谈环境与安装；未确认路径不得操作。
2. 确认**是否复用已有环境**。
3. **新 conda 环境名**与已有 conda/镜像目录**不得重名**，再执行创建命令。
4. 扫描 **`README` → conda → lock 文件 → requirements → pyproject** 决定依赖安装方式；**新建根始终 conda**。
5. 在**已创建的 conda 环境**内安装；自动化场景优先 `conda run -n`，减少 shell 激活差异。
6. GPU 场景必须补做驱动与 CUDA 冒烟校验（`nvidia-smi` + `torch.cuda.is_available()` + 最小 GPU 张量计算）。
7. 全程**不污染系统环境**，不擅自修改环境定义文件（除非用户与项目允许）。

