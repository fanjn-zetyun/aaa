"""OpenclawRunner 接口与数据类型。

后端通过 OpenclawRunner 抽象接口调用 openclaw，提供两种实现：
- MockOpenclawRunner: 开发阶段使用，跑一个内置脚本输出模拟日志
- RealOpenclawRunner: 真实 openclaw CLI 调用（联调时启用）
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol


@dataclass(slots=True)
class TaskInput:
    """用户提交任务时的输入。"""

    task_id: int
    github_url: str
    paper_url: str | None = None
    user_prompt: str | None = None
    lab4ai_phone: str | None = None
    lab4ai_password: str | None = None


@dataclass(slots=True)
class ProcessHandle:
    """正在运行的 openclaw 进程句柄。"""

    task_id: int
    pid: int
    workspace_path: Path
    process: asyncio.subprocess.Process
    # 日志 fan-out：历史缓冲 + 多订阅者广播
    _log_history: list[str] = field(default_factory=list)
    _subscribers: list[asyncio.Queue[str | None]] = field(default_factory=list)
    _finished: bool = field(default=False)

    def subscribe(self) -> asyncio.Queue[str | None]:
        """创建一个新的日志订阅队列，先回放历史再接收新行。"""
        q: asyncio.Queue[str | None] = asyncio.Queue()
        for line in self._log_history:
            q.put_nowait(line)
        if self._finished:
            q.put_nowait(None)
        else:
            self._subscribers.append(q)
        return q

    def publish(self, line: str) -> None:
        """发布一行日志到所有订阅者 + 历史缓冲。"""
        self._log_history.append(line)
        for q in self._subscribers:
            q.put_nowait(line)

    def finish(self) -> None:
        """标记日志流结束。"""
        self._finished = True
        for q in self._subscribers:
            q.put_nowait(None)
        self._subscribers.clear()


class OpenclawRunner(Protocol):
    """OpenClaw 进程运行器协议。"""

    async def start(self, task: TaskInput) -> ProcessHandle:
        """为任务创建 workspace 并启动 openclaw 子进程。"""
        ...

    async def stop(self, handle: ProcessHandle, timeout: float = 30.0) -> int:
        """停止进程：先 SIGTERM，超时后 SIGKILL。返回退出码。"""
        ...

    async def stream_logs(self, handle: ProcessHandle) -> AsyncIterator[str]:
        """订阅指定进程的日志流（直到进程退出）。"""
        ...

    async def wait(self, handle: ProcessHandle) -> int:
        """等待进程结束，返回退出码。"""
        ...
