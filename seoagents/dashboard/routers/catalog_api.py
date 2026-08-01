"""Tool catalog API (L2) — the capability landscape, installed or not.

Backs a dashboard that shows every known tool as a card. Installed tools render
live data; uninstalled ones render as placeholders you can click to see what the
tool does, what it would cost locally, and what is known to be wrong with it.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from dojocore.capability import capabilities as _caps
from seoagents.plugins.catalog_loader import (
    capability_map,
    estimate_footprint,
    load_catalog,
)
from seoagents.plugins.catalog_loader import (
    installed_ids as _installed_ids,
)

router = APIRouter(prefix="/api", tags=["catalog"])

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
        if e.id != entry.id and {c.id for c in e.capabilities} & {c.id for c in entry.capabilities}
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
    for cap in _caps.list():
        tools = grouped.get(cap.id, [])
        usable = [t for t in tools if t.installable]
        inst = [t.id for t in usable if t.id in installed]
        out[cap.id] = {
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
