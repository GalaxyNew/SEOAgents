"""Tool catalog — the capability landscape, including what is NOT installed."""
from __future__ import annotations

import httpx
import pytest

from seoagents.dashboard.server import create_app
from seoagents.plugins.catalog_loader import (
    CatalogStatus,
    DeployMode,
    estimate_footprint,
    load_catalog,
)


def test_catalog_covers_all_twelve_manual_tools():
    entries = load_catalog()
    assert len(entries) >= 12


def test_unfindable_tools_are_kept_and_flagged():
    """Named in the manual, found nowhere.

    They stay in the catalog on purpose: deleting them would quietly erase the
    gap between what the design document claims and what exists.
    """
    missing = {e.id for e in load_catalog() if e.status is CatalogStatus.NOT_FOUND}
    assert missing == {"rankwise", "claude_seo", "searchstack_aeo"}
    for entry in load_catalog():
        if entry.status is CatalogStatus.NOT_FOUND:
            assert entry.caveats, f"{entry.id} 必须写明为何不可用"
            assert not entry.installable


def test_known_deployment_traps_are_recorded():
    """The caveats are the point: they are read before install, not after."""
    seonaut = next(e for e in load_catalog() if e.id == "seonaut")
    caveats = " ".join(seonaut.caveats)
    assert "GHCR" in caveats                      # wrong registry in the manual
    assert "SEONAUT_DATABASE_" in caveats         # wrong env var names


def test_remote_and_saas_modes_cost_nothing_locally():
    """A modest box can still offer the whole capability map."""
    hosted = estimate_footprint(
        [{"id": "dataforseo", "mode": "hosted_saas"}, {"id": "lighthouse", "mode": "hosted_saas"}]
    )
    assert hosted["delta_memory_mb"] == 0

    local = estimate_footprint(
        [{"id": "seonaut", "mode": "local_docker"}, {"id": "lighthouse", "mode": "local_docker"}]
    )
    assert local["delta_memory_mb"] > 2000


def test_openserp_can_run_off_box():
    entry = next(e for e in load_catalog() if e.id == "openserp")
    assert DeployMode.REMOTE_HTTP in entry.deploy_modes
    assert entry.footprint(DeployMode.REMOTE_HTTP)["memory_mb"] == 0


@pytest.fixture()
async def client(runtime):
    app = create_app()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


async def test_catalog_endpoints(client: httpx.AsyncClient):
    res = await client.get("/api/catalog")
    assert res.status_code == 200
    body = res.json()
    assert body["total"] >= 12
    assert all("installed" in item for item in body["items"])

    # Detail works for a tool that is not installed — that is the whole point.
    res = await client.get("/api/catalog/seonaut")
    assert res.status_code == 200
    detail = res.json()
    assert detail["homepage"]
    assert detail["what_it_does"]
    assert detail["caveats"]

    res = await client.get("/api/capabilities")
    caps = res.json()
    assert "serp_rank" in caps
    assert set(caps["serp_rank"]) >= {"installed", "comparable", "single_source_risk"}
