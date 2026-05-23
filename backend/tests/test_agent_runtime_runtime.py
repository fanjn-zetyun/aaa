import pytest

from app.agent_runtime.events import ListEventSink
from app.agent_runtime.llm import ModelResponse
from app.agent_runtime.recovery import RecoveryPolicy
from app.agent_runtime.runtime import AgentRuntime
from app.agent_runtime.skills import SkillInvokeTool
from app.agent_runtime.tool_executor import ToolExecutor
from app.models import Conversation, ConversationStatus, ConversationTaskType
from app.services.llm_client import LLMToolUse
from app.services.skills import SkillDefinition
from app.services.tools import ToolDefinition, ToolResult


class FakeLLM:
    def __init__(self):
        self.calls = 0

    async def complete(self, request):
        self.calls += 1
        if self.calls == 1:
            return ModelResponse(
                text="需要询问用户。",
                tool_calls=[LLMToolUse(id="toolu_1", name="ask_user", input={"question": "继续吗？"})],
                stop_reason="tool_use",
                usage={},
                raw={},
            )
        return ModelResponse(
            text="完成。",
            tool_calls=[],
            stop_reason="end_turn",
            usage={},
            raw={},
        )


class CapturingLLM:
    def __init__(self):
        self.system_prompts: list[str] = []

    async def complete(self, request):
        self.system_prompts.append(request.system)
        return ModelResponse(
            text="完成。",
            tool_calls=[],
            stop_reason="end_turn",
            usage={},
            raw={},
        )


class CapturingToolsLLM:
    def __init__(self):
        self.tools: list[dict] = []

    async def complete(self, request):
        self.tools = list(request.tools)
        return ModelResponse(
            text="完成。",
            tool_calls=[],
            stop_reason="end_turn",
            usage={},
            raw={},
        )


class WorkflowLLM:
    def __init__(self):
        self.calls = 0

    async def complete(self, request):
        self.calls += 1
        if self.calls == 1:
            return ModelResponse(
                text="加载 workflow skill。",
                tool_calls=[
                    LLMToolUse(
                        id="toolu_skill",
                        name="skill.invoke",
                        input={"skill": "workflow-skill"},
                    )
                ],
                stop_reason="tool_use",
                usage={},
                raw={},
            )
        if self.calls == 2:
            assert "当前 workflow step：step_3_deploy_cpu" in request.system
            return ModelResponse(
                text="创建 CPU 实例。",
                tool_calls=[
                    LLMToolUse(
                        id="toolu_cpu",
                        name="lab4ai_create_instance",
                        input={"resource_kind": "CPU"},
                    )
                ],
                stop_reason="tool_use",
                usage={},
                raw={},
            )
        return ModelResponse(
            text="完成。",
            tool_calls=[],
            stop_reason="end_turn",
            usage={},
            raw={},
        )


class WorkflowRegistry:
    def __init__(self):
        self.definitions = {
            "lab4ai_create_instance": ToolDefinition(
                name="lab4ai_create_instance",
                description="create",
                input_schema={
                    "type": "object",
                    "properties": {"resource_kind": {"type": "string"}},
                },
            ),
            "ask_user": ToolDefinition(
                name="ask_user",
                description="ask",
                input_schema={"type": "object", "properties": {"question": {"type": "string"}}},
                read_only=True,
            ),
        }

    def definition(self, name):
        return self.definitions[name]

    def list_definitions(self, allowed_tools=None):
        allowed = set(allowed_tools or [])
        return [item for item in self.definitions.values() if not allowed or item.name in allowed]

    def list_anthropic_tools(self, allowed_tools=None):
        return [item.anthropic_schema() for item in self.list_definitions(allowed_tools)]

    def confirmation_for(self, name, tool_input):
        return None

    async def invoke(self, name, tool_input, context=None):
        return ToolResult(
            name,
            f"{name} ok",
            ok=True,
            metadata={"evidence": {"cpu_instance_created": True}},
        )


class ExhaustedRecoveryLLM:
    def __init__(self):
        self.calls = 0

    async def complete(self, request):
        self.calls += 1
        if self.calls == 1:
            return ModelResponse(
                text="加载 workflow skill。",
                tool_calls=[
                    LLMToolUse(
                        id="toolu_skill",
                        name="skill.invoke",
                        input={"skill": "workflow-skill"},
                    )
                ],
                stop_reason="tool_use",
                usage={},
                raw={},
            )
        return ModelResponse(
            text="执行 GPU smoke。",
            tool_calls=[
                LLMToolUse(
                    id="toolu_gpu",
                    name="ssh_execute",
                    input={"command": "python - <<'PY'\nprint('cuda smoke')\nPY"},
                )
            ],
            stop_reason="tool_use",
            usage={},
            raw={},
        )


class RecoveryRegistry:
    def __init__(self):
        self.definitions = {
            "ssh_execute": ToolDefinition(
                name="ssh_execute",
                description="ssh",
                input_schema={
                    "type": "object",
                    "required": ["command"],
                    "properties": {"command": {"type": "string"}},
                },
            ),
            "ask_user": ToolDefinition(
                name="ask_user",
                description="ask",
                input_schema={"type": "object", "properties": {"question": {"type": "string"}}},
                read_only=True,
            ),
        }

    def definition(self, name):
        return self.definitions[name]

    def list_definitions(self, allowed_tools=None):
        allowed = set(allowed_tools or [])
        return [item for item in self.definitions.values() if not allowed or item.name in allowed]

    def list_anthropic_tools(self, allowed_tools=None):
        return [item.anthropic_schema() for item in self.list_definitions(allowed_tools)]

    def confirmation_for(self, name, tool_input):
        return None

    async def invoke(self, name, tool_input, context=None):
        return ToolResult(
            name,
            "inline CUDA smoke completed",
            ok=True,
            metadata={"evidence": {"inline_cuda_smoke": True}},
        )


