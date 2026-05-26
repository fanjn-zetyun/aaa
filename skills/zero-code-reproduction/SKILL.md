---
name: zero-code-reproduction
description: >
  无代码论文复现脚手架生成器 (Zero-Code Reproduction Scaffolding Generator)。
  T型架构：通用路由层 + 通用解析引擎(Base) + 垂直行业插件(Plugins)。
  输入一篇PDF论文，自动判断学科方向，提取核心要素（公式/超参/数据集/方法步骤），
  路由到对应方向插件生成可执行的复现脚手架（代码/SOP/Pipeline），
  附带置信度报告和人工补全清单。
version: "1.0"
tags: [research, reproduction, paper-parsing, agentic-workflow, scaffolding]
triggers:
  - 论文复现
  - 复现这篇论文
  - zero-code reproduction
  - paper reproduction
  - 从论文生成代码
  - reproduce this paper
  - 生成复现脚手架
related_skills:
  - zero-code-repro-csai
  - crystal-structure-extraction
  - zero-code-repro-biodefense
  - lab4ai-instance-manage
---

# Zero-Code Reproduction — 无代码论文复现脚手架生成器

## 1. 定位与边界

### 1.1 这个Skill是什么

一个**复现脚手架生成器 (Reproduction Scaffolding Generator)**。
它帮助研究人员完成论文复现中前 70% 的"脏活累活"：

- 解析论文全文，提取所有可复现要素
- 自动判断学科方向，路由到专用处理模块
- 生成结构化的代码框架 / 实验SOP / 分析Pipeline
- 标注每个产出物的置信度和需要人工补全的地方

### 1.2 这个Skill不是什么

- ❌ 不是"一键跑通SOTA结果"的魔法工具
- ❌ 不保证生成的代码开箱即用（需要人工调试最后30%）
- ❌ 不替代领域专家的判断（特别是湿实验SOP）
- ❌ 不做实际训练/实验执行（无GPU、无实验室）

### 1.3 复现层次定义

```
Level 1: 理解复现  — "我看懂了论文在做什么"              → Skill 自动完成
Level 2: 脚手架复现 — "我有了可运行的代码/SOP框架"        → Skill 核心产出 ✅
Level 3: 结果复现  — "我跑出了和论文一致的数字"           → 需要人工调试+算力
Level 4: 完全复现  — "独立团队验证了所有claims"            → 博士级工作
```

本Skill目标：稳定达到 Level 2，为 Level 3 提供起点。


## 1.5 执行铁律（Agent 必读）

🚨 **绝对禁止跳步执行。** 以下规则的优先级高于任何"优化判断"：

1. **Step 0 必须第一个执行** — 无论论文来源是 URL 还是本地 PDF，
   都必须先创建远程 CPU 实例。PDF 下载、文本提取、所有文件操作
   全部在远程实例上完成（远程有代理，网络快）。
   ❌ 禁止在本地下载 arXiv/HuggingFace 等外部资源。

2. **每一步开始前，必须校验 checklist**：
   - 前置步骤是否已完成？
   - 当前步骤的执行位置是"本地"还是"远程"？
   - 如果是"远程"，SSH 信息是否在上下文中？

3. **任何"省钱/省时"的优化冲动 → 忽略它，按流程走。**
   流程存在的意义就是消除个人判断带来的风险。

4. **输入为 URL 时的处理方式**：
   - arXiv URL → Step 0 开实例 → 远程用代理 wget 下载
   - 本地 PDF → Step 0 开实例 → SCP 上传到远程
   - 两种情况都必须经过 Step 0，不存在跳过 Step 0 的合法场景

5. **事故记录 (2026-04-23)**：
   Agent 试图在本地直接 curl arXiv PDF，跳过 Step 0，
   结果因本地无代理导致下载超时卡死。教训：永远按流程走。


## 2. T型架构总览

