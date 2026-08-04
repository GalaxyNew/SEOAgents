"""Agent data contracts (L3) — mirrors DojoAgents ``agent/models.py``.

ChatMessage / ToolCall / ToolResult / LLMResult are the wire types shared by
providers, the agent loop, and the tool executor.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any, Literal

Role = Literal["system", "user", "assistant", "tool"]


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


@dataclass
class ToolCall:
    name: str
    arguments: dict[str, Any] = field(default_factory=dict)
    id: str = field(default_factory=lambda: _new_id("call"))


@dataclass
class ToolResult:
    call_id: str
    name: str
    ok: bool = True
    content: str = ""
    error: str = ""
    latency_ms: int = 0

    def as_text(self) -> str:
        return self.content if self.ok else f"Tool Error: {self.error}"


@dataclass
class ChatMessage:
    role: Role
    content: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    tool_results: list[ToolResult] = field(default_factory=list)


@dataclass
class LLMResult:
    """One completion turn from a provider."""

    content: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    stop_reason: str = "end_turn"  # end_turn | tool_use | max_tokens | error
    usage: dict[str, int] = field(default_factory=dict)

    @property
    def wants_tools(self) -> bool:
        return bool(self.tool_calls)


@dataclass
class TraceStep:
    """One executed action — the raw material for L5 skill distillation."""

    action: str
    tool: str
    arguments: dict[str, Any] = field(default_factory=dict)
    output: str = ""
    ok: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "action": self.action,
            "tool": self.tool,
            "arguments": self.arguments,
            "output": self.output[:2000],
            "ok": self.ok,
        }


@dataclass
class AgentRunResult:
    session_id: str
    final_text: str = ""
    turns: int = 0
    trace: list[TraceStep] = field(default_factory=list)
    ok: bool = True
    error: str = ""

    def trace_dicts(self) -> list[dict[str, Any]]:
        return [t.to_dict() for t in self.trace]
