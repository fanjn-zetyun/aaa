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


class PrematureWorkflowLLM:
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
            text="我认为已经完成。",
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


class TwoStepWorkflowLLM:
    def __init__(self):
        self.calls = 0

    async def complete(self, request):
        self.calls += 1
        if self.calls == 1:
            return ModelResponse(
                text="Load workflow skill.",
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
            return ModelResponse(
                text="Create CPU.",
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
        if self.calls == 3:
            assert "当前 workflow step：step_4_cpu_env_setup" in request.system
            return ModelResponse(
                text="Prepare CPU.",
                tool_calls=[
                    LLMToolUse(
                        id="toolu_ssh",
                        name="ssh_execute",
                        input={"command": "pwd"},
                    ),
                    LLMToolUse(
                        id="toolu_prep",
                        name="remote_project_prep",
                        input={"command": "prep"},
                    )
                ],
                stop_reason="tool_use",
                usage={},
                raw={},
            )
        return ModelResponse(
            text="Workflow complete.",
            tool_calls=[],
            stop_reason="end_turn",
            usage={},
            raw={},
        )


class FinalReportWorkflowLLM:
    def __init__(self):
        self.calls = 0

    async def complete(self, request):
        self.calls += 1
        if self.calls == 1:
            return ModelResponse(
                text="Load reproduction workflow skill.",
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
            assert "当前 workflow step：step_8_generate_report" in request.system
            return ModelResponse(
                text="Generate the final reproduction report.",
                tool_calls=[
                    LLMToolUse(
                        id="toolu_report",
                        name="repro_report",
                        input={"repo_name": "motion-guided-flow"},
                    )
                ],
                stop_reason="tool_use",
                usage={},
                raw={},
            )
        if self.calls == 3:
            assert "当前 workflow step：step_9_release_gpu" in request.system
            return ModelResponse(
                text="Release GPU instance.",
                tool_calls=[
                    LLMToolUse(
                        id="toolu_release_gpu",
                        name="lab4ai_stop_instance",
                        input={"resource_kind": "GPU", "server_id": "gpu-test-1"},
                    )
                ],
                stop_reason="tool_use",
                usage={},
                raw={},
            )
        return ModelResponse(
            text="Model natural-language fallback should not be needed.",
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
            "ssh_execute": ToolDefinition(
                name="ssh_execute",
                description="ssh",
                input_schema={"type": "object", "properties": {"command": {"type": "string"}}},
            ),
            "ask_user": ToolDefinition(
                name="ask_user",
                description="ask",
                input_schema={"type": "object", "properties": {"question": {"type": "string"}}},
                read_only=True,
            ),
            "remote_project_prep": ToolDefinition(
                name="remote_project_prep",
                description="prep",
                input_schema={"type": "object", "properties": {"command": {"type": "string"}}},
            ),
            "repro_report": ToolDefinition(
                name="repro_report",
                description="report",
                input_schema={"type": "object", "properties": {"repo_name": {"type": "string"}}},
            ),
            "lab4ai_stop_instance": ToolDefinition(
                name="lab4ai_stop_instance",
                description="stop",
                input_schema={
                    "type": "object",
                    "properties": {
                        "resource_kind": {"type": "string"},
                        "server_id": {"type": "string"},
                    },
                },
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
        evidence = {"cpu_instance_created": True}
        if name == "ssh_execute":
            evidence = {
                "clone_completed": True,
                "remote_workspace_verified": True,
                "git_repo_verified": True,
            }
        if name == "remote_project_prep":
            evidence = {
                "clone_completed": True,
                "remote_workspace_verified": True,
                "git_repo_verified": True,
                "dependency_install_attempted": True,
                "project_prep_completed": True,
                "remote_workspace_ready": True,
                "repo_cloned": True,
            }
        if name == "repro_report":
            return ToolResult(
                name,
                "Word report generated: /workspace/user-data/codelab/motion-guided-flow/report.docx",
                ok=True,
                metadata={
                    "local_report_path": "runtime/workspaces/7/motion-guided-flow/report.docx",
                    "remote_report_path": (
                        "/workspace/user-data/codelab/motion-guided-flow/report.docx"
                    ),
                    "report_path": "/workspace/user-data/codelab/motion-guided-flow/report.docx",
                    "artifact_paths": [
                        "/workspace/user-data/codelab/motion-guided-flow/report.docx",
                        "runtime/workspaces/7/motion-guided-flow/report.docx",
                    ],
                },
            )
        if name == "lab4ai_stop_instance":
            return ToolResult(
                name,
                "GPU instance gpu-test-1 released.",
                ok=True,
                metadata={"server_id": "gpu-test-1", "resource_kind": "GPU"},
            )
        return ToolResult(
            name,
            f"{name} ok",
            ok=True,
            metadata={"evidence": evidence},
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
async def test_general_chat_can_complete_without_invoking_skill(db_session, test_user):
    conversation = Conversation(
        user_id=test_user.id,
        task_type=ConversationTaskType.GENERAL,
        title="general chat",
        status=ConversationStatus.RUNNING,
        metadata_={},
    )
    db_session.add(conversation)
    await db_session.commit()
    await db_session.refresh(conversation)

    skill = SkillDefinition(
        name="lab4ai-auto-reproduct",
        triggers=["reproduce"],
        workflow_context="version: agent-workflow/v1",
    )
    runtime = AgentRuntime(
        session=db_session,
        llm=CapturingToolsLLM(),
        tool_executor=ToolExecutor(
            registry=WorkflowRegistry(),
            event_sink=ListEventSink(),
            runtime_tools={"skill.invoke": SkillInvokeTool({"lab4ai-auto-reproduct": skill})},
        ),
        event_sink=ListEventSink(),
    )

    result = await runtime.run_conversation(conversation.id, model="claude-test")

    assert result.status == "completed"
    assert result.metadata["runtime"]["active_skill"] is None
    assert result.metadata["runtime"]["active_workflow"] is None


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
    step_events = [event for event in events.events if event["type"] == "workflow_step_updated"]
    assert step_events
    assert step_events[-1]["step"]["id"] == "step_3_deploy_cpu"
    assert "instruction_plan" in step_events[-1]["step"]
    skill_events = [
        event
        for event in events.events
        if event["type"] == "tool_completed" and event.get("tool_name") == "skill.invoke"
    ]
    assert skill_events


@pytest.mark.asyncio
async def test_agent_runtime_advances_across_workflow_steps_until_contract_complete(
    db_session, test_user
):
    conversation = Conversation(
        user_id=test_user.id,
        task_type=ConversationTaskType.REPRODUCE,
        title="runtime multi step workflow",
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
      Create CPU instance.
    expected_output: |
      CPU instance created.
  - id: step_4_cpu_env_setup
    name: CPU env
    depends_on: [step_3_deploy_cpu]
    instruction: |
      Prepare CPU environment.
    expected_output: |
      CPU environment ready.
"""
    skill = SkillDefinition(
        name="workflow-skill",
        allowed_tools=[],
        workflow_context=workflow,
    )
    events = ListEventSink()
    runtime = AgentRuntime(
        session=db_session,
        llm=TwoStepWorkflowLLM(),
        tool_executor=ToolExecutor(
            registry=WorkflowRegistry(),
            event_sink=events,
            runtime_tools={"skill.invoke": SkillInvokeTool({"workflow-skill": skill})},
        ),
        event_sink=events,
    )

    result = await runtime.run_conversation(conversation.id, model="claude-test")

    workflow_state = result.metadata["runtime"]["active_workflow"]
    assert result.status == "completed"
    assert workflow_state["status"] == "completed"
    assert workflow_state["steps"]["step_3_deploy_cpu"]["status"] == "completed"
    assert workflow_state["steps"]["step_4_cpu_env_setup"]["status"] == "completed"
    workflow_events = [event for event in events.events if event["type"] == "workflow_step_updated"]
    assert workflow_events
    event_steps = {step["id"]: step for step in workflow_events[-1]["workflow"]["steps"]}
    assert event_steps["step_3_deploy_cpu"]["status"] == "completed"
    assert event_steps["step_4_cpu_env_setup"]["status"] == "completed"


@pytest.mark.asyncio
async def test_agent_runtime_generates_final_report_when_project_reproduce_workflow_completes(
    db_session, test_user
):
    conversation = Conversation(
        user_id=test_user.id,
        task_type=ConversationTaskType.REPRODUCE,
        title="runtime final report workflow",
        status=ConversationStatus.RUNNING,
        metadata_={},
    )
    db_session.add(conversation)
    await db_session.commit()
    await db_session.refresh(conversation)
    workflow = """
version: agent-workflow/v1
name: Lab4AI_Auto_Reproduction_Pipeline
description: Demo final workflow
tasks:
  - id: step_8_generate_report
    name: Generate report
    instruction: |
      调用 lab4ai-repro-report，生成结项 Word 报告。
    expected_output: |
      Word file path.
  - id: step_9_release_gpu
    name: Release GPU
    depends_on: [step_8_generate_report]
    instruction: |
      释放 GPU 实例。
    expected_output: |
      GPU instance released.
"""
    skill = SkillDefinition(
        name="workflow-skill",
        allowed_tools=[],
        workflow_context=workflow,
    )
    events = ListEventSink()
    llm = FinalReportWorkflowLLM()
    runtime = AgentRuntime(
        session=db_session,
        llm=llm,
        tool_executor=ToolExecutor(
            registry=WorkflowRegistry(),
            event_sink=events,
            runtime_tools={"skill.invoke": SkillInvokeTool({"workflow-skill": skill})},
        ),
        event_sink=events,
    )

    result = await runtime.run_conversation(conversation.id, model="claude-test")

    workflow_state = result.metadata["runtime"]["active_workflow"]
    assert result.status == "completed"
    assert workflow_state["status"] == "completed"
    assert workflow_state["steps"]["step_8_generate_report"]["status"] == "completed"
    assert workflow_state["steps"]["step_9_release_gpu"]["status"] == "completed"
    assert workflow_state["results"]["word_report_path"] == (
        "runtime/workspaces/7/motion-guided-flow/report.docx"
    )
    assert "## 结项报告" in result.final_text
    assert "已按 project_reproduce.yaml 完成全部 2 个步骤" in result.final_text
    assert "runtime/workspaces/7/motion-guided-flow/report.docx" in result.final_text
    assert "/workspace/user-data/codelab/motion-guided-flow/report.docx" in result.final_text
    assert "GPU 实例已释放" in result.final_text
    assert llm.calls == 3


@pytest.mark.asyncio
async def test_agent_runtime_does_not_complete_workflow_from_model_text_only(db_session, test_user):
    conversation = Conversation(
        user_id=test_user.id,
        task_type=ConversationTaskType.REPRODUCE,
        title="runtime no text-only workflow completion",
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
      Task 0.5: Import precheck. Run python -c "import torch" first.
    expected_output: |
      Model runs on GPU and captures loss plus resource metrics.
"""
    skill = SkillDefinition(
        name="workflow-skill",
        allowed_tools=[],
        workflow_context=workflow,
    )
    events = ListEventSink()
    runtime = AgentRuntime(
        session=db_session,
        llm=PrematureWorkflowLLM(),
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
    assert runtime_state["pending_tool_call"]["tool_name"] == "workflow_recovery"
    assert runtime_state["active_workflow"]["steps"]["step_7_gpu_execution"]["status"] == "recovery"


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
