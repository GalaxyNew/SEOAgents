"""Department registry — where the 'how to reach them' complexity lives.

Composing a pipeline should mean picking a department and saying what you need.
Endpoints, service tokens and auth headers are operational configuration, not
something the person designing a workflow should have to think about.

Capabilities are fetched live from each department's ``/api/v1/capabilities``
and cached briefly, so a node editor can list exactly what that department can
currently accept — including what it *cannot* do and why.
"""
from __future__ import annotations

import os
import time
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

import httpx

from dojocore.logging import LOGGER

__all__ = ["Department", "DepartmentRegistry"]

_CACHE_TTL = 300.0


@dataclass(frozen=True)
class Department:
    id: str
    display_name: str
    endpoint: str = ""
    access_client_id_env: str = ""
    access_client_secret_env: str = ""
    enabled: bool = True
    note: str = ""

    def auth_headers(self) -> dict[str, str]:
        """Cloudflare Access service-token headers.

        Machine-to-machine: an agent cannot complete an email one-time-PIN
        flow, so cross-department calls must use service tokens.
        """
        cid = os.environ.get(self.access_client_id_env, "")
        sec = os.environ.get(self.access_client_secret_env, "")
        if not (cid and sec):
            return {}
        return {"CF-Access-Client-Id": cid, "CF-Access-Client-Secret": sec}

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id, "display_name": self.display_name,
            "endpoint": self.endpoint, "enabled": self.enabled,
            "reachable": bool(self.endpoint), "note": self.note,
            "has_credentials": bool(self.auth_headers()),
        }


class DepartmentRegistry:
    def __init__(self, departments: Mapping[str, Department] | None = None) -> None:
        self._depts: dict[str, Department] = dict(departments or {})
        self._cache: dict[str, tuple[float, list[dict[str, Any]]]] = {}

    # -- registration ------------------------------------------------------
    def register(self, dept: Department) -> None:
        self._depts[dept.id] = dept
        LOGGER.info(f"department registered: {dept.id} → {dept.endpoint or '(no endpoint)'}")

    def get(self, dept_id: str) -> Department | None:
        return self._depts.get(dept_id)

    def list(self, *, enabled_only: bool = True) -> list[Department]:
        out = [d for d in self._depts.values() if d.enabled or not enabled_only]
        return sorted(out, key=lambda d: d.id)

    @classmethod
    def from_config(cls, raw: Mapping[str, Any] | None) -> DepartmentRegistry:
        reg = cls()
        for item in (raw or {}).get("departments", []) or []:
            reg.register(
                Department(
                    id=str(item["id"]),
                    display_name=str(item.get("display_name", item["id"])),
                    endpoint=str(item.get("endpoint", "")).rstrip("/"),
                    access_client_id_env=str(item.get("access_client_id_env", "")),
                    access_client_secret_env=str(item.get("access_client_secret_env", "")),
                    enabled=bool(item.get("enabled", True)),
                    note=str(item.get("note", "")),
                )
            )
        return reg

    # -- capability discovery ---------------------------------------------
    async def capabilities(
        self, dept_id: str, *, force: bool = False
    ) -> dict[str, Any]:
        """What that department can currently be asked to do.

        Never guesses: an unreachable department returns an explicit error
        rather than a stale or invented capability list, because a node
        configured against a capability that does not exist will simply BLOCK
        later — at which point the pipeline is already running.
        """
        dept = self.get(dept_id)
        if dept is None:
            return {"error": f"未注册的部门 '{dept_id}'", "capabilities": []}
        if not dept.endpoint:
            return {
                "error": f"部门 '{dept_id}' 尚未联邦化(无 endpoint);"
                         f"过渡期请走指挥台垫片",
                "capabilities": [], "transitional": True,
            }

        now = time.time()
        if not force and dept_id in self._cache:
            ts, cached = self._cache[dept_id]
            if now - ts < _CACHE_TTL:
                return {"dept": dept_id, "capabilities": cached, "cached": True}

        url = f"{dept.endpoint}/api/v1/capabilities"
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(url, headers=dept.auth_headers())
                resp.raise_for_status()
                payload = resp.json()
        except Exception as exc:  # noqa: BLE001 - network boundary
            LOGGER.warning(f"capability discovery failed for {dept_id}: {exc}")
            return {"error": f"无法获取 '{dept_id}' 的能力清单: {exc}", "capabilities": []}

        caps = payload.get("capabilities", [])
        self._cache[dept_id] = (now, caps)
        return {"dept": dept_id, "capabilities": caps, "cached": False}

    async def acceptable_capabilities(self, dept_id: str) -> list[dict[str, Any]]:
        """Only the capabilities that department will actually accept right now."""
        result = await self.capabilities(dept_id)
        return [c for c in result.get("capabilities", []) if c.get("accepts_external")]
