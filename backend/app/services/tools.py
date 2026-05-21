"""Declarative tool registry used by the backend agent loop.

The registry mirrors the shape we want for the later model-driven tool-use
loop: each tool owns its schema, safety policy, confirmation copy and executor.
"""

from __future__ import annotations

import asyncio
from copy import deepcopy
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import CloudInstance, CloudInstanceStatus, CloudInstanceType
from app.services.lab4ai.client import (
    create_instance,
    list_instances,
    stop_instance_details,
)
from app.services.lab4ai.credentials import load_lab4ai_credentials

TOOL_CONFIRM_STEP_PREFIX = "tool_confirm:"


@dataclass(frozen=True, slots=True)
class ToolDefinition:
    name: str
    description: str
    input_schema: dict[str, Any]
    read_only: bool = False
    confirmation_policy: str = "never"
    confirmation_reason: str = ""
    risk_level: str = "low"
    audit_category: str = "general"

    @property
    def confirmation_step(self) -> str:
        return f"{TOOL_CONFIRM_STEP_PREFIX}{self.name}"

    def confirmation_step_for(self, payload: dict[str, Any]) -> str:
        workflow_run_id = _non_empty_str(payload.get("workflow_run_id") or payload.get("run_id"))
        tool_call_id = _non_empty_str(payload.get("tool_call_id"))
        workflow_step_id = _non_empty_str(payload.get("workflow_step_id"))
        if workflow_run_id and tool_call_id:
            step = f"{self.confirmation_step}:{workflow_run_id}:{tool_call_id}"
            if workflow_step_id:
                return f"{step}:{workflow_step_id}"
            return step
        if tool_call_id:
            step = f"{self.confirmation_step}:{tool_call_id}"
            if workflow_step_id:
                return f"{step}:{workflow_step_id}"
            return step
        if workflow_step_id:
            return f"{self.confirmation_step}:{workflow_step_id}"
        return self.confirmation_step

    @property
    def can_require_confirmation(self) -> bool:
        return self.confirmation_policy != "never"

    def anthropic_schema(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": deepcopy(self.input_schema),
        }


@dataclass(frozen=True, slots=True)
class ToolConfirmation:
    step: str
    question: str
    options: tuple[str, ...]
    tool_name: str
    tool_input: dict[str, Any] = field(default_factory=dict)
    workflow_run_id: str | None = None
    tool_call_id: str | None = None
    workflow_step_id: str | None = None
    risk_level: str = "low"
    audit_category: str = "general"

    def as_pending_input(self) -> dict[str, Any]:
        pending = {
            "question": self.question,
            "options": list(self.options),
            "step": self.step,
            "tool_name": self.tool_name,
            "tool_input": self.tool_input,
            "risk_level": self.risk_level,
            "audit_category": self.audit_category,
        }
        if self.workflow_run_id:
            pending["workflow_run_id"] = self.workflow_run_id
            pending["run_id"] = self.workflow_run_id
        if self.tool_call_id:
            pending["tool_call_id"] = self.tool_call_id
        if self.workflow_step_id:
            pending["workflow_step_id"] = self.workflow_step_id
        return pending


