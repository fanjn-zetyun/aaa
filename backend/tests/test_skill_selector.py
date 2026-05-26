from __future__ import annotations

import pytest

from app.services.llm_client import LLMRuntimeConfig, LLMToolResponse, LLMToolUse
from app.services.skill_selector import SkillSelector
from app.services.skills import SkillDefinition


pytestmark = pytest.mark.asyncio


def _config(api_key: str | None = "key") -> LLMRuntimeConfig:
    return LLMRuntimeConfig(
        provider="anthropic",
        base_url="https://api.example.com",
        api_key=api_key,
        model="claude-compatible",
        max_tokens=1024,
    )


def _skills() -> dict[str, SkillDefinition]:
    return {
        "lab4ai-auto-reproduct": SkillDefinition(
            name="lab4ai-auto-reproduct",
            description="Project reproduction",
            triggers=["reproduce", "github"],
            when_to_use="Use for GitHub project reproduction.",
            allowed_tools=["analyze_repo"],
            workflow_context="name: lab4ai-auto-reproduct\nsteps: []",
        ),
        "lab4ai-paper-analysis": SkillDefinition(
            name="lab4ai-paper-analysis",
            description="Paper analysis",
            triggers=["paper"],
            when_to_use="Use for paper-only analysis.",
            allowed_tools=["analyze_paper"],
        ),
        "lab4ai-auto-research": SkillDefinition(
            name="lab4ai-auto-research",
            description="Automated training experiments",
            triggers=["自动化实验", "自动调参"],
            when_to_use="Use for automated experiment pipelines.",
            workflow_context="WORKFLOW_KIND: autoresearch_pipeline\nname: autoresearch_pipeline",
        ),
        "zero-code-reproduction": SkillDefinition(
            name="zero-code-reproduction",
            description="Paper-only zero-code reproduction",
            triggers=["论文复现", "zero-code reproduction"],
            when_to_use="Use for paper-only reproduction without a GitHub repository.",
            workflow_context="WORKFLOW_KIND: zero_code_reproduction_pipeline\nname: zero_code_reproduction_pipeline",
        ),
    }


async def test_model_skill_choice_wins(monkeypatch):
    captured: dict[str, object] = {}

    async def fake_tool_use(config, *, system, messages, tools):
        captured["system"] = system
        captured["messages"] = messages
        captured["tools"] = tools
        return LLMToolResponse(
            text="",
            tool_calls=[
                LLMToolUse(
                    id="toolu-select",
                    name="select_skill",
                    input={"skill_name": "lab4ai-auto-reproduct"},
                )
            ],
            stop_reason="tool_use",
            raw={},
        )

    monkeypatch.setattr("app.services.skill_selector.call_anthropic_compatible_tool_use", fake_tool_use)

    result = await SkillSelector().select(
        config=_config(),
        skills=_skills(),
        metadata={
            "task_type": "reproduce",
            "github_url": "https://github.com/jsnzwu/motion-guided-flow",
        },
        latest_user="Please reproduce https://github.com/jsnzwu/motion-guided-flow",
    )

    assert result.skill_name == "lab4ai-auto-reproduct"
    assert result.source == "model"
    assert result.model_choice == "lab4ai-auto-reproduct"
    assert result.fallback_choice is None
    assert result.error is None
    assert result.confidence is None
    assert result.to_metadata() == {
        "selected_skill": "lab4ai-auto-reproduct",
        "source": "model",
        "model_choice": "lab4ai-auto-reproduct",
        "fallback_choice": None,
        "reason": "Model selected registered skill `lab4ai-auto-reproduct`.",
        "confidence": None,
        "error": None,
    }
    assert captured["tools"] == [SkillSelector.select_skill_tool_schema()]
    assert "motion-guided-flow" in str(captured["messages"])


