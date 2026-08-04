"""SandboxPolicy (L4) — physical & network constraints for tool execution.

All tool invocations flow through ``ToolExecutor`` which consults this policy;
bypassing it is an architectural violation (DojoAgents guardrail).
"""
from __future__ import annotations

from urllib.parse import urlparse

from dojocore.logging import LOGGER
from dojocore.config.models import SandboxConfig


class SandboxViolation(RuntimeError):
    """Raised when a tool call breaches sandbox policy."""


class SandboxPolicy:
    def __init__(self, config: SandboxConfig) -> None:
        self._config = config
        self.timeout_seconds = config.execution_timeout_seconds
        self._denied_tools = set(config.denied_tools)
        self._allowed_hosts = set(config.allow_network_hosts)

    @property
    def restricted_builtins(self) -> bool:
        return self._config.restricted_builtins

    def check_tool(self, name: str) -> None:
        if name in self._denied_tools:
            LOGGER.warning(f"Sandbox denied tool call: {name}")
            raise SandboxViolation(f"Tool '{name}' is denied by sandbox policy")

    def is_host_allowed(self, url_or_host: str) -> bool:
        host = url_or_host
        if "://" in url_or_host:
            host = urlparse(url_or_host).hostname or ""
        if not host:
            return False
        if host in self._allowed_hosts:
            return True
        # suffix match: allowing "example.com" also allows "www.example.com"
        return any(host == allowed or host.endswith("." + allowed) for allowed in self._allowed_hosts)

    def check_host(self, url_or_host: str) -> None:
        if not self.is_host_allowed(url_or_host):
            raise SandboxViolation(
                f"Network host not allowed by sandbox policy: {url_or_host}. "
                f"Add it to sandbox.allow_network_hosts in agents.yaml."
            )

    def allow_host(self, host: str) -> None:
        """Runtime-scoped extension (e.g. the audited site itself)."""
        self._allowed_hosts.add(host)


__all__ = ["SandboxPolicy", "SandboxViolation"]