```
┌─────────────────────────────────────────────────────────────┐
│                    用户输入: PDF论文                          │
└──────────────────────┬──────────────────────────────────────┘
                       ▼
┌─────────────────────────────────────────────────────────────┐
│  Layer 1: 路由层 (Router Agent)                              │
│  ├─ 提取 Abstract + Methods                                 │
│  ├─ 判断学科方向: [CS/AI] [BioMed-Wet] [BioInfo] [Econ]     │
│  ├─ 判断实验类型: [Dry-只有计算] [Wet-只有实验] [Hybrid]      │
│  └─ 生成路由决策 → 激活对应插件                               │
└──────────────────────┬──────────────────────────────────────┘
                       ▼
┌─────────────────────────────────────────────────────────────┐
│  Layer 2: 通用解析引擎 (Universal Extraction Base)           │
│  ├─ 2a. 论文元信息提取 (标题/作者/期刊/年份)                  │
│  ├─ 2b. 章节分割 (Abstract/Intro/Methods/Results/Discussion)│
│  ├─ 2c. 数学公式提取 (text + vision双通道)                   │
│  ├─ 2d. 表格数据提取 (PyMuPDF + LLM理解)                    │
│  ├─ 2e. 超参数提取 (文本搜索 + LLM结构化)                    │
│  ├─ 2f. 数据集/基准识别 (名称 + 来源 + 下载链接)              │
│  └─ 2g. 基线方法识别 (Baselines + 对比指标)                  │
└──────────────────────┬──────────────────────────────────────┘
                       ▼
┌─────────────────────────────────────────────────────────────┐
│  Layer 3: 垂直方向插件 (Domain-Specific Plugins)             │
│                                                              │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐       │
│  │  CS/AI   │ │  BioInfo │ │   Econ   │ │  WetLab  │       │
│  │ 代码生成  │ │ Pipeline │ │ 回归分析  │ │   SOP    │       │
│  │model.py  │ │pipeline  │ │regress.  │ │checklist │       │
│  │train.py  │ │  .sh     │ │  .do/.R  │ │  .md     │       │
│  │config.yml│ │analysis.R│ │clean.py  │ │reagent   │       │
│  └──────────┘ └──────────┘ └──────────┘ └──────────┘       │
└──────────────────────┬──────────────────────────────────────┘
                       ▼
┌─────────────────────────────────────────────────────────────┐
│  Layer 4: 交付层 (Deliverable Packager)                      │
│  ├─ 收集所有产出物                                           │
│  ├─ 生成 CONFIDENCE_REPORT.md (置信度 + TODO清单)            │
│  ├─ 生成 README.md (复现指南)                                │
│  └─ 打包为 reproduction_scaffold/ 目录                       │
└─────────────────────────────────────────────────────────────┘
```


## 3. Layer 1: 路由层详细设计

### 3.1 路由流程

```python
# 执行流程 (在Hermes Agent中)
#
# Step 1: 用 scripts/pdf_extractor.py 提取PDF前5页文本
#         (Abstract + Introduction + Methods开头通常在前5页)
#
# Step 2: 将文本送入 templates/router_prompt.txt 做学科分类
#         → 输出: domain_tag, experiment_type, activated_plugins
#
# Step 3: 根据路由结果加载对应的子skill
#         → skill_view("zero-code-repro-csai") 等
```

### 3.2 学科分类标签体系

```json
{
  "domains": {
    "CS_AI":       "计算机/人工智能 — 算法、模型、深度学习",
    "CS_SYSTEMS":  "计算机系统 — 分布式、数据库、网络",
    "BIOINFO":     "生物信息学 — 基因组、蛋白质、序列分析",
    "BIOMED_WET":  "生物医药湿实验 — 细胞、动物、临床",
    "CHEM_MAT":    "化学/材料科学 — 合成、表征、计算化学",
    "ECON_QUANT":  "经济学/量化社科 — 计量、因果推断",
    "PHYSICS":     "物理学 — 理论、计算、实验",
    "OTHER":       "其他/跨学科"
  },
  "experiment_types": {
    "DRY":    "纯计算/模拟 (代码可完全复现)",
    "WET":    "纯实验 (需要实验室)",
    "HYBRID": "干湿结合 (如: AI模型 + 实验验证)"
  }
}
```

### 3.3 路由决策规则

```
IF domain == CS_AI:
  → 加载 zero-code-repro-csai
  → 主要产出: model.py, train.py, config.yaml

IF domain == BIOINFO:
  → 加载 zero-code-repro-bioinfo (未来)
  → 主要产出: pipeline.sh, analysis.R

IF domain == ECON_QUANT:
  → 加载 zero-code-repro-econ (未来)
  → 主要产出: data_cleaning.py, regression.do

IF domain == BIOMED_WET:
  → 加载 zero-code-repro-wetlab (未来)
  → 主要产出: SOP_checklist.md

IF domain == CHEM_MAT:
  → 加载 crystal-structure-extraction (已有)
  → 主要产出: 结构化数据JSON

IF experiment_type == HYBRID:
  → 同时加载多个插件，分别处理干/湿部分
```


## 4. Layer 2: 通用解析引擎详细设计

所有学科论文都需要提取的共性要素。这一层的输出是一个标准化的
**Paper Profile JSON**，供下游插件消费。

### 4.1 Paper Profile 数据结构

