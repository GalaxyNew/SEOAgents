"""ToolExecutor (L4) — the golden execution pattern from DojoAgents AGENTS.md.

Bounded async execution, structured error handling, unified logging:
registry lookup -> sandbox check -> timeout-guarded handler -> coerced ToolResult.
"""
from __future__ import annotations

import asyncio
import json
import time
from contextvars import ContextVar
from typing import Any

from dojocore.logging import LOGGER
from dojocore.quality import DataIntegrityError, validate_tool_output
from dojocore.agent.models import ToolCall, ToolResult
from dojocore.tools.base import ToolRegistry
from dojocore.tools.environments.sandbox import SandboxPolicy, SandboxViolation

active_session_id: ContextVar[str] = ContextVar("active_session_id", default="")


class ToolExecutor:
    """Gate 1 of the data-integrity contract lives here.

    Validating centrally (rather than per-spec) means a newly added tool cannot
    bypass the ``data_status`` requirement by forgetting to declare it — the
    executor refuses the result and the failure is loud instead of silent.
    """

    def __init__(
        self,
        registry: ToolRegistry,
        sandbox: SandboxPolicy,
        *,
        enforce_data_status: bool = True,
    ) -> None:
        self.registry = registry
        self.sandbox = sandbox
        self.enforce_data_status = enforce_data_status

    async def execute_one(self, call: ToolCall, *, session_id: str = "") -> ToolResult:
        spec = self.registry.get(call.name)
        if spec is None:
            LOGGER.error(f"Tool '{call.name}' is not registered")
            return ToolResult(
                call_id=call.id, name=call.name, ok=False,
                error=f"Tool '{call.name}' is not registered",
            )

        token = active_session_id.set(session_id)
        try:
            self.sandbox.check_tool(call.name)
            started_at = time.perf_counter()
            raw = await asyncio.wait_for(
                spec.execute(dict(call.arguments), session_id),
                timeout=self.sandbox.timeout_seconds,
            )
            latency_ms = int((time.perf_counter() - started_at) * 1000)
            result = self._coerce_result(call, raw, latency_ms=latency_ms)
            if self.enforce_data_status and result.ok:
                validate_tool_output(call.name, result.content)
            return result
        except DataIntegrityError as exc:
            LOGGER.error(f"Data-integrity violation from '{call.name}': {exc}")
            return ToolResult(call_id=call.id, name=call.name, ok=False, error=str(exc))
        except SandboxViolation as exc:
            LOGGER.warning(f"Sandbox violation on '{call.name}': {exc}")
            return ToolResult(call_id=call.id, name=call.name, ok=False, error=str(exc))
        except (TimeoutError, asyncio.TimeoutError):
            LOGGER.error(
                f"Tool '{call.name}' exceeded sandbox limit of {self.sandbox.timeout_seconds}s"
            )
            return ToolResult(
                call_id=call.id, name=call.name, ok=False,
                error=f"Execution exceeded sandbox limit of {self.sandbox.timeout_seconds}s",
            )
        except Exception as exc:  # noqa: BLE001 - boundary logging, never silent
            LOGGER.exception(f"Error executing tool '{call.name}' (call_id: {call.id})")
            return ToolResult(call_id=call.id, name=call.name, ok=False, error=str(exc))
        finally:
            active_session_id.reset(token)

    async def execute_many(self, calls: list[ToolCall], *, session_id: str = "") -> list[ToolResult]:
        return [await self.execute_one(call, session_id=session_id) for call in calls]

    @staticmethod
    def _coerce_result(call: ToolCall, raw: Any, *, latency_ms: int) -> ToolResult:
        if isinstance(raw, ToolResult):
            raw.latency_ms = latency_ms
            return raw
        if isinstance(raw, str):
            content = raw
        else:
            try:
                content = json.dumps(raw, ensure_ascii=False, default=str)
            except (TypeError, ValueError):
                content = str(raw)
        return ToolResult(call_id=call.id, name=call.name, ok=True, content=content,
                          latency_ms=latency_ms)


__all__ = ["ToolExecutor", "active_session_id"]
