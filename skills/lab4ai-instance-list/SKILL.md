---
name: lab4ai-instance-list
description: 查询 Lab4AI 平台当前运行中的实例列表。返回所有运行中的 CPU/GPU 实例及其 SSH 连接信息。适用于检查资源占用、排查遗留实例、确认实例状态。
---

# Lab4AI 运行实例查询 Skill (lab4ai-instance-list)

通过 Lab4AI 云端 REST API 查询当前账户下所有运行中的实例。

---

## 使用方法

```bash
python scripts/list.py
```

无需任何参数，自动从 `/root/.openclaw/.env` 读取 `LAB4AI_PHONE` 和 `LAB4AI_PASSWORD`。

## 输出

### 有运行中实例时

```json
{
  "status": "success",
  "count": 2,
  "instances": [
    {
      "serverId": "abc123",
      "instanceId": "uuid-xxx",
      "ruleName": "GPU",
      "gpuCount": 1,
      "ssh_host": "182.242.159.112",
      "ssh_port": "38854",
      "ssh_user": "root",
      "ssh_pass": "xxxxx",
      "startTime": "2026-04-15 11:50:37"
    }
  ]
}
```

### 无运行中实例时

```json
{
  "status": "success",
  "count": 0,
  "instances": [],
  "message": "当前无运行中的实例"
}
```

## 前置条件

- `/root/.openclaw/.env` 中配置了 `LAB4AI_PHONE` 和 `LAB4AI_PASSWORD`
- 已安装 `httpx`（通常已预装）

## 典型用途

1. **流水线前检查**：复现流水线开始前确认无遗留实例空转
2. **异常恢复**：流水线中断后查找未释放的实例并手动关闭
3. **成本监控**：定期检查是否有被遗忘的运行实例
4. **与 lab4ai-instance-manage 配合**：查到 serverId 后可直接调用 stop.py 释放
