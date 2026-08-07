from __future__ import annotations

import concurrent.futures
import multiprocessing
import sqlite3
from dataclasses import replace

import pytest

from dojocore.quality import DataStatus
from seoagents.control_tower import ControlTowerStore, MetricPoint, ModuleFinding, ModuleRun


def run(*, status=DataStatus.REAL, reason=None, collected_at="2026-08-07T12:00:00+00:00"):
    return ModuleRun(
        site_id="mejorsiptv.shop",
        module_id="gsc",
        business_date="2026-08-07",
        data_status=status,
        source="Google Search Console Search Analytics API",
        data_window={"d0": "2026-08-05", "d1": "2026-08-04", "timezone": "UTC"},
        reason=reason,
        known_limitations=("GSC 通常延迟 2–3 日",),
        cross_validation="单源，未经外部 SERP 交叉验证",
        single_source_risk=True,
        collected_at=collected_at,
        workflow_instance_id="WF-GSC-1",
        timeline_node_id="TL-GSC-1",
        asset_id="asset_gsc_1",
        metrics=(
            {"periods": {"d0": {"clicks": 1, "impressions": 19}}}
            if status is not DataStatus.UNAVAILABLE else {}
        ),
        dimensions={"queries": []} if status is not DataStatus.UNAVAILABLE else {},
        findings=(() if status is DataStatus.UNAVAILABLE else (
            ModuleFinding(
                finding_key="low_sample",
                severity="INFO",
                title="样本量较小",
                conclusion="待验证",
                evidence={"metric_keys": ["impressions"], "asset_id": "asset_gsc_1"},
                recommendation="继续按相同窗口观察",
                expected_benefit="待验证，当前不能量化",
                verification_method="观察 14/28 日同口径数据",
            ),
        )),
    )


def points():
    return [
        MetricPoint(
            metric_key="clicks", metric_label="自然搜索点击", period_key="d0",
            window_start="2026-08-05", window_end="2026-08-05", value_num=1,
            unit="次", data_status=DataStatus.REAL,
        ),
        MetricPoint(
            metric_key="ctr", metric_label="点击率", period_key="d0",
            window_start="2026-08-05", window_end="2026-08-05", value_num=1 / 19,
            unit="比例", data_status=DataStatus.REAL,
        ),
    ]


def _process_write(data_dir: str, minute: int, output: multiprocessing.Queue) -> None:
    try:
        saved = ControlTowerStore(data_dir).record_attempt(
            run(collected_at=f"2026-08-07T12:{minute:02d}:00+00:00")
        )
        output.put(("ok", saved["module_run_id"], saved["attempt_no"]))
    except Exception as exc:  # noqa: BLE001  # pragma: no cover - child boundary
        output.put(("error", type(exc).__name__, str(exc)))


def test_non_real_requires_reason():
    with pytest.raises(ValueError, match="必须说明 reason"):
        run(status=DataStatus.UNAVAILABLE).validate()


def test_metric_point_rejects_missing_and_nan():
    with pytest.raises(ValueError, match="必须有"):
        MetricPoint(
            metric_key="clicks", metric_label="点击", period_key="d0",
            window_start="2026-08-05", window_end="2026-08-05", unit="次",
        ).validate()
    with pytest.raises(ValueError):
        MetricPoint(
            metric_key="clicks", metric_label="点击", period_key="d0",
            window_start="2026-08-05", window_end="2026-08-05", unit="次",
            value_num=float("nan"),
        ).validate()


def test_record_and_read_latest(tmp_path):
    store = ControlTowerStore(tmp_path)
    saved = store.record_attempt(run(), metric_points=points())
    assert saved["attempt_no"] == 1
    latest = store.latest("mejorsiptv.shop", "gsc")
    assert latest is not None
    assert latest["module_run_id"] == saved["module_run_id"]
    assert latest["data_status"] == "REAL"
    assert latest["single_source_risk"] is True
    assert latest["asset_id"] == "asset_gsc_1"
    assert len(latest["metric_points"]) == 2
    assert latest["findings"][0]["conclusion"] == "待验证"


def test_same_business_key_adds_attempt_without_duplicate_run(tmp_path):
    store = ControlTowerStore(tmp_path)
    first = store.record_attempt(run(), metric_points=points())
    second = store.record_attempt(
        run(collected_at="2026-08-07T12:30:00+00:00"), metric_points=points()
    )
    assert first["module_run_id"] == second["module_run_id"]
    assert (first["attempt_no"], second["attempt_no"]) == (1, 2)
    attempts = store.attempts(first["module_run_id"])
    assert [x["attempt_no"] for x in attempts] == [2, 1]
    with sqlite3.connect(store.db) as conn:
        assert conn.execute("SELECT count(*) FROM module_runs").fetchone()[0] == 1
        assert conn.execute("SELECT count(*) FROM module_attempts").fetchone()[0] == 2


def test_different_business_date_creates_new_logical_run(tmp_path):
    store = ControlTowerStore(tmp_path)
    first = store.record_attempt(run())
    other = replace(run(), business_date="2026-08-08")
    second = store.record_attempt(other)
    assert first["module_run_id"] != second["module_run_id"]
    assert len(store.history("mejorsiptv.shop", "gsc")) == 2


def test_concurrent_attempts_keep_one_logical_run(tmp_path):
    def write(n):
        store = ControlTowerStore(tmp_path)
        return store.record_attempt(
            run(collected_at=f"2026-08-07T12:{n:02d}:00+00:00")
        )

    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(write, range(4)))
    assert len({x["module_run_id"] for x in results}) == 1
    assert sorted(x["attempt_no"] for x in results) == [1, 2, 3, 4]


def test_cross_process_attempts_keep_one_logical_run(tmp_path):
    ctx = multiprocessing.get_context("spawn")
    output = ctx.Queue()
    processes = [
        ctx.Process(target=_process_write, args=(str(tmp_path), minute, output))
        for minute in range(4)
    ]
    for process in processes:
        process.start()
    for process in processes:
        process.join(timeout=30)
        assert process.exitcode == 0
    results = [output.get(timeout=5) for _ in processes]
    assert {item[0] for item in results} == {"ok"}
    assert len({item[1] for item in results}) == 1
    assert sorted(item[2] for item in results) == [1, 2, 3, 4]


def test_unavailable_is_not_persisted_as_zero_metric(tmp_path):
    store = ControlTowerStore(tmp_path)
    unavailable = run(status=DataStatus.UNAVAILABLE, reason="GSC 权限不足")
    saved = store.record_attempt(unavailable)
    latest = store.latest("mejorsiptv.shop", "gsc")
    assert latest is not None
    assert saved["attempt_no"] == 1
    assert latest["data_status"] == "UNAVAILABLE"
    assert latest["metrics"] == {}
    assert latest["dimensions"] == {}
    assert latest["findings"] == []
    assert latest["metric_points"] == []
    with pytest.raises(ValueError, match="只有 REAL|UNAVAILABLE"):
        store.record_attempt(
            unavailable,
            metric_points=[
                MetricPoint(
                    metric_key="clicks", metric_label="点击", period_key="d0",
                    window_start="2026-08-05", window_end="2026-08-05",
                    value_num=0, unit="次", data_status=DataStatus.UNAVAILABLE,
                )
            ],
        )