```json
{
  "meta": {
    "title": "string",
    "authors": ["string"],
    "journal": "string",
    "year": 2024,
    "doi": "string or null"
  },
  "routing": {
    "domain": "CS_AI",
    "experiment_type": "DRY",
    "activated_plugins": ["zero-code-repro-csai"],
    "confidence": 0.95
  },
  "sections": {
    "abstract": "string",
    "introduction": "string",
    "methods": "string",
    "results": "string",
    "discussion": "string",
    "supplementary": "string or null"
  },
  "formulas": [
    {
      "id": "eq1",
      "latex": "\\mathcal{L} = -\\log\\frac{\\exp(sim(z_i, z_j)/\\tau)}{...}",
      "description": "InfoNCE contrastive loss",
      "source": "Equation (3), page 4",
      "extraction_method": "vision",
      "confidence": 0.85
    }
  ],
  "hyperparameters": [
    {
      "name": "learning_rate",
      "value": "1e-4",
      "context": "We use Adam optimizer with lr=1e-4",
      "source": "Section 3.2"
    }
  ],
  "datasets": [
    {
      "name": "ImageNet-1K",
      "url": "https://image-net.org/",
      "description": "1.28M training images, 1000 classes",
      "source": "Section 4.1"
    }
  ],
  "baselines": [
    {
      "name": "ResNet-50",
      "metrics": {"Top-1 Acc": "76.1%"},
      "source": "Table 1"
    }
  ],
  "software_dependencies": [
    {
      "name": "PyTorch",
      "version": "2.0+",
      "source": "Section 3"
    }
  ],
  "key_contributions": [
    "提出了XXX方法...",
    "在YYY基准上达到SOTA..."
  ],
  "reproducibility_assessment": {
    "code_available": false,
    "data_available": true,
    "overall_difficulty": "MEDIUM",
    "missing_details": [
      "未公开预训练权重",
      "数据增强策略描述不完整"
    ]
  }
}
```

### 4.2 通用提取流程

```
Step 2a: 元信息提取
  → 从第一页提取标题、作者、期刊
  → 简单文本匹配 + LLM辅助

Step 2b: 章节分割
  → 关键词匹配: "Abstract", "Introduction", "Method", "Results"
  → LLM辅助处理非标准章节名(如 "Experimental Setup")

Step 2c: 公式提取 (双通道)
  → 通道1-Text: 从文本中搜索 "Eq.", "equation", LaTeX符号
  → 通道2-Vision: 对公式密集页面截图 → vision_analyze
  → 合并去重，标注extraction_method和confidence

Step 2d: 表格提取
  → PyMuPDF page.find_tables() 结构化提取
  → 兜底: 文本提取 + LLM重构表格结构

Step 2e: 超参数提取
  → 关键词搜索: learning rate, batch size, epoch, optimizer...
  → LLM从Methods章节结构化提取

Step 2f: 数据集识别
  → 关键词匹配已知数据集名称(ImageNet, CIFAR, COCO...)
  → LLM提取自定义数据集描述
  → 尝试匹配 HuggingFace/Kaggle URL

Step 2g: 基线方法识别
  → 从Results/Experiments章节的表格中提取
  → 识别对比方法名称和指标数值
```

### 4.3 公式提取双通道策略（核心难点）

```
场景判断:
  IF 论文 < 15页 且 公式 < 20个:
    → 全文vision提取 (每页截图, 高质量但高成本)

  IF 论文 > 15页 或 公式密集:
    → 文本预扫描定位公式所在页
    → 仅对公式页做vision提取 (精准但低成本)

  IF 论文有LaTeX源码可获取 (如arXiv论文):
    → 直接从.tex文件提取 (最高质量, 零成本)

Vision prompt for formula extraction:
  "This is page N of a research paper.
   List ALL mathematical equations/formulas on this page.
   For each formula, provide:
   1. The equation number (if labeled)
   2. The LaTeX representation
   3. A text description of what the formula computes
   Return as JSON array."
```


## 5. Layer 4: 交付层设计

### 5.1 产出物目录结构

```
reproduction_scaffold/
├── README.md                    # 复现指南(如何使用这些文件)
├── CONFIDENCE_REPORT.md         # 置信度报告 + 人工TODO清单
├── paper_profile.json           # 通用解析引擎的完整输出
├── src/                         # 源代码(CS/AI方向)
│   ├── model.py
│   ├── train.py
│   ├── evaluate.py
│   ├── data_loader.py
│   └── utils.py
├── configs/
│   └── default.yaml             # 超参数配置
├── scripts/                     # 辅助脚本
│   ├── setup.sh                 # 环境安装
│   └── download_data.sh         # 数据下载
└── docs/
    ├── architecture.md           # 模型架构说明
    └── formulas.md               # 提取的公式汇总
```

### 5.2 置信度报告模板

见 templates/confidence_report.md


## 6. 执行方式

### 6.1 执行架构

```
本地 OpenClaw Agent 职责: LLM 思考（路由/提取/生成代码）
远程 Lab4AI 实例职责:     所有文件存储 + 所有脚本执行 + 所有产出物
数据流: 远程读取 → 本地 LLM 分析 → 远程写入
```

### 6.2 单篇论文处理流程 (Agent指令)

