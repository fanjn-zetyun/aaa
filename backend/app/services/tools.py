"""Declarative tool registry used by the backend agent loop.

The registry mirrors the shape we want for the later model-driven tool-use
loop: each tool owns its schema, safety policy, confirmation copy and executor.
"""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass, field
from typing import Any

TOOL_CONFIRM_STEP_PREFIX = "tool_confirm:"


@dataclass(frozen=True, slots=True)
class ToolDefinition:
    name: str
    description: str
    input_schema: dict[str, Any]
    read_only: bool = False
    confirmation_policy: str = "never"
    confirmation_reason: str = ""

    @property
    def confirmation_step(self) -> str:
        return f"{TOOL_CONFIRM_STEP_PREFIX}{self.name}"

    @property
    def can_require_confirmation(self) -> bool:
        return self.confirmation_policy != "never"


@dataclass(frozen=True, slots=True)
class ToolConfirmation:
    step: str
    question: str
    options: tuple[str, ...]
    tool_name: str
    tool_input: dict[str, Any] = field(default_factory=dict)

    def as_pending_input(self) -> dict[str, Any]:
        return {
            "question": self.question,
            "options": list(self.options),
            "step": self.step,
            "tool_name": self.tool_name,
            "tool_input": self.tool_input,
        }


@dataclass(slots=True)
class ToolResult:
    name: str
    content: str
    ok: bool = True
    metadata: dict[str, Any] = field(default_factory=dict)


class ToolRegistry:
    def __init__(self) -> None:
        self._definitions = _build_tool_definitions()

    def definition(self, name: str) -> ToolDefinition:
        try:
            return self._definitions[name]
        except KeyError as exc:
            raise ValueError(f"未知工具：{name}") from exc

    def list_definitions(self, allowed_tools: list[str] | None = None) -> list[ToolDefinition]:
        allowed = set(allowed_tools or [])
        definitions = self._definitions.values()
        if allowed:
            definitions = [tool for tool in definitions if tool.name in allowed]
        return sorted(definitions, key=lambda item: item.name)

    def prompt_context(self, allowed_tools: list[str] | None = None) -> str:
        lines = ["可用后端 Tool："]
        for tool in self.list_definitions(allowed_tools):
            safety = "只读" if tool.read_only else "有副作用"
            confirmation = _format_confirmation_policy(tool.confirmation_policy)
            lines.append(f"- {tool.name}: {tool.description} ({safety}，{confirmation})")
        return "\n".join(lines)

    def confirmation_for(
        self,
        name: str,
        tool_input: dict[str, Any] | None = None,
    ) -> ToolConfirmation | None:
        tool = self.definition(name)
        payload = dict(tool_input or {})
        if not _requires_confirmation(tool, payload):
            return None

        return ToolConfirmation(
            step=tool.confirmation_step,
            question=_build_confirmation_question(tool, payload),
            options=("继续执行", "先修改方案", "停止任务"),
            tool_name=tool.name,
            tool_input=payload,
        )

    async def invoke(
        self,
        name: str,
        tool_input: dict[str, Any] | None = None,
    ) -> ToolResult:
        self.definition(name)
        payload = dict(tool_input or {})
        if name == "analyze_repo":
            return await self._analyze_repo(payload.get("github_url"))
        if name == "lab4ai_create_instance":
            return await self._lab4ai_create_instance(payload)
        if name == "lab4ai_stop_instance":
            return await self._lab4ai_stop_instance(payload)
        if name == "ssh_execute":
            return await self._ssh_execute(str(payload.get("command") or ""))
        if name == "ask_user":
            return await self._ask_user(str(payload.get("question") or ""))
        raise ValueError(f"未知工具：{name}")

    async def analyze_repo(self, github_url: str | None) -> ToolResult:
        return await self.invoke("analyze_repo", {"github_url": github_url})

    async def lab4ai_create_instance(self) -> ToolResult:
        return await self.invoke("lab4ai_create_instance")

    async def ssh_execute(self, command: str) -> ToolResult:
        return await self.invoke("ssh_execute", {"command": command})

    async def lab4ai_stop_instance(self) -> ToolResult:
        return await self.invoke("lab4ai_stop_instance")

    async def ask_user(self, question: str) -> ToolResult:
        return await self.invoke("ask_user", {"question": question})

    async def _analyze_repo(self, github_url: str | None) -> ToolResult:
        await asyncio.sleep(0.1)
        if not github_url:
            return ToolResult("analyze_repo", "未提供 GitHub URL，无法分析仓库。", ok=False)
        repo = github_url.rstrip("/").split("github.com/")[-1]
        return ToolResult(
            "analyze_repo",
            f"已识别仓库 {repo}。MVP 阶段先生成复现计划，并把后续环境准备交给 Lab4AI/SSH 工具。",
            metadata={"repo": repo},
        )

    async def _lab4ai_create_instance(self, payload: dict[str, Any]) -> ToolResult:
        await asyncio.sleep(0.1)
        return ToolResult(
            "lab4ai_create_instance",
            "已通过 MVP 工具层模拟创建 Lab4AI 实例；真实创建会接入 Lab4AI API/skills。",
            metadata={"simulated": True, **payload},
        )

    async def _ssh_execute(self, command: str) -> ToolResult:
        await asyncio.sleep(0.1)
        if not command.strip():
            return ToolResult("ssh_execute", "未提供远程命令，SSH 工具未执行。", ok=False)
        return ToolResult(
            "ssh_execute",
            f"已模拟执行远程命令：{command}",
            metadata={"command": command, "simulated": True},
        )

    async def _lab4ai_stop_instance(self, payload: dict[str, Any]) -> ToolResult:
        await asyncio.sleep(0.1)
        return ToolResult(
            "lab4ai_stop_instance",
            "已模拟释放 Lab4AI 实例。",
            metadata={"simulated": True, **payload},
        )

    async def _ask_user(self, question: str) -> ToolResult:
        await asyncio.sleep(0.1)
        return ToolResult("ask_user", question, metadata={"control": "human_input"})


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