@dataclass(slots=True)
class ToolResult:
    name: str
    content: str
    ok: bool = True
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ToolExecutionContext:
    user_id: int
    conversation_id: int
    session: AsyncSession


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

    def list_anthropic_tools(self, allowed_tools: list[str] | None = None) -> list[dict[str, Any]]:
        return [tool.anthropic_schema() for tool in self.list_definitions(allowed_tools)]

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
        *,
        workflow_run_id: str | None = None,
        tool_call_id: str | None = None,
        workflow_step_id: str | None = None,
    ) -> ToolConfirmation | None:
        tool = self.definition(name)
        payload = dict(tool_input or {})
        _set_if_present(payload, "workflow_run_id", workflow_run_id)
        _set_if_present(payload, "tool_call_id", tool_call_id)
        _set_if_present(payload, "workflow_step_id", workflow_step_id)
        if not _requires_confirmation(tool, payload):
            return None

        return ToolConfirmation(
            step=tool.confirmation_step_for(payload),
            question=_build_confirmation_question(tool, payload),
            options=("继续执行", "先修改方案", "停止任务"),
            tool_name=tool.name,
            tool_input=payload,
            workflow_run_id=_non_empty_str(payload.get("workflow_run_id") or payload.get("run_id")),
            tool_call_id=_non_empty_str(payload.get("tool_call_id")),
            workflow_step_id=_non_empty_str(payload.get("workflow_step_id")),
            risk_level=tool.risk_level,
            audit_category=tool.audit_category,
        )

    async def invoke(
        self,
        name: str,
        tool_input: dict[str, Any] | None = None,
        context: ToolExecutionContext | None = None,
    ) -> ToolResult:
        self.definition(name)
        payload = dict(tool_input or {})
        if name == "analyze_repo":
            return await self._analyze_repo(payload.get("github_url"))
        if name == "lab4ai_create_instance":
            return await self._lab4ai_create_instance(payload, context)
        if name == "lab4ai_stop_instance":
            return await self._lab4ai_stop_instance(payload, context)
        if name == "lab4ai_list_instances":
            return await self._lab4ai_list_instances(context)
        if name == "ssh_execute":
            return await self._ssh_execute(str(payload.get("command") or ""))
        if name == "file_write":
            return await self._file_write(payload)
        if name == "repro_report":
            return await self._repro_report(payload)
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

    async def _lab4ai_create_instance(
        self,
        payload: dict[str, Any],
        context: ToolExecutionContext | None,
    ) -> ToolResult:
        resource_kind = str(payload.get("resource_kind") or "instance").lower()
        if context is None:
            raise RuntimeError("缺少 Tool 执行上下文，无法创建 Lab4AI 实例")
        creds = await load_lab4ai_credentials(context.session)
        if creds is None:
            raise RuntimeError("Lab4AI 凭证未配置，请先由管理员配置平台账号")

        target_model = "GPU" if resource_kind == "gpu" else "CPU"
        instance = await create_instance(
            creds.phone,
            creds.password,
            target_model=target_model,
            cpu_count=_as_int(payload.get("cpu_cores"), default=2),
            gpu_count=_as_int(payload.get("gpu_count"), default=1),
            image_tag=str(
                payload.get("image_tag") or "lf0.9.4-tf4.57.1-torch2.8.0-cu12.6-1.1"
            ),
            source=str(payload.get("source") or "lab"),
        )
        if not instance.server_id:
            raise RuntimeError("Lab4AI 创建实例成功响应缺少 serverId")

        cloud = CloudInstance(
            user_id=context.user_id,
            conversation_id=context.conversation_id,
            server_id=instance.server_id,
            instance_id=instance.instance_id or None,
            instance_type=CloudInstanceType.GPU
            if target_model == "GPU"
            else CloudInstanceType.CPU,
            gpu_count=instance.gpu_count,
            ssh_host=instance.ssh_host or None,
            ssh_port=_as_int(instance.ssh_port, default=0) or None,
            ssh_user=instance.ssh_user or "root",
            ssh_pass=instance.ssh_pass or None,
            status=CloudInstanceStatus.RUNNING,
            raw_payload=instance.raw_payload or {},
        )
        context.session.add(cloud)
        await context.session.commit()
        await context.session.refresh(cloud)
        return ToolResult(
            "lab4ai_create_instance",
            f"已创建 Lab4AI {target_model} 实例：{instance.server_id}",
            metadata={
                "cloud_instance_id": cloud.id,
                "server_id": instance.server_id,
                "instance_id": instance.instance_id,
                "resource_kind": target_model,
                "ssh_host": instance.ssh_host,
                "ssh_port": instance.ssh_port,
                "ssh_user": instance.ssh_user or "root",
                **payload,
            },
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

    async def _file_write(self, payload: dict[str, Any]) -> ToolResult:
        await asyncio.sleep(0.1)
        path = str(payload.get("path") or payload.get("remote_path") or "").strip()
        if not path:
            return ToolResult(
                "file_write",
                "No target path was provided; file_write did not run.",
                ok=False,
                metadata={"simulated": True, "written": False, **payload},
            )
        if _is_skills_path(path):
            return ToolResult(
                "file_write",
                "Refused to target the skills directory; no file was written.",
                ok=False,
                metadata={"simulated": True, "written": False, "path": path, **payload},
            )
        return ToolResult(
            "file_write",
            f"Simulated remote file write to {path}; no local file was written.",
            metadata={"simulated": True, "written": False, "path": path, **payload},
        )

    async def _lab4ai_stop_instance(
        self,
        payload: dict[str, Any],
        context: ToolExecutionContext | None,
    ) -> ToolResult:
        if context is None:
            raise RuntimeError("缺少 Tool 执行上下文，无法停止 Lab4AI 实例")
        server_id = str(payload.get("server_id") or "").strip()
        if not server_id:
            raise RuntimeError("缺少 server_id，无法停止 Lab4AI 实例")

        instance = await context.session.scalar(
            select(CloudInstance).where(
                CloudInstance.server_id == server_id,
                CloudInstance.user_id == context.user_id,
            )
        )
        if instance is None:
            raise RuntimeError("未找到当前用户名下的 Lab4AI 实例记录，拒绝停止未绑定实例")
        if instance.status == CloudInstanceStatus.STOPPED:
            return ToolResult(
                "lab4ai_stop_instance",
                f"Lab4AI 实例已处于停止状态：{server_id}",
                metadata={"cloud_instance_id": instance.id, "server_id": server_id, **payload},
            )

        creds = await load_lab4ai_credentials(context.session)
        if creds is None:
            raise RuntimeError("Lab4AI 凭证未配置，请先由管理员配置平台账号")

        stop_result = await stop_instance_details(creds.phone, creds.password, server_id)
        instance.status = CloudInstanceStatus.STOPPED
        instance.stopped_at = datetime.now(UTC)
        instance.raw_payload = {
            **(instance.raw_payload or {}),
            "stop": stop_result.raw_payload or {},
        }
        await context.session.commit()
        return ToolResult(
            "lab4ai_stop_instance",
            f"已停止 Lab4AI 实例：{server_id}",
            metadata={
                "cloud_instance_id": instance.id,
                "server_id": server_id,
                "start_time": stop_result.start_time,
                "stop_time": stop_result.stop_time,
                **payload,
            },
        )

    async def _lab4ai_list_instances(
        self,
        context: ToolExecutionContext | None,
    ) -> ToolResult:
        if not context:
            return ToolResult(
                "lab4ai_list_instances",
                "当前缺少执行上下文，无法查询用户实例。",
                ok=False,
            )
        creds = await load_lab4ai_credentials(context.session)
        if creds is None:
            raise RuntimeError("Lab4AI 凭证未配置，请先由管理员配置平台账号")

        instances = await list_instances(creds.phone, creds.password)
        remote_by_id = {item.server_id: item for item in instances}
        local_instances = (
            await context.session.execute(
                select(CloudInstance).where(CloudInstance.user_id == context.user_id)
            )
        ).scalars().all()
        for item in local_instances:
            if (
                item.status == CloudInstanceStatus.RUNNING
                and item.server_id not in remote_by_id
            ):
                item.status = CloudInstanceStatus.STOPPED
                item.stopped_at = datetime.now(UTC)
        await context.session.commit()
        visible = [
            item
            for item in instances
            if any(local.server_id == item.server_id for local in local_instances)
        ]
        return ToolResult(
            "lab4ai_list_instances",
            f"已从 Lab4AI 查询到当前用户可见运行实例 {len(visible)} 台。",
            metadata={
                "instances": [item.raw_payload or {} for item in visible],
            },
        )

    async def _repro_report(self, payload: dict[str, Any]) -> ToolResult:
        await asyncio.sleep(0.1)
        repo_name = str(payload.get("repo_name") or "project")
        report_path = f"/root/lab4ai/workspace/{repo_name}/{repo_name}_Repro_Report.docx"
        return ToolResult(
            "repro_report",
            f"已模拟生成工业级复现报告：{report_path}",
            metadata={"simulated": True, "report_path": report_path, **payload},
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
            risk_level="low",
            audit_category="workflow",
        ),
        "lab4ai_create_instance": ToolDefinition(
            name="lab4ai_create_instance",
            description="创建 Lab4AI 云实例并绑定到当前对话。",
            input_schema={"type": "object", "properties": {}},
            confirmation_policy="always",
            risk_level="critical",
            audit_category="lab4ai",
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
            risk_level="high",
            audit_category="ssh",
            confirmation_reason="检测到命令可能破坏环境或产生长时间副作用。",
        ),
        "lab4ai_stop_instance": ToolDefinition(
            name="lab4ai_stop_instance",
            description="停止并释放当前对话绑定的 Lab4AI 云实例。",
            input_schema={"type": "object", "properties": {"server_id": {"type": "string"}}},
            risk_level="high",
            audit_category="lab4ai",
            confirmation_reason="会释放远程算力资源。",
        ),
        "lab4ai_list_instances": ToolDefinition(
            name="lab4ai_list_instances",
            description="查询当前用户可见的 Lab4AI 云实例。",
            input_schema={"type": "object", "properties": {}},
            read_only=True,
            risk_level="low",
            audit_category="lab4ai",
        ),
        "file_write": ToolDefinition(
            name="file_write",
            description="Simulate writing content to a remote task file.",
            input_schema={
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "content": {"type": "string"},
                },
                "required": ["path", "content"],
            },
            confirmation_policy="always",
            confirmation_reason="Writing files can overwrite task artifacts or remote workspace state.",
            risk_level="high",
            audit_category="file",
        ),
        "repro_report": ToolDefinition(
            name="repro_report",
            description="生成项目复现报告并返回报告路径。",
            input_schema={
                "type": "object",
                "properties": {"repo_name": {"type": "string"}},
                "required": ["repo_name"],
            },
            risk_level="medium",
            audit_category="workflow",
        ),
        "ask_user": ToolDefinition(
            name="ask_user",
            description="向用户提出需要人工决策的问题并暂停当前工作流。",
            input_schema={
                "type": "object",
                "properties": {"question": {"type": "string"}},
                "required": ["question"],
            },
            risk_level="low",
            audit_category="workflow",
        ),
    }


