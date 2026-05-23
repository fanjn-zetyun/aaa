from app.agent_runtime.workflows.tool_mapping import normalize_allowed_tools, normalize_tool_name


def test_normalize_legacy_claw_tools_to_runtime_tools():
    assert normalize_tool_name("claw_shell_run") == "ssh_execute"
    assert normalize_tool_name("ssh_essentials_execute") == "ssh_execute"
    assert normalize_tool_name("file_system_read") == "file_system_read"
    assert normalize_tool_name("file_system_write") == "file_system_write"


def test_normalize_allowed_tools_deduplicates_preserving_order():
    assert normalize_allowed_tools(
        ["claw_shell_run", "ssh_execute", "file_system_read", "ask_user"]
    ) == ["ssh_execute", "file_system_read", "ask_user"]