```
0. [远程] 调用 lab4ai-instance-manage 创建 CPU 实例 (2C, name={project_name})
   → SSH 探活 (最多30次, 间隔10s)
   → 创建目录: code/ code/paper/ code/scripts/ dataset/ model/
   → SCP 上传 PDF → code/paper/
   → SCP 上传 pdf_extractor.py, code_validator.py → code/scripts/
   → 远程环境探测 (python版本/conda位置/GPU状态), 记录到 code/env_probe.json
   → 远程 pip install PyMuPDF

1. [远程] Agent通过SSH在远程执行 pdf_extractor.py 提取全文 + 关键词扫描 + vision页导出
   → 产出(远程): code/extracted_text.json, code/vision_pages/

2. [本地LLM→远程存储] Agent从远程SSH cat读取文本 → router_prompt.txt 做学科路由
   → SSH写回(远程): code/routing_result.json

3. [本地LLM→远程存储] Agent从远程读取文本 → base_extraction_prompt.txt 做通用要素提取
   → SSH写回(远程): code/paper_profile.json

4. [本地LLM→远程存储] Agent加载对应方向插件，生成代码脚手架
   → 逐文件SSH写回(远程): code/reproduction_scaffold/
   → 同步生成 requirements.txt (基于代码import分析)
   → 同步生成 test_forward.py, test_training.py, download_weights.py → code/scripts/

5. [远程] 语法检查 (系统 Python, 不需要 Conda)
   → python -m py_compile 检查所有 .py 文件
   → code_validator.py syntax + todos
   → 不创建 Conda 环境 (推迟到 Step 7)

6. [本地LLM→远程存储] 生成 CONFIDENCE_REPORT.md + README.md
   → SSH写回(远程): code/reproduction_scaffold/

7. [远程 CPU] 环境+数据+权重准备
   → 创建 Conda 环境 (conda create -p /workspace/envs/{project_name})
   → pip install -r requirements.txt (已在 Step 4 生成)
   → **PyTorch 统一安装 CUDA 版 (cu124)**，即使在 CPU 实例上
     (torch+cu124 在 CPU 机器也能运行，避免 Step 9 重复安装)
   → 执行 download_weights.py 下载模型权重到 model/
   → 下载数据到 dataset/ (如有公开链接)
   → 对第三方模型代码执行兼容性 patch (见 Pitfall 17)
   → 执行 test_forward.py 验证模型加载 + Forward pass
   → 产出(远程): Conda环境 + requirements.txt + model/* + dataset/*

8. [远程] 释放 CPU 实例
   → 调用 lab4ai-instance-manage 释放

9. [远程 GPU] 创建 GPU 实例 + 轻量验证训练
   → 环境已在 Step 7 完全就绪 (CUDA PyTorch + 权重 + patch)
   → GPU 实例启动后立即执行 test_training.py，**目标 < 5 分钟完成**
   → 轻量验证: 模拟数据 + 各模型跑几步训练 + 验证 loss 下降
   → Checkpoint 保存/加载验证
   → Evaluate 指标计算验证
   → 收集结果后立即释放，不做额外调试
   → 产出(远程): 训练日志 + checkpoint + 评估结果

10. [远程] 释放 GPU 实例
    → 调用 lab4ai-instance-manage 释放

11. [本地] 生成最终复现报告 (.docx)
    → 汇总 Step 0-10 所有结果，填充 report_config.json
    → 调用 templates/report_generator.py --config report_config.json --output report.docx
    → 包含: 论文信息 + 脚手架产出 + 验证结果 + 训练验证 + 算力消耗

#### 步骤依赖关系图
```
Step 0 → 1 → 2 → 3 → 4 → 5 → 6 → 7 → 8 (释放 CPU)
                                              ↓
                                     9 (GPU 验证) → 10 (释放 GPU)
                                              ↓
                                     11 (报告，可与 Step 10 并行)

依赖说明:
- Step 9 依趖 Step 7 (环境完全就绪)，不依赖 Step 8 (可先开 GPU 再释放 CPU)
- Step 11 依趖 Step 9 结果，不依赖 Step 10 (可并行执行)
- Step 8 和 Step 10 是资源释放，失败不影响流程正确性
```
```

### 6.3 远程实例规范

#### 项目目录结构
```
/workspace/user-data/codelab/{project_name}/
├── code/                          ← 所有代码 + 解析产出
│   ├── paper/                     ← 论文 PDF
│   ├── scripts/                   ← 工具脚本
│   │   ├── pdf_extractor.py        ← PDF解析
│   │   ├── code_validator.py        ← 代码验证
│   │   ├── test_forward.py          ← 模型 Forward pass 验证 (Step 5/7)
│   │   ├── test_training.py         ← 轻量训练验证 (Step 9)
│   │   └── download_weights.py      ← 模型权重下载 (Step 7)
│   ├── extracted_text.json        ← Step 1 产出
│   ├── vision_pages/              ← Step 1 产出 (公式页 PNG)
│   ├── routing_result.json        ← Step 2 产出
│   ├── paper_profile.json         ← Step 3 产出
│   └── reproduction_scaffold/     ← Step 4-6 产出
│       ├── src/ 或 models/ 等     ← 代码脚手架 (按方向插件决定)
│       ├── configs/
│       ├── scripts/
│       ├── CONFIDENCE_REPORT.md
│       └── README.md
├── dataset/                       ← 数据集 (预建)
└── model/                         ← 模型权重 (预建)
```

#### 虚拟环境
```
/workspace/envs/{project_name}/    ← 独立 Conda 环境 (Step 7 创建)
```

