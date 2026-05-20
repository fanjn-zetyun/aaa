"""Workflow runtime for skill-backed reproduction tasks."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Awaitable, Callable

from app.services.conversation_memory import ensure_memory, remember_artifact, remember_fact
from app.services.tools import ToolResult

WORKFLOW_STEP_PENDING = "pending"
WORKFLOW_STEP_RUNNING = "running"
WORKFLOW_STEP_WAITING = "waiting_for_user"
WORKFLOW_STEP_COMPLETED = "completed"
WORKFLOW_STEP_FAILED = "failed"
WORKFLOW_STEP_SKIPPED = "skipped"


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
    ) -> None:
        self.workflow = workflow
        self.skill_name = skill_name
        self.invoke_tool = invoke_tool
        self.write_metadata = write_metadata
        self.publish = publish

    async def run(self, metadata: dict) -> WorkflowRunResult:
        metadata = ensure_workflow_metadata(
            metadata,
            self.workflow,
            skill_name=self.skill_name,
        )
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
                continue
            if not dependencies_completed(metadata, step):
                metadata = mark_workflow_step(
                    metadata,
                    step,
                    WORKFLOW_STEP_FAILED,
                    output="依赖步骤尚未完成，workflow 已中止。",
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

            try:
                metadata, outputs, paused = await self._execute_step(metadata, step)
            except Exception as exc:
                metadata = mark_workflow_step(
                    metadata,
                    step,
                    WORKFLOW_STEP_FAILED,
                    output=f"{type(exc).__name__}: {exc}",
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

        if step.id == "step_1_audit":
            result, metadata, paused = await self.invoke_tool(
                metadata,
                "analyze_repo",
                {"github_url": metadata.get("github_url")},
            )
            if paused:
                return metadata, outputs, True
            if result:
                outputs.append(f"{result.name}: {result.content}")
            metadata = ensure_workflow_results(metadata)
            metadata["workflow_results"].update(
                {
                    "repo_name": repo_name,
                    "score": 75,
                    "audit_report_path": f"/root/lab4ai/workspace/{repo_name}/{repo_name}_Audit_Report.md",
                    "baseline_metrics": "MVP 阶段记录论文链接，真实指标待 paper_analysis 接入后提取。",
                }
            )
            metadata = remember_fact(metadata, f"目标仓库：{metadata.get('github_url')}")
            if metadata.get("paper_url"):
                metadata = remember_fact(metadata, f"论文链接：{metadata.get('paper_url')}")
            return (
                mark_workflow_step(
                    metadata,
                    step,
                    WORKFLOW_STEP_COMPLETED,
                    output="score=75；已完成项目与论文审计的 MVP 记录。",
                ),
                outputs,
                False,
            )

        if step.id == "step_2_condition_check":
            score = int(ensure_workflow_results(metadata)["workflow_results"].get("score") or 0)
            status = WORKFLOW_STEP_COMPLETED if score >= 60 else WORKFLOW_STEP_FAILED
            output = "验证通过，继续执行。" if score >= 60 else f"score={score}，低于 60，触发熔断。"
            return mark_workflow_step(metadata, step, status, output=output), outputs, False

        if step.id == "step_3_deploy_cpu":
            result, metadata, paused = await self.invoke_tool(
                metadata,
                "lab4ai_create_instance",
                {
                    "resource_kind": "CPU",
                    "cpu_cores": 2,
                    "workflow_step_id": step.id,
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
            command = f"prepare CPU workspace and dependencies for {repo_name}"
            result, metadata, paused = await self.invoke_tool(
                metadata,
                "ssh_execute",
                {"command": command, "workflow_step_id": step.id},
            )
            if paused:
                return metadata, outputs, True
            if result:
                outputs.append(f"{result.name}: {result.content}")
            return (
                mark_workflow_step(
                    metadata,
                    step,
                    WORKFLOW_STEP_COMPLETED,
                    output="CPU 环境准备已完成（MVP 模拟）。",
                ),
                outputs,
                False,
            )

        if step.id == "step_5_release_cpu":
            server_id = workflow_resource_server_id(metadata, "cpu")
            result, metadata, paused = await self.invoke_tool(
                metadata,
                "lab4ai_stop_instance",
                {"server_id": server_id, "workflow_step_id": step.id},
            )
            if paused:
                return metadata, outputs, True
            if result:
                outputs.append(f"{result.name}: {result.content}")
            metadata = set_workflow_resource(metadata, "cpu", released=True)
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
            result, metadata, paused = await self.invoke_tool(
                metadata,
                "lab4ai_create_instance",
                {
                    "resource_kind": "GPU",
                    "gpu_count": 1,
                    "workflow_step_id": step.id,
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
            command = f"run GPU smoke test for {repo_name}"
            result, metadata, paused = await self.invoke_tool(
                metadata,
                "ssh_execute",
                {"command": command, "workflow_step_id": step.id},
            )
            if paused:
                return metadata, outputs, True
            if result:
                outputs.append(f"{result.name}: {result.content}")
            metadata = ensure_workflow_results(metadata)
            metadata["workflow_results"]["smoke_test_metrics"] = {
                "status": "passed",
                "vram": "MVP simulated",
            }
            return (
                mark_workflow_step(
                    metadata,
                    step,
                    WORKFLOW_STEP_COMPLETED,
                    output="GPU Smoke Test 已跑通（MVP 模拟）。",
                ),
                outputs,
                False,
            )

        if step.id == "step_8_generate_report":
            result, metadata, paused = await self.invoke_tool(
                metadata,
                "repro_report",
                {"repo_name": repo_name, "workflow_step_id": step.id},
            )
            if paused:
                return metadata, outputs, True
            report_path = f"/root/lab4ai/workspace/{repo_name}/{repo_name}_Repro_Report.docx"
            if result:
                outputs.append(f"{result.name}: {result.content}")
                report_path = str(result.metadata.get("report_path") or report_path)
            metadata = ensure_workflow_results(metadata)
            metadata["workflow_results"]["word_report_path"] = report_path
            metadata = remember_artifact(metadata, f"复现报告：{report_path}")
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
            result, metadata, paused = await self.invoke_tool(
                metadata,
                "lab4ai_stop_instance",
                {"server_id": server_id, "workflow_step_id": step.id},
            )
            if paused:
                return metadata, outputs, True
            if result:
                outputs.append(f"{result.name}: {result.content}")
            metadata = set_workflow_resource(metadata, "gpu", released=True)
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
        result, metadata, paused = await invoke_tool(
            metadata,
            "lab4ai_stop_instance",
            {
                "server_id": server_id,
                "workflow_step_id": step_id,
                "resource_kind": kind.upper(),
                "force_cleanup": True,
            },
        )
        if paused:
            continue
        if result:
            outputs.append(f"{result.name}: {result.content}")
        metadata = set_workflow_resource(metadata, kind, released=True)
        step = _cleanup_step(step_id, kind)
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
    version = _extract_top_scalar(raw, "version")
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
) -> dict:
    result = ensure_memory(metadata)
    steps = []
    found = False
    for item in result.get("workflow_steps") or []:
        current = dict(item)
        if current.get("id") == step.id:
            current["status"] = status
            if output is not None:
                current["output"] = output
            found = True
        steps.append(current)
    if not found:
        steps.append(
            {
                "id": step.id,
                "name": step.name,
                "status": status,
                "output": output or "",
                "depends_on": step.depends_on,
                "expected_output": step.expected_output,
            }
        )
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


def step_output_for(metadata: dict, step_id: str) -> str:
    return str(workflow_step_state(metadata, step_id).get("output") or "")


def repo_name_from_url(url: str) -> str:
    value = url.rstrip("/").split("/")[-1]
    if value.endswith(".git"):
        value = value[:-4]
    return re.sub(r"[^A-Za-z0-9_.-]+", "-", value).strip("-") or "project"


def _cleanup_step(step_id: str, kind: str) -> WorkflowStep:
    name = "释放 CPU 实例" if kind == "cpu" else "释放 GPU 实例"
    return WorkflowStep(id=step_id, name=name)


def _extract_top_scalar(raw: str, key: str) -> str:
    match = re.search(rf"(?m)^{re.escape(key)}:\s*(.+)$", raw)
    return _clean_scalar(match.group(1)) if match else ""


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
