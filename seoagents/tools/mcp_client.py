"""MCP bridge (L4) — mount external MCP servers (e.g. dataseo-mcp) as ToolSpecs.

Each remote tool becomes a ``BaseToolSpec`` named ``mcp_{server}_{tool}`` in the
central ToolRegistry. Connections are lazy (first call) over stdio, matching
the manual's L4 "MCP Registry" role. Requires the optional ``mcp`` extra;
without it (or without configured servers) the bridge is a silent no-op.
"""
from __future__ import annotations

import json
from typing import Any

from dojocore.logging import LOGGER
from seoagents.config.models import MCPServerConfig
from seoagents.tools.base import BaseToolSpec, ToolRegistry


class McpProxySpec(BaseToolSpec):
    def __init__(self, server: MCPServerConfig, tool_name: str, description: str,
                 input_schema: dict[str, Any]) -> None:
        self.server = server
        self.tool_name = tool_name
        self.description = description
        self.input_schema = input_schema or {"type": "object", "properties": {}}

    def get_name(self) -> str:
        return f"mcp_{self.server.name}_{self.tool_name}"

    def get_schema(self) -> dict[str, Any]:
        return {
            "name": self.get_name(),
            "description": f"[MCP:{self.server.name}] {self.description}",
            "parameters": self.input_schema,
        }

    async def execute(self, arguments: dict[str, Any], session_id: str) -> str:
        from mcp import ClientSession, StdioServerParameters  # lazy optional import
        from mcp.client.stdio import stdio_client

        params = StdioServerParameters(
            command=self.server.command, args=list(self.server.args), env=dict(self.server.env)
        )
        async with stdio_client(params) as (read, write), ClientSession(read, write) as session:
            await session.initialize()
            result = await session.call_tool(self.tool_name, arguments)
        chunks: list[str] = []
        for block in getattr(result, "content", []) or []:
            text = getattr(block, "text", None)
            chunks.append(text if text is not None else json.dumps(block, default=str))
        return "\n".join(chunks) if chunks else "(empty MCP result)"


async def mount_mcp_servers(registry: ToolRegistry, servers: tuple[MCPServerConfig, ...]) -> int:
    """Discover each configured MCP server's tools and register proxies."""
    if not servers:
        return 0
    try:
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client
    except ImportError:
        LOGGER.warning(
            "mcp package not installed — skipping MCP server mounting "
            "(pip install 'seoagents[mcp]')"
        )
        return 0

    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    mounted = 0
    for server in servers:
        if not server.command:
            continue
        try:
            params = StdioServerParameters(
                command=server.command, args=list(server.args), env=dict(server.env)
            )
            async with stdio_client(params) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    listing = await session.list_tools()
            for tool in listing.tools:
                registry.register(
                    McpProxySpec(server, tool.name, tool.description or "", tool.inputSchema)
                )
                mounted += 1
            LOGGER.info(f"MCP server '{server.name}' mounted with {len(listing.tools)} tools")
        except Exception:  # noqa: BLE001 - a broken server must not break boot
            LOGGER.exception(f"Failed to mount MCP server '{server.name}' — continuing without it")
    return mounted


__all__ = ["McpProxySpec", "mount_mcp_servers"]
