"""Security and projection tests for the public SEO Control Tower surface."""
from __future__ import annotations

import copy
import json
import sqlite3
from pathlib import Path

import httpx
import pytest

from seoagents.dashboard.routers import public_seo_control_tower as tower
from seoagents.dashboard.server import create_app


@pytest.fixture()
async def anonymous_client(runtime, monkeypatch):
    """Undo the suite-wide cookie injector for this client only."""
    app = create_app()
    transport = httpx.ASGITransport(app=app)
    wrapper = httpx.AsyncClient.request
    closure = {
        name: cell.cell_contents
        for name, cell in zip(wrapper.__code__.co_freevars, wrapper.__closure__ or ())
    }
    original_request = closure["orig"]
    monkeypatch.setattr(httpx.AsyncClient, "request", original_request)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


@pytest.fixture()
def tower_snapshots(tmp_path: Path, monkeypatch) -> dict[str, Path]:
    official = {
        "site": "https://mejorsiptv.shop",
        "credentials": "must-never-leak",
        "gsc": {
            "data_status": "REAL", "d0": "2026-08-04", "d1": "2026-08-03",
            "ranges": {"cur30": ["2026-07-06", "2026-08-04"]},
            "global": {
                "d0": {"clicks": 1, "impressions": 19, "ctr": .0526, "position": 37.9},
                "d1": {"clicks": 1, "impressions": 14, "ctr": .0714, "position": 38.9},
                "cur7": {"clicks": 3, "impressions": 61, "ctr": .049, "position": 28.3},
                "prev7": {"clicks": 10, "impressions": 161, "ctr": .062, "position": 3.4},
                "cur30": {"clicks": 18, "impressions": 258, "ctr": .0698, "position": 10.2},
                "prev30": None,
            },
            "dimensions": {"cur30": {"date": [
                {"keys": ["2026-08-03"], "clicks": 1, "impressions": 14, "ctr": .0714, "position": 38.9},
                {"keys": ["2026-08-04"], "clicks": 0, "impressions": 0, "ctr": 0, "position": 0},
            ]}},
        },
        "ga4": {
            "data_status": "REAL", "property": "secret-property", "d0": "2026-08-05", "d1": "2026-08-04",
            "hostnames": [{"hostName": "mejorsiptv.shop", "sessions": "26"}],
            "ranges": {"cur7": ["2026-07-30", "2026-08-05"]},
            "totals": {
                "d0": [{"sessions": "10", "totalUsers": "6", "newUsers": "4", "engagedSessions": "0", "engagementRate": "0", "keyEvents": "0", "screenPageViews": "11"}],
                "d1": [{"sessions": "4", "totalUsers": "4", "newUsers": "3", "engagedSessions": "1", "engagementRate": ".25", "keyEvents": "0", "screenPageViews": "6"}],
                "cur7": [{"sessions": "26", "totalUsers": "18", "newUsers": "17", "engagedSessions": "3", "engagementRate": ".115", "keyEvents": "0", "screenPageViews": "48"}],
                "prev7": [], "cur30": [], "prev30": [],
            },
            "dimensions": {"cur7": {
                "sessionDefaultChannelGroup": [{"sessionDefaultChannelGroup": "Organic Search", "sessions": "9", "totalUsers": "3", "engagedSessions": "2", "engagementRate": ".222", "keyEvents": "0", "screenPageViews": "16"}],
                "country": [{"country": "United States", "sessions": "12", "totalUsers": "12", "engagementRate": "0"}],
                "landingPage": [{"landingPage": "/", "sessions": "18", "totalUsers": "12", "engagementRate": "0"}],
                "deviceCategory": [{"deviceCategory": "mobile", "sessions": "8", "totalUsers": "8", "engagementRate": ".125"}],
            }},
        },
    }
    psi = {
        "target_url": "https://mejorsiptv.shop/", "collected_at": "2026-08-06T14:02:17+00:00",
        "runs": {
            "mobile": {"data_status": "REAL", "high_variance": False, "raw": [{"fetchTime": "same"}, {"fetchTime": "same"}], "median": {"performance": 76, "fcp_ms": 2855, "lcp_ms": 4996, "cls": .0014, "tbt_ms": 91, "speed_index_ms": 2926, "total_payload_kb": 975, "request_count": 29}},
            "desktop": {"data_status": "REAL", "high_variance": True, "raw": [{"fetchTime": "a"}, {"fetchTime": "b"}], "median": {"performance": 95, "fcp_ms": 728, "lcp_ms": 1055, "cls": .0001, "tbt_ms": 117, "speed_index_ms": 1292, "total_payload_kb": 975, "request_count": 29}},
        },
    }
    live = {
        "collected_at": "2026-08-06T14:03:45+00:00", "data_status": "REAL",
        "robots": {"status": 200},
        "sitemap": {"status": 200, "url_count": 1, "urls": ["https://mejorsiptv.shop/"]},
        "pages": [{"url": "https://mejorsiptv.shop/", "status": 200, "title": "title", "description": "description"}],
        "broken_internal": [{"source": "https://mejorsiptv.shop/", "target": "https://mejorsiptv.shop/cdn-cgi/l/email-protection", "status": 404}],
        "canonical_conflicts": {}, "duplicate_titles": {"duplicate": ["a", "b"]},
    }
    database = {"queries": {"blogposts": {"code": 0, "rows": [{"status": "published"}, {"status": "draft"}]}}}

    paths: dict[str, Path] = {}
    for key, value in {"OFFICIAL": official, "PSI": psi, "LIVE": live, "DB": database}.items():
        path = tmp_path / f"{key.lower()}.json"
        path.write_text(json.dumps(value), encoding="utf-8")
        monkeypatch.setenv(f"SEO_CONTROL_TOWER_{key}_JSON", str(path))
        paths[key] = path

    data_dir = tmp_path / "tower-data"
    data_dir.mkdir()
    monkeypatch.setenv("SEO_CONTROL_TOWER_DATA_DIR", str(data_dir))
    with sqlite3.connect(data_dir / "workflows.db") as conn:
        conn.execute("CREATE TABLE wf_instances (updated_at TEXT, payload TEXT)")
        safe = {
            "instance_id": "WF-SAFE-1", "template_id": "blog_content_chain", "title": "Safe workflow",
            "status": "PAUSED", "updated_at": "2026-08-06T00:00:00+00:00",
            "runs": {"intel": {"node_id": "intel", "state": "READY", "runtime_status": "STOPPED", "runtime_run_id": "", "evidence": ""}},
        }
        unsafe = {"instance_id": "WF-PRIVATE", "template_id": "credential_rotation", "status": "RUNNING", "runs": {}, "secret": "workflow-secret"}
        conn.executemany("INSERT INTO wf_instances VALUES (?,?)", [(safe["updated_at"], json.dumps(safe)), ("2026-08-05", json.dumps(unsafe))])
    with sqlite3.connect(data_dir / "timeline.db") as conn:
        conn.execute("CREATE TABLE timeline_nodes (scheduled_at TEXT, payload TEXT)")
        safe = {"node_id": "TL-20260806-aaaaaaaa", "scheduled_at": "2026-08-06T01:00:00+00:00", "kind": "REVIEW", "state": "ACKED", "subject_ref": "https://mejorsiptv.shop", "intent": "Safe review", "context": {"runtime_state": "", "raw_prompt": "do-not-leak"}}
        other = {"node_id": "TL-20260806-bbbbbbbb", "scheduled_at": "2026-08-06T02:00:00+00:00", "kind": "START", "state": "FIRED", "subject_ref": "https://other.example", "intent": "Other site", "context": {}}
        conn.executemany("INSERT INTO timeline_nodes VALUES (?,?)", [(safe["scheduled_at"], json.dumps(safe)), (other["scheduled_at"], json.dumps(other))])
    return paths