#### 科学上网
```bash
export http_proxy=http://10.201.85.65:1080
export https_proxy=http://10.201.85.65:1080
```

#### SSH 命令模板
```bash
# 变量定义 (从 lab4ai-instance-manage 创建结果获取)
SSH_CMD="sshpass -p {ssh_pass} ssh -o StrictHostKeyChecking=no -p {ssh_port} root@{ssh_host}"
SCP_CMD="sshpass -p {ssh_pass} scp -o StrictHostKeyChecking=no -P {ssh_port}"
PROJECT_ROOT="/workspace/user-data/codelab/{project_name}"

# 环境变量注入 (PATH + 科学上网, 所有远程命令必须带此前缀)
# Lab4AI CPU实例默认PATH不含/opt/conda/bin/, python3/pip/conda均在该目录
SSH_ENV="export PATH=/opt/conda/bin:\$PATH && export http_proxy=http://10.201.85.65:1080 && export https_proxy=http://10.201.85.65:1080"

# Conda 环境执行命令 (代理+PATH 注入, 解决 conda run 不继承环境变量问题)
SSH_CONDA="conda run -p /workspace/envs/{project_name} env http_proxy=http://10.201.85.65:1080 https_proxy=http://10.201.85.65:1080"

# === 标准远程 Python 执行模式 (强制) ===
# 禁止使用 ssh "python -c '...'" 或 ssh 'python << PY...PY'
# 原因: shell/SSH/Python 三层引号嵌套极易出错
# 正确做法: 先写本地文件 → SCP上传 → SSH执行
#
# 简单命令 (无引号):
#   $SSH_CMD "$SSH_ENV && <simple_command>"
#
# Python 脚本 (推荐):
#   write /tmp/script.py locally
#   $SCP_CMD /tmp/script.py root@{ssh_host}:$PROJECT_ROOT/code/scripts/
#   $SSH_CMD "$SSH_ENV && $SSH_CONDA $PROJECT_ROOT/code/scripts/script.py"
#
# 快速单行 (仅限无引号的简单表达式):
#   $SSH_CMD "$SSH_ENV && $SSH_CONDA -c 'import torch; print(torch.__version__)'"

# HuggingFace 模型下载 (铁律: 禁止wget/curl, 统一用Python API)
# 默认首选 hf-mirror.com 镜像, 降级链: hf-mirror → huggingface.co → ModelScope
HF_DOWNLOAD="export HF_ENDPOINT=https://hf-mirror.com && $SSH_CONDA python"

# 远程执行命令 (注意: 每条命令都要带 $SSH_ENV)
$SSH_CMD "$SSH_ENV && cd $PROJECT_ROOT && <command>"

# 本地内容写入远程文件
echo '<content>' | $SSH_CMD "cat > $PROJECT_ROOT/code/<file>"

# 远程文件读取到本地 (供LLM分析)
$SSH_CMD "cat $PROJECT_ROOT/code/<file>"

# SCP 上传本地文件到远程
$SCP_CMD <local_path> root@{ssh_host}:$PROJECT_ROOT/code/<remote_path>
```

### 6.4 复杂论文的分段处理

对于 Science/Nature 级别的长论文(30-50页+附录):
- 分3次读取: 正文前半(Methods)、正文后半(Results)、附录
- 用 delegate_task 并行处理不同章节
- 最后合并为统一的 paper_profile.json
- 所有中间产出物均通过SSH写回远程实例

### 6.5 复现层次策略

| 层次 | 做什么 | 成本 | 何时执行 |
|------|--------|------|----------|
| Level 2 验证层 | 模拟数据 + 各模型跑几步训练 + 验证 loss 下降 | CPU ¥0.3/h + GPU 几块 | 默认执行 |
| Level 3 完整层 | 真实数据 + 完整训练 + 复现论文数字 | A100 数天 ¥500+ | 用户明确要求时 |

默认执行 Level 2 验证层。验证目标:
- 模型加载 ✅ → Forward ✅ → Backward ✅ → Loss 下降 ✅
- Checkpoint 保存 ✅ → 加载恢复 ✅
- Evaluate 指标计算 ✅
- 端到端流程闭环证明

### 6.6 requirements.txt 生成规则

```
1. 用 code_validator.py deps 扫描所有 .py 文件的 import
2. 映射到 pip 包名 (validator 已有 pip_map)
3. 写入 reproduction_scaffold/requirements.txt
4. PyTorch 行注释为 "# install separately with CUDA version"
5. 区分 core / bioinformatics / optional 三组
```


## 7. 当前可用插件

| 插件名 | 学科方向 | 状态 | 主要产出 |
|-------|---------|------|---------|
| zero-code-repro-csai | CS/AI | ✅ 可用 | model.py, train.py, config.yaml |
| crystal-structure-extraction | 材料科学 | ✅ 可用 | 结构数据JSON |
| zero-code-repro-biodefense | 计算生物(HYBRID) | ✅ 可用 | data_pipeline/ + models/ + training/ |
| zero-code-repro-bioinfo | 生信(干) | 🔮 规划中 | pipeline.sh, analysis.R |
| zero-code-repro-econ | 经济学 | 🔮 规划中 | regression.do, clean.py |
| zero-code-repro-wetlab | 湿实验 | 🔮 规划中 | SOP_checklist.md |

