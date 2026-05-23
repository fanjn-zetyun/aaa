"""Declarative tool registry used by the backend agent loop.

The registry mirrors the shape we want for the later model-driven tool-use
loop: each tool owns its schema, safety policy, confirmation copy and executor.
"""

from __future__ import annotations

import asyncio
from copy import deepcopy
from pathlib import Path
import re
import time
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
from app.services.skill_runtime import SkillRuntime
from app.core.config import get_settings

TOOL_CONFIRM_STEP_PREFIX = "tool_confirm:"
SSH_EXECUTE_TOOL_NAMES = {"ssh_execute", "claw_shell_run", "ssh_essentials_execute"}
FILE_WRITE_TOOL_NAMES = {"file_write", "file_system_write", "workspace_write"}
FILE_READ_TOOL_NAMES = {"file_system_read", "workspace_read"}
FILE_LIST_TOOL_NAMES = {"file_system_list", "workspace_list"}


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
    error_code: str | None = None
    retryable: bool | None = None
    recovery_suggestion: str | None = None


@dataclass(slots=True)
class ToolExecutionContext:
    user_id: int
    conversation_id: int
    session: AsyncSession


class ToolRegistry:
    def __init__(self) -> None:
        settings = get_settings()
        self._skill_runtime = SkillRuntime(
            settings.skills_dir_path,
            settings.workspace_root_path,
        )
        self._definitions = _build_tool_definitions(self._skill_runtime)

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
        if _contains_unrendered_template(payload):
            return ToolResult(
                name,
                "工具参数中包含未渲染模板变量 `{{...}}`，已拒绝执行。",
                ok=False,
                metadata={"error_code": "unrendered_template"},
            )
        if name in {"analyze_repo", "repo_audit"}:
            return await self._analyze_repo(payload, context, result_name=name)
        if name in {"analyze_paper", "paper_analyze"}:
            return await self._analyze_paper(payload, context, result_name=name)
        if name in {"lab4ai_create_instance", "instance_create"}:
            return await self._lab4ai_create_instance(payload, context)
        if name in {"lab4ai_stop_instance", "instance_stop"}:
            return await self._lab4ai_stop_instance(payload, context)
        if name == "lab4ai_list_instances":
            return await self._lab4ai_list_instances(context)
        if name in SSH_EXECUTE_TOOL_NAMES:
            return await self._ssh_execute(payload, context, result_name=name)
        if name == "remote_project_prep":
            return await self._remote_project_prep(payload, context)
        if name in FILE_WRITE_TOOL_NAMES:
            return await self._file_write(payload, context, result_name=name)
        if name in FILE_READ_TOOL_NAMES:
            return await self._file_read(payload, context, result_name=name)
        if name in FILE_LIST_TOOL_NAMES:
            return await self._file_list(payload, context, result_name=name)
        if name in {"repro_report", "generate_repro_report"}:
            return await self._repro_report(payload, context, result_name=name)
        if name == "ask_user":
            return await self._ask_user(str(payload.get("question") or ""))
        if self._skill_runtime.spec(name):
            return ToolResult(
                name,
                f"skill tool `{name}` 已被识别，但当前没有安全的后端执行适配器。",
                ok=False,
                metadata={"error_code": "missing_adapter"},
            )
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

    async def _analyze_repo(
        self,
        payload: dict[str, Any],
        context: ToolExecutionContext | None,
        *,
        result_name: str = "analyze_repo",
    ) -> ToolResult:
        github_url = payload.get("github_url") or payload.get("repo_url")
        if not github_url:
            return ToolResult(result_name, "未提供 GitHub URL，无法分析仓库。", ok=False)
        runtime_payload = {
            **payload,
            "repo_url": github_url,
            "github_url": github_url,
        }
        if context:
            runtime_payload.setdefault("conversation_id", context.conversation_id)
        result = await self._skill_runtime.invoke("repo_audit", runtime_payload)
        return ToolResult(
            result_name,
            result.content,
            ok=result.ok,
            metadata=result.metadata,
        )

    async def _analyze_paper(
        self,
        payload: dict[str, Any],
        context: ToolExecutionContext | None,
        *,
        result_name: str = "analyze_paper",
    ) -> ToolResult:
        runtime_payload = dict(payload)
        if context:
            runtime_payload.setdefault("conversation_id", context.conversation_id)
        result = await self._skill_runtime.invoke("paper_analyze", runtime_payload)
        return ToolResult(
            result_name,
            result.content,
            ok=result.ok,
            metadata=result.metadata,
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

    async def _ssh_execute(
        self,
        payload: dict[str, Any],
        context: ToolExecutionContext | None,
        *,
        result_name: str = "ssh_execute",
    ) -> ToolResult:
        command = str(payload.get("command") or "")
        if not command.strip():
            return ToolResult(result_name, "未提供远程命令，SSH 工具未执行。", ok=False)
        if context is None:
            return ToolResult(
                result_name,
                "缺少 Tool 执行上下文，无法解析当前对话绑定的远程实例。",
                ok=False,
                metadata={"error_code": "missing_context", "command": command},
            )
        instance = await _resolve_cloud_instance(payload, context)
        if instance is None:
            return ToolResult(
                result_name,
                "未找到当前任务可用的 Lab4AI 实例，无法执行 SSH 命令。",
                ok=False,
                metadata={"error_code": "missing_cloud_instance", "command": command},
            )
        if not instance.ssh_host or not instance.ssh_port or not instance.ssh_pass:
            return ToolResult(
                result_name,
                "Lab4AI 实例缺少 SSH 连接信息，无法执行远程命令。",
                ok=False,
                metadata={
                    "error_code": "missing_ssh_credentials",
                    "server_id": instance.server_id,
                    "command": command,
                },
            )
        try:
            import paramiko
        except ImportError:
            return ToolResult(
                result_name,
                "后端缺少 paramiko 依赖，无法执行真实 SSH。",
                ok=False,
                metadata={"error_code": "missing_dependency", "dependency": "paramiko"},
            )

        timeout = _as_int(payload.get("timeout"), default=300)
        connect_retries = max(1, _as_int(payload.get("connect_retries"), default=1))
        connect_retry_interval = max(
            1,
            _as_int(payload.get("connect_retry_interval"), default=10),
        )
        started = datetime.now(UTC)

        def _run_ssh() -> dict[str, Any]:
            for attempt in range(1, connect_retries + 1):
                client = paramiko.SSHClient()
                client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
                try:
                    client.connect(
                        hostname=str(instance.ssh_host),
                        port=int(instance.ssh_port or 22),
                        username=instance.ssh_user or "root",
                        password=instance.ssh_pass,
                        timeout=min(timeout, 30),
                        banner_timeout=min(timeout, 30),
                        auth_timeout=min(timeout, 30),
                    )
                except Exception:
                    client.close()
                    if attempt >= connect_retries:
                        raise
                    time.sleep(connect_retry_interval)
                    continue
                try:
                    stdin, stdout, stderr = client.exec_command(
                        command,
                        timeout=timeout,
                        get_pty=bool(payload.get("pty", False)),
                    )
                    if stdin:
                        stdin.close()
                    stdout_text = stdout.read().decode("utf-8", errors="replace")
                    stderr_text = stderr.read().decode("utf-8", errors="replace")
                    exit_code = stdout.channel.recv_exit_status()
                    return {
                        "exit_code": exit_code,
                        "stdout": stdout_text,
                        "stderr": stderr_text,
                    }
                finally:
                    client.close()
            raise RuntimeError("SSH connect retry loop exhausted")

        try:
            result = await asyncio.wait_for(asyncio.to_thread(_run_ssh), timeout=timeout + 10)
        except TimeoutError:
            return ToolResult(
                result_name,
                f"SSH 命令执行超时：{command}",
                ok=False,
                metadata={
                    "error_code": "ssh_timeout",
                    "server_id": instance.server_id,
                    "command": command,
                    "timeout": timeout,
                    "connect_retries": connect_retries,
                    "started_at": started.isoformat(),
                    "completed_at": datetime.now(UTC).isoformat(),
                },
            )
        except Exception as exc:
            return ToolResult(
                result_name,
                f"SSH 命令执行失败：{type(exc).__name__}: {exc}",
                ok=False,
                metadata={
                    "error_code": "ssh_execute_failed",
                    "server_id": instance.server_id,
                    "command": command,
                    "connect_retries": connect_retries,
                    "started_at": started.isoformat(),
                    "completed_at": datetime.now(UTC).isoformat(),
                },
            )

        completed = datetime.now(UTC)
        ok = int(result["exit_code"]) == 0
        content = (
            f"SSH 命令执行完成，exit_code={result['exit_code']}。\n"
            f"stdout:\n{_tail(result['stdout'])}\n"
            f"stderr:\n{_tail(result['stderr'])}"
        )
        return ToolResult(
            result_name,
            content.strip(),
            ok=ok,
            metadata={
                "error_code": None if ok else "nonzero_exit",
                "server_id": instance.server_id,
                "remote_host": instance.ssh_host,
                "remote_port": instance.ssh_port,
                "command": command,
                "exit_code": result["exit_code"],
                "stdout": result["stdout"],
                "stderr": result["stderr"],
                "connect_retries": connect_retries,
                "started_at": started.isoformat(),
                "completed_at": completed.isoformat(),
            },
        )

    async def _remote_project_prep(
        self,
        payload: dict[str, Any],
        context: ToolExecutionContext | None,
    ) -> ToolResult:
        repo_name = str(payload.get("repo_name") or "project").strip() or "project"
        dependency_cmds = _as_list(payload.get("dependency_cmds"))
        data_cmds = _as_list(payload.get("data_cmds"))
        weight_cmds = _as_list(payload.get("weight_cmds"))
        command = _remote_project_prep_command(
            repo_name=repo_name,
            python_version=str(payload.get("python_version") or "3.10"),
            dependency_cmds=dependency_cmds,
            data_cmds=data_cmds,
            weight_cmds=weight_cmds,
        )
        result = await self._ssh_execute(
            {
                **payload,
                "command": command,
                "timeout": _as_int(payload.get("timeout"), default=7200),
            },
            context,
        )
        return ToolResult(
            "remote_project_prep",
            result.content,
            ok=result.ok,
            metadata={
                **result.metadata,
                "repo_name": repo_name,
                "dependency_cmds_count": len(dependency_cmds),
                "data_cmds_count": len(data_cmds),
                "weight_cmds_count": len(weight_cmds),
            },
        )

    async def _file_write(
        self,
        payload: dict[str, Any],
        context: ToolExecutionContext | None,
        *,
        result_name: str = "file_write",
    ) -> ToolResult:
        path = str(payload.get("path") or payload.get("remote_path") or "").strip()
        content = str(payload.get("content") or "")
        if not path:
            return ToolResult(
                result_name,
                "No target path was provided; file_write did not run.",
                ok=False,
                metadata={"error_code": "missing_path", "written": False, **payload},
            )
        if _is_skills_path(path):
            return ToolResult(
                result_name,
                "Refused to target the skills directory; no file was written.",
                ok=False,
                metadata={"error_code": "forbidden_path", "written": False, "path": path, **payload},
            )
        if _is_remote_path(path) and not payload.get("local_only"):
            return await self._remote_file_write(payload, context, result_name=result_name)

        try:
            target = _resolve_workspace_path(path, context)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
        except Exception as exc:
            return ToolResult(
                result_name,
                f"文件写入失败：{type(exc).__name__}: {exc}",
                ok=False,
                metadata={"error_code": "file_write_failed", "path": path, "written": False},
            )
        return ToolResult(
            result_name,
            f"已写入任务工作区文件：{target}",
            metadata={"written": True, "path": str(target), "artifact_paths": [str(target)]},
        )

    async def _remote_file_write(
        self,
        payload: dict[str, Any],
        context: ToolExecutionContext | None,
        *,
        result_name: str = "file_write",
    ) -> ToolResult:
        path = str(payload.get("path") or payload.get("remote_path") or "").strip()
        content = str(payload.get("content") or "")
        if context is None:
            return ToolResult(
                result_name,
                "缺少 Tool 执行上下文，无法写入远程文件。",
                ok=False,
                metadata={"error_code": "missing_context", "path": path, "written": False},
            )
        instance = await _resolve_cloud_instance(payload, context)
        if instance is None or not instance.ssh_host or not instance.ssh_port or not instance.ssh_pass:
            return ToolResult(
                result_name,
                "当前任务没有可用 SSH 实例，无法写入远程文件。",
                ok=False,
                metadata={"error_code": "missing_cloud_instance", "path": path, "written": False},
            )
        try:
            import paramiko
        except ImportError:
            return ToolResult(
                result_name,
                "后端缺少 paramiko 依赖，无法通过 SFTP 写入远程文件。",
                ok=False,
                metadata={"error_code": "missing_dependency", "dependency": "paramiko"},
            )

        def _write_remote() -> None:
            client = paramiko.SSHClient()
            client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            try:
                client.connect(
                    hostname=str(instance.ssh_host),
                    port=int(instance.ssh_port or 22),
                    username=instance.ssh_user or "root",
                    password=instance.ssh_pass,
                    timeout=30,
                    banner_timeout=30,
                    auth_timeout=30,
                )
                parent = str(Path(path).parent).replace("\\", "/")
                client.exec_command(f"mkdir -p {_shell_quote(parent)}")
                sftp = client.open_sftp()
                try:
                    with sftp.open(path, "w") as handle:
                        handle.write(content)
                finally:
                    sftp.close()
            finally:
                client.close()

        try:
            await asyncio.to_thread(_write_remote)
        except Exception as exc:
            return ToolResult(
                result_name,
                f"远程文件写入失败：{type(exc).__name__}: {exc}",
                ok=False,
                metadata={"error_code": "remote_file_write_failed", "path": path, "written": False},
            )
        return ToolResult(
            result_name,
            f"已通过 SFTP 写入远程文件：{path}",
            metadata={"written": True, "remote": True, "path": path},
        )

    async def _file_read(
        self,
        payload: dict[str, Any],
        context: ToolExecutionContext | None,
        *,
        result_name: str = "file_system_read",
    ) -> ToolResult:
        path = str(payload.get("path") or payload.get("remote_path") or "").strip()
        if not path:
            return ToolResult(
                result_name,
                "未提供读取路径。",
                ok=False,
                metadata={"error_code": "missing_path"},
            )
        if _is_skills_path(path):
            return ToolResult(
                result_name,
                "拒绝读取 skills 目录内容。",
                ok=False,
                metadata={"error_code": "forbidden_path", "path": path},
            )
        max_chars = max(1, _as_int(payload.get("max_chars"), default=12000))
        if _is_remote_path(path) and not payload.get("local_only"):
            return await self._remote_file_read(
                payload,
                context,
                result_name=result_name,
                max_chars=max_chars,
            )

        try:
            target = _resolve_workspace_path(path, context)
            content = target.read_text(encoding="utf-8", errors="replace")
        except Exception as exc:
            return ToolResult(
                result_name,
                f"文件读取失败：{type(exc).__name__}: {exc}",
                ok=False,
                metadata={"error_code": "file_read_failed", "path": path},
            )
        truncated = len(content) > max_chars
        if truncated:
            content = content[:max_chars]
        return ToolResult(
            result_name,
            content,
            metadata={"path": str(target), "truncated": truncated},
        )

    async def _remote_file_read(
        self,
        payload: dict[str, Any],
        context: ToolExecutionContext | None,
        *,
        result_name: str,
        max_chars: int,
    ) -> ToolResult:
        path = str(payload.get("path") or payload.get("remote_path") or "").strip()
        if context is None:
            return ToolResult(
                result_name,
                "缺少 Tool 执行上下文，无法读取远程文件。",
                ok=False,
                metadata={"error_code": "missing_context", "path": path},
            )
        instance = await _resolve_cloud_instance(payload, context)
        if instance is None or not instance.ssh_host or not instance.ssh_port or not instance.ssh_pass:
            return ToolResult(
                result_name,
                "当前任务没有可用 SSH 实例，无法读取远程文件。",
                ok=False,
                metadata={"error_code": "missing_cloud_instance", "path": path},
            )
        try:
            import paramiko
        except ImportError:
            return ToolResult(
                result_name,
                "后端缺少 paramiko 依赖，无法通过 SFTP 读取远程文件。",
                ok=False,
                metadata={"error_code": "missing_dependency", "dependency": "paramiko"},
            )

        def _read_remote() -> str:
            client = paramiko.SSHClient()
            client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            try:
                client.connect(
                    hostname=str(instance.ssh_host),
                    port=int(instance.ssh_port or 22),
                    username=instance.ssh_user or "root",
                    password=instance.ssh_pass,
                    timeout=30,
                    banner_timeout=30,
                    auth_timeout=30,
                )
                sftp = client.open_sftp()
                try:
                    with sftp.open(path, "r") as handle:
                        data = handle.read(max_chars + 1)
                finally:
                    sftp.close()
            finally:
                client.close()
            if isinstance(data, bytes):
                return data.decode("utf-8", errors="replace")
            return str(data)

        try:
            content = await asyncio.to_thread(_read_remote)
        except Exception as exc:
            return ToolResult(
                result_name,
                f"远程文件读取失败：{type(exc).__name__}: {exc}",
                ok=False,
                metadata={"error_code": "remote_file_read_failed", "path": path},
            )
        truncated = len(content) > max_chars
        if truncated:
            content = content[:max_chars]
        return ToolResult(
            result_name,
            content,
            metadata={"remote": True, "path": path, "truncated": truncated},
        )

    async def _file_list(
        self,
        payload: dict[str, Any],
        context: ToolExecutionContext | None,
        *,
        result_name: str = "file_system_list",
    ) -> ToolResult:
        path = str(payload.get("path") or payload.get("remote_path") or ".").strip() or "."
        if _is_skills_path(path):
            return ToolResult(
                result_name,
                "拒绝列出 skills 目录内容。",
                ok=False,
                metadata={"error_code": "forbidden_path", "path": path},
            )
        max_entries = max(1, _as_int(payload.get("max_entries"), default=200))
        if _is_remote_path(path) and not payload.get("local_only"):
            return await self._remote_file_list(
                payload,
                context,
                result_name=result_name,
                max_entries=max_entries,
            )

        try:
            target = _resolve_workspace_path(path, context)
            entries = sorted(target.iterdir(), key=lambda item: item.name.lower())
        except Exception as exc:
            return ToolResult(
                result_name,
                f"目录读取失败：{type(exc).__name__}: {exc}",
                ok=False,
                metadata={"error_code": "file_list_failed", "path": path},
            )
        rows = [
            f"{'d' if entry.is_dir() else '-'} {entry.name}"
            for entry in entries[:max_entries]
        ]
        return ToolResult(
            result_name,
            "\n".join(rows),
            metadata={
                "path": str(target),
                "entries": [entry.name for entry in entries[:max_entries]],
                "truncated": len(entries) > max_entries,
            },
        )

    async def _remote_file_list(
        self,
        payload: dict[str, Any],
        context: ToolExecutionContext | None,
        *,
        result_name: str,
        max_entries: int,
    ) -> ToolResult:
        path = str(payload.get("path") or payload.get("remote_path") or ".").strip() or "."
        if context is None:
            return ToolResult(
                result_name,
                "缺少 Tool 执行上下文，无法列出远程目录。",
                ok=False,
                metadata={"error_code": "missing_context", "path": path},
            )
        instance = await _resolve_cloud_instance(payload, context)
        if instance is None or not instance.ssh_host or not instance.ssh_port or not instance.ssh_pass:
            return ToolResult(
                result_name,
                "当前任务没有可用 SSH 实例，无法列出远程目录。",
                ok=False,
                metadata={"error_code": "missing_cloud_instance", "path": path},
            )
        try:
            import paramiko
        except ImportError:
            return ToolResult(
                result_name,
                "后端缺少 paramiko 依赖，无法通过 SFTP 列出远程目录。",
                ok=False,
                metadata={"error_code": "missing_dependency", "dependency": "paramiko"},
            )

        def _list_remote() -> list[dict[str, Any]]:
            client = paramiko.SSHClient()
            client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            try:
                client.connect(
                    hostname=str(instance.ssh_host),
                    port=int(instance.ssh_port or 22),
                    username=instance.ssh_user or "root",
                    password=instance.ssh_pass,
                    timeout=30,
                    banner_timeout=30,
                    auth_timeout=30,
                )
                sftp = client.open_sftp()
                try:
                    attrs = sftp.listdir_attr(path)
                finally:
                    sftp.close()
            finally:
                client.close()
            return [
                {"name": item.filename, "size": int(getattr(item, "st_size", 0) or 0)}
                for item in sorted(attrs, key=lambda attr: attr.filename.lower())[:max_entries]
            ]

        try:
            entries = await asyncio.to_thread(_list_remote)
        except Exception as exc:
            return ToolResult(
                result_name,
                f"远程目录读取失败：{type(exc).__name__}: {exc}",
                ok=False,
                metadata={"error_code": "remote_file_list_failed", "path": path},
            )
        rows = [f"- {item['name']} {item['size']}B" for item in entries]
        return ToolResult(
            result_name,
            "\n".join(rows),
            metadata={"remote": True, "path": path, "entries": entries},
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

    async def _repro_report(
        self,
        payload: dict[str, Any],
        context: ToolExecutionContext | None,
        *,
        result_name: str = "repro_report",
    ) -> ToolResult:
        repo_name = str(payload.get("repo_name") or "project")
        report_payload = _build_report_kwargs(repo_name, payload)
        if context:
            report_payload["conversation_id"] = context.conversation_id
        result = await self._skill_runtime.invoke("generate_repro_report", report_payload)
        metadata = {**payload, **result.metadata}
        if result.ok and context:
            local_report_path = str(result.metadata.get("report_path") or "")
            remote_report_path = str(
                payload.get("remote_report_path") or _remote_codelab_report_path(repo_name)
            )
            publish_result = await self._publish_report_to_codelab(
                local_report_path,
                remote_report_path,
                {**payload, "resource_kind": payload.get("resource_kind") or "GPU"},
                context,
            )
            if publish_result.ok is False:
                return ToolResult(
                    result_name,
                    f"{result.content}\n{publish_result.content}",
                    ok=False,
                    metadata={**metadata, **publish_result.metadata},
                )
            metadata = {
                **metadata,
                "local_report_path": local_report_path,
                "remote_report_path": remote_report_path,
                "report_path": remote_report_path,
                "artifact_paths": [remote_report_path, local_report_path],
                "report_path_mapping": {
                    "skill_output_path": local_report_path,
                    "codelab_output_path": remote_report_path,
                },
            }
            return ToolResult(
                result_name,
                f"{result.content}\n远程报告已生成：{remote_report_path}",
                ok=True,
                metadata=metadata,
            )
        return ToolResult(
            result_name,
            result.content,
            ok=result.ok,
            metadata=metadata,
        )

    async def _publish_report_to_codelab(
        self,
        local_report_path: str,
        remote_report_path: str,
        payload: dict[str, Any],
        context: ToolExecutionContext,
    ) -> ToolResult:
        local_path = Path(local_report_path)
        if not local_path.exists():
            return ToolResult(
                "repro_report_publish",
                f"本地报告文件不存在，无法映射到远程 codelab 目录：{local_report_path}",
                ok=False,
                metadata={"error_code": "local_report_missing", "report_path": local_report_path},
            )
        instance = await _resolve_cloud_instance(payload, context)
        if instance is None or not instance.ssh_host or not instance.ssh_port or not instance.ssh_pass:
            return ToolResult(
                "repro_report_publish",
                "当前任务没有可用 GPU/SSH 实例，无法将报告写入 /workspace/user-data/codelab。",
                ok=False,
                metadata={"error_code": "missing_cloud_instance", "remote_report_path": remote_report_path},
            )
        try:
            import paramiko
        except ImportError:
            return ToolResult(
                "repro_report_publish",
                "后端缺少 paramiko 依赖，无法发布报告到远程实例。",
                ok=False,
                metadata={"error_code": "missing_dependency", "dependency": "paramiko"},
            )

        def _upload() -> None:
            client = paramiko.SSHClient()
            client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            try:
                client.connect(
                    hostname=str(instance.ssh_host),
                    port=int(instance.ssh_port or 22),
                    username=instance.ssh_user or "root",
                    password=instance.ssh_pass,
                    timeout=30,
                    banner_timeout=30,
                    auth_timeout=30,
                )
                parent = str(Path(remote_report_path).parent).replace("\\", "/")
                _stdin, stdout, stderr = client.exec_command(f"mkdir -p {_shell_quote(parent)}")
                exit_code = stdout.channel.recv_exit_status()
                if exit_code != 0:
                    error_text = stderr.read().decode("utf-8", errors="replace")
                    raise RuntimeError(error_text or f"mkdir failed with exit_code={exit_code}")
                sftp = client.open_sftp()
                try:
                    with local_path.open("rb") as source, sftp.open(remote_report_path, "wb") as target:
                        while chunk := source.read(1024 * 1024):
                            target.write(chunk)
                finally:
                    sftp.close()
            finally:
                client.close()

        try:
            await asyncio.to_thread(_upload)
        except Exception as exc:
            return ToolResult(
                "repro_report_publish",
                f"报告发布到远程 codelab 目录失败：{type(exc).__name__}: {exc}",
                ok=False,
                metadata={
                    "error_code": "remote_report_publish_failed",
                    "local_report_path": local_report_path,
                    "remote_report_path": remote_report_path,
                },
            )
        return ToolResult(
            "repro_report_publish",
            f"报告已映射到远程 codelab 目录：{remote_report_path}",
            metadata={
                "local_report_path": local_report_path,
                "remote_report_path": remote_report_path,
                "server_id": instance.server_id,
                "remote": True,
            },
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


def _build_tool_definitions(skill_runtime: SkillRuntime) -> dict[str, ToolDefinition]:
    definitions = {
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
        "analyze_paper": ToolDefinition(
            name="analyze_paper",
            description="解析论文 PDF，提取复现实验相关的方法、数据集、指标和超参数。",
            input_schema={
                "type": "object",
                "properties": {
                    "github_url": {"type": ["string", "null"]},
                    "paper_url": {"type": ["string", "null"]},
                    "paper_path": {"type": ["string", "null"]},
                    "output_dir": {"type": ["string", "null"]},
                },
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
                "properties": {
                    "command": {"type": "string"},
                    "server_id": {"type": "string"},
                    "resource_kind": {"type": "string", "enum": ["CPU", "GPU"]},
                    "timeout": {"type": "integer"},
                    "connect_retries": {"type": "integer"},
                    "connect_retry_interval": {"type": "integer"},
                },
                "required": ["command"],
            },
            confirmation_policy="risky",
            risk_level="high",
            audit_category="ssh",
            confirmation_reason="检测到命令可能破坏环境或产生长时间副作用。",
        ),
        "claw_shell_run": ToolDefinition(
            name="claw_shell_run",
            description="兼容旧 claw-shell 技能入口；底层映射为受控 ssh_execute，不执行本机 tmux。",
            input_schema={
                "type": "object",
                "properties": {
                    "command": {"type": "string"},
                    "server_id": {"type": "string"},
                    "resource_kind": {"type": "string", "enum": ["CPU", "GPU"]},
                    "timeout": {"type": "integer"},
                    "connect_retries": {"type": "integer"},
                    "connect_retry_interval": {"type": "integer"},
                },
                "required": ["command"],
            },
            confirmation_policy="risky",
            risk_level="high",
            audit_category="ssh",
            confirmation_reason="兼容旧 shell 技能的远程命令执行，必须通过后端 SSH 审计路径。",
        ),
        "ssh_essentials_execute": ToolDefinition(
            name="ssh_essentials_execute",
            description="兼容 ssh-essentials 中的远程命令语义；底层映射为受控 ssh_execute。",
            input_schema={
                "type": "object",
                "properties": {
                    "command": {"type": "string"},
                    "server_id": {"type": "string"},
                    "resource_kind": {"type": "string", "enum": ["CPU", "GPU"]},
                    "timeout": {"type": "integer"},
                },
                "required": ["command"],
            },
            confirmation_policy="risky",
            risk_level="high",
            audit_category="ssh",
            confirmation_reason="兼容旧 SSH 技能的远程命令执行，必须通过后端 SSH 审计路径。",
        ),
        "remote_project_prep": ToolDefinition(
            name="remote_project_prep",
            description="执行 lab4ai-project-prep 的后端安全适配器：创建或复用 Conda 环境、安装依赖、下载数据和权重。",
            input_schema={
                "type": "object",
                "properties": {
                    "repo_name": {"type": "string"},
                    "python_version": {"type": "string"},
                    "dependency_cmds": {"type": "array", "items": {"type": "string"}},
                    "data_cmds": {"type": "array", "items": {"type": "string"}},
                    "weight_cmds": {"type": "array", "items": {"type": "string"}},
                    "server_id": {"type": "string"},
                    "resource_kind": {"type": "string", "enum": ["CPU", "GPU"]},
                    "timeout": {"type": "integer"},
                },
                "required": ["repo_name", "dependency_cmds"],
            },
            confirmation_policy="risky",
            risk_level="high",
            audit_category="ssh",
            confirmation_reason="会在远程实例安装依赖、写入工作区或下载数据/权重。",
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
        "file_system_read": ToolDefinition(
            name="file_system_read",
            description="读取受控任务 workspace 或当前任务远程 workspace 中的文件。",
            input_schema={
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "server_id": {"type": "string"},
                    "resource_kind": {"type": "string", "enum": ["CPU", "GPU"]},
                    "max_chars": {"type": "integer"},
                },
                "required": ["path"],
            },
            read_only=True,
            risk_level="low",
            audit_category="file",
        ),
        "file_system_list": ToolDefinition(
            name="file_system_list",
            description="列出受控任务 workspace 或当前任务远程 workspace 中的目录。",
            input_schema={
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "server_id": {"type": "string"},
                    "resource_kind": {"type": "string", "enum": ["CPU", "GPU"]},
                    "max_entries": {"type": "integer"},
                },
            },
            read_only=True,
            risk_level="low",
            audit_category="file",
        ),
        "file_system_write": ToolDefinition(
            name="file_system_write",
            description="兼容 file-system 写入语义；底层映射为受控 file_write。",
            input_schema={
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "content": {"type": "string"},
                    "server_id": {"type": "string"},
                    "resource_kind": {"type": "string", "enum": ["CPU", "GPU"]},
                },
                "required": ["path", "content"],
            },
            confirmation_policy="always",
            confirmation_reason="写入文件可能覆盖任务产物或改变远程工作区状态。",
            risk_level="high",
            audit_category="file",
        ),
        "file_write": ToolDefinition(
            name="file_write",
            description="写入受控任务 workspace 或当前任务远程 workspace 文件。",
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
    for spec in skill_runtime.list_specs():
        definitions.setdefault(
            spec.name,
            ToolDefinition(
                name=spec.name,
                description=spec.description,
                input_schema=spec.input_schema,
            read_only=spec.name in {"repo_audit", "paper_analyze", "autoresearch_pipeline"},
            confirmation_policy=_skill_confirmation_policy(spec.name),
            confirmation_reason=_skill_confirmation_reason(spec.name),
            risk_level=_skill_risk_level(spec.name),
            audit_category=_skill_audit_category(spec.name),
            ),
        )
        for alias in spec.aliases:
            definitions.setdefault(
                alias,
                ToolDefinition(
                    name=alias,
                    description=spec.description,
                    input_schema=spec.input_schema,
                    read_only=alias in {"analyze_repo", "analyze_paper"},
                    risk_level="low",
                    audit_category="workflow",
                ),
            )
    return definitions


def _build_confirmation_question(tool: ToolDefinition, payload: dict[str, Any]) -> str:
    if tool.name in {"lab4ai_create_instance", "instance_create"}:
        resource_kind = str(payload.get("resource_kind") or "算力").upper()
        return (
            f"接下来需要创建一个 Lab4AI {resource_kind} 实例，用于继续复现流程。"
            "这会占用远程算力资源并可能产生费用。是否继续？"
        )
    if tool.name in SSH_EXECUTE_TOOL_NAMES:
        command = str(payload.get("command") or "").strip() or "(空命令)"
        return (
            "接下来需要在远程实例执行一条高风险命令："
            f"`{command}`。该操作可能修改环境或产生较长时间的副作用。是否继续？"
        )
    if tool.name in {"lab4ai_stop_instance", "instance_stop"}:
        return (
            "接下来需要停止并释放当前 Lab4AI 实例。"
            "释放后实例上的临时运行状态可能不可恢复。是否继续？"
        )
    if tool.name == "remote_project_prep":
        return (
            "接下来需要在远程实例执行项目准备命令。"
            "该操作会安装依赖、写入工作区或下载数据/权重。是否继续？"
        )
    if tool.name in FILE_WRITE_TOOL_NAMES:
        return (
            "接下来需要写入任务工作区文件。"
            "该操作可能覆盖已有产物或改变远程工作区状态。是否继续？"
        )
    return f"接下来需要执行一步受控操作。{tool.confirmation_reason}是否继续？"


def _skill_confirmation_policy(name: str) -> str:
    if name == "instance_create":
        return "always"
    if name in {"instance_stop", "remote_project_prep"}:
        return "risky"
    return "never"


def _skill_confirmation_reason(name: str) -> str:
    return {
        "instance_create": "会占用远程算力资源并可能产生费用。",
        "instance_stop": "会释放远程算力资源。",
        "remote_project_prep": "会在远程实例安装依赖、写入工作区或下载数据。",
    }.get(name, "")


def _skill_risk_level(name: str) -> str:
    if name == "instance_create":
        return "critical"
    if name in {"instance_stop", "remote_project_prep"}:
        return "high"
    return "low"


def _skill_audit_category(name: str) -> str:
    if name in {"instance_create", "instance_stop"}:
        return "lab4ai"
    if name == "remote_project_prep":
        return "ssh"
    return "workflow"


def _requires_confirmation(tool: ToolDefinition, payload: dict[str, Any]) -> bool:
    if tool.name == "lab4ai_stop_instance" and payload.get("force_cleanup"):
        return False
    if tool.name == "instance_stop" and payload.get("force_cleanup"):
        return False
    if tool.confirmation_policy == "never":
        return False
    if tool.confirmation_policy == "always":
        return True
    if tool.confirmation_policy == "risky" and tool.name in SSH_EXECUTE_TOOL_NAMES:
        return _is_risky_ssh_command(str(payload.get("command") or ""))
    if tool.confirmation_policy == "risky" and tool.name == "remote_project_prep":
        return True
    if tool.confirmation_policy == "risky" and tool.name in FILE_WRITE_TOOL_NAMES:
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


def _contains_unrendered_template(value: object) -> bool:
    if isinstance(value, str):
        return bool(re.search(r"\{\{\s*[^}]+\s*\}\}", value))
    if isinstance(value, dict):
        return any(_contains_unrendered_template(item) for item in value.values())
    if isinstance(value, (list, tuple, set)):
        return any(_contains_unrendered_template(item) for item in value)
    return False


def _as_list(value: object) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item) for item in value if str(item).strip()]
    if isinstance(value, tuple):
        return [str(item) for item in value if str(item).strip()]
    text = str(value).strip()
    return [text] if text else []


def _remote_project_prep_command(
    *,
    repo_name: str,
    python_version: str,
    dependency_cmds: list[str],
    data_cmds: list[str],
    weight_cmds: list[str],
) -> str:
    safe_name = _safe_remote_name(repo_name)
    base_dir = f"/workspace/user-data/codelab/{safe_name}"
    code_dir = f"{base_dir}/code"
    data_dir = f"{base_dir}/data"
    model_dir = f"{base_dir}/model"
    conda_env = f"/workspace/envs/{safe_name}"
    pyver = re.sub(r"[^0-9.]+", "", python_version).strip(".") or "3.10"

    lines = [
        "set -e",
        "export http_proxy=${http_proxy:-http://10.201.85.65:1080}",
        "export https_proxy=${https_proxy:-http://10.201.85.65:1080}",
        "export CUDA_HOME=${CUDA_HOME:-/usr/local/cuda}",
        "export PATH=$CUDA_HOME/bin:$PATH",
        f"BASE={_shell_quote(base_dir)}",
        f"CODE_DIR={_shell_quote(code_dir)}",
        f"DATA_DIR={_shell_quote(data_dir)}",
        f"MODEL_DIR={_shell_quote(model_dir)}",
        f"CONDA_ENV={_shell_quote(conda_env)}",
        'mkdir -p "$CODE_DIR" "$DATA_DIR" "$MODEL_DIR"',
        'test -d "$CODE_DIR"',
        'cd "$CODE_DIR"',
        'ln -sfn ../data data',
        'ln -sfn ../model model',
        "if [ ! -x /opt/conda/bin/conda ]; then echo 'Conda not found at /opt/conda/bin/conda'; exit 127; fi",
        'if [ -x "$CONDA_ENV/bin/python" ]; then',
        '  echo "Conda env already exists: $CONDA_ENV"',
        "else",
        f"  /opt/conda/bin/conda create --prefix \"$CONDA_ENV\" python={pyver} -y",
        "fi",
        'source /opt/conda/bin/activate "$CONDA_ENV"',
        "python -m pip install --upgrade pip",
        "python -m pip install gdown",
        'echo "Active Python: $(python --version)"',
    ]

    if dependency_cmds:
        lines.append("echo '[4/8] Installing dependency_cmds'")
        lines.extend(_retry_command_lines(dependency_cmds, label="dependency", sleep_seconds=5))
    else:
        lines.append("echo '[4/8] No dependency_cmds provided'")

    if data_cmds:
        lines.append("echo '[5/8] Running data_cmds'")
        lines.extend(_plain_command_lines(data_cmds, label="data"))
    else:
        lines.append("echo '[5/8] No data_cmds provided'")

    if weight_cmds:
        lines.extend(
            [
                "echo '[6/8] Running weight_cmds'",
                "export HF_ENDPOINT=${HF_ENDPOINT:-https://hf-mirror.com}",
            ]
        )
        lines.extend(_retry_command_lines(weight_cmds, label="weight", sleep_seconds=10))
        lines.extend(
            [
                'EMPTY_FILES=$(find "$MODEL_DIR" -type f \\( -name \'*.pt\' -o -name \'*.pth\' -o -name \'*.safetensors\' -o -name \'*.pkl\' -o -name \'*.bin\' -o -name \'*.npz\' \\) -size 0 2>/dev/null || true)',
                'if [ -n "$EMPTY_FILES" ]; then echo "Zero-byte model files found"; echo "$EMPTY_FILES"; exit 1; fi',
            ]
        )
    else:
        lines.append("echo '[6/8] No weight_cmds provided'")

    lines.extend(
        [
            "echo '[7/8] Import smoke test'",
            'if [ -f "$CODE_DIR/requirements.txt" ]; then',
            "  FAILED_IMPORTS=''",
            "  for PKG in $(grep -v '^#' \"$CODE_DIR/requirements.txt\" | grep -v '^$' | sed 's/[>=<!=].*//' | sed 's/\\[.*//' | tr '-' '_' | head -30); do",
            '    python -c "import $PKG" 2>/dev/null || FAILED_IMPORTS="$FAILED_IMPORTS $PKG"',
            "  done",
            '  if [ -n "$FAILED_IMPORTS" ]; then echo "Non-fatal import failures:$FAILED_IMPORTS"; fi',
            "fi",
            "echo REMOTE_PROJECT_PREP_SUCCESS",
        ]
    )
    return "bash -lc " + _shell_quote("\n".join(lines))


def _retry_command_lines(commands: list[str], *, label: str, sleep_seconds: int) -> list[str]:
    lines: list[str] = []
    total = len(commands)
    for index, command in enumerate(commands, start=1):
        lines.append(f"echo '[{label} {index}/{total}]'")
        lines.append(
            "{ "
            + command
            + "; } || { echo 'retry 1/2'; sleep "
            + str(sleep_seconds)
            + "; "
            + command
            + "; } || { echo 'retry 2/2'; sleep "
            + str(sleep_seconds)
            + "; "
            + command
            + "; }"
        )
    return lines


def _plain_command_lines(commands: list[str], *, label: str) -> list[str]:
    lines: list[str] = []
    total = len(commands)
    for index, command in enumerate(commands, start=1):
        lines.append(f"echo '[{label} {index}/{total}]'")
        lines.append(command)
    return lines


def _remote_codelab_report_path(repo_name: str) -> str:
    safe_name = _safe_remote_name(repo_name)
    return f"/workspace/user-data/codelab/{safe_name}/{safe_name}_Final_Repro_Report.docx"


def _safe_remote_name(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "-", value).strip("-") or "project"


async def _resolve_cloud_instance(
    payload: dict[str, Any],
    context: ToolExecutionContext,
) -> CloudInstance | None:
    server_id = str(payload.get("server_id") or "").strip()
    resource_kind = str(payload.get("resource_kind") or "").strip().upper()
    query = select(CloudInstance).where(
        CloudInstance.user_id == context.user_id,
        CloudInstance.status == CloudInstanceStatus.RUNNING,
    )
    if server_id:
        query = query.where(CloudInstance.server_id == server_id)
    elif context.conversation_id:
        query = query.where(CloudInstance.conversation_id == context.conversation_id)
    query = query.order_by(CloudInstance.started_at.desc())
    instances = (await context.session.execute(query)).scalars().all()
    if resource_kind in {"CPU", "GPU"}:
        expected = CloudInstanceType.CPU if resource_kind == "CPU" else CloudInstanceType.GPU
        instances = [item for item in instances if item.instance_type == expected]
    return instances[0] if instances else None


def _is_remote_path(path: str) -> bool:
    normalized = path.replace("\\", "/")
    return normalized.startswith("/workspace/") or normalized.startswith("/root/")


def _resolve_workspace_path(path: str, context: ToolExecutionContext | None) -> Path:
    settings = get_settings()
    root = settings.workspace_root_path.resolve()
    target = Path(path)
    if target.is_absolute():
        resolved = target.resolve()
    else:
        conversation = str(context.conversation_id if context else "manual")
        resolved = (root / conversation / target).resolve()
    if not _is_relative_to(resolved, root):
        raise ValueError("只能写入 runtime/workspaces 下的任务工作区")
    return resolved


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _tail(text: str, *, max_chars: int = 4000) -> str:
    if len(text) <= max_chars:
        return text
    return text[-max_chars:]


def _shell_quote(value: str) -> str:
    return "'" + value.replace("'", "'\"'\"'") + "'"


def _build_report_kwargs(repo_name: str, payload: dict[str, Any]) -> dict[str, Any]:
    workflow_results = payload.get("workflow_results") if isinstance(payload.get("workflow_results"), dict) else {}
    paper_info = payload.get("paper_info") if isinstance(payload.get("paper_info"), dict) else {}
    audit_info = payload.get("audit_info") if isinstance(payload.get("audit_info"), dict) else {}
    baseline_metrics = workflow_results.get("baseline_metrics")
    if not isinstance(baseline_metrics, dict):
        baseline_metrics = {}
    hyperparams = workflow_results.get("hyperparams")
    datasets = workflow_results.get("datasets")
    smoke_metrics = workflow_results.get("smoke_test_metrics")
    if not isinstance(smoke_metrics, dict):
        smoke_metrics = {}
    project_profile = str(
        payload.get("project_profile")
        or _join_non_empty(
            [
                f"项目名称：{repo_name}",
                f"GitHub：{payload.get('github_url') or workflow_results.get('github_url') or ''}",
                f"论文：{payload.get('paper_url') or workflow_results.get('paper_url') or ''}",
                f"仓库审计：{audit_info.get('summary') or workflow_results.get('audit_report_path') or ''}",
                f"论文/官方基准：{baseline_metrics or 'N/A'}",
            ]
        )
    )
    implementation_steps = payload.get("implementation_steps")
    if not isinstance(implementation_steps, dict):
        implementation_steps = {
            "code_fetch": str(
                payload.get("code_fetch")
                or f"Step 4 将代码克隆到远程共享目录 /workspace/user-data/codelab/{repo_name}/code。"
            ),
            "env_setup": str(
                payload.get("env_setup")
                or (
                    "Step 4 调用 lab4ai-project-prep 创建/复用 Conda 环境并安装依赖；"
                    "Step 7 激活该环境，注入 CUDA_HOME、CPATH、LD_LIBRARY_PATH、"
                    "TORCH_CUDA_ARCH_LIST=9.0 和 MAX_JOBS=8，并记录 env_patches.md。"
                )
            ),
            "data_params": str(
                payload.get("data_params")
                or f"数据集：{datasets or 'N/A'}；超参数：{hyperparams or 'N/A'}。"
            ),
            "core_loop": str(
                payload.get("core_loop")
                or (
                    "Step 7 按优先级探测 scripts/*.sh、examples/demo Python 入口，"
                    "失败时执行内联 CUDA smoke test；日志写入 repro_run.log。"
                    f" stdout_tail={smoke_metrics.get('stdout_tail') or 'N/A'}"
                )
            ),
            "eval_process": str(
                payload.get("eval_process")
                or (
                    "评估以 Step 7 捕获的真实 GPU smoke/推理日志为依据；"
                    f"status={smoke_metrics.get('status') or 'N/A'}，"
                    f"exit_code={smoke_metrics.get('exit_code') or 'N/A'}。"
                )
            ),
        }
    results_comparison = payload.get("results_comparison")
    if not isinstance(results_comparison, list):
        metrics = paper_info.get("metrics") or workflow_results.get("metrics") or baseline_metrics
        results_comparison = _report_results_comparison(metrics, smoke_metrics)
    return {
        "repo_name": repo_name,
        "project_profile": project_profile,
        "implementation_steps": implementation_steps,
        "results_comparison": results_comparison,
        "optimization_suggestions": str(
            payload.get("optimization_suggestions")
            or "建议在真实 GPU 阶段完成全量训练后，用记录的日志和指标更新本报告。"
        ),
        "font_english": str(payload.get("font_english") or "Times New Roman"),
        "font_chinese": str(payload.get("font_chinese") or "微软雅黑"),
    }


def _report_results_comparison(metrics: object, smoke_metrics: dict[str, Any]) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    if isinstance(metrics, dict):
        for key, value in metrics.items():
            rows.append(
                {
                    "metric_name": str(key),
                    "official_value": str(value or "N/A"),
                    "reproduced_value": "Pending" if not smoke_metrics else str(smoke_metrics.get(key) or "N/A"),
                }
            )
    elif isinstance(metrics, list):
        for item in metrics:
            rows.append(
                {
                    "metric_name": str(item),
                    "official_value": "N/A",
                    "reproduced_value": "Pending",
                }
            )
    rows.append(
        {
            "metric_name": "GPU smoke test status",
            "official_value": "N/A",
            "reproduced_value": str(smoke_metrics.get("status") or "Pending"),
        }
    )
    if smoke_metrics.get("exit_code") is not None:
        rows.append(
            {
                "metric_name": "GPU smoke test exit_code",
                "official_value": "0",
                "reproduced_value": str(smoke_metrics.get("exit_code")),
            }
        )
    return rows


def _join_non_empty(parts: list[str]) -> str:
    return "\n".join(part for part in parts if part.strip())


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
