"""Tool catalog — the capability map, including tools that are NOT installed.

The dashboard shows a *capability landscape*, not an inventory of what happens
to be installed today. A tool that is not installed still gets a card; it is
simply in a different state, and clicking it explains what the tool does, what
it costs, how it can be deployed, and what is known to be wrong with it.

Three reasons this matters:

* You can see at a glance what is still missing.
* Nothing has to be installed all at once — pick tools when you need them.
* It is honest. The source manual claimed twelve open-source tools were
  "seamlessly integrated"; two actually were. A placeholder card keeps that gap
  visible instead of letting a document assert a capability that does not exist.

Catalog entries are pure data (``catalog/builtin.yaml`` plus an optional
user-supplied override file), so reserving a slot for a future tool costs
nothing and requires no code.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

import yaml

from dojocore.capability import Capability, capabilities
from dojocore.logging import LOGGER

_BUILTIN_CATALOG = Path(__file__).parent / "catalog" / "builtin.yaml"


class DeployMode(str, Enum):
    """How a tool can be run. Not every tool has to live on this machine."""

    HOSTED_SAAS = "hosted_saas"    # credentials only, zero deployment
    REMOTE_HTTP = "remote_http"    # point at an endpoint elsewhere
    LOCAL_PIP = "local_pip"        # installed into this Python environment
    LOCAL_DOCKER = "local_docker"  # container on this host

    @property
    def uses_local_resources(self) -> bool:
        return self in (DeployMode.LOCAL_PIP, DeployMode.LOCAL_DOCKER)


class CatalogStatus(str, Enum):
    AVAILABLE = "available"      # verified to exist and be usable
    UNVERIFIED = "unverified"    # exists, but not validated for this project
    NOT_FOUND = "not_found"      # named in the manual, no trace of it anywhere
    DEPRECATED = "deprecated"


@dataclass(frozen=True)
class CatalogEntry:
    id: str
    display_name: str
    capabilities: tuple[Capability, ...] = ()
    summary: str = ""
    homepage: str = ""
    license: str = ""
    popularity: str = ""
    what_it_does: tuple[str, ...] = ()
    deploy_modes: tuple[DeployMode, ...] = ()
    recommended_mode: DeployMode | None = None
    cost: str = "free"
    memory_mb: int = 0            # local footprint at peak, 0 when remote/SaaS
    disk_mb: int = 0
    caveats: tuple[str, ...] = ()
    status: CatalogStatus = CatalogStatus.AVAILABLE
    verified_at: str = ""
    replaces: tuple[str, ...] = ()
    notes: str = ""
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def installable(self) -> bool:
        return self.status in (CatalogStatus.AVAILABLE, CatalogStatus.UNVERIFIED)

    def footprint(self, mode: DeployMode | None = None) -> dict[str, int]:
        """Local resource cost for a given deploy mode.

        Remote and SaaS modes cost nothing locally — which is exactly how a
        modest box can still offer the full capability map.
        """
        chosen = mode or self.recommended_mode
        if chosen is None or not chosen.uses_local_resources:
            return {"memory_mb": 0, "disk_mb": 0}
        return {"memory_mb": self.memory_mb, "disk_mb": self.disk_mb}

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "display_name": self.display_name,
            "capabilities": [c.id for c in self.capabilities],
            "capability_labels": [c.label for c in self.capabilities],
            "summary": self.summary,
            "homepage": self.homepage,
            "license": self.license,
            "popularity": self.popularity,
            "what_it_does": list(self.what_it_does),
            "deploy_modes": [m.value for m in self.deploy_modes],
            "recommended_mode": self.recommended_mode.value if self.recommended_mode else None,
            "cost": self.cost,
            "memory_mb": self.memory_mb,
            "disk_mb": self.disk_mb,
            "caveats": list(self.caveats),
            "status": self.status.value,
            "verified_at": self.verified_at,
            "replaces": list(self.replaces),
            "notes": self.notes,
            "installable": self.installable,
        }


def _coerce(raw: dict[str, Any]) -> CatalogEntry:
    caps: list[Capability] = []
    for c in raw.get("capabilities", []) or []:
        if capabilities.has(str(c)):
            caps.append(capabilities.get(str(c)))
        else:
            LOGGER.warning(
                f"catalog entry '{raw.get('id')}': 能力 '{c}' 未被任何部门注册,已跳过"
            )
    modes = []
    for m in raw.get("deploy_modes", []) or []:
        try:
            modes.append(DeployMode(m))
        except ValueError:
            LOGGER.warning(f"catalog entry '{raw.get('id')}': unknown deploy mode '{m}', skipped")
    rec = raw.get("recommended_mode")
    try:
        recommended = DeployMode(rec) if rec else None
    except ValueError:
        recommended = None
    try:
        status = CatalogStatus(raw.get("status", "available"))
    except ValueError:
        status = CatalogStatus.UNVERIFIED
    known = {
        "id", "display_name", "capabilities", "summary", "homepage", "license", "popularity",
        "what_it_does", "deploy_modes", "recommended_mode", "cost", "memory_mb", "disk_mb",
        "caveats", "status", "verified_at", "replaces", "notes",
    }
    return CatalogEntry(
        id=str(raw["id"]),
        display_name=str(raw.get("display_name", raw["id"])),
        capabilities=tuple(caps),
        summary=str(raw.get("summary", "")),
        homepage=str(raw.get("homepage", "")),
        license=str(raw.get("license", "")),
        popularity=str(raw.get("popularity", "")),
        what_it_does=tuple(raw.get("what_it_does", []) or []),
        deploy_modes=tuple(modes),
        recommended_mode=recommended,
        cost=str(raw.get("cost", "free")),
        memory_mb=int(raw.get("memory_mb", 0) or 0),
        disk_mb=int(raw.get("disk_mb", 0) or 0),
        caveats=tuple(raw.get("caveats", []) or []),
        status=status,
        verified_at=str(raw.get("verified_at", "")),
        replaces=tuple(raw.get("replaces", []) or []),
        notes=str(raw.get("notes", "")),
        extra={k: v for k, v in raw.items() if k not in known},
    )


def load_catalog(extra_path: str | os.PathLike[str] | None = None) -> list[CatalogEntry]:
    """Built-in catalog, with optional user overrides merged in by ``id``."""
    entries: dict[str, CatalogEntry] = {}
    for path in (_BUILTIN_CATALOG, Path(os.path.expanduser(str(extra_path))) if extra_path else None):
        if path is None or not path.exists():
            continue
        try:
            raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except yaml.YAMLError as exc:
            LOGGER.error(f"catalog file unparseable, skipped: {path} ({exc})")
            continue
        for item in raw.get("tools", []) or []:
            try:
                entry = _coerce(item)
            except (KeyError, TypeError) as exc:
                LOGGER.error(f"catalog entry malformed in {path}, skipped: {exc}")
                continue
            entries[entry.id] = entry
    return sorted(entries.values(), key=lambda e: (e.status.value, e.id))


def capability_map(entries: list[CatalogEntry] | None = None) -> dict[str, list[CatalogEntry]]:
    """Group catalog entries by capability, for the dashboard's sections."""
    catalog = entries if entries is not None else load_catalog()
    grouped: dict[str, list[CatalogEntry]] = {c.id: [] for c in capabilities.list()}
    for entry in catalog:
        for cap in entry.capabilities:
            grouped.setdefault(cap.id, []).append(entry)
    return grouped


def estimate_footprint(plan: list[dict[str, str]]) -> dict[str, Any]:
    """Local memory/disk cost of a proposed set of ``{id, mode}`` choices.

    Lets the deployment decision be made in the UI ("what will this cost me?")
    rather than discovered later through an out-of-memory kill.
    """
    by_id = {e.id: e for e in load_catalog()}
    total_mem = total_disk = 0
    breakdown = []
    for item in plan:
        entry = by_id.get(item.get("id", ""))
        if entry is None:
            continue
        try:
            mode = DeployMode(item["mode"]) if item.get("mode") else entry.recommended_mode
        except ValueError:
            mode = entry.recommended_mode
        fp = entry.footprint(mode)
        total_mem += fp["memory_mb"]
        total_disk += fp["disk_mb"]
        breakdown.append(
            {"id": entry.id, "mode": mode.value if mode else None, **fp}
        )
    return {"delta_memory_mb": total_mem, "delta_disk_mb": total_disk, "breakdown": breakdown}


__all__ = [
    "CatalogEntry",
    "CatalogStatus",
    "DeployMode",
    "capability_map",
    "estimate_footprint",
    "load_catalog",
]
