import pytest

from app.agent_runtime.events import ListEventSink
from app.agent_runtime.llm import ModelResponse
from app.agent_runtime.runtime import AgentRuntime
from app.agent_runtime.skills import SkillInvokeTool
from app.agent_runtime.state import RuntimeState, save_runtime_state
from app.agent_runtime.workflows.autoresearch import activate_autoresearch_workflow
from app.agent_runtime.workflows.zero_code_reproduction import activate_zero_code_workflow
from app.agent_runtime.tool_executor import ToolExecutor
from app.core.config import get_settings
from app.models import Conversation, ConversationMessage, ConversationStatus, ConversationTaskType
from app.models.conversation import MessageRole
from app.services.llm_client import LLMToolUse
from app.services.skills import SkillLoader
from app.services.tools import ToolDefinition, ToolResult


class ExistingSkillFakeLLM:
    def __init__(self):
        self.calls = 0

    async def complete(self, request):
        self.calls += 1
        if self.calls == 1:
            return ModelResponse(
                text="加载复现 skill。",
                tool_calls=[
                    LLMToolUse(
                        id="toolu_skill",
                        name="skill.invoke",
                        input={
                            "skill": "lab4ai-auto-reproduct",
                            "args": {
                                "github_url": "https://github.com/example/repo",
                                "paper_url": "https://arxiv.org/abs/0000.00000",
                            },
                        },
                    )
                ],
                stop_reason="tool_use",
                usage={},
                raw={},
            )
        return ModelResponse(
            text="dry-run 完成。",
            tool_calls=[],
            stop_reason="end_turn",
            usage={},
            raw={},
        )


class ExistingAutoResearchFakeLLM:
    def __init__(self):
        self.calls = 0

    async def complete(self, request):
        self.calls += 1
        return ModelResponse(
            text="加载自动化实验 skill。",
            tool_calls=[
                LLMToolUse(
                    id="toolu_skill",
                    name="skill.invoke",
                    input={
                        "skill": "lab4ai-auto-research",
                        "args": {
                            "user_prompt": "做学习率和 batch size 自动化实验",
                        },
                    },
                )
            ],
            stop_reason="tool_use",
            usage={},
            raw={},
        )


class ExistingZeroCodeFakeLLM:
    def __init__(self):
        self.calls = 0

    async def complete(self, request):
        self.calls += 1
        return ModelResponse(
            text="加载零代码复现 skill。",
            tool_calls=[
                LLMToolUse(
                    id="toolu_skill",
                    name="skill.invoke",
                    input={
                        "skill": "zero-code-reproduction",
                        "args": {
                            "paper_url": "https://arxiv.org/pdf/2502.14397",
                        },
                    },
                )
            ],
            stop_reason="tool_use",
            usage={},
            raw={},
        )


