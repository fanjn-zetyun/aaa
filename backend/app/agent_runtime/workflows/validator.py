from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class WorkflowValidationReport:
    ok: bool
    step_count: int
    step_ids: list[str]
    warnings: list[str] = field(default_factory=list)
    fatal_errors: list[str] = field(default_factory=list)


def validate_workflow_contract(
    active_workflow: dict[str, Any] | None,
) -> WorkflowValidationReport:
    if not isinstance(active_workflow, dict):
        return WorkflowValidationReport(
            ok=False,
            step_count=0,
            step_ids=[],
            fatal_errors=["missing active workflow contract"],
        )
    steps = active_workflow.get("steps")
    if not isinstance(steps, dict) or not steps:
        return WorkflowValidationReport(
            ok=False,
            step_count=0,
            step_ids=[],
            fatal_errors=["workflow contract contains no steps"],
        )

    warnings: list[str] = []
    fatal_errors: list[str] = []
    if active_workflow.get("compatibility_mode"):
        warnings.append("legacy_compatibility_mode")

    for step_id, step in steps.items():
        if not isinstance(step, dict):
            fatal_errors.append(f"step `{step_id}` is not an object")
            continue
        if not step.get("instruction"):
            fatal_errors.append(f"step `{step_id}` missing instruction")
        if "allowed_tools" not in step:
            fatal_errors.append(f"step `{step_id}` missing allowed_tools")

    return WorkflowValidationReport(
        ok=not fatal_errors,
        step_count=len(steps),
        step_ids=[str(item) for item in steps.keys()],
        warnings=warnings,
        fatal_errors=fatal_errors,
    )
