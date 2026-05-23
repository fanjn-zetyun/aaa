from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class PostconditionResult:
    ok: bool
    missing_evidence: list[str] = field(default_factory=list)


STEP_REQUIRED_EVIDENCE = {
    "step_3_deploy_cpu": ["cpu_instance_created"],
    "step_4_cpu_env_setup": ["remote_workspace_ready", "repo_cloned"],
    "step_5_release_cpu": ["cpu_instance_released"],
    "step_6_deploy_gpu": ["gpu_instance_created"],
    "step_7_gpu_execution": ["project_reproduction_log", "gpu_execution_attempted"],
    "step_8_generate_report": ["report_path"],
    "step_9_release_gpu": ["gpu_instance_released"],
}


def evaluate_step_postconditions(
    step_id: str,
    *,
    workflow_state: dict[str, Any],
    step_state: dict[str, Any],
) -> PostconditionResult:
    evidence = dict(step_state.get("evidence") or {})
    results = dict(workflow_state.get("results") or {})
    resources = dict(workflow_state.get("resources") or {})

    if step_id == "step_3_deploy_cpu" and _resource_server_id(resources, "cpu"):
        evidence["cpu_instance_created"] = True
    if step_id == "step_6_deploy_gpu" and _resource_server_id(resources, "gpu"):
        evidence["gpu_instance_created"] = True
    if step_id == "step_8_generate_report" and results.get("report_path"):
        evidence["report_path"] = True

    missing = [
        name
        for name in STEP_REQUIRED_EVIDENCE.get(step_id, [])
        if not evidence.get(name)
    ]
    return PostconditionResult(ok=not missing, missing_evidence=missing)


def _resource_server_id(resources: dict[str, Any], key: str) -> str:
    resource = resources.get(key)
    if not isinstance(resource, dict):
        return ""
    return str(resource.get("server_id") or "").strip()