def _build_confirmation_question(tool: ToolDefinition, payload: dict[str, Any]) -> str:
    if tool.name == "lab4ai_create_instance":
        resource_kind = str(payload.get("resource_kind") or "算力").upper()
        return (
            f"接下来需要创建一个 Lab4AI {resource_kind} 实例，用于继续复现流程。"
            "这会占用远程算力资源并可能产生费用。是否继续？"
        )
    if tool.name == "ssh_execute":
        command = str(payload.get("command") or "").strip() or "(空命令)"
        return (
            "接下来需要在远程实例执行一条高风险命令："
            f"`{command}`。该操作可能修改环境或产生较长时间的副作用。是否继续？"
        )
    if tool.name == "lab4ai_stop_instance":
        return (
            "接下来需要停止并释放当前 Lab4AI 实例。"
            "释放后实例上的临时运行状态可能不可恢复。是否继续？"
        )
    if tool.name == "file_write":
        return (
            "接下来需要写入任务工作区文件。"
            "该操作可能覆盖已有产物或改变远程工作区状态。是否继续？"
        )
    return f"接下来需要执行一步受控操作。{tool.confirmation_reason}是否继续？"


def _requires_confirmation(tool: ToolDefinition, payload: dict[str, Any]) -> bool:
    if tool.name == "lab4ai_stop_instance" and payload.get("force_cleanup"):
        return False
    if tool.confirmation_policy == "never":
        return False
    if tool.confirmation_policy == "always":
        return True
    if tool.confirmation_policy == "risky" and tool.name == "ssh_execute":
        return _is_risky_ssh_command(str(payload.get("command") or ""))
    if tool.confirmation_policy == "risky" and tool.name == "file_write":
        return True
    return False


def _set_if_present(payload: dict[str, Any], key: str, value: str | None) -> None:
    if value is not None:
        payload[key] = value


def _non_empty_str(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _is_skills_path(path: str) -> bool:
    normalized = path.replace("\\", "/").lower().strip()
    parts = [part for part in normalized.split("/") if part not in ("", ".")]
    return "skills" in parts


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


def _as_int(value: object, *, default: int = 0) -> int:
    try:
        return int(value if value not in (None, "") else default)
    except (TypeError, ValueError):
        return default
