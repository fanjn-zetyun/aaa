from __future__ import annotations

from app.services.tools import ToolRegistry


def test_tool_registry_builds_confirmation_for_resource_creation():
    registry = ToolRegistry()

    confirmation = registry.confirmation_for("lab4ai_create_instance", {})

    assert confirmation is not None
    assert confirmation.tool_name == "lab4ai_create_instance"
    assert confirmation.step == "tool_confirm:lab4ai_create_instance"
    assert "Lab4AI" in confirmation.question


def test_tool_registry_only_confirms_risky_ssh_commands():
    registry = ToolRegistry()

    safe_confirmation = registry.confirmation_for(
        "ssh_execute",
        {"command": "git clone https://github.com/example/demo"},
    )
    risky_confirmation = registry.confirmation_for("ssh_execute", {"command": "sudo rm -rf /tmp/x"})

    assert safe_confirmation is None
    assert risky_confirmation is not None
    assert risky_confirmation.tool_name == "ssh_execute"


def test_tool_registry_prompt_context_filters_by_allowed_tools():
    registry = ToolRegistry()

    context = registry.prompt_context(["analyze_repo"])

    assert "analyze_repo" in context
    assert "lab4ai_create_instance" not in context
