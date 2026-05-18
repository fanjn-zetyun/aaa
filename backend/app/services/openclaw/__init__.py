"""OpenClaw 进程封装：协议、mock 实现、生命周期管理器。"""

from .manager import OpenclawManager, get_manager
from .runner import OpenclawRunner, ProcessHandle, TaskInput

__all__ = ["OpenclawManager", "OpenclawRunner", "ProcessHandle", "TaskInput", "get_manager"]
