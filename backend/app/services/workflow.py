"""Workflow runtime for skill-backed reproduction tasks."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Awaitable, Callable
from uuid import uuid4

from app.services.conversation_memory import ensure_memory, remember_artifact, remember_fact
from app.services.tools import ToolResult

WORKFLOW_STEP_PENDING = "pending"
WORKFLOW_STEP_RUNNING = "running"
WORKFLOW_STEP_WAITING = "waiting_for_user"
WORKFLOW_STEP_COMPLETED = "completed"
WORKFLOW_STEP_FAILED = "failed"
WORKFLOW_STEP_SKIPPED = "skipped"

STEP_ALLOWED_TOOLS = {
    "step_1_audit": ["analyze_repo", "analyze_paper"],
    "step_2_condition_check": [],
    "step_3_deploy_cpu": ["lab4ai_create_instance"],
    "step_4_cpu_env_setup": [
        "ssh_execute",
        "claw_shell_run",
        "remote_project_prep",
        "file_system_read",
        "file_system_list",
        "file_write",
    ],
    "step_5_release_cpu": ["lab4ai_stop_instance"],
    "step_6_deploy_gpu": ["lab4ai_create_instance"],
    "step_7_gpu_execution": [
        "ssh_execute",
        "claw_shell_run",
        "file_system_read",
        "file_system_list",
        "file_write",
    ],
    "step_8_generate_report": ["repro_report", "file_write"],
    "step_9_release_gpu": ["lab4ai_stop_instance"],
}

TOOL_AUDIT_METADATA = {
    "analyze_repo": {"audit_category": "general", "risk_level": "low"},
    "analyze_paper": {"audit_category": "general", "risk_level": "low"},
    "lab4ai_create_instance": {"audit_category": "lab4ai", "risk_level": "high"},
    "lab4ai_stop_instance": {"audit_category": "lab4ai", "risk_level": "medium"},
    "ssh_execute": {"audit_category": "ssh", "risk_level": "high"},
    "claw_shell_run": {"audit_category": "ssh", "risk_level": "high"},
    "remote_project_prep": {"audit_category": "ssh", "risk_level": "high"},
    "file_system_read": {"audit_category": "file", "risk_level": "low"},
    "file_system_list": {"audit_category": "file", "risk_level": "low"},
    "file_write": {"audit_category": "file", "risk_level": "high"},
    "repro_report": {"audit_category": "workflow", "risk_level": "low"},
}

FIXED_EXECUTOR_STEPS = {
    "step_1_audit",
    "step_2_condition_check",
    "step_3_deploy_cpu",
    "step_4_cpu_env_setup",
    "step_5_release_cpu",
    "step_6_deploy_gpu",
    "step_7_gpu_execution",
    "step_8_generate_report",
    "step_9_release_gpu",
}


@dataclass(frozen=True, slots=True)
class StepCompletionContract:
    required_tools: tuple[str, ...] = ()
    required_effects: tuple[str, ...] = ()
    required_evidence: tuple[str, ...] = ()


TOOL_EFFECTS = {
    "analyze_repo": {"analysis"},
    "analyze_paper": {"analysis"},
    "lab4ai_create_instance": {"instance_lifecycle"},
    "lab4ai_stop_instance": {"instance_lifecycle"},
    "ssh_execute": {"remote_execute", "remote_write"},
    "claw_shell_run": {"remote_execute", "remote_write"},
    "ssh_essentials_execute": {"remote_execute", "remote_write"},
    "remote_project_prep": {"remote_execute", "remote_write"},
    "file_system_read": {"read_only"},
    "file_system_list": {"read_only"},
    "file_write": {"file_write"},
    "file_system_write": {"file_write"},
    "repro_report": {"local_artifact"},
    "generate_repro_report": {"local_artifact"},
}

TOOL_CONTRACT_ALIASES = {
    "claw_shell_run": "ssh_execute",
    "ssh_essentials_execute": "ssh_execute",
    "remote_project_prep": "ssh_execute",
    "generate_repro_report": "repro_report",
}

STEP_COMPLETION_CONTRACTS = {
    "step_3_deploy_cpu": StepCompletionContract(
        required_tools=("lab4ai_create_instance",),
        required_effects=("instance_lifecycle",),
        required_evidence=("cpu_instance_created",),
    ),
    "step_4_cpu_env_setup": StepCompletionContract(
        required_tools=("ssh_execute",),
        required_effects=("remote_execute", "remote_write"),
        required_evidence=(
            "remote_workspace_verified",
            "git_repo_verified",
            "dependency_install_attempted",
        ),
    ),
    "step_5_release_cpu": StepCompletionContract(
        required_tools=("lab4ai_stop_instance",),
        required_effects=("instance_lifecycle",),
        required_evidence=("cpu_instance_released",),
    ),
    "step_6_deploy_gpu": StepCompletionContract(
        required_tools=("lab4ai_create_instance",),
        required_effects=("instance_lifecycle",),
        required_evidence=("gpu_instance_created",),
    ),
    "step_7_gpu_execution": StepCompletionContract(
        required_tools=("ssh_execute",),
        required_effects=("remote_execute",),
        required_evidence=("gpu_workspace_verified", "smoke_test_executed"),
    ),
    "step_8_generate_report": StepCompletionContract(
        required_tools=("repro_report",),
        required_effects=("local_artifact",),
        required_evidence=("report_generated",),
    ),
    "step_9_release_gpu": StepCompletionContract(
        required_tools=("lab4ai_stop_instance",),
        required_effects=("instance_lifecycle",),
        required_evidence=("gpu_instance_released",),
    ),
}


@dataclass(frozen=True, slots=True)
class WorkflowStep:
    id: str
    name: str
    depends_on: list[str] = field(default_factory=list)
    instruction: str = ""
    expected_output: str = ""


@dataclass(frozen=True, slots=True)
class WorkflowDefinition:
    version: str = ""
    name: str = ""
    description: str = ""
    steps: list[WorkflowStep] = field(default_factory=list)


ToolInvoker = Callable[
    [dict, str, dict[str, object]],
    Awaitable[tuple[ToolResult | None, dict, bool]],
]
StepModelToolRunner = Callable[
    [dict, WorkflowStep],
    Awaitable[tuple[dict, list[str], bool, bool] | tuple[dict, list[str], bool, bool, bool]],
]
MetadataWriter = Callable[[dict], Awaitable[None]]
EventPublisher = Callable[[dict], None]


@dataclass(slots=True)
class WorkflowRunResult:
    metadata: dict
    tool_outputs: list[str]
    paused: bool = False
    failed: bool = False


class SkillWorkflowRunner:
    def __init__(
        self,
        workflow: WorkflowDefinition,
        *,
        skill_name: str,
        invoke_tool: ToolInvoker,
        write_metadata: MetadataWriter,
        publish: EventPublisher,
        run_step_model_tools: StepModelToolRunner | None = None,
    ) -> None:
        self.workflow = workflow
        self.skill_name = skill_name
        self.invoke_tool = invoke_tool
        self.write_metadata = write_metadata
        self.publish = publish
        self.run_step_model_tools = run_step_model_tools
        self._latest_metadata: dict = {}

    async def run(self, metadata: dict) -> WorkflowRunResult:
        metadata = ensure_workflow_metadata(
            metadata,
            self.workflow,
            skill_name=self.skill_name,
        )
        self._latest_metadata = metadata
        await self.write_metadata(metadata)
        self.publish(
            {
                "type": "workflow_loaded",
                "workflow": workflow_public_state(metadata),
            }
        )

        tool_outputs: list[str] = []
        for step in self.workflow.steps:
            current = workflow_step_state(metadata, step.id)
            if current and current.get("status") == WORKFLOW_STEP_COMPLETED:
                contract_error = validate_workflow_step_contract(metadata, step)
                if contract_error:
                    metadata = mark_workflow_step(
                        metadata,
                        step,
                        WORKFLOW_STEP_FAILED,
                        output=contract_error,
                        error=contract_error,
                    )
                    metadata, cleanup_outputs = await cleanup_workflow_resources(
                        metadata,
                        self.invoke_tool,
                        self.write_metadata,
                        self.publish,
                    )
                    tool_outputs.extend(cleanup_outputs)
                    await self.write_metadata(metadata)
                    self._publish_step("workflow_step_failed", metadata, step)
                    return WorkflowRunResult(
                        metadata=metadata,
                        tool_outputs=tool_outputs,
                        failed=True,
                    )
                continue
            if not dependencies_completed(metadata, step):
                metadata = mark_workflow_step(
                    metadata,
                    step,
                    WORKFLOW_STEP_FAILED,
                    output="依赖步骤尚未完成，workflow 已中止。",
                    error="Workflow dependency step has not completed.",
                )
                metadata, cleanup_outputs = await cleanup_workflow_resources(
                    metadata,
                    self.invoke_tool,
                    self.write_metadata,
                    self.publish,
                )
                tool_outputs.extend(cleanup_outputs)
                await self.write_metadata(metadata)
                self._publish_step("workflow_step_failed", metadata, step)
                return WorkflowRunResult(
                    metadata=metadata,
                    tool_outputs=tool_outputs,
                    failed=True,
                )

            metadata = mark_workflow_step(metadata, step, WORKFLOW_STEP_RUNNING)
            metadata["workflow_current_step_id"] = step.id
            await self.write_metadata(metadata)
            self._publish_step("workflow_step_started", metadata, step)
            metadata = await self._publish_step_progress(
                metadata,
                step,
                f"Start step: {step.name}",
            )

            try:
                metadata, outputs, paused = await self._execute_step(metadata, step)
            except Exception as exc:
                metadata = self._latest_metadata or metadata
                metadata = mark_workflow_step(
                    metadata,
                    step,
                    WORKFLOW_STEP_FAILED,
                    output=f"{type(exc).__name__}: {exc}",
                    error=f"{type(exc).__name__}: {exc}",
                )
                metadata, cleanup_outputs = await cleanup_workflow_resources(
                    metadata,
                    self.invoke_tool,
                    self.write_metadata,
                    self.publish,
                )
                tool_outputs.extend(cleanup_outputs)
                await self.write_metadata(metadata)
                self._publish_step("workflow_step_failed", metadata, step)
                raise

            tool_outputs.extend(outputs)
            if paused:
                metadata = mark_workflow_step(
                    metadata,
                    step,
                    WORKFLOW_STEP_WAITING,
                    output="等待用户确认后继续。",
                )
                await self.write_metadata(metadata)
                self._publish_step("workflow_step_waiting", metadata, step)
                return WorkflowRunResult(metadata=metadata, tool_outputs=tool_outputs, paused=True)

            current_status = workflow_step_state(metadata, step.id).get("status")
            if current_status == WORKFLOW_STEP_FAILED:
                metadata, cleanup_outputs = await cleanup_workflow_resources(
                    metadata,
                    self.invoke_tool,
                    self.write_metadata,
                    self.publish,
                )
                tool_outputs.extend(cleanup_outputs)
                await self.write_metadata(metadata)
                self._publish_step("workflow_step_failed", metadata, step)
                return WorkflowRunResult(
                    metadata=metadata,
                    tool_outputs=tool_outputs,
                    failed=True,
                )
            if current_status == WORKFLOW_STEP_SKIPPED:
                await self.write_metadata(metadata)
                self._publish_step("workflow_step_completed", metadata, step)
                continue
            if current_status != WORKFLOW_STEP_COMPLETED:
                metadata = mark_workflow_step(
                    metadata,
                    step,
                    WORKFLOW_STEP_COMPLETED,
                    output=step_output_for(metadata, step.id),
                )
            contract_error = validate_workflow_step_contract(metadata, step)
            if contract_error:
                metadata = mark_workflow_step(
                    metadata,
                    step,
                    WORKFLOW_STEP_FAILED,
                    output=contract_error,
                    error=contract_error,
                )
                metadata, cleanup_outputs = await cleanup_workflow_resources(
                    metadata,
                    self.invoke_tool,
                    self.write_metadata,
                    self.publish,
                )
                tool_outputs.extend(cleanup_outputs)
                await self.write_metadata(metadata)
                self._publish_step("workflow_step_failed", metadata, step)
                return WorkflowRunResult(
                    metadata=metadata,
                    tool_outputs=tool_outputs,
                    failed=True,
                )
            await self.write_metadata(metadata)
            self._publish_step("workflow_step_completed", metadata, step)

        metadata["workflow_current_step_id"] = None
        await self.write_metadata(metadata)
        return WorkflowRunResult(metadata=metadata, tool_outputs=tool_outputs)

    async def _execute_step(
        self,
        metadata: dict,
        step: WorkflowStep,
    ) -> tuple[dict, list[str], bool]:
        repo_name = repo_name_from_url(str(metadata.get("github_url") or "project"))
        outputs: list[str] = []

        metadata, model_outputs, paused, handled, model_failed = await self._run_model_tools_for_step(
            metadata,
            step,
        )
        outputs.extend(model_outputs)
        if paused:
            return metadata, outputs, True
        if model_failed:
            output = "\n".join(model_outputs) or "step 内模型 tool-use 执行失败。"
            return (
                mark_workflow_step(
                    metadata,
                    step,
                    WORKFLOW_STEP_FAILED,
                    output=output,
                    error=output,
                ),
                outputs,
                False,
            )
        if handled and step.id not in FIXED_EXECUTOR_STEPS:
            return (
                mark_workflow_step(
                    metadata,
                    step,
                    WORKFLOW_STEP_COMPLETED,
                    output="\n".join(model_outputs) or "step 内模型 tool-use 已完成。",
                ),
                outputs,
                False,
            )

        if step.id == "step_1_audit":
            repo_result, metadata, paused = await self._invoke_step_tool(
                metadata,
                step,
                "analyze_repo",
                {"github_url": metadata.get("github_url")},
            )
            if paused:
                return metadata, outputs, True
            if repo_result:
                outputs.append(f"{repo_result.name}: {repo_result.content}")
            if not repo_result or repo_result.ok is False:
                return metadata, outputs, False

            paper_result = None
            if metadata.get("paper_url"):
                paper_result, metadata, paused = await self._invoke_step_tool(
                    metadata,
                    step,
                    "analyze_paper",
                    {
                        "github_url": metadata.get("github_url"),
                        "paper_url": metadata.get("paper_url"),
                    },
                )
                if paused:
                    return metadata, outputs, True
                if paper_result:
                    outputs.append(f"{paper_result.name}: {paper_result.content}")
                if paper_result and paper_result.ok is False:
                    return metadata, outputs, False

            repo_score = _score_from_tool(repo_result, default=0)
            paper_score = _score_from_tool(paper_result, default=repo_score)
            combined_score = _combined_score(repo_score, paper_score, has_paper=bool(paper_result))
            metadata = ensure_workflow_results(metadata)
            metadata["workflow_results"].update(
                {
                    "repo_name": repo_name,
                    "score": combined_score,
                    "repo_score": repo_score,
                    "paper_score": paper_score if paper_result else None,
                    "audit_report_path": str(repo_result.metadata.get("report_path") or ""),
                    "paper_report_path": str(
                        (paper_result.metadata if paper_result else {}).get("report_path") or ""
                    ),
                    "baseline_metrics": (
                        (paper_result.metadata if paper_result else {}).get("metrics") or {}
                    ),
                    "hyperparams": (
                        (paper_result.metadata if paper_result else {}).get("hyperparams") or {}
                    ),
                    "datasets": (
                        (paper_result.metadata if paper_result else {}).get("datasets") or []
                    ),
                }
            )
            for artifact in _artifact_paths(repo_result):
                metadata = add_workflow_step_artifact(metadata, step, artifact)
            if paper_result:
                for artifact in _artifact_paths(paper_result):
                    metadata = add_workflow_step_artifact(metadata, step, artifact)
            metadata = remember_fact(metadata, f"目标仓库：{metadata.get('github_url')}")
            if metadata.get("paper_url"):
                metadata = remember_fact(metadata, f"论文链接：{metadata.get('paper_url')}")
            return (
                mark_workflow_step(
                    metadata,
                    step,
                    WORKFLOW_STEP_COMPLETED,
                    output=f"score={combined_score}；已完成仓库审计"
                    + ("与论文分析。" if paper_result else "。"),
                ),
                outputs,
                False,
            )

        if step.id == "step_2_condition_check":
            score = int(ensure_workflow_results(metadata)["workflow_results"].get("score") or 0)
            status = WORKFLOW_STEP_COMPLETED if score >= 60 else WORKFLOW_STEP_FAILED
            output = "验证通过，继续执行。" if score >= 60 else f"score={score}，低于 60，触发熔断。"
            return (
                mark_workflow_step(
                    metadata,
                    step,
                    status,
                    output=output,
                    error=None if status == WORKFLOW_STEP_COMPLETED else output,
                ),
                outputs,
                False,
            )

        if step.id == "step_3_deploy_cpu":
            result, metadata, paused = await self._invoke_step_tool(
                metadata,
                step,
                "lab4ai_create_instance",
                {
                    "resource_kind": "CPU",
                    "cpu_cores": 2,
                },
            )
            if paused:
                return metadata, outputs, True
            if result:
                outputs.append(f"{result.name}: {result.content}")
                server_id = str(result.metadata.get("server_id") or "")
                if not server_id:
                    raise RuntimeError("lab4ai_create_instance 未返回 server_id")
                metadata = set_workflow_resource(
                    metadata,
                    "cpu",
                    server_id=server_id,
                    released=False,
                    raw=result.metadata,
                )
                metadata = add_workflow_step_artifact(metadata, step, f"lab4ai:cpu:{server_id}")
                metadata = set_workflow_step_evidence(
                    metadata,
                    step,
                    cpu_instance_created=True,
                    server_id=server_id,
                    completion_source="fixed_executor",
                )
                metadata = remember_artifact(metadata, f"CPU 实例：{server_id}")
                return (
                    mark_workflow_step(
                        metadata,
                        step,
                        WORKFLOW_STEP_COMPLETED,
                        output=f"CPU 实例已创建：{server_id}",
                    ),
                    outputs,
                    False,
                )

        if step.id == "step_4_cpu_env_setup":
            server_id = workflow_resource_server_id(metadata, "cpu")
            command = _cpu_prepare_command(metadata, repo_name)
            result, metadata, paused = await self._invoke_step_tool(
                metadata,
                step,
                "ssh_execute",
                {
                    "server_id": server_id,
                    "resource_kind": "CPU",
                    "command": command,
                    "timeout": 600,
                },
            )
            if paused:
                return metadata, outputs, True
            if result:
                outputs.append(f"{result.name}: {result.content}")
            if not result or result.ok is False:
                return metadata, outputs, False
            verify_result, metadata, paused = await self._invoke_step_tool(
                metadata,
                step,
                "ssh_execute",
                {
                    "server_id": server_id,
                    "resource_kind": "CPU",
                    "command": _cpu_prepare_verify_command(repo_name),
                    "timeout": 120,
                },
            )
            if paused:
                return metadata, outputs, True
            if verify_result:
                outputs.append(f"{verify_result.name}: {verify_result.content}")
            if not verify_result or verify_result.ok is False:
                return metadata, outputs, False
            metadata = add_workflow_step_artifact(metadata, step, f"remote:/workspace/user-data/codelab/{repo_name}")
            metadata = set_workflow_step_evidence(
                metadata,
                step,
                remote_workspace_verified=True,
                git_repo_verified=True,
                dependency_install_attempted=True,
                completion_source="fixed_executor",
                verify_stdout_tail=str(verify_result.metadata.get("stdout") or "")[-1000:],
            )
            return (
                mark_workflow_step(
                    metadata,
                    step,
                    WORKFLOW_STEP_COMPLETED,
                    output="CPU 环境准备命令已真实执行完成。",
                ),
                outputs,
                False,
            )

        if step.id == "step_5_release_cpu":
            server_id = workflow_resource_server_id(metadata, "cpu")
            result, metadata, paused = await self._invoke_step_tool(
                metadata,
                step,
                "lab4ai_stop_instance",
                {"server_id": server_id},
            )
            if paused:
                return metadata, outputs, True
            if result:
                outputs.append(f"{result.name}: {result.content}")
            metadata = set_workflow_resource(metadata, "cpu", released=True)
            metadata = set_workflow_step_evidence(
                metadata,
                step,
                cpu_instance_released=bool(server_id),
                server_id=server_id or "",
                completion_source="fixed_executor",
            )
            return (
                mark_workflow_step(
                    metadata,
                    step,
                    WORKFLOW_STEP_COMPLETED,
                    output=f"CPU 实例已释放：{server_id or '未记录 server_id'}",
                ),
                outputs,
                False,
            )

        if step.id == "step_6_deploy_gpu":
            result, metadata, paused = await self._invoke_step_tool(
                metadata,
                step,
                "lab4ai_create_instance",
                {
                    "resource_kind": "GPU",
                    "gpu_count": 1,
                },
            )
            if paused:
                return metadata, outputs, True
            if result:
                outputs.append(f"{result.name}: {result.content}")
                server_id = str(result.metadata.get("server_id") or "")
                if not server_id:
                    raise RuntimeError("lab4ai_create_instance 未返回 server_id")
                metadata = set_workflow_resource(
                    metadata,
                    "gpu",
                    server_id=server_id,
                    released=False,
                    raw=result.metadata,
                )
                metadata = add_workflow_step_artifact(metadata, step, f"lab4ai:gpu:{server_id}")
                metadata = set_workflow_step_evidence(
                    metadata,
                    step,
                    gpu_instance_created=True,
                    server_id=server_id,
                    completion_source="fixed_executor",
                )
                metadata = remember_artifact(metadata, f"GPU 实例：{server_id}")
                return (
                    mark_workflow_step(
                        metadata,
                        step,
                        WORKFLOW_STEP_COMPLETED,
                        output=f"GPU 实例已创建：{server_id}",
                    ),
                    outputs,
                    False,
                )

        if step.id == "step_7_gpu_execution":
            server_id = workflow_resource_server_id(metadata, "gpu")
            command = _gpu_smoke_command(repo_name)
            result, metadata, paused = await self._invoke_step_tool(
                metadata,
                step,
                "ssh_execute",
                {
                    "server_id": server_id,
                    "resource_kind": "GPU",
                    "command": command,
                    "timeout": 1800,
                },
            )
            if paused:
                return metadata, outputs, True
            if result:
                outputs.append(f"{result.name}: {result.content}")
            if not result or result.ok is False:
                return metadata, outputs, False
            verify_result, metadata, paused = await self._invoke_step_tool(
                metadata,
                step,
                "ssh_execute",
                {
                    "server_id": server_id,
                    "resource_kind": "GPU",
                    "command": _gpu_workspace_verify_command(repo_name),
                    "timeout": 120,
                },
            )
            if paused:
                return metadata, outputs, True
            if verify_result:
                outputs.append(f"{verify_result.name}: {verify_result.content}")
            if not verify_result or verify_result.ok is False:
                return metadata, outputs, False
            metadata = ensure_workflow_results(metadata)
            metadata["workflow_results"]["smoke_test_metrics"] = {
                "status": "passed" if result.ok else "failed",
                "exit_code": result.metadata.get("exit_code"),
                "stdout_tail": str(result.metadata.get("stdout") or "")[-2000:],
                "stderr_tail": str(result.metadata.get("stderr") or "")[-2000:],
            }
            metadata = set_workflow_step_evidence(
                metadata,
                step,
                gpu_workspace_verified=True,
                smoke_test_executed=True,
                completion_source="fixed_executor",
                verify_stdout_tail=str(verify_result.metadata.get("stdout") or "")[-1000:],
            )
            return (
                mark_workflow_step(
                    metadata,
                    step,
                    WORKFLOW_STEP_COMPLETED,
                    output="GPU Smoke Test 已真实执行完成。",
                ),
                outputs,
                False,
            )

        if step.id == "step_8_generate_report":
            result, metadata, paused = await self._invoke_step_tool(
                metadata,
                step,
                "repro_report",
                {
                    "repo_name": repo_name,
                    "github_url": metadata.get("github_url"),
                    "paper_url": metadata.get("paper_url"),
                    "workflow_results": metadata.get("workflow_results") or {},
                },
            )
            if paused:
                return metadata, outputs, True
            report_path = ""
            if result:
                outputs.append(f"{result.name}: {result.content}")
                report_path = str(result.metadata.get("report_path") or report_path)
            if not result or result.ok is False:
                return metadata, outputs, False
            metadata = ensure_workflow_results(metadata)
            metadata["workflow_results"]["word_report_path"] = report_path
            metadata = set_workflow_step_evidence(
                metadata,
                step,
                report_generated=bool(report_path),
                report_path=report_path,
                completion_source="fixed_executor",
            )
            for artifact in _artifact_paths(result):
                metadata = add_workflow_step_artifact(metadata, step, artifact)
                metadata = remember_artifact(metadata, f"复现报告：{artifact}")
            return (
                mark_workflow_step(
                    metadata,
                    step,
                    WORKFLOW_STEP_COMPLETED,
                    output=f"Word 报告已生成：{report_path}",
                ),
                outputs,
                False,
            )

        if step.id == "step_9_release_gpu":
            server_id = workflow_resource_server_id(metadata, "gpu")
            result, metadata, paused = await self._invoke_step_tool(
                metadata,
                step,
                "lab4ai_stop_instance",
                {"server_id": server_id},
            )
            if paused:
                return metadata, outputs, True
            if result:
                outputs.append(f"{result.name}: {result.content}")
            metadata = set_workflow_resource(metadata, "gpu", released=True)
            metadata = set_workflow_step_evidence(
                metadata,
                step,
                gpu_instance_released=bool(server_id),
                server_id=server_id or "",
                completion_source="fixed_executor",
            )
            return (
                mark_workflow_step(
                    metadata,
                    step,
                    WORKFLOW_STEP_COMPLETED,
                    output=f"GPU 实例已释放：{server_id or '未记录 server_id'}",
                ),
                outputs,
                False,
            )

        return (
            mark_workflow_step(
                metadata,
                step,
                WORKFLOW_STEP_SKIPPED,
                output="当前后端尚未实现该 workflow step 的 executor。",
            ),
            outputs,
            False,
        )

    def _publish_step(self, event_type: str, metadata: dict, step: WorkflowStep) -> None:
        self.publish(
            {
                "type": event_type,
                "step": workflow_step_state(metadata, step.id),
                "workflow": workflow_public_state(metadata),
            }
        )

    async def _publish_step_progress(
        self,
        metadata: dict,
        step: WorkflowStep,
        content: str,
    ) -> dict:
        metadata = add_workflow_step_progress(metadata, step, content)
        self._latest_metadata = metadata
        await self.write_metadata(metadata)
        self.publish(
            {
                "type": "workflow_step_progress",
                "workflow_step_id": step.id,
                "content": content,
                "step": workflow_step_state(metadata, step.id),
                "workflow": workflow_public_state(metadata),
            }
        )
        return metadata

    async def _invoke_step_tool(
        self,
        metadata: dict,
        step: WorkflowStep,
        tool_name: str,
        tool_input: dict[str, object] | None = None,
    ) -> tuple[ToolResult | None, dict, bool]:
        payload = dict(tool_input or {})
        payload.setdefault("workflow_step_id", step.id)
        tool_call_id = str(
            payload.get("tool_call_id")
            or _waiting_tool_call_id(metadata, step.id, tool_name)
            or f"toolu_{uuid4().hex}"
        )
        payload["tool_call_id"] = tool_call_id

        if _has_tool_call(metadata, step.id, tool_call_id):
            metadata = update_workflow_tool_call(
                metadata,
                step.id,
                tool_call_id,
                status="running",
            )
        else:
            metadata = add_workflow_tool_call(
                metadata,
                step,
                tool_call_id=tool_call_id,
                tool_name=tool_name,
                status="running",
            )
        self._latest_metadata = metadata
        metadata = await self._publish_step_progress(
            metadata,
            step,
            f"Invoking tool: {tool_name}",
        )

        try:
            result, metadata, paused = await self.invoke_tool(metadata, tool_name, payload)
        except Exception as exc:
            error = _format_exception(exc)
            metadata = update_workflow_tool_call(
                metadata,
                step.id,
                tool_call_id,
                status="failed",
                ok=False,
                error=error,
            )
            metadata = mark_workflow_step(
                metadata,
                step,
                WORKFLOW_STEP_FAILED,
                output=error,
                error=error,
            )
            metadata = await self._publish_step_progress(
                metadata,
                step,
                f"Tool failed: {tool_name}",
            )
            raise

        if paused:
            metadata = update_workflow_tool_call(
                metadata,
                step.id,
                tool_call_id,
                status="waiting_for_user",
            )
            metadata = await self._publish_step_progress(
                metadata,
                step,
                f"Tool waiting for user: {tool_name}",
            )
            return result, metadata, paused

        ok = result.ok if result else None
        metadata = update_workflow_tool_call(
            metadata,
            step.id,
            tool_call_id,
            status="completed" if ok is not False else "failed",
            ok=ok,
            result_metadata=result.metadata if result else None,
        )
        if result and result.ok is False:
            metadata = mark_workflow_step(
                metadata,
                step,
                WORKFLOW_STEP_FAILED,
                output=result.content,
                error=result.content,
            )
            self._latest_metadata = metadata
        metadata = await self._publish_step_progress(
            metadata,
            step,
            f"Tool completed: {tool_name}",
        )
        return result, metadata, paused

    async def _run_model_tools_for_step(
        self,
        metadata: dict,
        step: WorkflowStep,
    ) -> tuple[dict, list[str], bool, bool, bool]:
        if self.run_step_model_tools is None or step.id not in {
            "step_4_cpu_env_setup",
            "step_7_gpu_execution",
        }:
            return metadata, [], False, False, False
        result = await self.run_step_model_tools(metadata, step)
        if len(result) == 4:
            step_metadata, outputs, paused, handled = result
            return step_metadata, outputs, paused, handled, False
        return result


async def cleanup_workflow_resources(
    metadata: dict,
    invoke_tool: ToolInvoker,
    write_metadata: MetadataWriter,
    publish: EventPublisher,
) -> tuple[dict, list[str]]:
    """Release workflow-owned resources that are recorded but not released."""

    outputs: list[str] = []
    pending = [
        ("cpu", "step_5_release_cpu"),
        ("gpu", "step_9_release_gpu"),
    ]
    resources = metadata.get("workflow_resources") or {}
    to_release = [
        (kind, step_id, resource)
        for kind, step_id in pending
        if isinstance(resources.get(kind), dict)
        for resource in [resources[kind]]
        if resource.get("server_id") and not resource.get("released")
    ]
    if not to_release:
        return metadata, outputs

    publish(
        {
            "type": "workflow_cleanup_started",
            "content": f"检测到 {len(to_release)} 个未释放实例，开始兜底释放。",
            "workflow": workflow_public_state(metadata),
        }
    )

    for kind, step_id, resource in to_release:
        server_id = str(resource.get("server_id"))
        step = _cleanup_step(step_id, kind)
        metadata = ensure_workflow_metadata_for_step(metadata, step)
        metadata = mark_workflow_step(metadata, step, WORKFLOW_STEP_RUNNING)
        tool_call_id = f"toolu_{uuid4().hex}"
        metadata = add_workflow_tool_call(
            metadata,
            step,
            tool_call_id=tool_call_id,
            tool_name="lab4ai_stop_instance",
            status="running",
        )
        metadata = add_workflow_step_progress(
            metadata,
            step,
            f"Cleanup releasing {kind.upper()} instance: {server_id}",
        )
        await write_metadata(metadata)
        publish(
            {
                "type": "workflow_step_progress",
                "workflow_step_id": step_id,
                "content": f"Cleanup releasing {kind.upper()} instance: {server_id}",
                "step": workflow_step_state(metadata, step_id),
                "workflow": workflow_public_state(metadata),
            }
        )
        result, metadata, paused = await invoke_tool(
            metadata,
            "lab4ai_stop_instance",
            {
                "server_id": server_id,
                "workflow_step_id": step_id,
                "tool_call_id": tool_call_id,
                "resource_kind": kind.upper(),
                "force_cleanup": True,
            },
        )
        if paused:
            metadata = update_workflow_tool_call(
                metadata,
                step_id,
                tool_call_id,
                status="waiting_for_user",
            )
            await write_metadata(metadata)
            continue
        if result:
            outputs.append(f"{result.name}: {result.content}")
        ok = result.ok if result else None
        metadata = update_workflow_tool_call(
            metadata,
            step_id,
            tool_call_id,
            status="completed" if ok is not False else "failed",
            ok=ok,
            result_metadata=result.metadata if result else None,
        )
        metadata = set_workflow_resource(metadata, kind, released=True)
        metadata = mark_workflow_step(
            metadata,
            step,
            WORKFLOW_STEP_COMPLETED,
            output=f"{kind.upper()} 实例已兜底释放：{server_id}",
        )
        await write_metadata(metadata)
        publish(
            {
                "type": "workflow_step_completed",
                "step": workflow_step_state(metadata, step_id),
                "workflow": workflow_public_state(metadata),
            }
        )

    publish(
        {
            "type": "workflow_cleanup_completed",
            "content": "资源兜底释放检查已完成。",
            "workflow": workflow_public_state(metadata),
        }
    )
    return metadata, outputs


def parse_workflow(raw: str) -> WorkflowDefinition:
    version = _normalize_workflow_version(_extract_top_scalar(raw, "version"))
    name = _extract_top_scalar(raw, "name")
    description = _extract_top_scalar(raw, "description")
    steps: list[WorkflowStep] = []

    matches = list(re.finditer(r"(?m)^\s*-\s+id:\s*([^\n]+)", raw))
    for index, match in enumerate(matches):
        block_start = match.start()
        block_end = matches[index + 1].start() if index + 1 < len(matches) else len(raw)
        block = raw[block_start:block_end]
        step_id = _clean_scalar(match.group(1))
        steps.append(
            WorkflowStep(
                id=step_id,
                name=_extract_block_scalar(block, "name") or step_id,
                depends_on=_parse_depends_on(_extract_block_scalar(block, "depends_on")),
                instruction=_extract_literal_block(block, "instruction"),
                expected_output=_extract_block_scalar(block, "expected_output"),
            )
        )

    return WorkflowDefinition(
        version=version,
        name=name,
        description=description,
        steps=steps,
    )


def ensure_workflow_metadata(
    metadata: dict,
    workflow: WorkflowDefinition,
    *,
    skill_name: str,
) -> dict:
    result = ensure_memory(metadata)
    existing_steps = result.get("workflow_steps")
    should_reset = (
        not isinstance(existing_steps, list)
        or result.get("selected_skill") != skill_name
        or result.get("workflow_name") != workflow.name
    )
    result["selected_skill"] = skill_name
    result["workflow_name"] = workflow.name
    result["workflow_version"] = workflow.version
    result.setdefault("workflow_current_step_id", None)
    result.setdefault("workflow_resources", {})
    result.setdefault("workflow_results", {})

    if should_reset:
        result["workflow_steps"] = [
            {
                "id": step.id,
                "name": step.name,
                "status": WORKFLOW_STEP_PENDING,
                "output": "",
                "depends_on": step.depends_on,
                "expected_output": step.expected_output,
                **_initial_step_runtime_fields(step.id),
            }
            for step in workflow.steps
        ]
        return result

    by_id = {
        str(item.get("id")): dict(item)
        for item in existing_steps
        if isinstance(item, dict) and item.get("id")
    }
    merged = []
    for step in workflow.steps:
        item = by_id.get(step.id) or {}
        item.update(
            {
                "id": step.id,
                "name": step.name,
                "depends_on": step.depends_on,
                "expected_output": step.expected_output,
            }
        )
        item.setdefault("status", WORKFLOW_STEP_PENDING)
        item.setdefault("output", "")
        _ensure_step_runtime_fields(item, step.id)
        merged.append(item)
    result["workflow_steps"] = merged
    return result


def workflow_public_state(metadata: dict) -> dict:
    return {
        "name": metadata.get("workflow_name"),
        "version": metadata.get("workflow_version"),
        "current_step_id": metadata.get("workflow_current_step_id"),
        "steps": metadata.get("workflow_steps") or [],
        "resources": metadata.get("workflow_resources") or {},
        "results": metadata.get("workflow_results") or {},
    }


def workflow_step_state(metadata: dict, step_id: str) -> dict:
    for item in metadata.get("workflow_steps") or []:
        if isinstance(item, dict) and item.get("id") == step_id:
            return item
    return {}


def ensure_workflow_metadata_for_step(metadata: dict, step: WorkflowStep) -> dict:
    result = ensure_memory(metadata)
    steps = []
    found = False
    for item in result.get("workflow_steps") or []:
        current = dict(item)
        if current.get("id") == step.id:
            current.setdefault("name", step.name)
            current.setdefault("status", WORKFLOW_STEP_PENDING)
            current.setdefault("output", "")
            current.setdefault("depends_on", step.depends_on)
            current.setdefault("expected_output", step.expected_output)
            _ensure_step_runtime_fields(current, step.id)
            found = True
        steps.append(current)
    if not found:
        steps.append(
            {
                "id": step.id,
                "name": step.name,
                "status": WORKFLOW_STEP_PENDING,
                "output": "",
                "depends_on": step.depends_on,
                "expected_output": step.expected_output,
                **_initial_step_runtime_fields(step.id),
            }
        )
    result["workflow_steps"] = steps
    return result


def dependencies_completed(metadata: dict, step: WorkflowStep) -> bool:
    for dependency in step.depends_on:
        if workflow_step_state(metadata, dependency).get("status") != WORKFLOW_STEP_COMPLETED:
            return False
    return True


def mark_workflow_step(
    metadata: dict,
    step: WorkflowStep,
    status: str,
    *,
    output: str | None = None,
    error: str | None = None,
) -> dict:
    result = ensure_memory(metadata)
    steps = []
    found = False
    for item in result.get("workflow_steps") or []:
        current = dict(item)
        if current.get("id") == step.id:
            previous_status = current.get("status")
            _ensure_step_runtime_fields(current, step.id)
            current["status"] = status
            if status == WORKFLOW_STEP_RUNNING and previous_status != WORKFLOW_STEP_RUNNING:
                current["attempts"] = int(current.get("attempts") or 0) + 1
            if output is not None:
                current["output"] = output
            if error is not None:
                current["error"] = error
            elif status in (WORKFLOW_STEP_COMPLETED, WORKFLOW_STEP_RUNNING):
                current["error"] = None
            found = True
        steps.append(current)
    if not found:
        item = {
            "id": step.id,
            "name": step.name,
            "status": status,
            "output": output or "",
            "depends_on": step.depends_on,
            "expected_output": step.expected_output,
            **_initial_step_runtime_fields(step.id),
        }
        if status == WORKFLOW_STEP_RUNNING:
            item["attempts"] = 1
        if error is not None:
            item["error"] = error
        steps.append(item)
    result["workflow_steps"] = steps
    return result


def add_workflow_step_progress(metadata: dict, step: WorkflowStep, content: str) -> dict:
    result = ensure_memory(metadata)
    steps = []
    found = False
    for item in result.get("workflow_steps") or []:
        current = dict(item)
        if current.get("id") == step.id:
            _ensure_step_runtime_fields(current, step.id)
            current["progress"] = [*current["progress"], content]
            found = True
        steps.append(current)
    if not found:
        current = {
            "id": step.id,
            "name": step.name,
            "status": WORKFLOW_STEP_PENDING,
            "output": "",
            "depends_on": step.depends_on,
            "expected_output": step.expected_output,
            **_initial_step_runtime_fields(step.id),
        }
        current["progress"] = [content]
        steps.append(current)
    result["workflow_steps"] = steps
    return result


def add_workflow_tool_call(
    metadata: dict,
    step: WorkflowStep,
    *,
    tool_call_id: str,
    tool_name: str,
    status: str,
) -> dict:
    result = ensure_memory(metadata)
    steps = []
    found = False
    for item in result.get("workflow_steps") or []:
        current = dict(item)
        if current.get("id") == step.id:
            _ensure_step_runtime_fields(current, step.id)
            current["tool_calls"] = [
                *current["tool_calls"],
                _new_tool_call(tool_call_id, tool_name, status),
            ]
            found = True
        steps.append(current)
    if not found:
        current = {
            "id": step.id,
            "name": step.name,
            "status": WORKFLOW_STEP_PENDING,
            "output": "",
            "depends_on": step.depends_on,
            "expected_output": step.expected_output,
            **_initial_step_runtime_fields(step.id),
        }
        current["tool_calls"] = [_new_tool_call(tool_call_id, tool_name, status)]
        steps.append(current)
    result["workflow_steps"] = steps
    return result


def add_workflow_step_artifact(metadata: dict, step: WorkflowStep, artifact: str) -> dict:
    result = ensure_memory(metadata)
    steps = []
    found = False
    for item in result.get("workflow_steps") or []:
        current = dict(item)
        if current.get("id") == step.id:
            _ensure_step_runtime_fields(current, step.id)
            if artifact not in current["artifacts"]:
                current["artifacts"] = [*current["artifacts"], artifact]
            found = True
        steps.append(current)
    if not found:
        current = {
            "id": step.id,
            "name": step.name,
            "status": WORKFLOW_STEP_PENDING,
            "output": "",
            "depends_on": step.depends_on,
            "expected_output": step.expected_output,
            **_initial_step_runtime_fields(step.id),
        }
        current["artifacts"] = [artifact]
        steps.append(current)
    result["workflow_steps"] = steps
    return result


def set_workflow_step_evidence(metadata: dict, step: WorkflowStep, **evidence: object) -> dict:
    result = ensure_memory(metadata)
    steps = []
    found = False
    for item in result.get("workflow_steps") or []:
        current = dict(item)
        if current.get("id") == step.id:
            _ensure_step_runtime_fields(current, step.id)
            current["evidence"] = {**current["evidence"], **evidence}
            found = True
        steps.append(current)
    if not found:
        current = {
            "id": step.id,
            "name": step.name,
            "status": WORKFLOW_STEP_PENDING,
            "output": "",
            "depends_on": step.depends_on,
            "expected_output": step.expected_output,
            **_initial_step_runtime_fields(step.id),
        }
        current["evidence"] = {**current["evidence"], **evidence}
        steps.append(current)
    result["workflow_steps"] = steps
    return result


def validate_workflow_step_contract(metadata: dict, step: WorkflowStep) -> str | None:
    contract = STEP_COMPLETION_CONTRACTS.get(step.id)
    if contract is None:
        return None

    step_state = workflow_step_state(metadata, step.id)
    tool_calls = [
        item
        for item in (step_state.get("tool_calls") or [])
        if isinstance(item, dict)
        and item.get("status") == "completed"
        and item.get("ok") is not False
    ]
    completed_tools = {_contract_tool_name(str(item.get("name") or "")) for item in tool_calls}
    completed_effects: set[str] = set()
    for item in tool_calls:
        completed_effects.update(TOOL_EFFECTS.get(str(item.get("name") or ""), set()))
        completed_effects.update(TOOL_EFFECTS.get(_contract_tool_name(str(item.get("name") or "")), set()))

    evidence = step_state.get("evidence") if isinstance(step_state.get("evidence"), dict) else {}
    missing_tools = [name for name in contract.required_tools if name not in completed_tools]
    missing_effects = [name for name in contract.required_effects if name not in completed_effects]
    missing_evidence = [name for name in contract.required_evidence if not evidence.get(name)]

    if not missing_tools and not missing_effects and not missing_evidence:
        return None

    details = []
    if missing_tools:
        details.append(f"missing required tool(s): {', '.join(missing_tools)}")
    if missing_effects:
        details.append(f"missing required effect(s): {', '.join(missing_effects)}")
    if missing_evidence:
        details.append(f"missing evidence: {', '.join(missing_evidence)}")
    return f"Workflow step contract failed for {step.id}: {'; '.join(details)}"


def update_workflow_tool_call(
    metadata: dict,
    step_id: str,
    tool_call_id: str,
    *,
    status: str,
    ok: bool | None = None,
    error: str | None = None,
    result_metadata: dict | None = None,
) -> dict:
    result = ensure_memory(metadata)
    steps = []
    for item in result.get("workflow_steps") or []:
        current = dict(item)
        if current.get("id") == step_id:
            _ensure_step_runtime_fields(current, step_id)
            calls = []
            for call in current["tool_calls"]:
                current_call = dict(call)
                if current_call.get("tool_call_id") == tool_call_id:
                    current_call["status"] = status
                    if status in ("completed", "failed"):
                        current_call["completed_at"] = _now_iso()
                    if ok is not None:
                        current_call["ok"] = ok
                    if error is not None:
                        current_call["error"] = error
                    if result_metadata is not None:
                        current_call["metadata"] = result_metadata
                calls.append(current_call)
            current["tool_calls"] = calls
        steps.append(current)
    result["workflow_steps"] = steps
    return result


def ensure_workflow_results(metadata: dict) -> dict:
    result = ensure_memory(metadata)
    if not isinstance(result.get("workflow_results"), dict):
        result["workflow_results"] = {}
    return result


def set_workflow_resource(
    metadata: dict,
    kind: str,
    *,
    server_id: str | None = None,
    released: bool | None = None,
    raw: dict | None = None,
) -> dict:
    result = ensure_memory(metadata)
    resources = dict(result.get("workflow_resources") or {})
    item = dict(resources.get(kind) or {})
    if server_id is not None:
        item["server_id"] = server_id
    if released is not None:
        item["released"] = released
    if raw is not None:
        item["raw"] = raw
    resources[kind] = item
    result["workflow_resources"] = resources
    return result


def workflow_resource_server_id(metadata: dict, kind: str) -> str | None:
    resource = (metadata.get("workflow_resources") or {}).get(kind) or {}
    server_id = resource.get("server_id")
    return str(server_id) if server_id else None


def _waiting_tool_call_id(metadata: dict, step_id: str, tool_name: str) -> str | None:
    step = workflow_step_state(metadata, step_id)
    for item in reversed(step.get("tool_calls") or []):
        if (
            isinstance(item, dict)
            and item.get("name") == tool_name
            and item.get("status") == "waiting_for_user"
            and item.get("tool_call_id")
        ):
            return str(item["tool_call_id"])
    return None


def _has_tool_call(metadata: dict, step_id: str, tool_call_id: str) -> bool:
    step = workflow_step_state(metadata, step_id)
    return any(
        isinstance(item, dict) and item.get("tool_call_id") == tool_call_id
        for item in (step.get("tool_calls") or [])
    )


def _contract_tool_name(name: str) -> str:
    return TOOL_CONTRACT_ALIASES.get(name, name)


def _step_contract_public(step_id: str) -> dict:
    contract = STEP_COMPLETION_CONTRACTS.get(step_id)
    if contract is None:
        return {}
    return {
        "required_tools": list(contract.required_tools),
        "required_effects": list(contract.required_effects),
        "required_evidence": list(contract.required_evidence),
    }


def _initial_step_runtime_fields(step_id: str) -> dict:
    return {
        "attempts": 0,
        "allowed_tools": list(STEP_ALLOWED_TOOLS.get(step_id, [])),
        "tool_calls": [],
        "artifacts": [],
        "progress": [],
        "error": None,
        "evidence": {},
        "completion_contract": _step_contract_public(step_id),
    }


def _ensure_step_runtime_fields(item: dict, step_id: str) -> None:
    item.setdefault("attempts", 0)
    if not isinstance(item.get("attempts"), int):
        try:
            item["attempts"] = int(item.get("attempts") or 0)
        except (TypeError, ValueError):
            item["attempts"] = 0
    item["allowed_tools"] = list(STEP_ALLOWED_TOOLS.get(step_id, item.get("allowed_tools") or []))
    for key in ("tool_calls", "artifacts", "progress"):
        if not isinstance(item.get(key), list):
            item[key] = []
    item.setdefault("error", None)
    if not isinstance(item.get("evidence"), dict):
        item["evidence"] = {}
    item["completion_contract"] = _step_contract_public(step_id)


def _new_tool_call(tool_call_id: str, tool_name: str, status: str) -> dict:
    audit = TOOL_AUDIT_METADATA.get(tool_name, {})
    return {
        "tool_call_id": tool_call_id,
        "name": tool_name,
        "status": status,
        "started_at": _now_iso(),
        "completed_at": None,
        "ok": None,
        "audit_category": audit.get("audit_category", "general"),
        "risk_level": audit.get("risk_level", "low"),
        "error": None,
    }


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _format_exception(exc: Exception) -> str:
    message = str(exc).strip()
    if message:
        return f"{type(exc).__name__}: {message}"
    return type(exc).__name__


def step_output_for(metadata: dict, step_id: str) -> str:
    return str(workflow_step_state(metadata, step_id).get("output") or "")


def repo_name_from_url(url: str) -> str:
    value = url.rstrip("/").split("/")[-1]
    if value.endswith(".git"):
        value = value[:-4]
    return re.sub(r"[^A-Za-z0-9_.-]+", "-", value).strip("-") or "project"


def _score_from_tool(result: ToolResult | None, *, default: int) -> int:
    if not result:
        return default
    value = result.metadata.get("score")
    try:
        return max(0, min(100, int(value)))
    except (TypeError, ValueError):
        return default


def _combined_score(repo_score: int, paper_score: int, *, has_paper: bool) -> int:
    if not has_paper:
        return repo_score
    return round(repo_score * 0.65 + paper_score * 0.35)


def _artifact_paths(result: ToolResult | None) -> list[str]:
    if not result:
        return []
    raw_paths = result.metadata.get("artifact_paths")
    if isinstance(raw_paths, list):
        return [str(item) for item in raw_paths if str(item).strip()]
    path = result.metadata.get("report_path")
    return [str(path)] if path else []


def _cpu_prepare_command(metadata: dict, repo_name: str) -> str:
    repo_url = str(metadata.get("github_url") or "").strip()
    if not repo_url:
        raise RuntimeError("缺少 github_url，无法准备远程项目环境")
    clone_url = _github_clone_url(repo_url)
    base_dir = f"/workspace/user-data/codelab/{repo_name}"
    return (
        "set -e; "
        f"mkdir -p {base_dir}/code {base_dir}/data {base_dir}/model; "
        f"cd {base_dir}/code; "
        "if [ ! -d .git ]; then "
        f"git clone --recursive {_shell_quote(clone_url)} .; "
        "else git fetch --all --prune; fi; "
        "ln -sfn ../data data; "
        "ln -sfn ../model model; "
        'PYTHON_BIN="$(command -v python3 || command -v python || true)"; '
        "if [ -f requirements.txt ]; then "
        'if [ -n "$PYTHON_BIN" ] && "$PYTHON_BIN" -m pip --version >/dev/null 2>&1; '
        'then "$PYTHON_BIN" -m pip install -r requirements.txt; '
        "elif command -v pip3 >/dev/null 2>&1; then pip3 install -r requirements.txt; "
        "elif command -v pip >/dev/null 2>&1; then pip install -r requirements.txt; "
        "else echo 'No python/pip executable found for requirements install'; exit 127; fi; "
        "elif [ -f environment.yml ]; then echo 'environment.yml detected; manual conda solve may be required'; "
        "else echo 'No requirements.txt or environment.yml found'; fi"
    )


def _cpu_prepare_verify_command(repo_name: str) -> str:
    base_dir = f"/workspace/user-data/codelab/{repo_name}"
    return (
        "set -e; "
        f"base_dir={_shell_quote(base_dir)}; "
        'code_dir="$base_dir/code"; '
        'test -d "$code_dir"; '
        'test -d "$base_dir/data"; '
        'test -d "$base_dir/model"; '
        'cd "$code_dir"; '
        "test -d .git; "
        "git rev-parse --is-inside-work-tree >/dev/null; "
        "if [ -f requirements.txt ]; then echo dependency_manifest=requirements.txt; "
        "elif [ -f environment.yml ]; then echo dependency_manifest=environment.yml; "
        "else echo dependency_manifest=none; fi; "
        "echo REMOTE_WORKSPACE_READY"
    )


def _gpu_smoke_command(repo_name: str) -> str:
    base_dir = f"/workspace/user-data/codelab/{repo_name}/code"
    return (
        "set -e; "
        f"cd {base_dir}; "
        'PYTHON_BIN="$(command -v python3 || command -v python || true)"; '
        'if [ -z "$PYTHON_BIN" ]; then echo "No python executable found"; exit 127; fi; '
        '"$PYTHON_BIN" - <<\'PY\'\n'
        "import os, sys\n"
        "print('python', sys.version.split()[0])\n"
        "try:\n"
        "    import torch\n"
        "    print('torch', torch.__version__)\n"
        "    print('cuda_available', torch.cuda.is_available())\n"
        "    if torch.cuda.is_available():\n"
        "        print('gpu_name', torch.cuda.get_device_name(0))\n"
        "except Exception as exc:\n"
        "    print('torch_probe_error', type(exc).__name__, exc)\n"
        "PY"
    )


def _gpu_workspace_verify_command(repo_name: str) -> str:
    base_dir = f"/workspace/user-data/codelab/{repo_name}/code"
    return (
        "set -e; "
        f"code_dir={_shell_quote(base_dir)}; "
        'test -d "$code_dir"; '
        'cd "$code_dir"; '
        "test -d .git; "
        "git rev-parse --is-inside-work-tree >/dev/null; "
        "echo GPU_WORKSPACE_READY"
    )


def _shell_quote(value: str) -> str:
    return "'" + value.replace("'", "'\"'\"'") + "'"


def _github_clone_url(repo_url: str) -> str:
    prefix = "https://gh-proxy.org/"
    if repo_url.startswith(prefix):
        return repo_url
    if repo_url.startswith("https://github.com/") or repo_url.startswith("http://github.com/"):
        return prefix + repo_url
    return repo_url


def _cleanup_step(step_id: str, kind: str) -> WorkflowStep:
    name = "释放 CPU 实例" if kind == "cpu" else "释放 GPU 实例"
    return WorkflowStep(id=step_id, name=name)


def _extract_top_scalar(raw: str, key: str) -> str:
    match = re.search(rf"(?m)^{re.escape(key)}:\s*(.+)$", raw)
    return _clean_scalar(match.group(1)) if match else ""


def _normalize_workflow_version(version: str) -> str:
    if version.startswith("claw-workflow/"):
        return version.replace("claw-workflow/", "lab4ai-workflow/", 1)
    return version


def _extract_block_scalar(block: str, key: str) -> str:
    match = re.search(rf"(?m)^\s*{re.escape(key)}\s*:\s*(.+)$", block)
    return _clean_scalar(match.group(1)) if match else ""


def _extract_literal_block(block: str, key: str) -> str:
    lines = block.splitlines()
    result: list[str] = []
    collecting = False
    base_indent = 0
    for line in lines:
        stripped = line.strip()
        if not collecting:
            if re.match(rf"^{re.escape(key)}\s*:\s*\|\s*$", stripped):
                collecting = True
                base_indent = len(line) - len(line.lstrip())
            continue
        indent = len(line) - len(line.lstrip())
        if stripped and indent <= base_indent and re.match(
            r"^(id|name|depends_on|instruction|expected_output)\s*:", stripped
        ):
            break
        trim = base_indent + 2
        result.append(line[trim:] if len(line) >= trim else line.strip())
    return "\n".join(result).strip()


def _parse_depends_on(value: str) -> list[str]:
    if not value:
        return []
    stripped = value.strip()
    if stripped.startswith("[") and stripped.endswith("]"):
        stripped = stripped[1:-1]
    return [_clean_scalar(item) for item in stripped.split(",") if item.strip()]


def _clean_scalar(value: str) -> str:
    result = value.strip()
    if len(result) >= 2 and result[0] == result[-1] and result[0] in {"'", '"'}:
        return result[1:-1]
    return result
