---
name: zero-code-repro-biodefense
description: >
  计算生物学+深度学习(HYBRID)类型论文复现插件 — 专攻"生信数据管道+AI模型架构"
  的干湿结合论文。以GeneCLR(Science 2026)为原型设计，覆盖:
  (1)防数据泄露的生信数据处理管道 (2)蛋白质/基因组语言模型架构
  (3)对比学习+LoRA微调训练循环 (4)不平衡多分类评估指标。
  是 zero-code-reproduction 主skill的垂直方向插件。
version: "1.0"
tags: [bioinformatics, deep-learning, defense-systems, protein-LM, genomic-context, reproduction]
triggers:
  - 生物防御系统论文复现
  - GeneCLR reproduction
  - 蛋白质语言模型复现
  - bioinformatics ML pipeline
related_skills:
  - zero-code-reproduction
  - zero-code-repro-csai
---

# Biodefense / Computational Biology ML 论文复现插件

## 1. 适用范围

本插件适用于以下类型论文的复现:
- 蛋白质语言模型(ESM/ProtTrans)微调
- 基因组上下文模型(ALBERT/BERT变体)
- 对比学习(SimCLR/CLIP变体)应用于生物序列
- 需要严格防数据泄露的生物序列分类

## 2. 产出物结构

```
reproduction_scaffold/
├── README.md
├── CONFIDENCE_REPORT.md
├── data_pipeline/
│   ├── 01_run_defensefinder.sh
│   ├── 02_run_padloc.sh
│   ├── 03_extract_negatives.py
│   ├── 04_mmseqs_clustering.sh
│   └── 05_homology_split.py
├── models/
│   ├── albert_df.py
│   ├── esm_df.py
│   ├── geneclr.py
│   ├── losses.py
│   └── ds_attention_bias.py
├── training/
│   ├── pretrain_albert.py
│   ├── pretrain_geneclr.py
│   ├── finetune_esm.py
│   └── finetune_geneclr.py
├── evaluation/
│   └── evaluate.py
├── configs/
│   ├── albert_config.yaml
│   ├── esm_config.yaml
│   └── geneclr_config.yaml
└── scripts/
    └── setup.sh
```

## 3. 四大复现模块

### 模块1: 数据管道 (data_pipeline/)
- 正样本打标: DefenseFinder + PadLoc CLI调用
- 负样本提取: 核心基因组(PanACoTA) + MGE(HMM扫描)
- 序列聚类: MMseqs2 多级聚类 (30/50/80/95/99%)
- 防泄露划分: 同源性图→连通分量→按防御类型分折

### 模块2: 模型架构 (models/)
- ALBERT_DF: HuggingFace ALBERT + Geometric Attention + Distance Module(GLU)
- ESM_DF: ESM2(35M/650M) + LoRA + mean-pooling head
- GeneCLR: 双轨道(Sequence=SwiGLU, Context=Transformer+DS Attention Bias)
- 损失函数: 对称InfoNCE + 逆平方根频率重加权BCE

### 模块3: 训练循环 (training/)
- ALBERT MLM预训练: masking=0.15, batch=32×4, lr=5e-4
- GeneCLR对比预训练: masking=0.25, batch=1024, InfoNCE
- ESM LoRA微调: lr=1e-5, rank=4, alpha=1, 1 epoch
- GeneCLR分类微调: 冻结Context Track + LoRA

### 模块4: 评估 (evaluation/)
- Macro-AUROC (亚型平均)
- Micro-AP (全局)
- PR曲线 + 阈值校准 (GeneCLR: -0.74 → 99%P/92.4%R)

## 4. 经验证的执行工作流 (Proven Workflow)

处理HYBRID论文(如GeneCLR)的实际步骤。
**所有文件操作均通过SSH在远程Lab4AI实例上完成，本地不保存产出物。**

```
Step 1: 发现PDF结构 (远程)
  → $SSH_CMD "ls $PROJECT_ROOT/code/paper/"
  → 通常: 正文.pdf + 补充材料.pdf (两个文件！)

Step 2: 直接用fitz读取 (远程执行, 不要用pdf_extractor extract的JSON输出)
  → Science格式论文的pdf_extractor sections会把全文归入preamble
  → PDF文本含控制字符(如\x01)会导致json.loads失败
  → 最可靠方式: SSH远程执行 python3 脚本, fitz.open() → page.get_text()
  → 结果通过SSH cat读回本地供LLM分析

Step 3: 分页关键词扫描 (远程执行, 结果读回本地)
  → 对正文: 搜索模型名(ALBERT/ESM/GeneCLR)、loss、LoRA等
  → 对补充材料: 搜索超参数关键词(learning rate/batch/rank/alpha等)
  → 补充材料中的信息量通常远超正文（GeneCLR: 34页补充 vs 11页正文）

Step 4: 按模块提取参数 (本地LLM分析, 结果SSH写回远程)
  → 先从补充材料逐页阅读(page 3-11最关键)
  → 所有公式/维度/超参数都在这里
  → $SSH_CMD "cat > $PROJECT_ROOT/code/geneclr_extracted_params.json" <<< '<json>'

Step 5: 批量生成代码 (本地LLM生成, 逐文件SSH写回远程)
  → 一次写一个文件，不要试图用单个命令写所有文件
  → 按依赖顺序: ds_attention_bias.py → losses.py → albert_df.py → esm_df.py → geneclr.py
  → 模型文件中的import路径用 sys.path.insert(0, ...) 保持灵活
  → 目标路径: $PROJECT_ROOT/code/reproduction_scaffold/

Step 6: 用code_validator.py逐目录验证 (远程执行)
  → 先创建Conda环境 + 安装依赖 (在远程实例上)
  → $SSH_CMD "cd $PROJECT_ROOT/code && conda run -p /workspace/envs/{project_name} python scripts/code_validator.py full reproduction_scaffold/"
  → syntax检查: 所有.py文件必须通过
  → TODO标记: 统计LOW/MEDIUM置信度项
```

## 5. Pitfalls

1. GeneCLR Context Track的DS Attention Bias用6维距离向量(非ALBERT的4维)
2. ESM微调中LoRA alpha = rank × factor, 论文最优: rank=4, factor=1 → alpha=4
   (补充材料page 8原文: "LoRA rank of 4, and LoRA α of 1" 这里α指factor不是alpha,
   实际alpha = rank × factor = 4×1 = 4; 代码中LoRALinear的scaling = alpha/rank = 4/4 = 1)
3. ALBERT词表524,288极大, 嵌入维度仅32(ALBERT压缩特性)
4. 负样本标签-100表示"忽略", 不是负类(PyTorch cross_entropy的ignore_index约定)
5. 重加权BCE中负样本总权重 = 正样本总权重(平衡约束)
6. GeneCLR微调只冻结Context Track, Sequence Track不参与微调
7. Science/Nature论文正文几乎不含实现细节, 必须同等重视补充材料PDF
8. ALBERT fine-tuning的LoRA参数(rank=64, alpha=128)远大于ESM的(rank=4, alpha=4),
   两个模型不要混用LoRA配置
