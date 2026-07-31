"""L4 executor — golden pattern: lookup, sandbox, timeout, coercion."""
from __future__ import annotations

import asyncio
from typing import Any

import pytest

from seoagents.agent.models import ToolCall
from seoagents.config.models import SandboxConfig
from seoagents.quality import real
from seoagents.tools.base import BaseToolSpec, ToolRegistry
from seoagents.tools.environments.sandbox import SandboxPolicy
from seoagents.tools.executor import ToolExecutor, active_session_id


class _EchoSpec(BaseToolSpec):
    def get_name(self) -> str:
        return "echo"

    def get_schema(self) -> dict[str, Any]:
        return {"name": "echo", "description": "", "parameters": {"type": "object", "properties": {}}}

    async def execute(self, arguments: dict[str, Any], session_id: str) -> dict[str, Any]:
        return real({"echo": arguments.get("msg", ""), "session": active_session_id.get()}, source="echo")


class _SlowSpec(BaseToolSpec):
    def get_name(self) -> str:
        return "slow"

    def get_schema(self) -> dict[str, Any]:
        return {"name": "slow", "description": "", "parameters": {"type": "object", "properties": {}}}

    async def execute(self, arguments: dict[str, Any], session_id: str) -> str:
        await asyncio.sleep(5)
        return "never"


@pytest.fixture()
def executor() -> ToolExecutor:
    registry = ToolRegistry()
    registry.register(_EchoSpec())
    registry.register(_SlowSpec())
    sandbox = SandboxPolicy(SandboxConfig(execution_timeout_seconds=1, denied_tools=("forbidden",)))
    return ToolExecutor(registry, sandbox)


async def test_ok_path_coerces_dict_and_propagates_session(executor: ToolExecutor):
    res = await executor.execute_one(ToolCall(name="echo", arguments={"msg": "hi"}), session_id="s1")
    assert res.ok
    assert '"echo": "hi"' in res.content
    assert '"session": "s1"' in res.content
    assert res.latency_ms >= 0


async def test_unregistered_tool(executor: ToolExecutor):
    res = await executor.execute_one(ToolCall(name="nope"))
    assert not res.ok
    assert "not registered" in res.error


async def test_timeout_enforced(executor: ToolExecutor):
    res = await executor.execute_one(ToolCall(name="slow"))
    assert not res.ok
    assert "exceeded sandbox limit" in res.error


async def test_denied_tool_blocked(executor: ToolExecutor):
    executor.registry.register(_denied())
    res = await executor.execute_one(ToolCall(name="forbidden"))
    assert not res.ok
    assert "denied by sandbox policy" in res.error


def _denied() -> BaseToolSpec:
    class _D(BaseToolSpec):
        def get_name(self) -> str:
            return "forbidden"

        def get_schema(self) -> dict[str, Any]:
            return {"name": "forbidden", "description": "", "parameters": {}}

        async def execute(self, arguments: dict[str, Any], session_id: str) -> str:
            return "x"

    return _D()


def test_duplicate_registration_rejected():
    registry = ToolRegistry()
    registry.register(_EchoSpec())
    with pytest.raises(ValueError):
        registry.register(_EchoSpec())


def test_sandbox_host_allowlist():
    sandbox = SandboxPolicy(SandboxConfig(allow_network_hosts=("example.com", "localhost")))
    assert sandbox.is_host_allowed("https://example.com/page")
    assert sandbox.is_host_allowed("https://www.example.com/x")
    assert not sandbox.is_host_allowed("https://evil.com")
    sandbox.allow_host("evil.com")
    assert sandbox.is_host_allowed("https://evil.com")
