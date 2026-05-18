---
name: lab4ai-image-manage
description: Lab4AI 镜像能力：① 拉取可用 imageTag 列表（images_list）；② 根据本地项目路径或 git 仓库 README / 常见依赖文件启发式推荐与项目说明最匹配的镜像标签，供创建实例时使用。
---

# Lab4AI 镜像管理 Skill (lab4ai-image-manage)

包含两个脚本：

| 脚本 | 作用 |
|------|------|
| `scripts/show_image.py` | 调用 `https://tools.lab4ai.cn/api/v1/tools/images_list/invoke` 返回全部可选 `imageTag` |
| `scripts/image_choose.py` | 读取项目 **`README.md`**（及少量依赖文件）提取 PyTorch / CUDA / TensorFlow 等线索，结合列表打分并给出 **推荐 `imageTag`** |

## 前置条件

- `/root/.openclaw/.env` 中配置了 `LAB4AI_PHONE` 和 `LAB4AI_PASSWORD`（与 **`lab4ai-instance-manage`** 一致）
- 可选安装 `httpx`；未安装时 `show_image.py` 使用标准库 `urllib`（`instance-manage` 的创建/关机脚本为 `httpx` 专用，与此不同）
- 使用 **`git_url`** 时本机需可用 `git` 命令；默认浅克隆 `--depth 1`

---

## 一、`show_image.py` — 镜像列表

### 入参（`paras` 或环境变量）

| 参数 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `phone` | string | 条件 | 与 `password` 二选一可用环境变量代替 |
| `password` | string | 条件 | 同上 |

### 命令行

```bash
python scripts/show_image.py '{"phone":"<phone>","password":"<password>"}'
python scripts/show_image.py
```

### 返回（一行 JSON）

与平台接口一致：`{"code": 0, "message": "", "data": ["<imageTag>", ...]}`

---

## 二、`image_choose.py` — 按 README 推荐镜像

### 入参 `paras`（JSON）

**路径与仓库（二选一，必填其一）**

| 字段 | 说明 |
|------|------|
| `project_root` | 本地项目根目录（也可用别名 `path` / `local_path`） |
| `git_url` | Git 克隆地址（也可用别名 `repo_url`） |
| `git_branch` / `branch` | 可选，克隆指定分支 |

**鉴权（与 `show_image` 相同）**

| 字段 | 说明 |
|------|------|
| `phone` | 可选，缺省读 `LAB4AI_PHONE` |
| `password` | 可选，缺省读 `LAB4AI_PASSWORD` |

**其它**

| 字段 | 默认值 | 说明 |
|------|--------|------|
| `max_alternates` | `5` | 除推荐外返回的备选标签数量 |
| `keep_clone` | `false` | 为 `true` 时克隆目录不删除（仅调试用） |

### 说明文档与依赖扫描

1. **优先**读取项目根下 `README.md` / `readme.md`（大小写几种常见命名）。
2. **补充**扫描（若存在则读入前若干字符）：`environment.yml`、`conda.yml`、`requirements.txt`、`pyproject.toml`，用于增强对 `torch` / `cuda` / `tensorflow` 的识别。
3. 从 README/依赖文本中用正则**启发式**提取版本线索（非严谨解析，复杂 monorepo 需人工复核）。

### 命令行

```bash
# 本地路径
python scripts/image_choose.py '{"project_root":"/path/to/repo"}'

# Git（浅克隆）
python scripts/image_choose.py '{"git_url":"https://example.com/org/repo.git","git_branch":"main"}'
```

### 返回（一行 JSON）

成功时 `code == 0`，`data` 为对象，例如：

| 字段 | 说明 |
|------|------|
| `imageTag` | 推荐的镜像标签（传给 **`lab4ai-instance-manage`** 的 `create.py`，意图中加 `image=...`） |
| `alternates` | 备选标签列表 |
| `readme_path` | 实际读到的 README 路径，未找到则为空字符串 |
| `project_path` | 本地项目路径；`git_url` 时为临时克隆目录（默认结束后删除） |
| `hints` | 解析出的线索：`torch` / `cuda` / `tensorflow`（整数列表形式）、`wants_gpu` |
| `reason` | 简短说明为何给出该推荐 |

失败时 `code != 0`，`message` 说明原因，`data` 为 `{}`。

### 成功示例（结构示意）

```json
{
  "code": 0,
  "message": "",
  "data": {
    "imageTag": "lf0.9.4-tf4.57.1-torch2.8.0-cu12.6-1.1",
    "alternates": ["lf0.9.5-tf4.57.3-torch2.9.1-cu12.6-1.0"],
    "readme_path": "/tmp/lab4ai_image_choose_xxx/README.md",
    "project_path": "/tmp/lab4ai_image_choose_xxx",
    "hints": {
      "torch": [2, 8, 0],
      "cuda": [12, 6],
      "tensorflow": [],
      "wants_gpu": true
    },
    "reason": "README/deps torch ~2.8.0; CUDA ~12.6"
  }
}
```

---

## 与创建实例的关系

- **`lab4ai-instance-manage`** 的 `create.py` 需要 `imageTag`（可用默认或意图中 `image=...`）：可先 **`image_choose`** 得推荐值，再用 **`show_image`** 核对全列表或改选。
- **推荐结果仅为启发式**，若 README 未写清版本或与平台镜像命名不一致，请以人工判断为准。

## 注意事项

1. **勿将手机号、密码写入仓库**；用环境变量或运行时 `paras`。
2. 接口或标签命名变更时，以 `scripts/show_image.py` 的 `API_URL` 及 `scripts/image_choose.py` 内解析逻辑为准，并同步更新本 **`SKILL.md`**。
