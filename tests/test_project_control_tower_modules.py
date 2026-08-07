from __future__ import annotations

import datetime as dt
import importlib.util
import json
import sys
from pathlib import Path

from dojocore.quality import DataStatus
from seoagents.control_tower import ControlTowerStore
from seoagents.control_tower.models import ModuleRun


def _load():
    path = Path("/opt/hermes-seo/scripts/project_control_tower_modules.py")
    spec = importlib.util.spec_from_file_location("project_control_tower_modules_test", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _run(site: str) -> ModuleRun:
    return ModuleRun(
        site_id=site,
        module_id="gsc",
        business_date="2026-08-08",
        data_status=DataStatus.REAL,
        source="Google Search Console Search Analytics API",
        data_window={
            "d0": "2026-08-06",
            "d1": "2026-08-05",
            "prev30": {"start": "2026-07-01"},
        },
        metrics={"periods": {"d0": {"clicks": 1, "impressions": 2}}},
        dimensions={"daily": [], "queries": [], "pages": [], "countries": [], "devices": []},
        collected_at="2026-08-08T10:00:00+00:00",
        known_limitations=("single source",),
        cross_validation="单源，未经外部 SERP 交叉验证",
        single_source_risk=True,
        asset_id=f"seo/dataset/2026-08/gsc-{site}-2026-08-08",
        workflow_instance_id=f"WF-{site}",
    )


def test_projection_links_three_cards_from_same_matrix(tmp_path, monkeypatch):
    projector = _load()
    data = tmp_path / "data"
    data.mkdir()
    tower = tmp_path / "sites.json"
    tower.write_text(
        json.dumps(
            {
                "sites": {
                    "igoriptv2.com": {"site": {"hostname": "igoriptv2.com"}},
                    "mejorsiptv.shop": {"site": {"hostname": "mejorsiptv.shop"}},
                }
            }
        )
    )
    manifest = {
        "data_status": "REAL",
        "source": "Hermes Cron + SEO Timeline",
        "business_date": "2026-08-08",
        "timezone": "UTC",
        "slot_minutes": 10,
        "ordering": "module-first-site-second",
        "module_count": 7,
        "site_count": 2,
        "slots": [],
    }
    labels = list(projector.MODULE_LABELS.items())
    sites = [("igoriptv2.com", "西班牙一号"), ("mejorsiptv.shop", "西班牙二号")]
    slots = []
    base = dt.datetime(2026, 8, 8, 10, tzinfo=dt.UTC)
    for index, (module_id, label) in enumerate(labels):
        for site_index, (site_id, display) in enumerate(sites):
            stamp = base + dt.timedelta(minutes=(index * 2 + site_index) * 10)
            slots.append(
                {
                    "site_id": site_id,
                    "site_display_name": display,
                    "module_id": module_id,
                    "label": label,
                    "scheduled_at": stamp.isoformat(),
                    "schedule_hhmm": stamp.strftime("%H:%M"),
                    "enabled": module_id == "gsc",
                    "activation_status": "ENABLED" if module_id == "gsc" else "NOT_ENABLED",
                    "activation_reason": "" if module_id == "gsc" else "独立生产工作流尚未完成验收",
                }
            )
    manifest["slots"] = slots
    manifest_path = data / "control-tower-module-schedule.json"
    manifest_path.write_text(json.dumps(manifest))

    store = ControlTowerStore(data)
    for site_id, _ in sites:
        store.record_attempt(_run(site_id))

    monkeypatch.setattr(projector, "DATA_DIR", data)
    monkeypatch.setattr(projector, "MANIFEST_PATH", manifest_path)
    monkeypatch.setattr(projector, "TOWER_JSON", tower)
    monkeypatch.setattr(projector, "utc_now", lambda: dt.datetime(2026, 8, 8, 11, tzinfo=dt.UTC))
    result = projector.project()
    assert result["matrix_rows"] == 14
    assert result["real_rows"] == 2

    body = json.loads(tower.read_text())
    assert body["release_channel"] == "production"
    assert body["package_scope"] == "SEO Control Tower V1 Production"
    site = body["sites"]["igoriptv2.com"]
    assert site["inspection"]["summary"] == "1/7 个模块已有线上 REAL 结果"
    assert len(site["inspection"]["gates"]) == 7
    assert len(site["execution"]["module_matrix"]) == 7
    assert len(site["freshness"]["modules"]) == 7
    assert site["gsc"]["data_status"] == "REAL"
    assert site["ga4"]["data_status"] == "UNAVAILABLE"
    assert "sessions" not in site["ga4"]
