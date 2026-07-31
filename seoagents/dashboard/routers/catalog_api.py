"""Tool catalog API (L2) — the capability landscape, installed or not.

Backs a dashboard that shows every known tool as a card. Installed tools render
live data; uninstalled ones render as placeholders you can click to see what the
tool does, what it would cost locally, and what is known to be wrong with it.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from seoagents.agent.runtime import get_runtime
from seoagents.plugins.capabilities import Capability
from seoagents.plugins.catalog_loader import (
    capability_map,
    estimate_footprint,
    load_catalog,
)

router = APIRouter(prefix="/api", tags=["catalog"])

# Which registered ToolSpec satisfies which catalog entry. Until the full plugin
# contract lands, this mapping is what lets the UI mark a card "installed".
_SPEC_TO_CATALOG: dict[str, str] = {
    "google_seo_monitor": "google_search_console",
    "serp_rank_tracker": "openserp",
    "site_technical_auditor": "python_seo_analyzer",
    "lighthouse_audit": "lighthouse",
    "gsc_indexing_ops": "google_search_console",
}


def _installed_ids() -> set[str]:
    try:
        names = set(get_runtime().registry.names())
    except Exception:  # noqa: BLE001 - catalog must render even without a runtime
        return set()
    installed = {cid for spec, cid in _SPEC_TO_CATALOG.items() if spec in names}
    # MCP-mounted providers appear as mcp_<server>_<tool>
    if any(n.startswith("mcp_dataforseo") for n in names):
        installed.add("dataforseo")
    return installed


@router.get("/catalog")
async def list_catalog() -> dict[str, Any]:
    """Every known tool with its install state."""
    installed = _installed_ids()
    entries = load_catalog()
    return {
        "total": len(entries),
        "installed_count": len(installed),
        "items": [{**e.to_dict(), "installed": e.id in installed} for e in entries],
    }


@router.get("/catalog/{entry_id}")
async def get_catalog_entry(entry_id: str) -> dict[str, Any]:
    """Detail for one tool — works whether or not it is installed."""
    entry = next((e for e in load_catalog() if e.id == entry_id), None)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"unknown catalog entry '{entry_id}'")
    installed = _installed_ids()
    peers = [
        e.to_dict()
        for e in load_catalog()
        if e.id != entry.id and set(e.capabilities) & set(entry.capabilities)
    ]
    return {
        **entry.to_dict(),
        "installed": entry.id in installed,
        "same_capability_tools": peers,
        "comparable_after_install": [p["id"] for p in peers if p["id"] in installed],
    }


@router.get("/capabilities")
async def list_capabilities() -> dict[str, Any]:
    """Capability -> tools, flagging single-source risk.

    A capability served by exactly one installed tool cannot be cross-checked;
    conclusions drawn from it must say so.
    """
    installed = _installed_ids()
    grouped = capability_map()
    out: dict[str, Any] = {}
    for cap in Capability:
        tools = grouped.get(cap.value, [])
        usable = [t for t in tools if t.installable]
        inst = [t.id for t in usable if t.id in installed]
        out[cap.value] = {
            "label": cap.label,
            "installed": inst,
            "available_to_install": [t.id for t in usable if t.id not in installed],
            "unavailable": [t.id for t in tools if not t.installable],
            "comparable": len(inst) > 1,
            "single_source_risk": len(inst) == 1,
            "uncovered": len(inst) == 0,
        }
    return out


class FootprintPlanItem(BaseModel):
    id: str
    mode: str | None = None


class FootprintPlanRequest(BaseModel):
    plan: list[FootprintPlanItem] = Field(default_factory=list)


@router.post("/resources/estimate")
async def estimate_resources(request: FootprintPlanRequest) -> dict[str, Any]:
    """Local memory/disk cost of a proposed install plan.

    Makes the deploy-mode decision answerable in the UI instead of discovered
    later through an out-of-memory kill: SaaS and remote modes cost 0 locally.
    """
    return estimate_footprint([item.model_dump() for item in request.plan])


__all__ = ["router"]
