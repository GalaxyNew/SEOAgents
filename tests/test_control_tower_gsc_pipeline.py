from __future__ import annotations

import json

from dojocore.quality import DataStatus
from dojocore.tools.executor import active_runtime_metadata
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


def test_normalize_archive_payload_persist_and_readback_keep_runtime_lineage(tmp_path):
    spec = GoogleSEOMonitorSpec(_config(tmp_path))
    runtime_token = active_runtime_metadata.set(
        {
            "instance_id": "WF-DAILY-GSC-REAL",
            "node_id": "normalize",
            "timeline_node_id": "TL-20260807-REAL",
            "lineage_instance_id": "WF-DAILY-GSC-REAL",
            "lineage_timeline_node_id": "TL-20260807-REAL",
        }
    )
    try:
        normalized = spec._normalize_gsc_payload(
            _collector_payload(),
            workflow_instance_id="WF-DAILY-GSC-REAL",
            timeline_node_id="TL-20260807-REAL",
        )
    finally:
        active_runtime_metadata.reset(runtime_token)
    assert normalized["data_status"] == "REAL"
    assert normalized["run"]["site_id"] == "example.com"
    assert normalized["run"]["workflow_instance_id"] == "WF-DAILY-GSC-REAL"
    assert normalized["run"]["timeline_node_id"] == "TL-20260807-REAL"
    assert normalized["metric_points"]

    # This is the exact structured value daily_gsc passes to Asset Hub content.
    archived_content = json.loads(json.dumps(normalized, ensure_ascii=False))
    assert archived_content["run"]["workflow_instance_id"] == "WF-DAILY-GSC-REAL"
    assert archived_content["run"]["timeline_node_id"] == "TL-20260807-REAL"

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
    assert verified["workflow_instance_id"] == "WF-DAILY-GSC-REAL"
    assert verified["timeline_node_id"] == "TL-20260807-REAL"
    latest = ControlTowerStore(tmp_path).latest("example.com", "gsc")
    assert latest is not None
    assert latest["asset_id"] == "seo/dataset/2026-08/gsc-example"
    assert latest["workflow_instance_id"] == "WF-DAILY-GSC-REAL"
    assert latest["timeline_node_id"] == "TL-20260807-REAL"


def test_direct_caller_cannot_self_report_workflow_lineage(tmp_path):
    spec = GoogleSEOMonitorSpec(_config(tmp_path))
    payload = _collector_payload()
    payload["workflow_instance_id"] = "WF-PAYLOAD-FORGED"
    payload["timeline_node_id"] = "TL-PAYLOAD-FORGED"

    normalized = spec._normalize_gsc_payload(
        payload,
        workflow_instance_id="WF-ARG-FORGED",
        timeline_node_id="TL-ARG-FORGED",
    )
    assert normalized["data_status"] == "REAL"
    assert normalized["run"]["workflow_instance_id"] == ""
    assert normalized["run"]["timeline_node_id"] == ""


def test_runtime_metadata_cannot_bless_different_lineage_arguments(tmp_path):
    spec = GoogleSEOMonitorSpec(_config(tmp_path))
    token = active_runtime_metadata.set(
        {
            "instance_id": "WF-REAL",
            "node_id": "normalize",
            "timeline_node_id": "TL-REAL",
            "lineage_instance_id": "WF-REAL",
            "lineage_timeline_node_id": "TL-REAL",
        }
    )
    try:
        normalized = spec._normalize_gsc_payload(
            _collector_payload(),
            workflow_instance_id="WF-FORGED",
            timeline_node_id="TL-FORGED",
        )
    finally:
        active_runtime_metadata.reset(token)
    assert normalized["run"]["workflow_instance_id"] == ""
    assert normalized["run"]["timeline_node_id"] == ""


def test_normalize_rejects_unconfigured_property(tmp_path):
    spec = GoogleSEOMonitorSpec(_config(tmp_path))
    payload = _collector_payload()
    payload["site"] = "sc-domain:other.com"
    result = spec._normalize_gsc_payload(payload)
    assert result["data_status"] == "UNAVAILABLE"
    assert "monitored_sites" in result["degraded_reason"]