async def test_anonymous_public_private_matrix(anonymous_client: httpx.AsyncClient, tower_snapshots):
    public = await anonymous_client.get("/api/public/seo-control-tower/overview")
    assert public.status_code == 200
    assert public.json()["schema_version"] == "seo-control-tower.public.v2"
    public_head = await anonymous_client.head("/api/public/seo-control-tower/overview")
    assert public_head.status_code == 200
    assert public_head.content == b""

    assert (await anonymous_client.get("/api/config")).status_code == 401
    assert (await anonymous_client.get("/api/gsc/overview")).status_code == 401
    assert (await anonymous_client.get("/api/workflows/instances")).status_code == 401
    assert (await anonymous_client.post("/api/workflows/instances/WF-SAFE-1/start")).status_code == 401
    assert (await anonymous_client.post("/api/audit/run", json={})).status_code == 401

    # Exact method/path allowlist: no broad /api/public prefix and no write method.
    assert (await anonymous_client.post("/api/public/seo-control-tower/overview")).status_code == 401
    assert (await anonymous_client.get("/api/public/seo-control-tower/overview/extra")).status_code == 401
    assert (await anonymous_client.get("/api/auth/session-extra")).status_code == 401
    assert (await anonymous_client.get("/login-extra")).status_code == 401


async def test_public_projection_is_fixed_site_and_secret_free(anonymous_client: httpx.AsyncClient, tower_snapshots):
    response = await anonymous_client.get("/api/public/seo-control-tower/overview?site_url=https://other.example")
    body = response.json()
    serialized = json.dumps(body, ensure_ascii=False).lower()

    assert body["site"]["hostname"] == "mejorsiptv.shop"
    assert body["gsc"]["periods"]["d0"]["impressions"] == 19
    assert body["gsc"]["trend"][-1]["position"] is None  # zero impressions is not P0
    assert body["ga4"]["countries"][0]["country"] == "United States"
    assert body["psi"]["mobile"]["data_status"] == "DEGRADED"  # duplicate fetchTime
    assert body["technical"]["indexing"]["indexed_urls"] is None
    assert body["technical"]["suspected_broken_links"]["data_status"] == "DISPUTED"
    assert [item["instance_id"] for item in body["execution"]["workflow"]["items"]] == ["WF-SAFE-1"]
    assert [item["node_id"] for item in body["execution"]["timeline"]["items"]] == ["TL-20260806-aaaaaaaa"]

    for forbidden in ("must-never-leak", "secret-property", "workflow-secret", "do-not-leak", "traceback", "api_key", "service_account_email", "credentials"):
        assert forbidden not in serialized


