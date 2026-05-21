from __future__ import annotations

from app.core.config import get_settings
from app.services.skill_runtime import SkillRuntime, _github_clone_url


def test_skill_runtime_loads_declared_skill_tools():
    settings = get_settings()
    runtime = SkillRuntime(settings.skills_dir_path, settings.workspace_root_path)

    specs = {spec.name: spec for spec in runtime.list_specs()}

    assert "repo_audit" in specs
    assert "paper_analyze" in specs
    assert "generate_repro_report" in specs
    assert specs["repo_audit"].entry_point == "scripts/main.py:audit_repo"
    assert "analyze_repo" in specs["repo_audit"].aliases
    assert "analyze_paper" in specs["paper_analyze"].aliases
    assert "repro_report" in specs["generate_repro_report"].aliases


def test_skill_runtime_health_reports_paper_backend_adapter():
    settings = get_settings()
    runtime = SkillRuntime(settings.skills_dir_path, settings.workspace_root_path)

    health = {item["name"]: item for item in runtime.health()}

    assert health["paper_analyze"]["loaded"] is True
    assert health["paper_analyze"]["adapter"] is True
    assert health["paper_analyze"]["entrypoint_note"] == "backend_adapter_wraps_existing_script_functions"


def test_github_clone_url_uses_default_proxy_prefix():
    clone_url = _github_clone_url("https://github.com/jsnzwu/motion-guided-flow", {})

    assert clone_url == "https://gh-proxy.org/https://github.com/jsnzwu/motion-guided-flow"


def test_github_clone_url_does_not_double_prefix():
    url = "https://gh-proxy.org/https://github.com/jsnzwu/motion-guided-flow"

    assert _github_clone_url(url, {}) == url