### 7.1 HYBRID论文的产出物结构(如计算生物学)

HYBRID类型论文(如GeneCLR/Science 2026)需要同时激活CS/AI插件和
领域插件。产出物结构扩展为:

```
reproduction_scaffold/
├── data_pipeline/                  # 领域插件产出
│   ├── 01_annotation.sh            # 外部工具标注 (DefenseFinder等)
│   ├── 02_clustering.sh            # 序列聚类去冗余 (MMseqs2等)
│   ├── 03_label_assignment.py      # 正负样本打标逻辑
│   ├── 04_homology_split.py        # 防泄露交叉验证划分
│   └── requirements_biotools.txt   # 外部工具版本清单
├── models/                         # CS/AI插件产出
│   ├── model_a.py                  # 模型A架构
│   ├── model_b.py                  # 模型B架构
│   └── losses.py                   # 自定义损失函数
├── training/                       # 多阶段训练脚本
│   ├── pretrain_a.py
│   ├── finetune_a.py
│   └── ...
├── evaluation/
│   └── evaluate.py
├── configs/
│   ├── model_a.yaml
│   └── model_b.yaml
├── CONFIDENCE_REPORT.md
└── README.md
```


## 8. Pitfalls

1. **公式提取是最薄弱环节**: PDF文本丢失LaTeX符号,
   务必用vision双通道。对公式密集论文直接走vision。

2. **论文Methods章节的隐含知识**: 如"使用标准预处理方法"
   这类描述需要LLM补全领域常识(但要标注为"推断"而非"原文")。

3. **附录中的关键超参数**: Science/Nature论文常把实现细节
   藏在Supplementary中。必须处理附录。
   **实测经验(GeneCLR/Science 2026)**: 正文11页仅有高层描述,
   所有架构细节(维度/层数/公式)、超参数、数据划分逻辑全在
   34页补充材料中。必须将正文和补充材料作为同等优先级处理。
   当发现正文+补充材料分开成两个PDF时, 自动合并处理。

4. **多版本问题**: arXiv论文可能有v1/v2/v3,
   不同版本的方法和超参数可能不同。

5. **置信度诚实标注**: 对于推断出来的内容,
   必须在 CONFIDENCE_REPORT 中标注为"推断",
   避免用户误以为是论文原文数据。

6. **Token成本控制**: 一篇30页论文可能需要100K+ tokens。
   通用解析引擎应在路由后只传递相关章节给插件,
   不要把全文都传给每个插件。

7. **Science/Nature非标准章节格式**: 高影响因子期刊的格式与
   标准IMRaD不同。例如Science用 "RESEARCH ARTICLE SUMMARY",
   "RATIONALE", "STRUCTURED ABSTRACT" 等。pdf_extractor.py的
   章节分割器会将大量正文归入"preamble"。遇到这种情况,
   不要依赖自动分割,改用LLM辅助分割或直接送全文。

8. **PDF文本中的控制字符**: PyMuPDF提取的文本可能包含
   \x01等控制字符,导致json.loads()失败。在pdf_extractor.py
   的JSON输出中必须清理控制字符,或使用json_parse()(strict=False)
   解析输出。

9. **HYBRID论文的数据管道是第一大痛点**: 计算生物学等交叉
   学科论文(如GeneCLR)的数据处理管道(聚类/去冗余/防泄露划分)
   往往比模型架构更难复现、更容易出错。CS/AI插件只覆盖模型代码
   生成,对于HYBRID论文必须同时激活数据管道生成插件。
   应将data_pipeline/作为与src/并列的一级产出物。

10. **双语论文**: Science等期刊可能在同一PDF中包含英文正文和
    中文/其他语言的翻译。文本提取不会出问题,但关键词搜索
    需要同时匹配两种语言的术语。

11. **Lab4AI CPU实例 PATH 缺失**: 远程实例默认PATH不包含
    `/opt/conda/bin/`,导致 python3/pip/conda 命令找不到。
    所有远程SSH命令必须先注入 `export PATH=/opt/conda/bin:$PATH`。
    已在 §6.3 SSH命令模板中通过 `SSH_ENV` 变量统一处理。

