"""UniversalAgentLoop (L3) — multi-turn Tool-Call closed loop.

One loop instance drives one task: provider completion -> tool execution ->
result feedback, until the provider stops calling tools or ``max_turns`` is
reached. Every executed call is captured as a ``TraceStep`` — the raw material
the L5 RuntimeSkillCompiler distills into static skills.
"""
from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Any

from dojocore.logging import LOGGER
from seoagents.agent.models import AgentRunResult, ChatMessage, TraceStep
from seoagents.agent.providers import BaseLLMProvider
from seoagents.utils.event_bus import EventBus

if TYPE_CHECKING:
    from seoagents.tools.executor import ToolExecutor



class UniversalAgentLoop:
    def __init__(
        self,
        provider: BaseLLMProvider,
        executor: ToolExecutor,
        *,
        event_bus: EventBus | None = None,
        max_turns: int = 12,
    ) -> None:
        self.provider = provider
        self.executor = executor
        self.event_bus = event_bus
        self.max_turns = max_turns

    async def run(
        self,
        task: str,
        *,
        system: str = "",
        allowed_tools: set[str] | None = None,
        session_id: str | None = None,
        extra_messages: list[ChatMessage] | None = None,
    ) -> AgentRunResult:
        session_id = session_id or f"sess_{uuid.uuid4().hex[:10]}"
        tools = self.executor.registry.schemas(allowed_tools)
        messages: list[ChatMessage] = list(extra_messages or [])
        messages.append(ChatMessage(role="user", content=task))
        result = AgentRunResult(session_id=session_id)

        for turn in range(1, self.max_turns + 1):
            result.turns = turn
            await self._emit("agent.turn", session_id=session_id, turn=turn)
            try:
                llm = await self.provider.complete(messages, tools, system=system)
            except Exception as exc:  # noqa: BLE001 - provider boundary
                LOGGER.exception("LLM provider call failed")
                result.ok = False
                result.error = f"provider failure: {exc}"
                return result

            if llm.stop_reason == "error":
                result.ok = False
                result.error = llm.content
                result.final_text = llm.content
                return result

            if not llm.wants_tools:
                result.final_text = llm.content
                await self._emit("agent.done", session_id=session_id, turns=turn)
                return result

            messages.append(
                ChatMessage(role="assistant", content=llm.content, tool_calls=llm.tool_calls)
            )
            # 模型在决定调工具之前那段话,就是它的思路。此前只进 messages、
            # 不往外发,前端只能看到「正在执行」然后干等两三分钟。
            if (llm.content or "").strip():
                await self._emit(
                    "agent.thinking", session_id=session_id, turn=turn,
                    text=llm.content.strip(),
                )
            await self._emit(
                "agent.tool_start", session_id=session_id, turn=turn,
                tools=[c.name for c in llm.tool_calls],
            )
            tool_results = await self.executor.execute_many(llm.tool_calls, session_id=session_id)
            for call, res in zip(llm.tool_calls, tool_results):
                result.trace.append(
                    TraceStep(
                        action=self._describe_action(call.name, call.arguments),
                        tool=call.name,
                        arguments=dict(call.arguments),
                        output=res.as_text(),
                        ok=res.ok,
                    )
                )
                await self._emit(
                    "agent.tool", session_id=session_id, tool=call.name, ok=res.ok,
                    latency_ms=res.latency_ms,
                )
            messages.append(ChatMessage(role="tool", tool_results=tool_results))

        result.final_text = result.final_text or "(max turns reached without final answer)"
        LOGGER.warning(f"Agent loop hit max_turns={self.max_turns} session={session_id}")
        return result

    @staticmethod
    def _describe_action(tool: str, arguments: dict[str, Any]) -> str:
        action = arguments.get("action")
        return f"{tool}.{action}" if action else tool

    async def _emit(self, topic: str, **payload: Any) -> None:
        if self.event_bus is not None:
            await self.event_bus.emit(topic, **payload)


__all__ = ["UniversalAgentLoop"]
