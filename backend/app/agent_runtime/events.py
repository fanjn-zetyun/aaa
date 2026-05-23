from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any


class EventSink:
    async def publish(self, event: dict[str, Any]) -> None:
        raise NotImplementedError


@dataclass(slots=True)
class ListEventSink(EventSink):
    events: list[dict[str, Any]] = field(default_factory=list)

    async def publish(self, event: dict[str, Any]) -> None:
        self.events.append(dict(event))


class CallbackEventSink(EventSink):
    def __init__(self, callback: Callable[[dict[str, Any]], Awaitable[None] | None]) -> None:
        self.callback = callback

    async def publish(self, event: dict[str, Any]) -> None:
        result = self.callback(dict(event))
        if result is not None:
            await result