async def test_wrong_site_snapshot_degrades_without_cross_site_leak(anonymous_client: httpx.AsyncClient, tower_snapshots):
    official = json.loads(tower_snapshots["OFFICIAL"].read_text())
    official["site"] = "https://other.example"
    official["gsc"]["global"]["d0"]["clicks"] = 999999
    tower_snapshots["OFFICIAL"].write_text(json.dumps(official), encoding="utf-8")

    body = (await anonymous_client.get("/api/public/seo-control-tower/overview")).json()
    assert body["site"]["hostname"] == "mejorsiptv.shop"
    assert body["gsc"]["data_status"] == "UNAVAILABLE"
    assert body["gsc"]["periods"] == {}
    assert body["ga4"]["data_status"] == "UNAVAILABLE"


async def test_v2_preview_is_served_with_required_modules(anonymous_client: httpx.AsyncClient):
    response = await anonymous_client.get("/static/preview/seo-control-tower-v2.html")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    for marker in (
        "SEO 总控大屏 V2", "GSC 点击 / 展示 / 加权排名趋势", "GA4 世界来访地图",
        "PageSpeed / Core Web Vitals", "技术 / 收录 / 内容健康", "今日巡检报告",
        "Workflow / Timeline 真实进度", tower._REPORT_ASSET_ID, tower._REPORT_URL,
    ):
        assert marker in response.text
