from __future__ import annotations

from dataclasses import dataclass, field
import re


@dataclass(slots=True)
class InstructionItem:
    id: str
    text: str
    required: bool = True
    status: str = "pending"
    evidence: list[str] = field(default_factory=list)
    missing_reason: str = ""


@dataclass(slots=True)
class StepInstructionPlan:
    step_id: str
    step_name: str
    instruction: str
    expected_output: str
    allowed_tools: list[str]
    recommended_tools: list[str]
    items: list[InstructionItem]

    def to_metadata(self) -> dict:
        return {
            "step_id": self.step_id,
            "step_name": self.step_name,
            "instruction": self.instruction,
            "expected_output": self.expected_output,
            "allowed_tools": list(self.allowed_tools),
            "recommended_tools": list(self.recommended_tools),
            "items": [
                {
                    "id": item.id,
                    "text": item.text,
                    "required": item.required,
                    "status": item.status,
                    "evidence": list(item.evidence),
                    "missing_reason": item.missing_reason,
                }
                for item in self.items
            ],
        }


def compile_step_instruction(
    *,
    step_id: str,
    step_name: str,
    instruction: str,
    expected_output: str,
    allowed_tools: list[str],
) -> StepInstructionPlan:
    text = f"{instruction}\n{expected_output}"
    items: list[InstructionItem] = []

    if _contains_any(text, "import", "precheck", "preflight", "预检"):
        items.append(
            InstructionItem(
                id="import_precheck",
                text="Run import/CUDA environment prechecks and record the result.",
            )
        )
    if _contains_any(text, "entrypoint", "entry point", "入口", "scripts", "examples", "demo", "README"):
        items.append(
            InstructionItem(
                id="entrypoint_detection",
                text="Inspect README, scripts, examples, demo, or CLI entrypoints and choose a smoke test path.",
            )
        )
    if _contains_any(text, "env_patches", "environment patch", "环境补丁", "补丁记录"):
        items.append(
            InstructionItem(
                id="env_patch_record",
                text="Record environment fixes, dependency changes, or CUDA/C++ patches in env_patches.md.",
            )
        )
    if _contains_any(text, "report", "报告", "Word", "docx"):
        items.append(
            InstructionItem(
                id="report_artifact",
                text="Generate and verify the report artifact path.",
            )
        )
    if _contains_any(text, "release", "stop", "释放", "关闭"):
        items.append(
            InstructionItem(
                id="resource_release",
                text="Release workflow-owned cloud resources and record the server_id.",
            )
        )
    if expected_output.strip() and step_id == "step_7_gpu_execution":
        items.append(
            InstructionItem(
                id="expected_output_validation",
                text=expected_output.strip(),
            )
        )
    if not items and instruction.strip():
        items.append(
            InstructionItem(
                id="general_instruction_1",
                text=_first_sentence(instruction),
            )
        )

    recommended_tools = [
        tool
        for tool in ("file_system_read", "file_system_list", "ssh_execute", "repro_report")
        if tool in allowed_tools
    ]
    return StepInstructionPlan(
        step_id=step_id,
        step_name=step_name,
        instruction=instruction,
        expected_output=expected_output,
        allowed_tools=list(allowed_tools),
        recommended_tools=recommended_tools,
        items=items,
    )


def _contains_any(text: str, *needles: str) -> bool:
    lowered = text.lower()
    return any(needle.lower() in lowered for needle in needles)


def _first_sentence(text: str) -> str:
    normalized = " ".join(text.strip().split())
    parts = re.split(r"[。.!?]", normalized, maxsplit=1)
    return parts[0].strip() or normalized[:120]
