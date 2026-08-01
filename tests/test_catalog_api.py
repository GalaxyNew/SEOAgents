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


async def test_capability_discovery_refuses_what_has_no_installed_provider(
    client: httpx.AsyncClient,
):
    """A capability whose providers are merely *installable* must not be offered.

    This shipped inverted: the filter asked `installable` ("could this be
    installed?") rather than "is it installed?", so the department advertised
    keyword_research, backlink and aeo_visibility to every other department
    while no provider was present. A request would be accepted and then BLOCK —
    precisely the outcome the collaboration protocol exists to avoid. Declining
    up front is the cheaper failure.
    """
    caps = (await client.get("/api/v1/capabilities")).json()["capabilities"]
    assert caps

    for cap in caps:
        if cap["accepts_external"]:
            assert cap["providers"], (
                f"'{cap['id']}' accepts external work with no installed provider — "
                "the advertise-then-BLOCK bug"
            )
        else:
            assert cap.get("reason"), f"'{cap['id']}' declines without saying why"

    # "Nobody implements this" and "the provider just isn't installed" are both
    # refusals, but they call for different actions, so they must read
    # differently — otherwise nobody can tell impossible from one install away.
    by_id = {c["id"]: c for c in caps}
    nothing_provides = [c for c in caps if not c["accepts_external"]
                        and not c.get("installable_providers")]
    not_installed = [c for c in caps if not c["accepts_external"]
                     and c.get("installable_providers")]
    assert nothing_provides and not_installed, (
        "fixture no longer exercises both refusal kinds; the distinction is the point"
    )
    assert nothing_provides[0]["reason"] != not_installed[0]["reason"]
    assert "internal_link" in by_id


async def test_capability_discovery_and_catalog_agree_on_installed(
    client: httpx.AsyncClient,
):
    """Both endpoints must decide 'installed' from one shared source.

    They each carried their own copy of the spec→catalog mapping, so the
    catalog could call a tool absent while capability discovery implied it was
    usable. Same question, two answers.
    """
    installed = {
        e["id"] for e in (await client.get("/api/catalog")).json()["items"] if e["installed"]
    }
    for cap in (await client.get("/api/v1/capabilities")).json()["capabilities"]:
        assert set(cap["providers"]) <= installed, (
            f"'{cap['id']}' lists a provider the catalog does not consider installed"
        )