12. **SSH heredoc 引号陷阱**: 远程执行复杂Python代码时,
    必须用单引号heredoc(`<< 'PY'`)而非双引号heredoc。
    双引号heredoc中 `$`、`"`、`\` 会被shell先解析,导致Python
    变量名被展开或转义符号丢失。典型报错: `NameError`
    或 `SyntaxError`。正确写法:
    ```bash
    $SSH_CMD '$SSH_ENV && python3 << "PY"
    import json
    with open("file.json") as f:
        d = json.load(f)
    print(d["key"])
    PY'
    ```

13. **Step 2 路由阶段读取策略**: 路由阶段读取 abstract + methods摘要
    (pdf_extractor.py summary 的 `router_input` + `methods_preview` 输出,
    通常 3-6K 字符)即可,不需要逐页拉取 extracted_text.json 的全量
    内容。全量文本留给 Step 3 要素提取阶段。对 HYBRID 判断,
    注意 methods_preview 是否提到实验验证关键词(cell culture,
    in vivo, phage assay, 实验验证等)。

14. **HuggingFace trust_remote_code 陷阱**: 如果模型 repo 中包含
    `modeling_*.py` 自定义代码,必须加 `trust_remote_code=True`。
    更隐蔽的问题: 自定义代码可能在类定义时隐式下载其他模型/tokenizer
    (如 Synthyra/ESM2-35M 会自动下载 facebook/esm2_t6_8M_UR50D
    tokenizer)。需要先预下载所有隐式依赖,或用 `HF_HUB_OFFLINE=1`
    离线模式。在 download_weights.py 中统一处理。

15. **conda run 不继承环境变量**: `conda run` 启动子进程时不会
    继承父进程的 `http_proxy/https_proxy`。必须用
    `conda run env http_proxy=... https_proxy=... python` 显式注入。
    已在 §6.3 通过 `SSH_CONDA` 变量统一处理。

16. **HuggingFace 下载铁律**:
    - **禁止使用 wget/curl 下载 HuggingFace 文件**（重定向不稳定,
      易下载到 HTML 错误页或文件损坏）
    - **统一使用 Python API**: `hf_hub_download` 或 `snapshot_download`
      （自带重定向处理、断点续传、完整性校验）
    - **默认首选 hf-mirror.com 镜像**，命令模板:
      ```
      export HF_ENDPOINT=https://hf-mirror.com
      python -c "from huggingface_hub import snapshot_download; \
        snapshot_download(repo_id='<repo_id>', local_dir='<target_dir>')"
      ```
    - 降级链: hf-mirror.com（默认首选）→ HuggingFace 原始地址 → ModelScope
    - 在 download_weights.py 中统一实现降级逻辑

17. **第三方模型代码 patch 标准流程**: HuggingFace 模型的自定义代码
    可能与当前 torch 版本不兼容（如 torch._dynamo.config 属性变更）。
    标准 patch 流程（在 Step 7 download_weights.py 中执行）:
    ```
    1. 先完整下载模型 (snapshot_download)
    2. 用 Python str.replace() 做精确单行替换（禁止 sed 多行替换）
    3. 替换后 grep 验证目标类/函数仍存在（防止误删）
    4. 删除所有 .pyc 缓存
    5. 删除 HF modules 缓存目录 (~/.cache/huggingface/modules/)
       强制 transformers 下次加载时重新编译
    ```
    常见 patch 模式:
    ```python
    old = "torch._dynamo.config.xxx = value"
    new = """try:\n    torch._dynamo.config.xxx = value
    \nexcept (AttributeError, Exception):\n    pass"""
    content = open(path).read()
    assert old in content, "target line not found"
    content = content.replace(old, new)
    open(path, 'w').write(content)
    assert 'class TargetClass' in content, "patch broke the file!"
    ```

## 9. 页面展示规范 (可视化交互)

### 9.1 实时进度看板 (流式播报)

在开始执行时输出此看板，**每完成一个步骤时更新对应行状态**。
看板采用 12 步通用设计（含实例管理 + 训练验证 + 报告），适用于所有学科方向：

```markdown
## 📊 零代码复现流水线: `[论文标题]`

