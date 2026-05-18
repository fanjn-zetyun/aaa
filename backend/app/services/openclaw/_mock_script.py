"""模拟的 openclaw 任务脚本：被 MockOpenclawRunner 拉起，按时间间隔输出日志。

通过环境变量传入：
    MOCK_TASK_ID, MOCK_GITHUB_URL, MOCK_PAPER_URL, MOCK_USER_PROMPT
"""

from __future__ import annotations

import os
import sys
import time

LINES = [
    "[boot] OpenClaw mock runner 启动",
    "[boot] 解析用户输入: github={github_url}",
    "[boot] paper={paper_url}",
    "[boot] prompt={user_prompt}",
    "[skill] 加载 lab4ai-auto-reproduct skill...",
    "[skill] 分析仓库结构: 检测到 PyTorch + CUDA 12.6",
    "[lab4ai] 调用 instance_create API (mock)...",
    "[lab4ai] mock serverId=mock-server-{task_id}",
    "[ssh] 连接到 mock 实例 ssh://root@mock-host:22",
    "[exec] git clone {github_url} ...",
    "[exec] pip install -r requirements.txt ...",
    "[exec] 训练任务开始 (mock)...",
    "[exec] epoch 1/3 loss=1.234",
    "[exec] epoch 2/3 loss=0.876",
    "[exec] epoch 3/3 loss=0.512",
    "[lab4ai] 调用 instance_stop API (mock)...",
    "[done] 任务完成",
]


def main() -> int:
    ctx = {
        "task_id": os.environ.get("MOCK_TASK_ID", "0"),
        "github_url": os.environ.get("MOCK_GITHUB_URL", "<unknown>"),
        "paper_url": os.environ.get("MOCK_PAPER_URL") or "<none>",
        "user_prompt": os.environ.get("MOCK_USER_PROMPT") or "<none>",
    }
    interval = float(os.environ.get("MOCK_INTERVAL_SECONDS", "1.0"))

    for line in LINES:
        print(line.format(**ctx), flush=True)
        time.sleep(interval)

    return 0


if __name__ == "__main__":
    sys.exit(main())