def _build_tool_definitions() -> dict[str, ToolDefinition]:
    return {
        "analyze_repo": ToolDefinition(
            name="analyze_repo",
            description="分析 GitHub 仓库结构和复现入口。",
            input_schema={
                "type": "object",
                "properties": {"github_url": {"type": ["string", "null"]}},
            },
            read_only=True,
        ),
        "lab4ai_create_instance": ToolDefinition(
            name="lab4ai_create_instance",
            description="创建 Lab4AI 云实例并绑定到当前对话。",
            input_schema={"type": "object", "properties": {}},
            confirmation_policy="always",
            confirmation_reason="会占用远程算力资源并可能产生费用。",
        ),
        "ssh_execute": ToolDefinition(
            name="ssh_execute",
            description="在远程实例上执行 SSH 命令。",
            input_schema={
                "type": "object",
                "properties": {"command": {"type": "string"}},
                "required": ["command"],
            },
            confirmation_policy="risky",
            confirmation_reason="检测到命令可能破坏环境或产生长时间副作用。",
        ),
        "lab4ai_stop_instance": ToolDefinition(
            name="lab4ai_stop_instance",
            description="停止并释放当前对话绑定的 Lab4AI 云实例。",
            input_schema={"type": "object", "properties": {"server_id": {"type": "string"}}},
            confirmation_reason="会释放远程算力资源。",
        ),
        "ask_user": ToolDefinition(
            name="ask_user",
            description="向用户提出需要人工决策的问题并暂停当前工作流。",
            input_schema={
                "type": "object",
                "properties": {"question": {"type": "string"}},
                "required": ["question"],
            },
        ),
    }


def _build_confirmation_question(tool: ToolDefinition, payload: dict[str, Any]) -> str:
    if tool.name == "lab4ai_create_instance":
        return (
            "下一步需要调用 `lab4ai_create_instance` 创建 Lab4AI 算力实例。"
            f"{tool.confirmation_reason}是否继续？"
        )
    if tool.name == "ssh_execute":
        command = str(payload.get("command") or "").strip() or "(空命令)"
        return (
            "下一步需要通过 `ssh_execute` 在远程实例执行命令："
            f"`{command}`。{tool.confirmation_reason}是否继续？"
        )
    if tool.name == "lab4ai_stop_instance":
        return (
            "下一步需要调用 `lab4ai_stop_instance` 停止并释放当前实例。"
            f"{tool.confirmation_reason}是否继续？"
        )
    return f"下一步需要调用 `{tool.name}`。{tool.confirmation_reason}是否继续？"


def _requires_confirmation(tool: ToolDefinition, payload: dict[str, Any]) -> bool:
    if tool.confirmation_policy == "never":
        return False
    if tool.confirmation_policy == "always":
        return True
    if tool.confirmation_policy == "risky" and tool.name == "ssh_execute":
        return _is_risky_ssh_command(str(payload.get("command") or ""))
    return False


def _is_risky_ssh_command(command: str) -> bool:
    lowered = command.lower()
    risky_patterns = (
        "rm -rf",
        "sudo",
        "mkfs",
        "dd if=",
        "shutdown",
        "reboot",
        "chmod -r 777",
        "curl",
        "wget",
        "pip install",
        "conda install",
        "apt-get",
        "apt ",
    )
    return any(pattern in lowered for pattern in risky_patterns)


def _format_confirmation_policy(policy: str) -> str:
    if policy == "always":
        return "需要 HITL 确认"
    if policy == "risky":
        return "高风险时需要 HITL 确认"
    return "无需确认"
