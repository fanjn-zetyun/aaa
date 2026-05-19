"""Small V2 tool registry used by the MVP agent loop."""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass


@dataclass(slots=True)
class ToolResult:
    name: str
    content: str
    ok: bool = True


class ToolRegistry:
    async def analyze_repo(self, github_url: str | None) -> ToolResult:
        await asyncio.sleep(0.1)
        if not github_url:
            return ToolResult("analyze_repo", "未提供 GitHub URL，无法分析仓库。", ok=False)
        repo = github_url.rstrip("/").split("github.com/")[-1]
        return ToolResult(
            "analyze_repo",
            f"已识别仓库 {repo}。MVP 阶段先生成复现计划，并把后续环境准备交给 Lab4AI/SSH 工具。",
        )

    async def lab4ai_create_instance(self) -> ToolResult:
        await asyncio.sleep(0.1)
        return ToolResult(
            "lab4ai_create_instance",
            "已通过 MVP 工具层模拟创建 Lab4AI 实例；真实创建会接入 Lab4AI API/skills。",
        )

    async def ssh_execute(self, command: str) -> ToolResult:
        await asyncio.sleep(0.1)
        return ToolResult("ssh_execute", f"已模拟执行远程命令：{command}")

    async def lab4ai_stop_instance(self) -> ToolResult:
        await asyncio.sleep(0.1)
        return ToolResult("lab4ai_stop_instance", "已模拟释放 Lab4AI 实例。")

    async def ask_user(self, question: str) -> ToolResult:
        await asyncio.sleep(0.1)
        return ToolResult("ask_user", question)


def infer_task_type(text: str, fallback: str = "general") -> str:
    lowered = text.lower()
    if re.search(r"github\.com/[\w.-]+/[\w.-]+", lowered) or any(
        key in lowered for key in ("复现", "reproduce", "replicate", "experiment")
    ):
        return "reproduce"
    if any(key in lowered for key in ("search", "搜索", "find", "论文")):
        return "search"
    if any(key in lowered for key in ("polish", "润色", "rewrite")):
        return "polish"
    return fallback
