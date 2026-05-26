---
name: zero-code-repro-csai
description: >
  CS/AI方向论文复现插件 — 从Paper Profile生成PyTorch模型代码脚手架。
  产出: model.py (网络结构), train.py (训练循环), evaluate.py (评估),
  data_loader.py (数据加载), config.yaml (超参数), setup.sh (环境安装)。
  是 zero-code-reproduction 主skill的垂直方向插件。
version: "1.0"
tags: [CS, AI, deep-learning, PyTorch, code-generation, reproduction]
triggers:
  - CS/AI论文复现
  - 生成PyTorch代码
  - 从论文生成模型代码
  - AI paper reproduction
related_skills:
  - zero-code-reproduction
---

# CS/AI 论文复现插件

## 1. 插件定位

接收 zero-code-reproduction 主skill的 Paper Profile JSON，
生成完整的 PyTorch 代码脚手架。

**输入**: Paper Profile (formulas, hyperparameters, datasets, baselines)
**输出**: 可语法检查通过的代码文件集合

### 1.1 产出物清单

```
src/
├── model.py          # 核心模型架构 (nn.Module)
├── train.py          # 训练循环 (含优化器/调度器/日志)
├── evaluate.py       # 评估脚本 (指标计算)
├── data_loader.py    # 数据集加载 + 预处理
├── losses.py         # 自定义损失函数 (如有)
└── utils.py          # 辅助函数
configs/
└── default.yaml      # 超参数配置
scripts/
├── setup.sh          # pip install + 环境配置
└── download_data.sh  # 数据下载脚本
```


## 2. 代码生成流程

### Phase 1: 架构分析 (Architecture Analysis)

从Paper Profile中提取:
- 模型架构描述 (来自 methods 章节)
- 关键公式 (来自 formulas 列表)
- 模型层次结构 (Encoder/Decoder/Head/Loss)

生成 architecture_plan:
```json
{
  "model_type": "encoder_only | decoder_only | encoder_decoder | custom",
  "base_model": "from_scratch | huggingface/model-name | torchvision/model-name",
  "components": [
    {"name": "Encoder", "type": "Transformer", "details": "..."},
    {"name": "ProjectionHead", "type": "MLP", "details": "..."},
    {"name": "ContrastiveLoss", "type": "InfoNCE", "details": "..."}
  ],
  "input_shape": {"batch": "B", "seq_len": "L", "dim": "D"},
  "output_shape": {"batch": "B", "num_classes": "C"}
}
```

### Phase 2: 代码生成 (Code Generation)

使用 templates/ 下的代码模板，逐文件生成:

#### 2a. model.py 生成规则

```
1. 每个公式 → 一个方法或一个子模块
   - 损失函数公式 → losses.py 中的 class
   - 注意力公式 → model.py 中的 attention 方法
   - 正则化项 → 嵌入 training step

2. 架构映射:
   - "Transformer" → nn.TransformerEncoder / nn.TransformerDecoder
   - "ResNet" → torchvision.models.resnet50(pretrained=...)
   - "BERT/GPT/..." → transformers.AutoModel.from_pretrained(...)
   - "GNN" → torch_geometric.nn.*
   - "CNN" → nn.Conv2d 堆叠
   - "MLP" → nn.Sequential(nn.Linear, nn.ReLU, ...)

3. 必须包含:
   - 完整的 __init__ 和 forward 方法
   - 输入/输出形状注释 (# Input: [B, L, D] → Output: [B, C])
   - 每个关键组件旁标注对应论文章节/公式
   - TODO注释标记不确定的实现细节
```

#### 2b. train.py 生成规则

```
1. 标准训练循环框架:
   - argparse 或 hydra 配置加载
   - DataLoader 创建
   - 模型/优化器/调度器初始化
   - 训练epoch循环 + 验证
   - checkpoint保存 + 日志记录

2. 从Paper Profile映射:
   - optimizer → hyperparameters中的optimizer字段
   - lr_scheduler → 搜索 "warmup", "cosine", "step decay" 等
   - epochs → hyperparameters中的epoch/total_steps字段
   - grad_clipping → 如论文提到 gradient clipping

3. 日志:
   - 使用 print 基础日志 (不强依赖wandb/tensorboard)
   - 可选注释掉的 wandb.log 调用
```

#### 2c. config.yaml 生成规则

```
1. 直接从 hyperparameters 列表生成
2. 按类别分组:
   model:
     hidden_dim: 768
     num_layers: 12
     ...
   training:
     learning_rate: 1e-4
     batch_size: 32
     ...
   data:
     dataset: ImageNet-1K
     ...
3. 对于缺失的参数，填入常见默认值并标注 # TODO: not in paper
```

#### 2d. data_loader.py 生成规则

