import pytest

from app.agent_runtime.events import ListEventSink
from app.agent_runtime.llm import ModelResponse
from app.agent_runtime.runtime import AgentRuntime
from app.agent_runtime.skills import SkillInvokeTool
from app.agent_runtime.tool_executor import ToolExecutor
from app.core.config import get_settings
from app.models import Conversation, ConversationStatus, ConversationTaskType
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

    assert result.status == "completed"
    assert result.metadata["runtime"]["active_skill"]["name"] == "lab4ai-auto-reproduct"
    assert result.metadata["runtime"]["active_workflow"]["current_step_id"] == "step_1_audit"