async def test_unconfigured_model_uses_reproduce_fallback(monkeypatch):
    async def fake_tool_use(config, *, system, messages, tools):
        raise AssertionError("model should not be called when config is incomplete")

    monkeypatch.setattr("app.services.skill_selector.call_anthropic_compatible_tool_use", fake_tool_use)

    result = await SkillSelector().select(
        config=_config(api_key=None),
        skills=_skills(),
        metadata={"task_type": "reproduce"},
        latest_user="Please reproduce this project",
    )

    assert result.skill_name == "lab4ai-auto-reproduct"
    assert result.source == "fallback"
    assert result.fallback_choice == "lab4ai-auto-reproduct"
    assert result.error == "llm_not_configured"


async def test_paper_only_reproduce_uses_zero_code_fallback(monkeypatch):
    async def fake_tool_use(config, *, system, messages, tools):
        raise AssertionError("model should not be called when config is incomplete")

    monkeypatch.setattr("app.services.skill_selector.call_anthropic_compatible_tool_use", fake_tool_use)

    result = await SkillSelector().select(
        config=_config(api_key=None),
        skills=_skills(),
        metadata={
            "task_type": "reproduce",
            "paper_url": "https://arxiv.org/pdf/2502.14397",
            "github_url": None,
        },
        latest_user="复现这篇论文，但没有代码仓库。",
    )

    assert result.skill_name == "zero-code-reproduction"
    assert result.source == "fallback"
    assert result.fallback_choice == "zero-code-reproduction"
    assert result.error == "llm_not_configured"


async def test_github_reproduce_still_uses_auto_reproduct_fallback(monkeypatch):
    async def fake_tool_use(config, *, system, messages, tools):
        raise AssertionError("model should not be called when config is incomplete")

    monkeypatch.setattr("app.services.skill_selector.call_anthropic_compatible_tool_use", fake_tool_use)

    result = await SkillSelector().select(
        config=_config(api_key=None),
        skills=_skills(),
        metadata={
            "task_type": "reproduce",
            "paper_url": "https://arxiv.org/pdf/2502.14397",
            "github_url": "https://github.com/example/repo",
        },
        latest_user="复现这个 GitHub 项目。",
    )

    assert result.skill_name == "lab4ai-auto-reproduct"
    assert result.source == "fallback"
    assert result.fallback_choice == "lab4ai-auto-reproduct"
    assert result.error == "llm_not_configured"


async def test_unknown_model_skill_falls_back(monkeypatch):
    async def fake_tool_use(config, *, system, messages, tools):
        return LLMToolResponse(
            text="",
            tool_calls=[
                LLMToolUse(
                    id="toolu-select",
                    name="select_skill",
                    input={"skill_name": "missing-skill"},
                )
            ],
            stop_reason="tool_use",
            raw={},
        )

    monkeypatch.setattr("app.services.skill_selector.call_anthropic_compatible_tool_use", fake_tool_use)

    result = await SkillSelector().select(
        config=_config(),
        skills=_skills(),
        metadata={"task_type": "reproduce", "github_url": "https://github.com/example/repo"},
        latest_user="Reproduce this repository",
    )

    assert result.skill_name == "lab4ai-auto-reproduct"
    assert result.source == "fallback"
    assert result.model_choice == "missing-skill"
    assert result.fallback_choice == "lab4ai-auto-reproduct"
    assert result.error == "unknown_skill"


async def test_text_json_model_skill_choice_wins(monkeypatch):
    async def fake_tool_use(config, *, system, messages, tools):
        return LLMToolResponse(
            text='{"skill_name": "lab4ai-auto-reproduct"}',
            tool_calls=[],
            stop_reason="end_turn",
            raw={},
        )

    monkeypatch.setattr("app.services.skill_selector.call_anthropic_compatible_tool_use", fake_tool_use)

    result = await SkillSelector().select(
        config=_config(),
        skills=_skills(),
        metadata={"task_type": "reproduce"},
        latest_user="Reproduce",
    )

    assert result.skill_name == "lab4ai-auto-reproduct"
    assert result.source == "model"
    assert result.model_choice == "lab4ai-auto-reproduct"
    assert result.confidence is None
    assert result.reason == "Model selected registered skill `lab4ai-auto-reproduct`."
    assert result.error is None


