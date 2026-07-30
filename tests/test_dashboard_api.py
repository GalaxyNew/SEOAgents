"""L2 API surface via ASGI test client (no network)."""
from __future__ import annotations

import httpx
import pytest

from seoagents.dashboard.server import create_app


@pytest.fixture()
async def client(runtime):
    # Build the app but do NOT run lifespan (scheduler off in tests).
    app = create_app()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


async def test_healthz(client: httpx.AsyncClient):
    res = await client.get("/healthz")
    assert res.status_code == 200
    assert res.json()["ok"] is True


async def test_metrics_summary_empty_state(client: httpx.AsyncClient):
    res = await client.get("/api/metrics/summary")
    assert res.status_code == 200
    body = res.json()
    assert body["site"] == "https://example.com"
    assert body["provider"] == "mock"
    assert body["latest_m_t"] is None
    assert isinstance(body["skills"], list)


async def test_audit_run_endpoint(client: httpx.AsyncClient):
    res = await client.post("/api/audit/run", json={})
    assert res.status_code == 200
    body = res.json()
    assert body["ok"] is True
    assert body["data"]["mode"] == "demo_snapshot"
    assert body["data"]["dead_link_count"] >= 1


async def test_evolution_then_metrics(client: httpx.AsyncClient):
    res = await client.post("/api/jobs/evolution/run")
    assert res.status_code == 200
    assert res.json()["ok"] is True

    res2 = await client.get("/api/metrics/summary")
    body = res2.json()
    assert body["latest_m_t"] is not None
    assert body["v_t"] is not None
    assert len(body["m_t_history"]) == 1


async def test_config_redacted(client: httpx.AsyncClient):
    res = await client.get("/api/config")
    assert res.status_code == 200
    body = res.json()
    assert "resolved" in body and "redacted" in body
    assert body["resolved"]["provider"] == "mock"
    assert "site_technical_auditor" in body["resolved"]["tools"]


async def test_agent_run_endpoint(client: httpx.AsyncClient):
    res = await client.post("/api/agent/run", json={"task": "审计站点", "role": "auditor"})
    assert res.status_code == 200
    body = res.json()
    assert body["ok"] is True
    assert body["data"]["turns"] >= 1
    assert any(t["tool"] == "site_technical_auditor" for t in body["data"]["trace"])


async def test_index_served(client: httpx.AsyncClient):
    res = await client.get("/")
    assert res.status_code == 200
    assert "SEOAgents" in res.text


async def test_config_update_endpoint(client: httpx.AsyncClient):
    patch = {
        "sites": {"brand_name": "TestBrand", "tracked_keywords": ["seo", "aeo"]},
        "scoring": {"alpha": 0.5},
    }
    res = await client.post("/api/config", json=patch)
    assert res.status_code == 200
    body = res.json()
    assert body["ok"] is True
    assert body["resolved"]["scoring"]["alpha"] == 0.5
    assert body["resolved"]["tracked_keywords"] == ["seo", "aeo"]