```
1. 知名数据集 → 使用现有API:
   - ImageNet → torchvision.datasets.ImageNet
   - CIFAR → torchvision.datasets.CIFAR10/100
   - COCO → torchvision.datasets.CocoDetection
   - GLUE/SQuAD → datasets.load_dataset("glue", ...)
   - 自定义CSV/JSON → torch.utils.data.Dataset子类

2. 数据增强/预处理:
   - 从论文Methods中提取描述
   - 映射到 torchvision.transforms 或 albumentations

3. 必须包含:
   - train/val/test split
   - DataLoader with num_workers, pin_memory
   - collate_fn (如需要)
```

### Phase 3: 验证 (Validation)

生成代码后，运行以下自动检查:

```bash
# 1. 语法检查
python -m py_compile src/model.py
python -m py_compile src/train.py
python -m py_compile src/evaluate.py
python -m py_compile src/data_loader.py

# 2. Import检查
python -c "
import sys; sys.path.insert(0, 'src')
from model import *
print('model.py imports OK')
"

# 3. 形状推断检查 (如果可能)
python -c "
import torch; sys.path.insert(0, 'src')
from model import Model
m = Model(**config)
x = torch.randn(2, 10, 768)  # dummy input
y = m(x)
print(f'Output shape: {y.shape}')
"
```


## 3. 子领域特化

### 3.1 NLP / Language Models

```
特殊处理:
- Tokenizer: 识别vocab_size → 选择 BPE/WordPiece/SentencePiece
- Positional Encoding: 搜索 "positional" → sinusoidal / learned / RoPE / ALiBi
- Attention Mask: causal (decoder) / bidirectional (encoder)
- 常用基座: BERT, GPT-2, T5, LLaMA → HuggingFace AutoModel

模板选择:
- 文本分类 → templates/nlp_classifier.py.j2
- 序列生成 → templates/nlp_generator.py.j2
- 对比学习 → templates/contrastive_model.py.j2
```

### 3.2 Computer Vision

```
特殊处理:
- Backbone: ResNet/ViT/ConvNeXt → torchvision.models or timm
- 数据增强: 从论文描述 → torchvision.transforms 链
- 预训练权重: ImageNet-1K / ImageNet-21K / CLIP

模板选择:
- 图像分类 → templates/cv_classifier.py.j2
- 目标检测 → templates/cv_detector.py.j2
- 语义分割 → templates/cv_segmentation.py.j2
```

### 3.3 Graph Neural Networks

```
特殊处理:
- 框架: PyG (torch_geometric) or DGL
- 消息传递: GCN/GAT/GIN/GraphSAGE
- 池化: global_mean_pool / TopK / SAGPool

模板选择:
- 节点分类 → templates/gnn_node.py.j2
- 图分类 → templates/gnn_graph.py.j2
- 链接预测 → templates/gnn_link.py.j2
```

### 3.4 Reinforcement Learning

```
特殊处理:
- 环境: Gym/Gymnasium 环境名
- 算法: PPO/SAC/DQN/A3C
- 框架: stable-baselines3 / cleanrl / tianshou

模板选择:
- On-policy → templates/rl_onpolicy.py.j2
- Off-policy → templates/rl_offpolicy.py.j2
```

### 3.5 Generative Models

```
特殊处理:
- 类型: GAN / VAE / Diffusion / Flow
- 噪声调度: linear / cosine / learned (diffusion)
- 采样: DDPM / DDIM / Euler (diffusion)

模板选择:
- GAN → templates/gen_gan.py.j2
- VAE → templates/gen_vae.py.j2
- Diffusion → templates/gen_diffusion.py.j2
```


## 4. LLM Prompt — 代码生成

### 4.1 model.py 生成 prompt

见 templates/codegen_model_prompt.txt

### 4.2 train.py 生成 prompt

见 templates/codegen_train_prompt.txt


## 5. 质量标准

生成的代码必须满足:

1. ✅ python -m py_compile 通过 (无语法错误)
2. ✅ 所有import的包存在 (torch, transformers, etc.)
3. ✅ model的forward方法有完整的输入输出形状注释
4. ✅ 超参数全部外化到config.yaml (不硬编码)
5. ✅ 每个关键实现旁有论文出处注释
6. ✅ 不确定的实现用 # TODO: [LOW CONFIDENCE] 标记
7. ✅ setup.sh 包含所有pip install
8. ✅ README中说明了如何运行


## 6. Pitfalls

1. **新架构 vs 已有框架**: 如果论文提出全新架构,
   从公式逐层实现。如果是魔改已有架构(如"改了attention的ResNet"),
   用已有模型作为base再修改。

2. **自定义算子**: 如果论文使用CUDA自定义算子,
   生成PyTorch等价实现并标注"原文使用自定义CUDA kernel,
   此处为PyTorch等价实现,速度可能较慢"。

3. **多阶段训练**: 如果论文有 pre-train → fine-tune 多阶段,
   为每个阶段生成独立的train脚本。

4. **分布式训练**: 如果论文使用多GPU/多节点,
   生成单GPU版本作为基础,附注分布式配置方法。

5. **随机种子**: 总是设置 torch.manual_seed + np.random.seed,
   从config中读取seed值。
