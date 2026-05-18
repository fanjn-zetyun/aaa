"""MockOpenclawRunner: 通过子进程跑一个内置脚本输出模拟日志。

特点：
- 真实 subprocess.Popen，可被 SIGTERM 中断
- stdout 行被推送到内置队列，便于 WebSocket 转发
- 支持 stop()、wait() 与 stream_logs()
"""

from __future__ import annotations

import asyncio
import signal
import sys
from collections.abc import AsyncIterator
from pathlib import Path

from app.core.config import get_settings

from .runner import OpenclawRunner, ProcessHandle, TaskInput
from .workspace import prepare_workspace, write_lab4ai_env

_MOCK_SCRIPT_PATH = Path(__file__).with_name("_mock_script.py")


class MockOpenclawRunner:
    """符合 OpenclawRunner 协议的 mock 实现。"""

    async def start(self, task: TaskInput) -> ProcessHandle:
        workspace = prepare_workspace(task.task_id)
        write_lab4ai_env(workspace, task.lab4ai_phone, task.lab4ai_password)

        env = {
            "MOCK_TASK_ID": str(task.task_id),
            "MOCK_GITHUB_URL": task.github_url,
            "MOCK_PAPER_URL": task.paper_url or "",
            "MOCK_USER_PROMPT": task.user_prompt or "",
            "MOCK_INTERVAL_SECONDS": "1.0",
            "PYTHONUNBUFFERED": "1",
        }
        # 继承基本环境变量
        import os as _os

        for key in ("PATH", "SYSTEMROOT", "TEMP", "TMP"):
            if key in _os.environ:
                env[key] = _os.environ[key]

        process = await asyncio.create_subprocess_exec(
            sys.executable,
            "-u",
            str(_MOCK_SCRIPT_PATH),
            cwd=str(workspace),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            env=env,
        )
        if process.pid is None:
            raise RuntimeError("mock openclaw 启动失败：未取得 PID")

        handle = ProcessHandle(
            task_id=task.task_id,
            pid=process.pid,
            workspace_path=workspace,
            process=process,
        )

        # 后台读取 stdout → 广播到所有订阅者
        asyncio.create_task(self._pump_logs(handle))
        return handle

    async def _pump_logs(self, handle: ProcessHandle) -> None:
        assert handle.process.stdout is not None
        try:
            while True:
                raw = await handle.process.stdout.readline()
                if not raw:
                    break
                line = raw.decode("utf-8", errors="replace").rstrip("\r\n")
                handle.publish(line)
        finally:
            handle.finish()

    async def stop(self, handle: ProcessHandle, timeout: float = 30.0) -> int:
        if handle.process.returncode is not None:
            return handle.process.returncode

        try:
            if sys.platform == "win32":
                handle.process.terminate()
            else:
                handle.process.send_signal(signal.SIGTERM)
        except ProcessLookupError:
            return handle.process.returncode or 0

        try:
            await asyncio.wait_for(handle.process.wait(), timeout=timeout)
        except asyncio.TimeoutError:
            handle.process.kill()
            await handle.process.wait()
        return handle.process.returncode or 0

    async def stream_logs(self, handle: ProcessHandle) -> AsyncIterator[str]:
        q = handle.subscribe()
        while True:
            line = await q.get()
            if line is None:
                break
            yield line

    async def wait(self, handle: ProcessHandle) -> int:
        return await handle.process.wait()


def build_runner() -> OpenclawRunner:
    """根据配置构造 runner（mock / real）。"""
    settings = get_settings()
    mode = settings.openclaw_runner.lower()
    if mode == "real":
        # 真实实现暂未提供，避免 mock 环境意外调用真 openclaw
        raise NotImplementedError(
            "RealOpenclawRunner 尚未实现，请先在 .env 中保留 OPENCLAW_RUNNER=mock。"
        )
    return MockOpenclawRunner()
