from __future__ import annotations

import json

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


def test_skill_summary_exposes_safe_model_fields(tmp_path):
    skill_dir = tmp_path / "skills" / "demo"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        """---
name: demo
description: Demo skill
when_to_use: Use for demo requests
triggers:
  - demo
allowed_tools:
  - analyze_repo
---

# Demo
The full body should stay out of model selection summaries.
""",
        encoding="utf-8",
    )

    skill = SkillLoader(tmp_path / "skills").load_all()["demo"]

    assert skill.summary_for_selection() == {
        "name": "demo",
        "description": "Demo skill",
        "when_to_use": "Use for demo requests",
        "triggers": ["demo"],
        "allowed_tools": ["analyze_repo"],
        "has_workflow": False,
    }


def test_skill_summary_marks_workflow_without_exposing_context(tmp_path):
    skill_dir = tmp_path / "skills" / "lab4ai-auto-reproduct"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text("---\nname: lab4ai-auto-reproduct\n---\nbody", encoding="utf-8")
    (skill_dir / "project_reproduce.yaml").write_text("tasks:\n  - id: step_1\n", encoding="utf-8")

    skill = SkillLoader(tmp_path / "skills").load_all()["lab4ai-auto-reproduct"]
    summary = skill.summary_for_selection()

    assert summary["has_workflow"] is True
    assert "body" not in summary
    assert "workflow_context" not in summary
    assert "step_1" not in json.dumps(summary)
    json.dumps(summary)


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


def test_auto_research_loads_pipeline_context_with_policy_and_stage_docs(tmp_path):
    skill_dir = tmp_path / "skills" / "lab4ai-auto-research"
    scripts_dir = skill_dir / "scripts"
    scripts_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "---\nname: lab4ai-auto-research\n---\nbody",
        encoding="utf-8",
    )
    (skill_dir / "pipeline.yml").write_text(
        """
name: autoresearch_pipeline
version: "2.0"
global_policies:
  policies_skill: scripts/skill_02policies.md
stages:
  - id: instance_provision
    title: Provision
    skill_file: scripts/skill_01lab_instance.md
    confirm_required: true
    gates:
      - lab_choice_confirmed
""",
        encoding="utf-8",
    )
    (scripts_dir / "skill_02policies.md").write_text("Gate protocol", encoding="utf-8")
    (scripts_dir / "skill_01lab_instance.md").write_text("Step 1 Lab", encoding="utf-8")

    skills = SkillLoader(tmp_path / "skills").load_all()
    selected = select_skill(skills, {"task_type": "experiments"})

    assert selected is not None
    assert selected.name == "lab4ai-auto-research"
    assert selected.summary_for_selection()["has_workflow"] is True
    assert "WORKFLOW_KIND: autoresearch_pipeline" in selected.workflow_context
    assert "pipeline.yml" in selected.workflow_context
    assert "Gate protocol" in selected.workflow_context
    assert "Step 1 Lab" in selected.workflow_context


def test_zero_code_reproduction_loads_main_and_plugin_contexts(tmp_path):
    skills_dir = tmp_path / "skills"
    main_dir = skills_dir / "zero-code-reproduction"
    csai_dir = skills_dir / "zero-code-repro-csai"
    bio_dir = skills_dir / "zero-code-repro-biodefense"
    for skill_dir, name, body in (
        (main_dir, "zero-code-reproduction", "Zero-Code main flow with 12 steps"),
        (csai_dir, "zero-code-repro-csai", "CS/AI PyTorch scaffold plugin"),
        (bio_dir, "zero-code-repro-biodefense", "Biodefense hybrid plugin"),
    ):
        (skill_dir / "templates").mkdir(parents=True)
        (skill_dir / "scripts").mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text(f"---\nname: {name}\n---\n{body}", encoding="utf-8")
        (skill_dir / "templates" / "prompt.txt").write_text(f"{name} prompt", encoding="utf-8")
        (skill_dir / "scripts" / "helper.py").write_text("# helper", encoding="utf-8")

    skills = SkillLoader(skills_dir).load_all()
    selected = select_skill(
        skills,
        {
            "task_type": "reproduce",
            "paper_url": "https://arxiv.org/pdf/2502.14397",
            "github_url": None,
        },
    )

    assert selected is not None
    assert selected.name == "zero-code-reproduction"
    assert selected.summary_for_selection()["has_workflow"] is True
    assert "WORKFLOW_KIND: zero_code_reproduction_pipeline" in selected.workflow_context
    assert "Zero-Code main flow with 12 steps" in selected.workflow_context
    assert "CS/AI PyTorch scaffold plugin" in selected.workflow_context
    assert "Biodefense hybrid plugin" in selected.workflow_context
    assert "templates/prompt.txt" in selected.workflow_context
    assert "scripts/helper.py" in selected.workflow_context
