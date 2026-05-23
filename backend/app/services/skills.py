"""Skill loading for the backend agent loop.

Skills are prompt/workflow definitions. They do not execute actions directly;
the agent loop injects their context and backend tools perform side effects.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass(slots=True)
class SkillDefinition:
    name: str
    description: str = ""
    triggers: list[str] = field(default_factory=list)
    when_to_use: str = ""
    allowed_tools: list[str] = field(default_factory=list)
    body: str = ""
    base_dir: Path = Path()
    workflow_context: str = ""

    @property
    def prompt_context(self) -> str:
        parts = [
            f"# Skill: {self.name}",
            f"Description: {self.description or '(none)'}",
        ]
        if self.when_to_use:
            parts.append(f"When to use: {self.when_to_use}")
        if self.allowed_tools:
            parts.append("Allowed tools: " + ", ".join(self.allowed_tools))
        if self.triggers:
            parts.append("Triggers: " + ", ".join(self.triggers[:20]))
        if self.body:
            parts.extend(["", "## Skill Body", self.body.strip()])
        if self.workflow_context:
            parts.extend(["", "## Workflow Context", self.workflow_context.strip()])
        return "\n".join(parts).strip()

    def summary_for_selection(self) -> dict[str, object]:
        return {
            "name": self.name,
            "description": self.description,
            "when_to_use": self.when_to_use,
            "triggers": list(self.triggers),
            "allowed_tools": list(self.allowed_tools),
            "has_workflow": bool(self.workflow_context),
        }


class SkillLoader:
    def __init__(self, skills_dir: Path) -> None:
        self.skills_dir = skills_dir

    def load_all(self) -> dict[str, SkillDefinition]:
        if not self.skills_dir.exists():
            return {}

        skills: dict[str, SkillDefinition] = {}
        for skill_file in sorted(self.skills_dir.glob("*/SKILL.md")):
            skill = self.load_file(skill_file)
            skills[skill.name] = skill
        return skills

    def load_file(self, skill_file: Path) -> SkillDefinition:
        raw = skill_file.read_text(encoding="utf-8")
        metadata, body = _split_frontmatter(raw)
        base_dir = skill_file.parent
        name = str(metadata.get("name") or base_dir.name).strip().strip("\"'")
        workflow_context = ""

        if name == "lab4ai-auto-reproduct":
            workflow_file = base_dir / "project_reproduce.yaml"
            if workflow_file.exists():
                workflow_context = workflow_file.read_text(encoding="utf-8")

        return SkillDefinition(
            name=name,
            description=str(metadata.get("description") or ""),
            triggers=_as_list(metadata.get("triggers")),
            when_to_use=str(metadata.get("when_to_use") or ""),
            allowed_tools=_as_list(metadata.get("allowed_tools")),
            body=body,
            base_dir=base_dir,
            workflow_context=workflow_context,
        )


def fallback_skill_name(metadata: dict) -> str:
    if metadata.get("task_type") == "reproduce" or metadata.get("github_url"):
        return "lab4ai-auto-reproduct"
    return "general-chat"


def select_skill(skills: dict[str, SkillDefinition], metadata: dict) -> SkillDefinition | None:
    name = fallback_skill_name(metadata)
    return skills.get(name)


def _split_frontmatter(raw: str) -> tuple[dict[str, object], str]:
    lines = raw.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}, raw

    end_index = None
    for index, line in enumerate(lines[1:], start=1):
        if line.strip() == "---":
            end_index = index
            break
    if end_index is None:
        return {}, raw

    metadata = _parse_simple_yaml(lines[1:end_index])
    body = "\n".join(lines[end_index + 1 :]).strip()
    return metadata, body


def _parse_simple_yaml(lines: list[str]) -> dict[str, object]:
    data: dict[str, object] = {}
    current_list_key: str | None = None

    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue

        if stripped.startswith("- ") and current_list_key:
            value = _clean_scalar(stripped[2:])
            casted = data.setdefault(current_list_key, [])
            if isinstance(casted, list):
                casted.append(value)
            continue

        current_list_key = None
        if ":" not in stripped:
            continue
        key, raw_value = stripped.split(":", 1)
        key = key.strip()
        raw_value = raw_value.strip()
        if raw_value:
            data[key] = _clean_scalar(raw_value)
        else:
            data[key] = []
            current_list_key = key

    return data


def _clean_scalar(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value


def _as_list(value: object) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item) for item in value if str(item).strip()]
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    return []
