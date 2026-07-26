"""Minimal in-process async event bus (utils) — progress events for dashboard/gateway."""
from __future__ import annotations

import asyncio
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

from seoagents.logging import LOGGER

Handler = Callable[["Event"], Awaitable[None] | None]


@dataclass(frozen=True)
class Event:
    topic: str
    payload: dict[str, Any] = field(default_factory=dict)
    ts: float = field(default_factory=time.time)


class EventBus:
    def __init__(self, history: int = 200) -> None:
        self._handlers: dict[str, list[Handler]] = {}
        self._history: deque[Event] = deque(maxlen=history)

    def subscribe(self, topic: str, handler: Handler) -> None:
        self._handlers.setdefault(topic, []).append(handler)

    def recent(self, topic: str | None = None, limit: int = 50) -> list[Event]:
        events = [e for e in self._history if topic is None or e.topic == topic]
        return events[-limit:]

    async def emit(self, topic: str, **payload: Any) -> None:
        event = Event(topic=topic, payload=payload)
        self._history.append(event)
        for handler in self._handlers.get(topic, []) + self._handlers.get("*", []):
            try:
                result = handler(event)
                if asyncio.iscoroutine(result):
                    await result
            except Exception:  # noqa: BLE001 - subscriber faults must not break emitters
                LOGGER.exception(f"Event handler failed for topic '{topic}'")


__all__ = ["Event", "EventBus"]
