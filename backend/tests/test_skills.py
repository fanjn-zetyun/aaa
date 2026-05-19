from __future__ import annotations

from app.services.skills import SkillLoader, select_skill


def test_loads_skill_frontmatter_and_body(tmp_path):
    skill_dir = tmp_path / "skills" / "demo"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        """---
name: demo
description: Demo skill
triggers:
  - reproduce
allowed_tools:
  - analyze_repo
---

# Demo
Use this workflow.
""",
        encoding="utf-8",
    )

    skills = SkillLoader(tmp_path / "skills").load_all()

    assert "demo" in skills
    assert skills["demo"].description == "Demo skill"
    assert skills["demo"].triggers == ["reproduce"]
    assert skills["demo"].allowed_tools == ["analyze_repo"]
    assert "Use this workflow." in skills["demo"].prompt_context


def test_auto_reproduct_loads_workflow_context(tmp_path):
    skill_dir = tmp_path / "skills" / "lab4ai-auto-reproduct"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text("---\nname: lab4ai-auto-reproduct\n---\nbody", encoding="utf-8")
    (skill_dir / "project_reproduce.yaml").write_text("tasks:\n  - id: step_1\n", encoding="utf-8")

    skills = SkillLoader(tmp_path / "skills").load_all()
    selected = select_skill(skills, {"task_type": "reproduce"})

    assert selected is not None
    assert selected.name == "lab4ai-auto-reproduct"
    assert "step_1" in selected.workflow_context
    assert "Workflow Context" in selected.prompt_context
