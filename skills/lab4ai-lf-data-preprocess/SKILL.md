---
name:       
description: 帮用户将下载的开源数据集处理成可以直接用于LlamaFactory项目微调的数据。如果用户有处理LlamaFactory数据处理需求，请直接调用此技能。

---

# LLaMA-Factory Data Process

## 项目背景介绍

LLaMA-Factory是一个大模型训练框架，支持大模型的预训练、微调、强化学习等。

目前支持 **alpaca** 格式和 **sharegpt** 格式的数据集。允许的文件类型包括 json、jsonl、csv、parquet 和 arrow。

## Alpaca 格式

### 预训练数据集

在预训练时，只有 `text` 列中的内容会用于模型学习。

```json
[
  {"text": "document"},
  {"text": "document"}
]
```

### 指令监督微调（SFT）数据集

在指令监督微调时，`instruction` 列对应的内容会与 `input` 列对应的内容拼接后作为提示词，即提示词为 `instruction\ninput`。而 `output` 列对应的内容为模型回答。
对于推理类模型的微调，如果数据集包含思维链，则需要把思维链放在模型回答中，例如 `<think>cot</think>output`。

`history` 列是由多个字符串二元组构成的列表，分别代表历史消息中每轮对话的指令和回答。注意在指令监督微调时，历史消息中的回答内容**也会被用于模型学习**。

```json
[
  {
    "instruction": "用户指令（必填）",
    "input": "用户输入（选填）",
    "output": "模型回答（必填）",
    "system": "系统提示词（选填）",
    "history": [
      ["第一轮指令（选填）", "第一轮回答（选填）"],
      ["第二轮指令（选填）", "第二轮回答（选填）"]
    ]
  }
]
```

### 偏好数据集

偏好数据集用于奖励模型训练、DPO 训练、ORPO 训练和 SimPO 训练。它需要在 `chosen` 列中提供更优的回答，并在 `rejected` 列中提供更差的回答。

```json
[
  {
    "instruction": "用户指令（必填）",
    "input": "用户输入（选填）",
    "chosen": "优质回答（必填）",
    "rejected": "劣质回答（必填）"
  }
]
```


## Sharegpt 格式

### 指令监督微调数据集

相比 alpaca 格式的数据集，sharegpt 格式支持更多的角色种类，例如 human、gpt、observation、function 等等。它们构成一个对象列表呈现在 `conversations` 列中。
注意其中 human 和 observation 必须出现在奇数位置，gpt 和 function 必须出现在偶数位置。默认所有的 gpt 和 function 会被用于学习。

```json
[
  {
    "conversations": [
      {
        "from": "human",
        "value": "用户指令"
      },
      {
        "from": "function_call",
        "value": "工具参数"
      },
      {
        "from": "observation",
        "value": "工具结果"
      },
      {
        "from": "gpt",
        "value": "模型回答"
      }
    ],
    "system": "系统提示词（选填）",
    "tools": "工具描述（选填）"
  }
]
```


### 多模态数据集

多模态数据集根据具体的模态（图像/视频/音频），需要额外添加一列：
- 图像数据集需要额外添加一个 `images` 列，包含输入图像的路径。
- 视频数据集需要额外添加一个 `videos` 列，包含输入视频的路径。
- 音频数据集需要额外添加一个 `audios` 列，包含输入音频的路径。

以上新添加的图像/视频/音频数量，必须与文本中所有的多模态标志数量严格一致：
- 图片的数量 = `<image>` 标记的数量
- 视频的数量 = `<video>` 标记的数量
- 音频的数量 = `<audio>` 标记的数量

#### 多模态图片数据集样例如下：
```json
[
  {
    "conversations": [
      {
        "from": "human",
        "value": "<image><image>用户指令"
      },
      {
        "from": "gpt",
        "value": "模型回答"
      }
    ],
    "images": [
      "图像路径（必填）",
      "图像路径（必填）"
    ]
  }
]
```

### 偏好数据集

Sharegpt 格式的偏好数据集同样需要在 `chosen` 列中提供更优的消息，并在 `rejected` 列中提供更差的消息。

```json
[
  {
    "conversations": [
      {
        "from": "human",
        "value": "用户指令"
      },
      {
        "from": "gpt",
        "value": "模型回答"
      },
      {
        "from": "human",
        "value": "用户指令"
      }
    ],
    "chosen": {
      "from": "gpt",
      "value": "优质回答"
    },
    "rejected": {
      "from": "gpt",
      "value": "劣质回答"
    }
  }
]
```
### KTO 数据集

KTO 数据集需要额外添加一个 `kto_tag` 列，包含 bool 类型的人类反馈。

```json
[
  {
    "conversations": [
      {
        "from": "human",
        "value": "用户指令"
      },
      {
        "from": "gpt",
        "value": "模型回答"
      }
    ],
    "kto_tag": "人类反馈 [true/false]（必填）"
  }
]
```



# Data Process Workflow
请你按照以下流程执行数据处理（`<dataset_name>`为用户期望处理的数据集的名称）：

1. 调用`lab4ai-instance-manage`技能，使用默认镜像，创建8核CPU实例，创建完成后，立即汇报实例 ID。若创建失败，停止执行技能，汇报失败报错信息即结束。
2. 在启动的实例内，调用`lab4ai-lf-data-sampling`技能，对初始数据集进行采样。
3. 读取采样结果，分析这个数据集该如何适配LlaMAFactory框架的训练。
4. 编写数据集处理的Python脚本（`process_dataset_<dataset_name>.py`），将该数据集处理成LLaMA-Factory框架支持的结构（list of dicts）：
	- 处理后的数据集文件名：`processed_<dataset_name>.json`
	- 处理后的数据集文件应保存在：`~/lobster/workspace/private_work_files/lf_datasets`目录下
	- **请注意：** 你编写的Python脚本是可以直接顺利运行的脚本，尽量使用基础的packages，只需要保证能处理当前用户需求的数据集即可。
5. 执行数据处理的脚本
6. 调用`lab4ai-lf-dataset-info-writter`技能，为这个数据集编写`dataset_info.json`内的信息。
7. 调用`lab4ai-instance-manage`技能，使用实例ID关闭该实例。
8. 使用中文向用户汇报：
	1. 采样脚本路径和采样后的数据集样本路径
	2. 采样分析结果，即数据集处理思路
	3. 数据集处理脚本路径
	4. 处理完的数据集路径
	5. `dataset_info.json`内添加的数据集信息字段
	6. （可选）Python环境的创建、安装的python包...
	7. 其他你在执行过程中的重要发现或操作


## 重要的参考信息
1. 用户给的数据集如果是工作空间路径，该路径在实例内也可获取，无需上传到实例，可以在实例内直接访问。
2. 你被部署在一个cpu实例内，请勿再次ssh连接新启动的实例，直接在新实例内进行操作即可。
3. 本技能在实例内默认使用此python执行脚本：`~/envs/data_preprocess/bin/python`。如果`data_preprocess`环境不存在，请使用conda创建该环境（python=3.10）。
- 实例内的conda路径：`/opt/conda/condabin/conda`
4. 如果编写的脚本内包含额外的包，你可以直接在`data_preprocess`环境内安装该包（建议使用清华源镜像：`https://pypi.tuna.tsinghua.edu.cn/simple/`） 
