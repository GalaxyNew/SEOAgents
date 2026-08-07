from __future__ import annotations

import datetime as dt
import importlib.util
import json
import sys
from pathlib import Path


def _load():
    _PLANNER_PATH = Path(__file__).resolve().parents[1] / "scripts" / "control_tower_module_planner.py"
    spec = importlib.util.spec_from_file_location("control_tower_module_planner_test", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_schedule_is_module_first_with_ten_minute_slots():
    planner = _load()
    rows = planner.schedule_rows(dt.date(2026, 8, 8))
    assert len(rows) == 14
    assert [(row["site_id"], row["module_id"], row["schedule_hhmm"]) for row in rows[:4]] == [
        ("igoriptv2.com", "gsc", "10:00"),
        ("mejorsiptv.shop", "gsc", "10:10"),
        ("igoriptv2.com", "ga4", "10:20"),
        ("mejorsiptv.shop", "ga4", "10:30"),
    ]
    assert rows[-1]["schedule_hhmm"] == "12:10"
    assert [row["module_id"] for row in rows if row["enabled"]] == ["gsc", "gsc"]


def test_materialize_is_idempotent_and_does_not_schedule_disabled_modules(tmp_path, monkeypatch):
    planner = _load()
    monkeypatch.setattr(planner, "DATA_DIR", tmp_path)
    monkeypatch.setattr(planner, "TIMELINE_DB", tmp_path / "timeline.db")
    monkeypatch.setattr(planner, "MANIFEST_PATH", tmp_path / "control-tower-module-schedule.json")
    day = dt.date(2026, 8, 8)

    first = planner.materialize(day)
    second = planner.materialize(day)

    assert len(first["created"]) == 2
    assert len(second["created"]) == 0
    assert sum(1 for item in second["skipped"] if item["reason"] == "already_planned") == 2
    manifest = json.loads(planner.MANIFEST_PATH.read_text())
    assert manifest["data_status"] == "REAL"
    assert manifest["module_count"] == 7
    assert manifest["site_count"] == 2
    assert sum(1 for row in manifest["slots"] if row["activation_status"] == "NOT_ENABLED") == 12

    import sqlite3

    with sqlite3.connect(planner.TIMELINE_DB) as conn:
        rows = conn.execute("SELECT payload FROM timeline_nodes ORDER BY scheduled_at").fetchall()
    assert len(rows) == 2
    payloads = [json.loads(row[0]) for row in rows]
    assert [item["context"]["parameters"]["site_id"] for item in payloads] == [
        "igoriptv2.com",
        "mejorsiptv.shop",
    ]
    assert all(item["context"]["workflow_version"] == "1.1" for item in payloads)
