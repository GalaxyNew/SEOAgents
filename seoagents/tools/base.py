"""BaseToolSpec + ToolRegistry (L4).

Every capability exposed to the agent loop is a ``BaseToolSpec`` registered in
the single ``ToolRegistry`` — registering tools anywhere else is forbidden
(DojoAgents guardrail). The spec interface follows the SEO manual:
``get_name() / get_schema() / async execute(arguments, session_id)``.
"""
from __future__ import annotations

import abc
from typing import Any

from dojocore.logging import LOGGER


class BaseToolSpec(abc.ABC):
    """One agent-callable tool."""

    @abc.abstractmethod
    def get_name(self) -> str: ...

    @abc.abstractmethod
    def get_schema(self) -> dict[str, Any]:
        """JSON-schema tool descriptor: {name, description, parameters}."""

    @abc.abstractmethod
    async def execute(self, arguments: dict[str, Any], session_id: str) -> str | dict[str, Any]:
        """Run the tool. Return str or JSON-serializable dict."""


class ToolRegistry:
    def __init__(self) -> None:
        self._specs: dict[str, BaseToolSpec] = {}

    def register(self, spec: BaseToolSpec) -> None:
        name = spec.get_name()
        if name in self._specs:
            raise ValueError(f"Tool '{name}' already registered")
        self._specs[name] = spec
        LOGGER.info(f"Tool registered: {name}")

    def get(self, name: str) -> BaseToolSpec | None:
        return self._specs.get(name)

    def names(self) -> list[str]:
        return sorted(self._specs)

    def schemas(self, allowed: set[str] | None = None) -> list[dict[str, Any]]:
        return [
            spec.get_schema()
            for name, spec in sorted(self._specs.items())
            if allowed is None or name in allowed
        ]


__all__ = ["BaseToolSpec", "ToolRegistry"]