class ExistingSkillFakeRegistry:
    def __init__(self):
        self.definitions = {
            "ask_user": ToolDefinition(
                name="ask_user",
                description="ask",
                input_schema={"type": "object", "properties": {"question": {"type": "string"}}},
                read_only=True,
            )
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
        return ToolResult(name, f"{name} ok", ok=True, metadata={})


@pytest.mark.asyncio
async def test_existing_skill_loads_through_skill_invoke_not_fixed_workflow(db_session, test_user):
    conversation = Conversation(
        user_id=test_user.id,
        task_type=ConversationTaskType.REPRODUCE,
        title="runtime skill dry run",
        status=ConversationStatus.RUNNING,
        metadata_={},
    )
    db_session.add(conversation)
    await db_session.commit()
    await db_session.refresh(conversation)
    events = ListEventSink()
    skills = SkillLoader(get_settings().skills_dir_path).load_all()
    executor = ToolExecutor(
        registry=ExistingSkillFakeRegistry(),
        event_sink=events,
        runtime_tools={"skill.invoke": SkillInvokeTool(skills)},
    )
    runtime = AgentRuntime(
        session=db_session,
        llm=ExistingSkillFakeLLM(),
        tool_executor=executor,
        event_sink=events,
    )

    result = await runtime.run_conversation(conversation.id, model="claude-test")

    assert result.status == "running"
    assert result.metadata["runtime"]["active_skill"]["name"] == "lab4ai-auto-reproduct"
    assert result.metadata["runtime"]["active_workflow"]["current_step_id"] == "step_1_audit"
    assert "step_1_audit" in result.metadata["runtime"]["instruction_plans"]
    step = result.metadata["runtime"]["active_workflow"]["steps"]["step_1_audit"]
    assert step["status"] == "recovery"
    assert "model text cannot complete workflow step without tool evidence" in step[
        "validation_failures"
    ]


@pytest.mark.asyncio
async def test_auto_research_skill_invoke_enters_lab_flow_gate(db_session, test_user):
    conversation = Conversation(
        user_id=test_user.id,
        task_type=ConversationTaskType.EXPERIMENTS,
        title="autoresearch runtime dry run",
        status=ConversationStatus.RUNNING,
        metadata_={},
    )
    db_session.add(conversation)
    await db_session.commit()
    await db_session.refresh(conversation)
    events = ListEventSink()
    skills = SkillLoader(get_settings().skills_dir_path).load_all()
    executor = ToolExecutor(
        registry=ExistingSkillFakeRegistry(),
        event_sink=events,
        runtime_tools={"skill.invoke": SkillInvokeTool(skills)},
    )
    runtime = AgentRuntime(
        session=db_session,
        llm=ExistingAutoResearchFakeLLM(),
        tool_executor=executor,
        event_sink=events,
    )

    result = await runtime.run_conversation(conversation.id, model="claude-test")

    runtime_state = result.metadata["runtime"]
    workflow = runtime_state["active_workflow"]
    assert result.status == "waiting_for_user"
    assert runtime_state["active_skill"]["name"] == "lab4ai-auto-research"
    assert workflow["kind"] == "autoresearch_pipeline"
    assert workflow["current_step_id"] == "instance_provision"
    assert workflow["gate_log"]["lab_instance_flow"]["value"] == "unresolved"
    assert runtime_state["pending_user_input"]["question"] == "是否创建实验室实例（Lab instance flow）？"


@pytest.mark.asyncio
async def test_auto_research_runtime_resumes_lab_no_reply_without_reinvoking_skill(
    db_session,
    test_user,
):
    conversation = Conversation(
        user_id=test_user.id,
        task_type=ConversationTaskType.EXPERIMENTS,
        title="autoresearch runtime resume",
        status=ConversationStatus.ACTIVE,
        metadata_={},
    )
    db_session.add(conversation)
    await db_session.commit()
    await db_session.refresh(conversation)
    state = activate_autoresearch_workflow(
        """
WORKFLOW_KIND: autoresearch_pipeline

## pipeline.yml
```yaml
name: autoresearch_pipeline
stages:
  - id: instance_provision
    title: Provision
    skill_file: scripts/skill_01lab_instance.md
  - id: policies
    title: Policies
    skill_file: scripts/skill_02policies.md
```
""",
        state=RuntimeState.new(conversation_id=conversation.id, model="claude-test"),
    )
    conversation.metadata_ = save_runtime_state(conversation.metadata_ or {}, state)
    db_session.add(
        ConversationMessage(
            conversation_id=conversation.id,
            role=MessageRole.USER,
            content="no",
            message_metadata={},
        )
    )
    await db_session.commit()

    events = ListEventSink()
    runtime = AgentRuntime(
        session=db_session,
        llm=ExistingAutoResearchFakeLLM(),
        tool_executor=ToolExecutor(
            registry=ExistingSkillFakeRegistry(),
            event_sink=events,
            runtime_tools={"skill.invoke": SkillInvokeTool({})},
        ),
        event_sink=events,
    )

    result = await runtime.run_conversation(conversation.id, model="claude-test")

    runtime_state = result.metadata["runtime"]
    workflow = runtime_state["active_workflow"]
    assert result.status == "running"
    assert workflow["gate_log"]["lab_instance_flow"]["value"] == "no"
    assert workflow["gate_log"]["step_2_lab_instance"]["value"] == "skipped"
    assert workflow["current_step_id"] == "policies"
    assert runtime_state["pending_user_input"] is None
    assert runtime.llm.calls == 0


@pytest.mark.asyncio
async def test_zero_code_skill_invoke_enters_step_zero_gate(db_session, test_user):
    conversation = Conversation(
        user_id=test_user.id,
        task_type=ConversationTaskType.REPRODUCE,
        title="zero code runtime dry run",
        status=ConversationStatus.RUNNING,
        metadata_={"paper_url": "https://arxiv.org/pdf/2502.14397"},
    )
    db_session.add(conversation)
    await db_session.commit()
    await db_session.refresh(conversation)
    events = ListEventSink()
    skills = SkillLoader(get_settings().skills_dir_path).load_all()
    executor = ToolExecutor(
        registry=ExistingSkillFakeRegistry(),
        event_sink=events,
        runtime_tools={"skill.invoke": SkillInvokeTool(skills)},
    )
    runtime = AgentRuntime(
        session=db_session,
        llm=ExistingZeroCodeFakeLLM(),
        tool_executor=executor,
        event_sink=events,
    )

    result = await runtime.run_conversation(conversation.id, model="claude-test")

    runtime_state = result.metadata["runtime"]
    workflow = runtime_state["active_workflow"]
    assert result.status == "waiting_for_user"
    assert runtime_state["active_skill"]["name"] == "zero-code-reproduction"
    assert workflow["kind"] == "zero_code_reproduction_pipeline"
    assert workflow["current_step_id"] == "step_0_remote_instance_init"
    assert workflow["gate_log"]["step_0_cpu_instance"]["value"] == "unresolved"
    assert runtime_state["pending_user_input"]["question"] == "是否创建远程 CPU 实例并开始零代码复现流水线？"


@pytest.mark.asyncio
async def test_zero_code_runtime_resumes_step_zero_yes_without_reinvoking_skill(
    db_session,
    test_user,
):
    conversation = Conversation(
        user_id=test_user.id,
        task_type=ConversationTaskType.REPRODUCE,
        title="zero code runtime resume",
        status=ConversationStatus.ACTIVE,
        metadata_={"paper_url": "https://arxiv.org/pdf/2502.14397"},
    )
    db_session.add(conversation)
    await db_session.commit()
    await db_session.refresh(conversation)
    state = activate_zero_code_workflow(
        "WORKFLOW_KIND: zero_code_reproduction_pipeline\n",
        state=RuntimeState.new(conversation_id=conversation.id, model="claude-test"),
    )
    conversation.metadata_ = save_runtime_state(conversation.metadata_ or {}, state)
    db_session.add(
        ConversationMessage(
            conversation_id=conversation.id,
            role=MessageRole.USER,
            content="yes",
            message_metadata={},
        )
    )
    await db_session.commit()

    events = ListEventSink()
    runtime = AgentRuntime(
        session=db_session,
        llm=ExistingZeroCodeFakeLLM(),
        tool_executor=ToolExecutor(
            registry=ExistingSkillFakeRegistry(),
            event_sink=events,
            runtime_tools={"skill.invoke": SkillInvokeTool({})},
        ),
        event_sink=events,
    )

    result = await runtime.run_conversation(conversation.id, model="claude-test")

    runtime_state = result.metadata["runtime"]
    workflow = runtime_state["active_workflow"]
    assert result.status == "running"
    assert workflow["gate_log"]["step_0_cpu_instance"]["value"] == "yes"
    assert workflow["current_step_id"] == "step_0_remote_instance_init"
    assert runtime_state["pending_user_input"] is None
    assert "lab4ai_create_instance" in runtime_state["allowed_tools"]
    assert runtime.llm.calls == 0