async def test_general_task_fallback_without_registered_skill_returns_no_selection(monkeypatch):
    async def fake_tool_use(config, *, system, messages, tools):
        raise AssertionError("model should not be called when config is incomplete")

    monkeypatch.setattr("app.services.skill_selector.call_anthropic_compatible_tool_use", fake_tool_use)

    result = await SkillSelector().select(
        config=_config(api_key=None),
        skills=_skills(),
        metadata={"task_type": "general"},
        latest_user="Hello",
    )

    assert result.skill_name == ""
    assert result.source == "fallback"
    assert result.fallback_choice == "general-chat"
    assert result.error == "llm_not_configured"


async def test_reproduce_fallback_missing_skill_returns_no_selection(monkeypatch):
    async def fake_tool_use(config, *, system, messages, tools):
        raise AssertionError("model should not be called when config is incomplete")

    monkeypatch.setattr("app.services.skill_selector.call_anthropic_compatible_tool_use", fake_tool_use)

    result = await SkillSelector().select(
        config=_config(api_key=None),
        skills={
            "lab4ai-paper-analysis": SkillDefinition(
                name="lab4ai-paper-analysis",
                description="Paper analysis",
                triggers=["paper"],
                when_to_use="Use for paper-only analysis.",
            )
        },
        metadata={
            "task_type": "reproduce",
            "github_url": "https://github.com/example/repo",
        },
        latest_user="Please reproduce this repo",
    )

    assert result.skill_name == ""
    assert result.source == "fallback"
    assert result.fallback_choice == "lab4ai-auto-reproduct"
    assert result.error == "llm_not_configured"
    assert result.to_metadata()["selected_skill"] == ""
    assert result.to_metadata()["fallback_choice"] != "general-chat"


async def test_experiments_task_uses_auto_research_fallback(monkeypatch):
    async def fake_tool_use(config, *, system, messages, tools):
        raise AssertionError("model should not be called when config is incomplete")

    monkeypatch.setattr("app.services.skill_selector.call_anthropic_compatible_tool_use", fake_tool_use)

    result = await SkillSelector().select(
        config=_config(api_key=None),
        skills=_skills(),
        metadata={"task_type": "experiments"},
        latest_user="自动化实验矩阵，做学习率和 batch size 搜索",
    )

    assert result.skill_name == "lab4ai-auto-research"
    assert result.source == "fallback"
    assert result.fallback_choice == "lab4ai-auto-research"
    assert result.error == "llm_not_configured"


async def test_experiments_task_ignores_model_reproduction_choice(monkeypatch):
    async def fake_tool_use(config, *, system, messages, tools):
        raise AssertionError("experiments should use deterministic auto-research selection")

    monkeypatch.setattr("app.services.skill_selector.call_anthropic_compatible_tool_use", fake_tool_use)

    result = await SkillSelector().select(
        config=_config(),
        skills=_skills(),
        metadata={
            "task_type": "experiments",
            "github_url": "https://github.com/jingyaogong/minimind",
        },
        latest_user="帮我跑下https://github.com/jingyaogong/minimind的自动化训练实验",
    )

    assert result.skill_name == "lab4ai-auto-research"
    assert result.source == "fallback"
    assert result.fallback_choice == "lab4ai-auto-research"
    assert result.error == "deterministic_task_type"


async def test_experiments_model_choice_without_workflow_falls_back(monkeypatch):
    async def fake_tool_use(config, *, system, messages, tools):
        raise AssertionError("experiments should use deterministic auto-research selection")

    monkeypatch.setattr("app.services.skill_selector.call_anthropic_compatible_tool_use", fake_tool_use)

    result = await SkillSelector().select(
        config=_config(),
        skills=_skills(),
        metadata={"task_type": "experiments"},
        latest_user="自动化调参",
    )

    assert result.skill_name == "lab4ai-auto-research"
    assert result.source == "fallback"
    assert result.model_choice is None
    assert result.fallback_choice == "lab4ai-auto-research"
    assert result.error == "deterministic_task_type"
