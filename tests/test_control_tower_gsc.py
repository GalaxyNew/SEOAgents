from __future__ import annotations

from dojocore.quality import DataStatus
from seoagents.control_tower.gsc import (
    aggregate_rows,
    build_gsc_module_run,
    period_windows,
)


def test_period_windows_are_exact_and_non_overlapping():
    windows = period_windows("2026-08-05")
    assert (windows["d0"].start, windows["d0"].end) == ("2026-08-05", "2026-08-05")
    assert (windows["d1"].start, windows["d1"].end) == ("2026-08-04", "2026-08-04")
    assert (windows["cur7"].start, windows["cur7"].end) == ("2026-07-30", "2026-08-05")
    assert (windows["prev7"].start, windows["prev7"].end) == ("2026-07-23", "2026-07-29")
    assert (windows["cur30"].start, windows["cur30"].end) == ("2026-07-07", "2026-08-05")
    assert (windows["prev30"].start, windows["prev30"].end) == ("2026-06-07", "2026-07-06")


def test_aggregate_uses_impression_weighted_position():
    result = aggregate_rows(
        [
            {"clicks": 2, "impressions": 10, "position": 2},
            {"clicks": 3, "impressions": 30, "position": 6},
        ]
    )
    assert result == {
        "clicks": 5.0,
        "impressions": 40.0,
        "ctr": 0.125,
        "weighted_position": 5.0,
    }


def _build(**overrides):
    kwargs = {
        "site_id": "mejorsiptv.shop",
        "business_date": "2026-08-07",
        "d0": "2026-08-05",
        "period_rows": {
            "d0": [{"clicks": 2, "impressions": 20, "position": 4}],
            "d1": [{"clicks": 1, "impressions": 10, "position": 5}],
            "cur7": [],
            "prev7": [],
            "cur30": [],
            "prev30": [],
        },
        "dimension_rows": {
            "daily": [{"key": "2026-08-05", "clicks": 2, "impressions": 20, "ctr": 0.1, "position": 4}],
            "queries": [],
            "pages": [],
            "countries": [],
            "devices": [],
        },
        "dimension_windows": {
            key: {"start": "2026-07-07", "end": "2026-08-05"}
            for key in ("daily", "queries", "pages", "countries", "devices")
        },
        "collected_at": "2026-08-07T12:00:00+00:00",
    }
    kwargs.update(overrides)
    return build_gsc_module_run(**kwargs)


def test_build_real_contract_and_metric_points():
    run, points = _build()
    assert run.data_status is DataStatus.REAL
    assert run.single_source_risk is True
    assert run.cross_validation == "单源，未经外部 SERP 交叉验证"
    assert run.metrics["periods"]["d0"]["weighted_position"] == 4.0
    assert run.dimensions["daily"][0]["window_end"] == "2026-08-05"
    assert len(points) == 24
    assert {point.period_key for point in points} == {
        "d0", "d1", "cur7", "prev7", "cur30", "prev30"
    }


def test_missing_period_stays_null_not_zero_filled():
    run, points = _build(
        period_rows={
            "d0": [{"clicks": 0, "impressions": 0, "position": 0}],
            "d1": None,
        }
    )
    assert run.metrics["periods"]["d0"]["clicks"] == 0.0
    assert run.metrics["periods"]["d1"] is None
    assert not any(point.period_key == "d1" for point in points)


def test_unavailable_has_no_metrics_dimensions_or_findings():
    run, points = _build(
        d0=None,
        source_status=DataStatus.UNAVAILABLE,
        reason="GSC 凭证不可用",
    )
    assert run.data_status is DataStatus.UNAVAILABLE
    assert run.reason == "GSC 凭证不可用"
    assert run.metrics == {}
    assert run.dimensions == {}
    assert run.findings == ()
    assert points == ()


def test_truncated_dimension_is_degraded_and_not_scorable():
    run, points = _build(truncated_dimensions=["queries"])
    assert run.data_status is DataStatus.DEGRADED
    assert "queries" in (run.reason or "")
    assert run.findings == ()
    assert points
