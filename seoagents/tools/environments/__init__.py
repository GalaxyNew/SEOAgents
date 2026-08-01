"""Execution environment adapters (L4) — where heavyweight subprocesses run.

DojoAgents ships Local/Docker/SSH/Modal adapters; SEOAgents implements the
Local adapter (asyncio subprocess with bounded timeout) which the technical
audit sandbox builds upon.
"""
from __future__ import annotations

import abc
import asyncio
import os
from dataclasses import dataclass

from dojocore.logging import LOGGER


@dataclass
class CommandResult:
    returncode: int
    stdout: str
    stderr: str

    @property
    def ok(self) -> bool:
        return self.returncode == 0


class BaseEnvironmentAdapter(abc.ABC):
    @abc.abstractmethod
    async def run(self, cmd: list[str], *, timeout: int, env: dict[str, str] | None = None,
                  cwd: str | None = None) -> CommandResult: ...


class LocalEnvironmentAdapter(BaseEnvironmentAdapter):
    """Runs commands as local subprocesses with a hard timeout."""

    async def run(self, cmd: list[str], *, timeout: int, env: dict[str, str] | None = None,
                  cwd: str | None = None) -> CommandResult:
        LOGGER.info(f"LocalEnv exec: {' '.join(cmd[:4])}{' ...' if len(cmd) > 4 else ''}")
        merged_env = {**os.environ, **(env or {})}
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=merged_env,
            cwd=cwd,
        )
        try:
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout)
        except (TimeoutError, asyncio.TimeoutError):
            process.kill()
            await process.wait()
            raise
        return CommandResult(
            returncode=process.returncode if process.returncode is not None else -1,
            stdout=stdout.decode(errors="replace"),
            stderr=stderr.decode(errors="replace"),
        )


__all__ = ["BaseEnvironmentAdapter", "CommandResult", "LocalEnvironmentAdapter"]
