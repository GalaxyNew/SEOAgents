"""Test the control-tower module API router."""
from __future__ import annotations

import httpx
import pytest

from seoagents.dashboard.server import create_app


@pytest.fixture()
async def client(runtime):
    app = create_app()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


async def test_latest_404_when_no_data(client: httpx.AsyncClient, tmp_path, monkeypatch):
    """When no module data exists, the endpoint returns 404, not a fabricated empty result."""
    monkeypatch.setenv("SEO_CONTROL_TOWER_DATA_DIR", str(tmp_path / "empty"))
    resp = await client.get("/api/control-tower/sites/example.com/modules/gsc/latest")
    assert resp.status_code == 404


async def test_invalid_module_id_returns_422(client: httpx.AsyncClient):
    """An unknown module_id should be rejected at the gate."""
    resp = await client.get("/api/control-tower/sites/example.com/modules/bogus/latest")
    assert resp.status_code == 422


async def test_unconfigured_site_fails_closed(client: httpx.AsyncClient):
    resp = await client.get("/api/control-tower/sites/not-configured.test/modules/gsc/latest")
    assert resp.status_code == 404
    assert "未配置" in resp.text


async def test_write_method_is_not_exposed(client: httpx.AsyncClient):
    resp = await client.post("/api/control-tower/sites/example.com/modules/gsc/latest", json={})
    assert resp.status_code == 405


async def test_head_is_supported_for_read_only_probe(
    client: httpx.AsyncClient, tmp_path, monkeypatch
):
    monkeypatch.setenv("SEO_CONTROL_TOWER_DATA_DIR", str(tmp_path / "empty"))
    resp = await client.head("/api/control-tower/sites/example.com/modules/gsc/history")
    assert resp.status_code == 200
    assert resp.content == b""


async def test_latest_returns_real_data(client: httpx.AsyncClient, tmp_path, monkeypatch):
    """After recording a run, the API returns the standardized result."""
    from dojocore.quality import DataStatus
    from seoagents.control_tower import ControlTowerStore, ModuleRun

    data_dir = tmp_path / "ct"
    monkeypatch.setenv("SEO_CONTROL_TOWER_DATA_DIR", str(data_dir))
    store = ControlTowerStore(data_dir)
    run = ModuleRun(
        site_id="mejorsiptv.shop",
        module_id="gsc",
        business_date="2026-08-07",
        data_status=DataStatus.REAL,
        source="Google Search Console Search Analytics API",
        data_window={"d0": "2026-08-05"},
        cross_validation="单源，未经交叉验证",
        metrics={"clicks": 10},
        known_limitations=("GSC 通常延迟 2–3 日",),
    )
    store.record_attempt(run)

    resp = await client.get("/api/control-tower/sites/mejorsiptv.shop/modules/gsc/latest")
    assert resp.status_code == 200
    body = resp.json()
    assert body["site_id"] == "mejorsiptv.shop"
    assert body["module_id"] == "gsc"
    assert body["data_status"] == "REAL"
    assert body["metrics"]["clicks"] == 10


async def test_history_returns_chronological(client: httpx.AsyncClient, tmp_path, monkeypatch):
    """History should return items sorted by business_date DESC."""
    from dataclasses import replace

    from dojocore.quality import DataStatus
    from seoagents.control_tower import ControlTowerStore, ModuleRun

    data_dir = tmp_path / "ct"
    monkeypatch.setenv("SEO_CONTROL_TOWER_DATA_DIR", str(data_dir))
    store = ControlTowerStore(data_dir)
    base = ModuleRun(
        site_id="mejorsiptv.shop",
        module_id="gsc",
        business_date="2026-08-06",
        data_status=DataStatus.REAL,
        source="test",
        data_window={},
        cross_validation="test",
        metrics={},
    )
    store.record_attempt(base)
    store.record_attempt(replace(base, business_date="2026-08-07"))

    resp = await client.get(
        "/api/control-tower/sites/mejorsiptv.shop/modules/gsc/history?limit=10"
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["count"] == 2
    dates = [item["business_date"] for item in body["items"]]
    assert dates == sorted(dates, reverse=True)


async def test_attempts_cross_site_blocked(client: httpx.AsyncClient, tmp_path, monkeypatch):
    """A request for module_run_id with a mismatched configured site_id must be blocked."""
    from dojocore.quality import DataStatus
    from seoagents.control_tower import ControlTowerStore, ModuleRun

    data_dir = tmp_path / "ct"
    monkeypatch.setenv("SEO_CONTROL_TOWER_DATA_DIR", str(data_dir))
    store = ControlTowerStore(data_dir)
    run = ModuleRun(
        site_id="mejorsiptv.shop",
        module_id="gsc",
        business_date="2026-08-07",
        data_status=DataStatus.REAL,
        source="test",
        data_window={},
        cross_validation="test",
        metrics={},
    )
    saved = store.record_attempt(run)
    mr_id = saved["module_run_id"]

    # Request with a different site_id
    resp = await client.get(
        f"/api/control-tower/sites/example.com/modules/gsc/attempts/{mr_id}"
    )
    assert resp.status_code == 403
