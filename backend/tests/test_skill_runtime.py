from __future__ import annotations

import urllib.request

import pytest

from app.core.config import get_settings
from app.services.skill_runtime import (
    SkillRuntime,
    SkillToolSpec,
    _arxiv_abs_url_from_pdf_url,
    _download_pdf,
    _github_clone_url,
    _run_repro_report,
    _git_usr_bin_from_git_executable,
    _strip_recurse_submodules_from_git_clone,
)


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


def test_git_usr_bin_is_derived_from_git_cmd_executable():
    git_executable = "D:/Program Files/Git/cmd/git.exe"

    assert str(_git_usr_bin_from_git_executable(git_executable)).replace("\\", "/") == (
        "D:/Program Files/Git/usr/bin"
    )


def test_repo_audit_git_clone_strips_recurse_submodules_for_local_static_audit():
    command = [
        "git",
        "clone",
        "--depth",
        "1",
        "--recurse-submodules",
        "https://github.com/showlab/PhotoDoodle",
        "target",
    ]

    assert _strip_recurse_submodules_from_git_clone(command) == [
        "git",
        "clone",
        "--depth",
        "1",
        "https://github.com/showlab/PhotoDoodle",
        "target",
    ]


def test_backend_pdf_downloader_writes_response_body(monkeypatch, tmp_path):
    class FakeResponse:
        headers = {}

        def __init__(self):
            self._chunks = [b"%PDF", b"-body", b""]

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self, size):
            return self._chunks.pop(0)

    def fake_urlopen(request, timeout):
        return FakeResponse()

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    target = tmp_path / "paper.pdf"

    assert _download_pdf("https://example.com/paper.pdf", target, timeout=10) is True
    assert target.read_bytes() == b"%PDF-body"


def test_backend_pdf_downloader_skips_large_content_length(monkeypatch, tmp_path):
    read_called = False

    class FakeResponse:
        headers = {"Content-Length": str(20 * 1024 * 1024)}

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self, size):
            nonlocal read_called
            read_called = True
            return b"too-large"

    def fake_urlopen(request, timeout):
        return FakeResponse()

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    target = tmp_path / "paper.pdf"

    assert _download_pdf("https://example.com/paper.pdf", target, timeout=10) is False
    assert read_called is False
    assert not target.exists()


def test_arxiv_abs_url_from_pdf_url():
    assert _arxiv_abs_url_from_pdf_url("https://arxiv.org/pdf/2502.14397") == (
        "https://arxiv.org/abs/2502.14397"
    )
    assert _arxiv_abs_url_from_pdf_url("https://arxiv.org/pdf/2502.14397.pdf") == (
        "https://arxiv.org/abs/2502.14397"
    )


@pytest.mark.asyncio
async def test_repro_report_falls_back_to_workspace_docx_when_skill_returns_legacy_path(
    monkeypatch,
    tmp_path,
):
    runtime = SkillRuntime(tmp_path / "skills", tmp_path / "workspaces")
    spec = SkillToolSpec(
        name="generate_repro_report",
        description="report",
        entry_point="report_generator.py:generate_report",
        input_schema={},
        skill_name="lab4ai-repro-report",
        base_dir=tmp_path,
    )

    def fake_load_entrypoint(base_dir, entry_point):
        def generate_report(**kwargs):
            return (
                "报告生成成功："
                "`/root/.openclaw/workspace/PhotoDoodle/PhotoDoodle_Final_Repro_Report.docx`"
            )

        return generate_report

    monkeypatch.setattr("app.services.skill_runtime._load_entrypoint", fake_load_entrypoint)

    result = await _run_repro_report(
        runtime,
        spec,
        {
            "conversation_id": 123,
            "repo_name": "PhotoDoodle",
            "project_profile": "PhotoDoodle project",
            "implementation_steps": {"code_fetch": "cloned"},
            "results_comparison": [],
            "optimization_suggestions": "none",
        },
    )

    report_path = tmp_path / "workspaces" / "123" / "PhotoDoodle" / "PhotoDoodle_Final_Repro_Report.docx"
    assert result.ok is True
    assert result.metadata["report_path"] == str(report_path)
    assert "markdown_report_path" not in result.metadata
    assert result.metadata["generation_source"] == "backend_report_fallback"
    assert report_path.exists()
    assert not report_path.with_suffix(".md").exists()
    assert result.metadata["artifact_paths"] == [str(report_path)]


@pytest.mark.asyncio
async def test_repro_report_publishes_existing_skill_docx_to_project_workspace(
    monkeypatch,
    tmp_path,
):
    runtime = SkillRuntime(tmp_path / "skills", tmp_path / "workspaces")
    spec = SkillToolSpec(
        name="generate_repro_report",
        description="report",
        entry_point="report_generator.py:generate_report",
        input_schema={},
        skill_name="lab4ai-repro-report",
        base_dir=tmp_path,
    )
    legacy_dir = tmp_path / "legacy-output"
    legacy_dir.mkdir()
    legacy_report = legacy_dir / "PhotoDoodle_Final_Repro_Report.docx"
    legacy_report.write_bytes(b"legacy docx bytes")

    def fake_load_entrypoint(base_dir, entry_point):
        def generate_report(**kwargs):
            return f"报告生成成功：`{legacy_report}`"

        return generate_report

    monkeypatch.setattr("app.services.skill_runtime._load_entrypoint", fake_load_entrypoint)

    result = await _run_repro_report(
        runtime,
        spec,
        {
            "conversation_id": 123,
            "repo_name": "PhotoDoodle",
            "project_profile": "PhotoDoodle project",
            "implementation_steps": {"code_fetch": "cloned"},
            "results_comparison": [],
            "optimization_suggestions": "none",
        },
    )

    report_path = tmp_path / "workspaces" / "123" / "PhotoDoodle" / "PhotoDoodle_Final_Repro_Report.docx"
    assert result.ok is True
    assert result.metadata["report_path"] == str(report_path)
    assert "markdown_report_path" not in result.metadata
    assert result.metadata["artifact_paths"] == [str(report_path)]
    assert "legacy_report_path" not in result.metadata
    assert report_path.read_bytes() == b"legacy docx bytes"
    assert not report_path.with_suffix(".md").exists()
