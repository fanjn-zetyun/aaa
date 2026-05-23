from __future__ import annotations


LEGACY_TOOL_ALIASES = {
    "claw_shell_run": "ssh_execute",
    "ssh_essentials_execute": "ssh_execute",
    "instance_create": "lab4ai_create_instance",
    "instance_stop": "lab4ai_stop_instance",
    "repo_audit": "analyze_repo",
    "paper_analyze": "analyze_paper",
    "generate_repro_report": "repro_report",
}


def normalize_tool_name(name: str) -> str:
    value = str(name or "").strip()
    return LEGACY_TOOL_ALIASES.get(value, value)


def normalize_allowed_tools(names: list[str]) -> list[str]:
    normalized: list[str] = []
    seen: set[str] = set()
    for name in names:
        value = normalize_tool_name(name)
        if value and value not in seen:
            normalized.append(value)
            seen.add(value)
    return normalized