| 阶段 | 步骤 | 执行位置 | 状态 | 产出 |
|:---|:---|:---|:---|:---|
| 🖥️ 环境 | 0. 远程实例初始化 | 远程 | [⏳/✅/❌] | 实例ID / SSH信息 / 目录结构 |
| 📥 输入 | 1. 论文获取与解析 | 远程 | [⏳] | 页数 / 字符数 / 章节数 |
| 🧭 路由 | 2. 学科方向判定 | 本地LLM→远程存储 | [⏳] | 学科 / 实验类型 / 激活插件 |
| 🔬 解析 | 3. 论文要素提取 | 本地LLM→远程存储 | [⏳] | Paper Profile (公式/超参/数据集/基线) |
| 🏭 生成 | 4. 复现产物生成 | 本地LLM→远程存储 | [⏳] | [按方向动态填充，见 9.2] |
| ✅ 验证 | 5. 产物质量检查 | 远程 | [⏳] | [按方向动态填充，见 9.2] |
| 📦 交付 | 6. 打包与报告 | 本地LLM→远程存储 | [⏳] | CONFIDENCE_REPORT / README |
| 📦 准备 | 7. 环境+数据+权重准备 | 远程 CPU | [⏳] | requirements.txt / 模型权重 / 数据集 |
| 🔚 释放 | 8. 释放 CPU 实例 | 远程 | [⏳] | CPU 实例关闭 / 算力消耗 |
| 🚀 训练 | 9. GPU 轻量验证训练 | 远程 GPU | [⏳] | 训练日志 / loss下降 / checkpoint |
| 🔚 释放 | 10. 释放 GPU 实例 | 远程 | [⏳] | GPU 实例关闭 / 算力消耗 |
| 📝 报告 | 11. 生成复现报告 | 本地 | [⏳] | .docx 复现报告 |
```

**规则**：
- 步骤 0 和 8/10 是实例生命周期管理，所有项目通用
- 步骤 1-6 是代码脚手架生成阶段 (Level 2)
- 步骤 7-10 是轻量验证训练阶段 (Level 2 验证)
- 步骤 11 是最终报告生成
- 步骤 4、5 的「产出」列根据步骤 2 路由结果动态填充
- 每完成一步，将状态从 `⏳等待中...` 更新为 `✅完成` 并精确填充产出列
- 若某步失败，标记 `❌失败` 并附原因，后续步骤标记 `⛔ 已跳过`
- 无论成功或失败，Step 8/10 释放实例必须执行（避免空转计费）

### 9.2 步骤 4-5 按方向动态内容

路由完成后，根据学科方向填充步骤 4 和 5 的产出描述：

| 学科方向 | 步骤 4「复现产物生成」产出 | 步骤 5「产物质量检查」产出 |
|---------|------------------------|------------------------|
| CS/AI (DRY) | model.py / train.py / config.yaml / 参数量 | 语法检查 / 导入测试 / Forward pass / 损失计算 |
| CS_SYSTEMS (DRY) | 同 CS/AI | 同 CS/AI |
| BIOINFO (DRY) | pipeline.sh / analysis.R / 环境脚本 | 脚本语法 / 干跑测试 / 依赖检查 |
| ECON_QUANT (DRY) | regression.do / clean.py / 变量字典 | 语法检查 / 数据格式匹配 / 变量覆盖率 |
| BIOMED_WET (WET) | SOP_checklist.md / reagent_list / 时间线 | 完整性检查 / 步骤覆盖率 / 安全提示 |
| CHEM_MAT (DRY/HYBRID) | 结构数据 JSON / 计算脚本 | 数据格式验证 / 字段完整性 |
| HYBRID | 干部分 + 湿部分各自产物 | 分别验证 |

### 9.3 结项播报模板

当步骤 6 完成后，用以下模板输出最终结果：

```markdown
## 🎉 零代码复现完成: [论文标题]

**1. 📄 论文信息**
| 维度 | 内容 |
|------|------|
| 标题 | [标题] |
| 作者 | [作者列表] |
| 期刊/会议 | [venue] |
| 学科方向 | [domain] / [experiment_type] |

**2. 🔬 Paper Profile 摘要**
| 维度 | 提取结果 |
|------|----------|
| 公式 | X 个 (HIGH: Y, MEDIUM: Z, LOW: W) |
| 超参数 | X 个 |
| 数据集 | X 个 |
| 基线方法 | X 个 |
| 模型/方法架构 | [简述] |

**3. 🏭 脚手架产出**
| 文件 | 对应论文位置 | 置信度 |
|------|------------|--------|
| [文件名] | [Section/Eq./Table] | ✅ HIGH / 🟡 MEDIUM / 🔴 LOW |
| ... | ... | ... |

**4. ✅ 验证结果**
[按方向动态填充验证项]

**5. 📋 人工 TODO 清单**
> 来自 CONFIDENCE_REPORT.md，列出需要人工补全的部分
- [ ] TODO 1
- [ ] TODO 2

**6. 📥 产出物路径 (远程实例)**
📁 脚手架目录: `/workspace/user-data/codelab/{project_name}/code/reproduction_scaffold/`
📄 置信度报告: `reproduction_scaffold/CONFIDENCE_REPORT.md`
📄 复现指南: `reproduction_scaffold/README.md`

**7. 🚀 训练验证结果**
| 模型 | 步数 | Loss 变化 | 状态 |
|------|------|----------|------|
| [模型名] | N steps | X.XX → Y.YY | ✅ 下降 / ❌ 异常 |
| ... | ... | ... | ... |

**8. 💰 算力消耗**
| 维度 | 内容 |
|------|------|
| CPU 实例 | 时长 / 费用 |
| GPU 实例 | 时长 / 费用 |
| 总计 | ¥X.XX |
```

### 9.4 看板更新时机

| 事件 | 动作 |
|------|------|
| 流水线启动 | 输出完整看板（所有步骤 `⏳等待中`，步骤 0 为 `⏳执行中`） |
| 每步完成 | 更新该步状态为 `✅完成`，下一步改为 `⏳执行中` |
| 步骤 2 完成 | 根据路由结果，回填步骤 4、5 的产出描述 |
| 步骤 6 完成 | 输出 Level 2 脚手架小结 |
| 步骤 9 完成 | 输出训练验证结果 |
| 步骤 11 完成 | 输出结项播报模板 |
| 任意步骤失败 | 标记 `❌失败`，后续 `⛔ 已跳过`，仍输出已有产出，但 Step 8/10 释放实例必须执行 |