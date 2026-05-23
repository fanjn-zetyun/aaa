from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
import re


TEMPLATE_RE = re.compile(r"{{\s*([^{}]+?)\s*}}")


@dataclass(slots=True)
class RenderedValue:
    ok: bool
    value: Any = None
    error_code: str | None = None
    unresolved_variables: list[str] = field(default_factory=list)


def render_runtime_templates(value: Any, context: dict[str, Any]) -> RenderedValue:
    unresolved: list[str] = []

    def resolve(path: str) -> Any:
        current: Any = context
        for part in path.split("."):
            if isinstance(current, dict) and part in current:
                current = current[part]
            else:
                unresolved.append(path)
                return ""
        return current

    def render_item(item: Any) -> Any:
        if isinstance(item, dict):
            return {key: render_item(inner) for key, inner in item.items()}
        if isinstance(item, list):
            return [render_item(inner) for inner in item]
        if not isinstance(item, str):
            return item
        matches = list(TEMPLATE_RE.finditer(item))
        if not matches:
            return item
        if len(matches) == 1 and matches[0].span() == (0, len(item)):
            return resolve(matches[0].group(1).strip())
        return TEMPLATE_RE.sub(lambda match: str(resolve(match.group(1).strip())), item)

    rendered = render_item(value)
    if unresolved:
        return RenderedValue(
            ok=False,
            value=rendered,
            error_code="unresolved_template_variable",
            unresolved_variables=sorted(set(unresolved)),
        )
    return RenderedValue(ok=True, value=rendered)
