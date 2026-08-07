from __future__ import annotations

from dojocore.quality import DataStatus
from seoagents.config.models import SeoAgentsConfig, SiteItemConfig, SitesConfig, StorageConfig
from seoagents.control_tower import ControlTowerStore
from seoagents.tools.seo_trends import GoogleSEOMonitorSpec


def _config(tmp_path):
    return SeoAgentsConfig(
        sites=SitesConfig(
            site_url="https://example.com",
            gsc_property="sc-domain:example.com",
            monitored_sites=(
                SiteItemConfig(
                    site_url="https://example.com",
                    gsc_property="sc-domain:example.com",
                    brand_name="Example",
                ),
            ),
        ),
        storage=StorageConfig(data_dir=str(tmp_path)),
    )


def _collector_payload():
    periods = {
        key: [{"key": "2026-08-05", "clicks": 1, "impressions": 10, "ctr": 0.1, "position": 4}]
        for key in ("d0", "d1", "cur7", "prev7", "cur30", "prev30")
    }
    dims = {
        "daily": [{"key": "2026-08-05", "clicks": 1, "impressions": 10, "ctr": 0.1, "position": 4}],
        "queries": [{"key": "iptv", "clicks": 1, "impressions": 10, "ctr": 0.1, "position": 4}],
        "pages": [], "countries": [], "devices": [],
    }
    windows = {
        key: {"start": "2026-07-07", "end": "2026-08-05"}
        for key in dims
    }
    return {
        "site": "sc-domain:example.com",
        "business_date": "2026-08-07",
        "source": "google_seo_monitor.collect_gsc_module",
        "data_status": "REAL",
        "data_window": "2026-07-07/2026-08-05",
        "d0": "2026-08-05",
        "period_rows": periods,
        "dimension_rows": dims,
        "dimension_windows": windows,
        "truncated_dimensions": [],
        "collected_at": "2026-08-07T12:00:00+00:00",
    }


def test_normalize_and_persist_requires_archive_key(tmp_path):
    spec = GoogleSEOMonitorSpec(_config(tmp_path))
    normalized = spec._normalize_gsc_payload(_collector_payload())
    assert normalized["data_status"] == "REAL"
    assert normalized["run"]["site_id"] == "example.com"
    assert normalized["metric_points"]

    refused = spec._persist_gsc_payload({"normalized": normalized})
    assert refused["data_status"] == "UNAVAILABLE"
    assert "Asset Hub" in refused["degraded_reason"]

    saved = spec._persist_gsc_payload(
        {"normalized": normalized, "archived": {"key": "seo/dataset/2026-08/gsc-example"}}
    )
    assert saved["data_status"] == "REAL"
    verified = saved["verified"]
    assert verified["asset_id"] == "seo/dataset/2026-08/gsc-example"
    assert verified["data_status"] == DataStatus.REAL.value
    latest = ControlTowerStore(tmp_path).latest("example.com", "gsc")
    assert latest is not None
    assert latest["asset_id"] == "seo/dataset/2026-08/gsc-example"


def test_normalize_rejects_unconfigured_property(tmp_path):
    spec = GoogleSEOMonitorSpec(_config(tmp_path))
    payload = _collector_payload()
    payload["site"] = "sc-domain:other.com"
    result = spec._normalize_gsc_payload(payload)
    assert result["data_status"] == "UNAVAILABLE"
    assert "monitored_sites" in result["degraded_reason"]
