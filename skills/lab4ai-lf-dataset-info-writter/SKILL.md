---
name: lab4ai-lf-dataset-info-writter
description: 根据处理完的数据集采样结果，编写LlaMAFactory项目的dataset_info.json内必须的数据集信息字典。
---

## 基础介绍

LlaMAFactory项目利用`dataset_info.json`文件来配置数据集信息，明确训练时该如何加载数据集。
具体的字段解释如下：

```json
"数据集名称": {
  "hf_hub_url": "Hugging Face 的数据集仓库地址（若指定，则忽略 script_url 和 file_name）",
  "ms_hub_url": "ModelScope 的数据集仓库地址（若指定，则忽略 script_url 和 file_name）",
  "script_url": "包含数据加载脚本的本地文件夹名称（若指定，则忽略 file_name）",
  "file_name": "该目录下数据集文件夹或文件的名称（若上述参数未指定，则此项必需）",
  "formatting": "数据集格式（可选，默认：alpaca，可以为 alpaca 或 sharegpt）",
  "ranking": "是否为偏好数据集（可选，默认：False）",
  "subset": "数据集子集的名称（可选，默认：None）",
  "split": "所使用的数据集切分（可选，默认：train）",
  "folder": "Hugging Face 仓库的文件夹名称（可选，默认：None）",
  "num_samples": "该数据集所使用的样本数量。（可选，默认：None）",
  "columns（可选）": {
    "prompt": "数据集代表提示词的表头名称（默认：instruction）",
    "query": "数据集代表请求的表头名称（默认：input）",
    "response": "数据集代表回答的表头名称（默认：output）",
    "history": "数据集代表历史对话的表头名称（默认：None）",
    "messages": "数据集代表消息列表的表头名称（默认：conversations）",
    "system": "数据集代表系统提示的表头名称（默认：None）",
    "tools": "数据集代表工具描述的表头名称（默认：None）",
    "images": "数据集代表图像输入的表头名称（默认：None）",
    "videos": "数据集代表视频输入的表头名称（默认：None）",
    "audios": "数据集代表音频输入的表头名称（默认：None）",
    "chosen": "数据集代表更优回答的表头名称（默认：None）",
    "rejected": "数据集代表更差回答的表头名称（默认：None）",
    "kto_tag": "数据集代表 KTO 标签的表头名称（默认：None）"
  },
  "tags（可选，用于 sharegpt 格式）": {
    "role_tag": "消息中代表发送者身份的键名（默认：from）",
    "content_tag": "消息中代表文本内容的键名（默认：value）",
    "user_tag": "消息中代表用户的 role_tag（默认：human）",
    "assistant_tag": "消息中代表助手的 role_tag（默认：gpt）",
    "observation_tag": "消息中代表工具返回结果的 role_tag（默认：observation）",
    "function_tag": "消息中代表工具调用的 role_tag（默认：function_call）",
    "system_tag": "消息中代表系统提示的 role_tag（默认：system，会覆盖 system column）"
  }
}
```


## 样例
### Alpaca 格式

#### SFT数据集

经典的"instruction-input-output"数据集，在`dataset_info.json`中，应该填写为：
```json
"数据集名称": {
  "file_name": "data.json",
  "columns": {
    "prompt": "instruction",
    "query": "input",
    "response": "output",
    "system": "system",
    "history": "history"
  }
}
```
(`system`和`history`根据实际情况选用)

#### 预训练数据集

数据存放在`text`字段下，在`dataset_info.json`中，应该填写为：

```json
"数据集名称": {
  "file_name": "data.json",
  "columns": {
    "prompt": "text"
  }
}
```

#### 偏好数据集

不使用SFT的`output`表达输出，而是有正负两种偏好（例如，分别是`chosen`和`rejected`），在`dataset_info.json`中，应该填写为：

```json
"数据集名称": {
  "file_name": "data.json",
  "ranking": true,
  "columns": {
    "prompt": "instruction",
    "query": "input",
    "chosen": "chosen",
    "rejected": "rejected"
  }
}
```

### Sharegpt 格式（多轮对话）
#### SFT数据集
经典数据样例：
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

在`dataset_info.json`中，应该填写为：
```json
"数据集名称": {
  "file_name": "data.json",
  "formatting": "sharegpt",
  "columns": {
    "messages": "conversations",
    "system": "system",
    "tools": "tools"
  }
}
```

#### 偏好数据集
Sharegpt格式的数据在 `chosen` 列中提供更优的消息，并在 `rejected` 列中提供更差的消息，在`dataset_info.json`中，应该填写为：
```json
"数据集名称": {
  "file_name": "data.json",
  "formatting": "sharegpt",
  "ranking": true,
  "columns": {
    "messages": "conversations",
    "chosen": "chosen",
    "rejected": "rejected"
  }
}
```

#### KTO数据集
KTO 数据集需要额外添加一个 `kto_tag` 列，包含 bool 类型的人类反馈：

```json
"数据集名称": {
  "file_name": "data.json",
  "formatting": "sharegpt",
  "columns": {
    "messages": "conversations",
    "kto_tag": "kto_tag"
  }
}
```


#### 多模态图像数据集
```json
"数据集名称": {
  "file_name": "data.json",
  "formatting": "sharegpt",
  "columns": {
    "messages": "conversations",
    "images": "images"
  }
}
```
如果是视频/音频数据集，则将`"images"`字段换成`"videos"`/`"audios"`。


## Workflow

`dataset_info.json`文件在实例里的路径：`~/.openclaw/workspace/private_work_files/lf_datasets/dataset_info.json`
- 若其不存在，请你创建该文件，内容是空字典：
```json
{}
```
- 若其存在，读取该文件，保留原有其他数据集的信息不变，在文件中插入新的字段，存放本次需要添加的数据集信息。
**请注意：** 仅添加新数据集的字段信息，请勿删除其他已有的数据集信息！