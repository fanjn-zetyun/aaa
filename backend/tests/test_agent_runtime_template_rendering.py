from app.agent_runtime.workflows.rendering import render_runtime_templates


def test_render_runtime_templates_resolves_known_values():
    payload = {
        "github_url": "{{parameters.github_url}}",
        "server_id": "{{workflow_resources.cpu.server_id}}",
    }
    context = {
        "parameters": {"github_url": "https://github.com/example/repo"},
        "workflow_resources": {"cpu": {"server_id": "cpu-1"}},
    }

    rendered = render_runtime_templates(payload, context)

    assert rendered.ok is True
    assert rendered.value == {
        "github_url": "https://github.com/example/repo",
        "server_id": "cpu-1",
    }


def test_render_runtime_templates_rejects_unresolved_value():
    rendered = render_runtime_templates(
        {"server_id": "{{workflow_resources.gpu.server_id}}"},
        {"workflow_resources": {}},
    )

    assert rendered.ok is False
    assert rendered.error_code == "unresolved_template_variable"
    assert rendered.unresolved_variables == ["workflow_resources.gpu.server_id"]
