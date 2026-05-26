"""Model-first skill selection with deterministic fallback."""

from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any, Literal

from app.services.llm_client import LLMRuntimeConfig, call_anthropic_compatible_tool_use
from app.services.skills import SkillDefinition, fallback_skill_name


@dataclass(slots=True)
class SkillSelectionResult:
    skill_name: str
    reason: str
    confidence: float | None
    source: Literal["model", "fallback"]
    model_choice: str | None = None
    fallback_choice: str | None = None
    error: str | None = None

    def to_metadata(self) -> dict[str, object]:
        return {
            "selected_skill": self.skill_name,
            "source": self.source,
            "model_choice": self.model_choice,
            "fallback_choice": self.fallback_choice,
            "reason": self.reason,
            "confidence": self.confidence,
            "error": self.error,
        }


class SkillSelector:
    async def select(
        self,
        *,
        config: LLMRuntimeConfig,
        skills: dict[str, SkillDefinition],
        metadata: dict,
        latest_user: str,
    ) -> SkillSelectionResult:
        if config.configured and metadata.get("task_type") == "experiments":
            return self._fallback(
                skills,
                metadata,
                reason="Task type `experiments` maps deterministically to auto research skill.",
                error="deterministic_task_type",
            )

        if not config.configured:
            return self._fallback(
                skills,
                metadata,
                reason="LLM is not configured; selected skill with deterministic fallback.",
                error="llm_not_configured",
            )

        try:
            response = await call_anthropic_compatible_tool_use(
                config,
                system=self._system_prompt(),
                messages=[
                    {
                        "role": "user",
                        "content": self._selection_context(skills, metadata, latest_user),
                    }
                ],
                tools=[self.select_skill_tool_schema()],
            )
        except Exception as exc:
            return self._fallback(
                skills,
                metadata,
                reason=f"Model skill selection failed; selected fallback. Error: {type(exc).__name__}: {exc}",
                error="model_call_failed",
            )

        payload = self._extract_selection_payload(response)
        if payload is None:
            return self._fallback(
                skills,
                metadata,
                reason="Model did not return a parseable skill selection; selected fallback.",
                error="invalid_model_response",
            )

        model_choice = str(payload.get("skill_name") or "").strip()

        if model_choice not in skills:
            return self._fallback(
                skills,
                metadata,
                reason=f"Model selected unknown skill `{model_choice}`; selected fallback.",
                model_choice=model_choice,
                error="unknown_skill",
            )

        selected = skills[model_choice]
        if _requires_workflow(metadata) and not selected.workflow_context:
            return self._fallback(
                skills,
                metadata,
                reason=f"Task requires a workflow, but `{model_choice}` has no workflow; selected fallback.",
                model_choice=model_choice,
                error="missing_workflow",
            )

        return SkillSelectionResult(
            skill_name=model_choice,
            reason=f"Model selected registered skill `{model_choice}`.",
            confidence=None,
            source="model",
            model_choice=model_choice,
        )

    @staticmethod
    def select_skill_tool_schema() -> dict[str, object]:
        return {
            "name": "select_skill",
            "description": "Select exactly one registered skill for the user's task.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "skill_name": {
                        "type": "string",
                        "description": "The exact name of one skill from the provided registry.",
                    },
                },
                "required": ["skill_name"],
            },
        }

    def _fallback(
        self,
        skills: dict[str, SkillDefinition],
        metadata: dict,
        *,
        reason: str,
        error: str,
        model_choice: str | None = None,
        confidence: float | None = None,
    ) -> SkillSelectionResult:
        fallback = fallback_skill_name(metadata)
        if fallback not in skills:
            missing_reason = f"Fallback skill `{fallback}` is not registered; no skill selected."
            if reason:
                missing_reason = f"{reason} {missing_reason}"
            return SkillSelectionResult(
                skill_name="",
                reason=missing_reason,
                confidence=confidence,
                source="fallback",
                model_choice=model_choice,
                fallback_choice=fallback,
                error=error,
            )
        return SkillSelectionResult(
            skill_name=fallback,
            reason=reason,
            confidence=confidence,
            source="fallback",
            model_choice=model_choice,
            fallback_choice=fallback,
            error=error,
        )

    @staticmethod
    def _system_prompt() -> str:
        return (
            "You are LOBSTER's skill selector. "
            "You must select only one skill_name from the provided available skills. "
            "Do not execute the task, do not plan tool calls, and do not return file paths. "
            "Return the selection by calling the select_skill tool."
        )

    @staticmethod
    def _selection_context(
        skills: dict[str, SkillDefinition],
        metadata: dict,
        latest_user: str,
    ) -> str:
        summaries = [
            skill.summary_for_selection()
            for skill in sorted(skills.values(), key=lambda item: item.name)
        ]
        context = {
            "instruction": (
                "Select one skill_name only. Do not execute the task, do not return paths, "
                "and do not choose skills outside available_skills."
            ),
            "latest_user": latest_user,
            "metadata": metadata,
            "available_skills": summaries,
        }
        return json.dumps(context, ensure_ascii=False, sort_keys=True)

    @staticmethod
    def _extract_selection_payload(response: Any) -> dict[str, object] | None:
        for tool_call in response.tool_calls:
            if tool_call.name == "select_skill" and isinstance(tool_call.input, dict):
                return dict(tool_call.input)
        return _extract_json_object(response.text)


def _extract_json_object(text: str) -> dict[str, object] | None:
    stripped = text.strip()
    if not stripped:
        return None

    try:
        parsed = json.loads(stripped)
    except json.JSONDecodeError:
        start = stripped.find("{")
        end = stripped.rfind("}")
        if start < 0 or end <= start:
            return None
        try:
            parsed = json.loads(stripped[start : end + 1])
        except json.JSONDecodeError:
            return None

    return parsed if isinstance(parsed, dict) else None


def _requires_workflow(metadata: dict) -> bool:
    return metadata.get("task_type") in {"experiments", "reproduce"} or bool(
        metadata.get("github_url")
    )
