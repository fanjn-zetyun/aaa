from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.services.tools import ToolResult


@dataclass(slots=True)
class InstructionEvaluation:
    plan: dict[str, Any]
    missing_required: list[str]


def evaluate_instruction_plan(
    plan: dict[str, Any],
    results: list[ToolResult],
) -> InstructionEvaluation:
    updated = dict(plan)
    items = [dict(item) for item in plan.get("items") or [] if isinstance(item, dict)]
    evidence_text = _joined_result_text(results)
    evidence = _merged_evidence(results)
    missing_required: list[str] = []

    for item in items:
        item_id = str(item.get("id") or "")
        satisfied = _item_satisfied(item_id, evidence_text=evidence_text, evidence=evidence, results=results)
        if satisfied:
            item["status"] = "completed"
            item["missing_reason"] = ""
            item["evidence"] = _item_evidence(item_id, evidence_text=evidence_text, evidence=evidence)
        elif item.get("required", True):
            item["status"] = "pending"
            item["missing_reason"] = f"missing instruction item: {item_id}"
            missing_required.append(item_id)

    updated["items"] = items
    return InstructionEvaluation(plan=updated, missing_required=missing_required)


def _item_satisfied(
    item_id: str,
    *,
    evidence_text: str,
    evidence: dict[str, Any],
    results: list[ToolResult],
) -> bool:
    if item_id == "import_precheck":
        return _has_any(evidence_text, "cuda=true", "torch=", "import ok", "import_precheck")
    if item_id == "entrypoint_detection":
        return _has_any(
            evidence_text,
            "readme",
            "scripts",
            "examples",
            "demo",
            "entrypoint",
            "train.py",
            "inference.py",
        )
    if item_id == "env_patch_record":
        return _has_any(evidence_text, "env_patches.md", "environment patch", "dependency change")
    if item_id == "report_artifact":
        return any(_has_metadata(result, "report_path") for result in results) or _has_any(
            evidence_text, ".docx", "final_repro_report"
        )
    if item_id == "resource_release":
        return any(_has_metadata(result, "server_id") and result.ok for result in results) and _has_any(
            evidence_text, "release", "stop", "released", "stopped"
        )
    if item_id == "expected_output_validation":
        return bool(evidence.get("inline_cuda_smoke")) or _has_any(
            evidence_text,
            "loss=",
            "vram",
            "gpu smoke",
            "cuda smoke",
            "output",
            "metric",
        )
    if item_id.startswith("general_instruction"):
        return any(result.ok for result in results)
    return any(result.ok for result in results if item_id and item_id in _result_text(result))


def _item_evidence(item_id: str, *, evidence_text: str, evidence: dict[str, Any]) -> list[str]:
    if item_id in evidence and evidence[item_id]:
        return [str(evidence[item_id])]
    return [evidence_text[:240]] if evidence_text else []


def _joined_result_text(results: list[ToolResult]) -> str:
    return "\n".join(_result_text(result) for result in results).lower()


def _result_text(result: ToolResult) -> str:
    metadata = result.metadata or {}
    return "\n".join(
        [
            str(result.name),
            str(result.content or ""),
            str(metadata.get("stdout") or ""),
            str(metadata.get("stderr") or ""),
            str(metadata.get("path") or ""),
            str(metadata.get("report_path") or ""),
            str(metadata.get("server_id") or ""),
            str(metadata.get("evidence") or ""),
        ]
    )


def _merged_evidence(results: list[ToolResult]) -> dict[str, Any]:
    merged: dict[str, Any] = {}
    for result in results:
        raw = (result.metadata or {}).get("evidence")
        if isinstance(raw, dict):
            merged.update(raw)
    return merged


def _has_any(text: str, *needles: str) -> bool:
    return any(needle.lower() in text for needle in needles)


def _has_metadata(result: ToolResult, key: str) -> bool:
    return bool((result.metadata or {}).get(key))
