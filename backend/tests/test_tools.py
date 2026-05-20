from __future__ import annotations

import pytest

from app.models import CloudInstance, CloudInstanceStatus, CloudInstanceType
from app.services.lab4ai.client import Lab4AIInstance, Lab4AIStopResult
from app.services.tools import ToolRegistry
from app.services.tools import ToolExecutionContext


pytestmark = pytest.mark.asyncio


async def test_tool_registry_builds_confirmation_for_resource_creation():
    registry = ToolRegistry()

    confirmation = registry.confirmation_for("lab4ai_create_instance", {})

    assert confirmation is not None
    assert confirmation.tool_name == "lab4ai_create_instance"
    assert confirmation.step == "tool_confirm:lab4ai_create_instance"
    assert "Lab4AI" in confirmation.question


async def test_tool_registry_only_confirms_risky_ssh_commands():
    registry = ToolRegistry()

    safe_confirmation = registry.confirmation_for(
        "ssh_execute",
        {"command": "git clone https://github.com/example/demo"},
    )
    risky_confirmation = registry.confirmation_for("ssh_execute", {"command": "sudo rm -rf /tmp/x"})

    assert safe_confirmation is None
    assert risky_confirmation is not None
    assert risky_confirmation.tool_name == "ssh_execute"


async def test_tool_registry_skips_confirmation_for_forced_cleanup():
    registry = ToolRegistry()

    confirmation = registry.confirmation_for(
        "lab4ai_stop_instance",
        {"workflow_step_id": "step_5_release_cpu", "force_cleanup": True},
    )

    assert confirmation is None


async def test_tool_registry_prompt_context_filters_by_allowed_tools():
    registry = ToolRegistry()

    context = registry.prompt_context(["analyze_repo"])

    assert "analyze_repo" in context
    assert "lab4ai_create_instance" not in context


async def test_lab4ai_create_instance_requires_credentials(test_user, db_session):
    registry = ToolRegistry()
    context = ToolExecutionContext(
        user_id=test_user.id,
        conversation_id=123,
        session=db_session,
    )

    with pytest.raises(RuntimeError, match="Lab4AI 凭证未配置"):
        await registry.invoke(
            "lab4ai_create_instance",
            {"resource_kind": "CPU", "workflow_step_id": "step_3_deploy_cpu"},
            context=context,
        )


async def test_lab4ai_create_instance_records_cloud_instance(
    monkeypatch,
    test_user,
    db_session,
):
    async def fake_credentials(session):
        return type("Creds", (), {"phone": "13800138000", "password": "secret"})()

    async def fake_create_instance(*args, **kwargs):
        return Lab4AIInstance(
            server_id="server-1",
            instance_id="inst-1",
            rule_name="GPU",
            gpu_count=1,
            ssh_host="127.0.0.1",
            ssh_port="2222",
            ssh_user="root",
            ssh_pass="pass",
            raw_payload={"serverId": "server-1"},
        )

    monkeypatch.setattr("app.services.tools.load_lab4ai_credentials", fake_credentials)
    monkeypatch.setattr("app.services.tools.create_instance", fake_create_instance)
    registry = ToolRegistry()
    context = ToolExecutionContext(
        user_id=test_user.id,
        conversation_id=456,
        session=db_session,
    )

    result = await registry.invoke(
        "lab4ai_create_instance",
        {"resource_kind": "GPU", "gpu_count": 1, "workflow_step_id": "step_6_deploy_gpu"},
        context=context,
    )

    cloud = await db_session.get(CloudInstance, result.metadata["cloud_instance_id"])
    assert cloud is not None
    assert cloud.user_id == test_user.id
    assert cloud.conversation_id == 456
    assert cloud.server_id == "server-1"
    assert cloud.status == CloudInstanceStatus.RUNNING
    assert "simulated" not in result.metadata


async def test_lab4ai_stop_instance_updates_cloud_instance(monkeypatch, test_user, db_session):
    cloud = CloudInstance(
        user_id=test_user.id,
        conversation_id=789,
        server_id="server-stop",
        instance_type=CloudInstanceType.CPU,
        status=CloudInstanceStatus.RUNNING,
    )
    db_session.add(cloud)
    await db_session.commit()
    await db_session.refresh(cloud)

    async def fake_credentials(session):
        return type("Creds", (), {"phone": "13800138000", "password": "secret"})()

    async def fake_stop_instance_details(phone, password, server_id):
        return Lab4AIStopResult(
            server_id=server_id,
            start_time="2026-05-20 10:00:00",
            stop_time="2026-05-20 11:00:00",
            raw_payload={"serverId": server_id},
        )

    monkeypatch.setattr("app.services.tools.load_lab4ai_credentials", fake_credentials)
    monkeypatch.setattr("app.services.tools.stop_instance_details", fake_stop_instance_details)
    registry = ToolRegistry()
    context = ToolExecutionContext(
        user_id=test_user.id,
        conversation_id=789,
        session=db_session,
    )

    result = await registry.invoke(
        "lab4ai_stop_instance",
        {"server_id": "server-stop", "force_cleanup": True},
        context=context,
    )

    await db_session.refresh(cloud)
    assert "simulated" not in result.metadata
    assert cloud.status == CloudInstanceStatus.STOPPED
    assert cloud.stopped_at is not None