@pytest.mark.asyncio
async def test_agent_runtime_runs_tool_loop_until_final_answer(db_session, test_user):
    conversation = Conversation(
        user_id=test_user.id,
        task_type=ConversationTaskType.GENERAL,
        title="runtime",
        status=ConversationStatus.RUNNING,
        metadata_={},
    )
    db_session.add(conversation)
    await db_session.commit()
    await db_session.refresh(conversation)

    events = ListEventSink()
    runtime = AgentRuntime.for_test(session=db_session, llm=FakeLLM(), event_sink=events)

    result = await runtime.run_conversation(conversation.id, model="claude-test")

    assert result.status == "completed"
    assert result.final_text == "完成。"
    assert [event["type"] for event in events.events if event["type"].startswith("runtime_")] == [
        "runtime_started",
        "runtime_completed",
    ]


@pytest.mark.asyncio
async def test_agent_runtime_uses_context_builder_system_prompt(db_session, test_user):
    conversation = Conversation(
        user_id=test_user.id,
        task_type=ConversationTaskType.GENERAL,
        title="runtime prompt",
        status=ConversationStatus.RUNNING,
        metadata_={},
    )
    db_session.add(conversation)
    await db_session.commit()
    await db_session.refresh(conversation)

    llm = CapturingLLM()
    runtime = AgentRuntime.for_test(session=db_session, llm=llm)

    await runtime.run_conversation(conversation.id, model="claude-test")

    assert "不要要求用户提供 Lab4AI 密码" in llm.system_prompts[0]


@pytest.mark.asyncio
async def test_agent_runtime_advertises_runtime_tool_schemas(db_session, test_user):
    conversation = Conversation(
        user_id=test_user.id,
        task_type=ConversationTaskType.GENERAL,
        title="runtime tools",
        status=ConversationStatus.RUNNING,
        metadata_={},
    )
    db_session.add(conversation)
    await db_session.commit()
    await db_session.refresh(conversation)

    llm = CapturingToolsLLM()
    runtime = AgentRuntime(
        session=db_session,
        llm=llm,
        tool_executor=ToolExecutor(
            registry=WorkflowRegistry(),
            event_sink=ListEventSink(),
            runtime_tools={"skill.invoke": SkillInvokeTool({})},
        ),
        event_sink=ListEventSink(),
    )

    await runtime.run_conversation(conversation.id, model="claude-test")

    assert "skill.invoke" in {tool["name"] for tool in llm.tools}


@pytest.mark.asyncio
async def test_agent_runtime_validates_workflow_contract_after_tool_results(db_session, test_user):
    conversation = Conversation(
        user_id=test_user.id,
        task_type=ConversationTaskType.REPRODUCE,
        title="runtime workflow",
        status=ConversationStatus.RUNNING,
        metadata_={},
    )
    db_session.add(conversation)
    await db_session.commit()
    await db_session.refresh(conversation)
    workflow = """
version: agent-workflow/v1
name: Demo
description: Demo workflow
tasks:
  - id: step_3_deploy_cpu
    name: CPU
    instruction: |
      创建 CPU 实例。
    expected_output: |
      CPU 实例已创建。
"""
    skill = SkillDefinition(
        name="workflow-skill",
        allowed_tools=[],
        workflow_context=workflow,
    )
    events = ListEventSink()
    runtime = AgentRuntime(
        session=db_session,
        llm=WorkflowLLM(),
        tool_executor=ToolExecutor(
            registry=WorkflowRegistry(),
            event_sink=events,
            runtime_tools={"skill.invoke": SkillInvokeTool({"workflow-skill": skill})},
        ),
        event_sink=events,
    )

    result = await runtime.run_conversation(conversation.id, model="claude-test")

    step = result.metadata["runtime"]["active_workflow"]["steps"]["step_3_deploy_cpu"]
    assert step["status"] == "completed"
    assert step["tool_calls"][0]["name"] == "lab4ai_create_instance"


@pytest.mark.asyncio
async def test_agent_runtime_escalates_exhausted_workflow_recovery(db_session, test_user):
    conversation = Conversation(
        user_id=test_user.id,
        task_type=ConversationTaskType.REPRODUCE,
        title="runtime recovery",
        status=ConversationStatus.RUNNING,
        metadata_={},
    )
    db_session.add(conversation)
    await db_session.commit()
    await db_session.refresh(conversation)
    workflow = """
version: agent-workflow/v1
name: Demo
description: Demo workflow
tasks:
  - id: step_7_gpu_execution
    name: GPU
    instruction: |
      执行项目复现。
    expected_output: |
      项目复现日志。
"""
    skill = SkillDefinition(
        name="workflow-skill",
        allowed_tools=[],
        workflow_context=workflow,
    )
    events = ListEventSink()
    runtime = AgentRuntime(
        session=db_session,
        llm=ExhaustedRecoveryLLM(),
        tool_executor=ToolExecutor(
            registry=RecoveryRegistry(),
            event_sink=events,
            runtime_tools={"skill.invoke": SkillInvokeTool({"workflow-skill": skill})},
        ),
        event_sink=events,
    )
    runtime.recovery_policy = RecoveryPolicy(max_attempts=0)

    result = await runtime.run_conversation(conversation.id, model="claude-test")

    runtime_state = result.metadata["runtime"]
    assert result.status == "waiting_for_user"
    assert runtime_state["status"] == "waiting_for_user"
    assert runtime_state["pending_tool_call"]["tool_name"] == "workflow_recovery"
    assert "自动恢复次数已耗尽" in runtime_state["pending_user_input"]["question"]
