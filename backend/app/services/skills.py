"""Skill loading for the backend agent loop.

Skills are prompt/workflow definitions. They do not execute actions directly;
the agent loop injects their context and backend tools perform side effects.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import re


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
        elif name == "lab4ai-auto-research":
            workflow_context = _load_autoresearch_workflow_context(base_dir)
        elif name == "zero-code-reproduction":
            workflow_context = _load_zero_code_workflow_context(base_dir)

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
    if metadata.get("task_type") == "experiments":
        return "lab4ai-auto-research"
    if (
        metadata.get("task_type") == "reproduce"
        and metadata.get("paper_url")
        and not metadata.get("github_url")
    ):
        return "zero-code-reproduction"
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


def _load_autoresearch_workflow_context(base_dir: Path) -> str:
    pipeline_file = base_dir / "pipeline.yml"
    if not pipeline_file.exists():
        return ""

    pipeline_raw = pipeline_file.read_text(encoding="utf-8")
    parts = [
        "WORKFLOW_KIND: autoresearch_pipeline",
        "",
        "## pipeline.yml",
        "```yaml",
        pipeline_raw.strip(),
        "```",
    ]
    for relative_path in _autoresearch_context_files(pipeline_raw):
        file_path = base_dir / relative_path
        if not file_path.exists() or not file_path.is_file():
            continue
        parts.extend(
            [
                "",
                f"## {relative_path.as_posix()}",
                file_path.read_text(encoding="utf-8").strip(),
            ]
        )
    return "\n".join(parts).strip()


def _autoresearch_context_files(pipeline_raw: str) -> list[Path]:
    paths: list[Path] = []
    for pattern in (
        r"(?m)^\s*policies_skill\s*:\s*['\"]?([^'\"\n#]+)",
        r"(?m)^\s*skill_file\s*:\s*['\"]?([^'\"\n#]+)",
    ):
        for match in re.finditer(pattern, pipeline_raw):
            raw_path = match.group(1).strip()
            if not raw_path:
                continue
            path = Path(raw_path)
            if path.is_absolute() or ".." in path.parts:
                continue
            if path not in paths:
                paths.append(path)
    return paths


def _load_zero_code_workflow_context(base_dir: Path) -> str:
    skills_dir = base_dir.parent
    skill_dirs = [
        base_dir,
        skills_dir / "zero-code-repro-csai",
        skills_dir / "zero-code-repro-biodefense",
    ]
    parts = [
        "WORKFLOW_KIND: zero_code_reproduction_pipeline",
        "",
        "## zero-code workflow contract",
        (
            "Paper-only reproduction must start at Step 0 by creating a remote CPU instance. "
            "GitHub repository reproduction remains handled by lab4ai-auto-reproduct."
        ),
    ]
    for skill_dir in skill_dirs:
        if not skill_dir.exists():
            continue
        for file_path in _zero_code_context_files(skill_dir):
            relative = file_path.relative_to(skill_dir)
            parts.extend(
                [
                    "",
                    f"## {skill_dir.name}/{relative.as_posix()}",
                    file_path.read_text(encoding="utf-8").strip(),
                ]
            )
    return "\n".join(parts).strip()


def _zero_code_context_files(skill_dir: Path) -> list[Path]:
    candidates = [skill_dir / "SKILL.md"]
    for folder_name in ("templates", "scripts"):
        folder = skill_dir / folder_name
        if folder.exists():
            candidates.extend(path for path in sorted(folder.rglob("*")) if path.is_file())
    references = skill_dir / "references"
    if references.exists():
        candidates.extend(path for path in sorted(references.rglob("*")) if path.is_file())
    return [path for path in candidates if path.exists() and path.is_file()]
