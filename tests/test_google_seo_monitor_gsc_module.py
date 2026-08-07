from __future__ import annotations

import pytest

from dojocore.quality import DataStatus
from seoagents.config.models import SeoAgentsConfig
from seoagents.tools.seo_trends import GoogleSEOMonitorSpec


class FakeGSC(GoogleSEOMonitorSpec):
    def __init__(self):
        super().__init__(SeoAgentsConfig())
        self.calls: list[tuple[str | None, str | None, tuple[str, ...], int]] = []

    def _init_gsc_client(self):
        return object()

    def query_gsc_raw(
        self,
        target_site: str,
        days_limit: int,
        dimensions=None,
        start_date_str=None,
        end_date_str=None,
        row_limit=25000,
        start_row=0,
    ):
        dims = tuple(dimensions or ())
        self.calls.append((start_date_str, end_date_str, dims, row_limit))
        # D0 probe: business_date 2026-08-07 -> starts at 2026-08-05.
        if dims == ("date",) and start_date_str == end_date_str == "2026-08-05":
            return [{"keys": ["2026-08-05"], "clicks": 2, "impressions": 20, "ctr": .1, "position": 4}]
        if dims == ("date",) and start_date_str == end_date_str == "2026-08-04":
            return [{"keys": ["2026-08-04"], "clicks": 1, "impressions": 10, "ctr": .1, "position": 5}]
        key = start_date_str if dims == ("date",) else f"{dims[0]}-value"
        return [{"keys": [key], "clicks": 3, "impressions": 30, "ctr": .1, "position": 6}]


@pytest.mark.asyncio
async def test_collect_gsc_module_detects_d0_and_collects_all_contract_windows():
    spec = FakeGSC()
    result = await spec.execute(
        {
            "action": "collect_gsc_module",
            "target_site": "sc-domain:mejorsiptv.shop",
            "business_date": "2026-08-07",
            "probe_days": 5,
            "row_limit": 100,
        },
        "test-session",
    )
    assert result["data_status"] == DataStatus.REAL.value
    assert result["d0"] == "2026-08-05"
    assert set(result["period_rows"]) == {"d0", "d1", "cur7", "prev7", "cur30", "prev30"}
    assert set(result["dimension_rows"]) == {"daily", "queries", "pages", "countries", "devices"}
    assert result["single_source_risk"] is True
    assert result["cross_validation"] == "单源，未经外部 SERP 交叉验证"
    assert len(spec.calls) == 12  # 1 probe + 6 windows + 5 dimensions


class MissingCredentials(FakeGSC):
    def _init_gsc_client(self):
        raise FileNotFoundError("[REDACTED]")


@pytest.mark.asyncio
async def test_collect_gsc_module_never_falls_back_to_mock_without_credentials():
    result = await MissingCredentials().execute(
        {
            "action": "collect_gsc_module",
            "target_site": "sc-domain:example.com",
            "business_date": "2026-08-07",
        },
        "test-session",
    )
    assert result["data_status"] == DataStatus.UNAVAILABLE.value
    assert "凭证缺失" in result["degraded_reason"]
    assert "period_rows" not in result
    assert "dimension_rows" not in result


class PartialDimensionFailure(FakeGSC):
    def query_gsc_raw(self, *args, **kwargs):
        if tuple(kwargs.get("dimensions") or ()) == ("country",):
            raise RuntimeError("country unavailable")
        return super().query_gsc_raw(*args, **kwargs)


@pytest.mark.asyncio
async def test_partial_dimension_failure_is_degraded_not_unavailable(monkeypatch):
    monkeypatch.setattr("seoagents.tools.seo_trends.time.sleep", lambda _seconds: None)
    result = await PartialDimensionFailure().execute(
        {
            "action": "collect_gsc_module",
            "target_site": "sc-domain:example.com",
            "business_date": "2026-08-07",
        },
        "test-session",
    )
    assert result["data_status"] == DataStatus.DEGRADED.value
    assert "countries" in result["degraded_reason"]
    assert result["period_rows"]
    assert result["dimension_rows"]["countries"] == []


class RetryOnce(FakeGSC):
    def __init__(self):
        super().__init__()
        self.failed = False

    def query_gsc_raw(self, *args, **kwargs):
        if not self.failed:
            self.failed = True
            raise RuntimeError("429")
        return super().query_gsc_raw(*args, **kwargs)


@pytest.mark.asyncio
async def test_collect_gsc_module_retries_transient_failure(monkeypatch):
    monkeypatch.setattr("seoagents.tools.seo_trends.time.sleep", lambda _seconds: None)
    spec = RetryOnce()
    result = await spec.execute(
        {
            "action": "collect_gsc_module",
            "target_site": "sc-domain:example.com",
            "business_date": "2026-08-07",
        },
        "test-session",
    )
    assert spec.failed is True
    assert result["data_status"] == DataStatus.REAL.value


def test_schema_exposes_strict_module_action():
    spec = GoogleSEOMonitorSpec(SeoAgentsConfig())
    actions = spec.get_schema()["parameters"]["properties"]["action"]["enum"]
    assert "collect_gsc_module" in actions
    assert "normalize_gsc_module" in actions
    assert "persist_gsc_module" in actions
