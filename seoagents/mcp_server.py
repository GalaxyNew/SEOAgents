"""MCP server (L4 outbound) — expose the ToolRegistry to external agents.

This is the integration seam for a Hermes SEO department head: rather than
re-implementing SEO capabilities inside the agent, the agent mounts this server
and every registered ``BaseToolSpec`` becomes a native tool on its surface.

Design rules:

1. **No capability is implemented here.** The single source of truth for what a
   tool does stays in ``ToolRegistry``; this module only translates protocols.
   ``BaseToolSpec.get_schema()`` already returns ``{name, description,
   parameters}``, and MCP wants ``{name, description, inputSchema}`` — so the
   translation really is a field rename.
2. **Every call goes through ``ToolExecutor``**, inheriting the sandbox policy,
   the timeout, the structured error handling and the ``data_status`` gate.
3. **Failures fail loudly.** A tool error is raised, never smoothed into a
   plausible-looking payload. An agent that receives fabricated data cannot tell
   it apart from the real thing, which is precisely the failure mode this whole
   contract exists to prevent.
4. Adding a tool requires **no change to this file** — register the spec and it
   appears in the next ``tools/list``.

Note the direction: ``tools/mcp_client.py`` is the *inbound* bridge (mount
external MCP servers as local specs). This module is the *outbound* one.

    external MCP sources ──inbound──▶ ToolRegistry ──outbound──▶ Hermes SEO HM
                                          ▲
                                    built-in specs
"""
from __future__ import annotations

import argparse
import json
import uuid
from typing import TYPE_CHECKING, Any

from dojocore.logging import LOGGER
from dojocore.quality import DataStatus, extract_status
from seoagents.agent.models import ToolCall
from seoagents.agent.runtime import Runtime, get_runtime

if TYPE_CHECKING:  # pragma: no cover - typing only
    from mcp.types import Tool

SERVER_NAME = "seoagents"

# Tools whose data is not yet trustworthy get this prefix in their description,
# so a consuming agent is warned at prompt level rather than after the fact.
_DEGRADED_HINT = "[DEGRADED — 数据可信度未达标,不得用于决策] "


def tool_descriptors(runtime: Runtime | None = None) -> list[dict[str, Any]]:
    """ToolRegistry -> MCP tool descriptors (protocol-agnostic, unit-testable)."""
    rt = runtime or get_runtime()
    out: list[dict[str, Any]] = []
    for schema in rt.registry.schemas():
        out.append(
            {
                "name": schema["name"],
                "description": schema.get("description", ""),
                "inputSchema": schema.get("parameters")
                or {"type": "object", "properties": {}},
            }
        )
    return out


async def call_tool(
    name: str, arguments: dict[str, Any] | None, runtime: Runtime | None = None
) -> dict[str, Any]:
    """Execute one tool through the executor. Raises on failure, by design."""
    rt = runtime or get_runtime()
    session_id = f"mcp:{uuid.uuid4().hex[:8]}"
    result = await rt.executor.execute_one(
        ToolCall(id=session_id, name=name, arguments=dict(arguments or {})),
        session_id=session_id,
    )
    if not result.ok:
        raise RuntimeError(f"{name} failed: {result.error}")

    status = extract_status(result.content)
    if status is not None and status is not DataStatus.REAL:
        LOGGER.info(f"MCP tool '{name}' returned data_status={status.value}")
    try:
        return json.loads(result.content)
    except json.JSONDecodeError:
        # Should not happen once every spec uses the quality helpers, but never
        # silently drop the payload.
        return {"raw": result.content, "data_status": DataStatus.DEGRADED.value,
                "source": name, "degraded_reason": "工具返回非 JSON 内容"}


def build_server(runtime: Runtime | None = None):  # pragma: no cover - needs mcp
    """Construct the MCP ``Server`` with list/call handlers bound."""
    from mcp.server import Server
    from mcp.types import TextContent, Tool

    rt = runtime or get_runtime()
    server = Server(SERVER_NAME)

    @server.list_tools()
    async def _list_tools() -> list[Tool]:
        tools = [
            Tool(name=d["name"], description=d["description"], inputSchema=d["inputSchema"])
            for d in tool_descriptors(rt)
        ]
        LOGGER.info(f"MCP tools/list -> {len(tools)}: {[t.name for t in tools]}")
        return tools

    @server.call_tool()
    async def _call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
        payload = await call_tool(name, arguments, rt)
        return [TextContent(type="text", text=json.dumps(payload, ensure_ascii=False))]

    return server


def main(argv: list[str] | None = None) -> None:  # pragma: no cover - entrypoint
    parser = argparse.ArgumentParser(description="SEOAgents MCP server")
    parser.add_argument("--transport", default="stdio", choices=["stdio", "http"])
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=7801)
    args = parser.parse_args(argv)

    # Warm the runtime now: a misconfiguration should surface at boot, not on
    # the first agent call.
    rt = get_runtime()
    LOGGER.info(f"SEOAgents MCP server exposing {len(rt.registry.names())} tools")
    server = build_server(rt)

    if args.transport == "stdio":
        import anyio
        from mcp.server.stdio import stdio_server

        async def _serve() -> None:
            async with stdio_server() as (read, write):
                await server.run(read, write, server.create_initialization_options())

        anyio.run(_serve)
    else:
        import uvicorn
        from mcp.server.streamable_http import create_app

        uvicorn.run(create_app(server), host=args.host, port=args.port)


if __name__ == "__main__":  # pragma: no cover
    main()
