"""Narrow, read-only public aggregate for the SEO Control Tower.

The browser never joins raw GSC/GA4/PSI, workflow, Timeline, or configuration
payloads.  This router reads the existing snapshots and SQLite stores in
read-only mode, validates the fixed public site scope, and copies only an
explicit allowlist of aggregate fields into the response.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import re
import sqlite3
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from fastapi import APIRouter
from fastapi.responses import Response

router = APIRouter(prefix="/api/public/seo-control-tower", tags=["public-readonly"])

_PUBLIC_SITE = "mejorsiptv.shop"
_PUBLIC_SITE_URL = f"https://{_PUBLIC_SITE}"
_REPORT_DATE = "2026-08-06"
_REPORT_ASSET_ID = "seo/report/2026-08/daily-diagnosis-spain2-mejorsiptv.shop-2026-08-06"
_REPORT_URL = "https://icnxbkdjuzio.feishu.cn/docx/KVTUdCB60ov5THxMRzdcORr3n8f"
_MAX_SNAPSHOT_BYTES = 8 * 1024 * 1024
_SAFE_STATUS = {"REAL", "DEGRADED", "UNAVAILABLE", "DISPUTED"}
_SAFE_ID = re.compile(r"^[A-Za-z0-9_.:-]{1,160}$")
_ALLOWED_WORKFLOW_TEMPLATES = {"blog_content_chain", "daily_seo_inspection"}


def _utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def _snapshot_path(env_name: str, default: str) -> Path:
    return Path(os.environ.get(env_name, default)).expanduser()


def _load_json(path: Path) -> dict[str, Any] | None:
    """Load a bounded local JSON object without returning parser details."""
    try:
        if not path.is_file() or path.stat().st_size > _MAX_SNAPSHOT_BYTES:
            return None
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else None
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None


def _site_matches(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    text = value.strip().lower()
    if "://" not in text:
        text = f"https://{text}"
    try:
        return (urlparse(text).hostname or "").lower() == _PUBLIC_SITE
    except ValueError:
        return False


def _status(value: Any, default: str = "UNAVAILABLE") -> str:
    text = str(value or "").upper()
    if text == "REAL_WITH_HIGH_VARIANCE":
        return "DEGRADED"
    return text if text in _SAFE_STATUS else default


def _text(value: Any, *, limit: int = 180) -> str:
    if value is None:
        return ""
    return str(value).replace("\x00", "").strip()[:limit]


def _safe_id(value: Any) -> str:
    text = _text(value, limit=160)
    return text if _SAFE_ID.fullmatch(text) else ""


def _num(value: Any, *, integer: bool = False) -> int | float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number != number or number in (float("inf"), float("-inf")):
        return None
    return int(round(number)) if integer else round(number, 6)


def _row_metrics(row: Any) -> dict[str, int | float | None] | None:
    if not isinstance(row, dict):
        return None
    return {
        "clicks": _num(row.get("clicks"), integer=True),
        "impressions": _num(row.get("impressions"), integer=True),
        "ctr": _num(row.get("ctr")),
        "position": _num(row.get("position")),
    }


def _ga_metrics(row: Any) -> dict[str, int | float | None] | None:
    if not isinstance(row, dict):
        return None
    return {
        "sessions": _num(row.get("sessions"), integer=True),
        "users": _num(row.get("totalUsers"), integer=True),
        "new_users": _num(row.get("newUsers"), integer=True),
        "engaged_sessions": _num(row.get("engagedSessions"), integer=True),
        "engagement_rate": _num(row.get("engagementRate")),
        "key_events": _num(row.get("keyEvents"), integer=True),
        "page_views": _num(row.get("screenPageViews"), integer=True),
    }


def _first_row(value: Any) -> dict[str, Any] | None:
    return value[0] if isinstance(value, list) and value and isinstance(value[0], dict) else None


def _empty_source(source: str, limitation: str) -> dict[str, Any]:
    return {
        "source": source,
        "data_status": "UNAVAILABLE",
        "data_window": "",
        "known_limitations": [limitation],
        "cross_validation": "未经交叉验证",
    }


def _gsc_section(snapshot: dict[str, Any] | None) -> dict[str, Any]:
    empty = {
        **_empty_source("Google Search Console Search Analytics API", "安全快照不可用"),
        "d0": "",
        "d1": "",
        "periods": {},
        "trend": [],
    }
    if not snapshot or not _site_matches(snapshot.get("site")):
        return empty
    raw = snapshot.get("gsc")
    if not isinstance(raw, dict):
        return empty
    global_rows = raw.get("global") if isinstance(raw.get("global"), dict) else {}
    periods = {key: _row_metrics(global_rows.get(key)) for key in ("d0", "d1", "cur7", "prev7", "cur30", "prev30")}
    dimensions = raw.get("dimensions") if isinstance(raw.get("dimensions"), dict) else {}
    cur30 = dimensions.get("cur30") if isinstance(dimensions.get("cur30"), dict) else {}
    trend: list[dict[str, Any]] = []
    for item in cur30.get("date", []) if isinstance(cur30.get("date"), list) else []:
        if not isinstance(item, dict):
            continue
        keys = item.get("keys")
        day = _text(keys[0], limit=10) if isinstance(keys, list) and keys else ""
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", day):
            continue
        impressions = _num(item.get("impressions"), integer=True)
        trend.append({
            "date": day,
            "clicks": _num(item.get("clicks"), integer=True),
            "impressions": impressions,
            # Position is undefined on a zero-impression day; never publish P0.
            "position": _num(item.get("position")) if impressions else None,
        })
    trend.sort(key=lambda row: row["date"])
    ranges = raw.get("ranges") if isinstance(raw.get("ranges"), dict) else {}
    cur30_range = ranges.get("cur30")
    data_window = ""
    if isinstance(cur30_range, list) and len(cur30_range) == 2:
        data_window = f"{_text(cur30_range[0], limit=10)}/{_text(cur30_range[1], limit=10)}"
    return {
        "source": "Google Search Console Search Analytics API",
        "data_status": _status(raw.get("data_status")),
        "data_window": data_window,
        "known_limitations": ["GSC 通常延迟 2–3 日", "查询/页面维度可能受隐私阈值影响", "加权排名不是实测 SERP 排名"],
        "cross_validation": "单源，未经外部 SERP 交叉验证",
        "d0": _text(raw.get("d0"), limit=10),
        "d1": _text(raw.get("d1"), limit=10),
        "periods": periods,
        "trend": trend[-31:],
    }


def _ga4_section(snapshot: dict[str, Any] | None) -> dict[str, Any]:
    empty = {
        **_empty_source("GA4 Data API v1beta", "安全快照不可用"),
        "d0": "",
        "d1": "",
        "totals": {},
        "organic_7d": None,
        "countries": [],
        "landing_pages": [],
        "devices": [],
    }
    if not snapshot or not _site_matches(snapshot.get("site")):
        return empty
    raw = snapshot.get("ga4")
    if not isinstance(raw, dict):
        return empty
    verified = any(
        isinstance(row, dict) and _site_matches(row.get("hostName"))
        for row in (raw.get("hostnames") or [])
    )
    if not verified:
        empty["known_limitations"] = ["hostName 未通过固定站点校验"]
        return empty
    totals_raw = raw.get("totals") if isinstance(raw.get("totals"), dict) else {}
    totals = {key: _ga_metrics(_first_row(totals_raw.get(key))) for key in ("d0", "d1", "cur7", "prev7", "cur30", "prev30")}
    dimensions = raw.get("dimensions") if isinstance(raw.get("dimensions"), dict) else {}
    cur7 = dimensions.get("cur7") if isinstance(dimensions.get("cur7"), dict) else {}
    channels = cur7.get("sessionDefaultChannelGroup") if isinstance(cur7.get("sessionDefaultChannelGroup"), list) else []
    organic = next((_ga_metrics(row) for row in channels if isinstance(row, dict) and row.get("sessionDefaultChannelGroup") == "Organic Search"), None)
    countries: list[dict[str, Any]] = []
    for row in cur7.get("country", []) if isinstance(cur7.get("country"), list) else []:
        if not isinstance(row, dict):
            continue
        name = _text(row.get("country"), limit=60) or "(not set)"
        countries.append({"country": name, **(_ga_metrics(row) or {})})
    countries.sort(key=lambda row: row.get("sessions") or 0, reverse=True)
    landing_pages: list[dict[str, Any]] = []
    for row in cur7.get("landingPage", []) if isinstance(cur7.get("landingPage"), list) else []:
        if not isinstance(row, dict):
            continue
        path = _text(row.get("landingPage"), limit=160)
        if path and not path.startswith("/"):
            continue
        landing_pages.append({"path": path or "(not set)", **(_ga_metrics(row) or {})})
    devices: list[dict[str, Any]] = []
    for row in cur7.get("deviceCategory", []) if isinstance(cur7.get("deviceCategory"), list) else []:
        if not isinstance(row, dict):
            continue
        device = _text(row.get("deviceCategory"), limit=20).lower()
        if device not in {"desktop", "mobile", "tablet", "smart tv"}:
            continue
        devices.append({"device": device, **(_ga_metrics(row) or {})})
    ranges = raw.get("ranges") if isinstance(raw.get("ranges"), dict) else {}
    cur7_range = ranges.get("cur7")
    data_window = ""
    if isinstance(cur7_range, list) and len(cur7_range) == 2:
        data_window = f"{_text(cur7_range[0], limit=10)}/{_text(cur7_range[1], limit=10)}"
    return {
        "source": "GA4 Data API v1beta（hostName 已校验）",
        "data_status": _status(raw.get("data_status")),
        "data_window": data_window,
        "known_limitations": ["全站与 Organic Search 是不同口径", "前一比较窗口为空时保持 UNAVAILABLE", "小样本不用于稳定增长结论"],
        "cross_validation": f"hostName={_PUBLIC_SITE}",
        "d0": _text(raw.get("d0"), limit=10),
        "d1": _text(raw.get("d1"), limit=10),
        "totals": totals,
        "organic_7d": organic,
        "countries": countries[:20],
        "landing_pages": landing_pages[:12],
        "devices": devices,
    }


def _psi_section(snapshot: dict[str, Any] | None) -> dict[str, Any]:
    empty = {
        **_empty_source("Google PageSpeed Insights API v5", "安全快照不可用"),
        "tested_at": "",
        "mobile": None,
        "desktop": None,
    }
    if not snapshot or not _site_matches(snapshot.get("target_url")):
        return empty
    runs = snapshot.get("runs")
    if not isinstance(runs, dict):
        return empty

    def project(device: str) -> dict[str, Any] | None:
        value = runs.get(device)
        if not isinstance(value, dict) or not isinstance(value.get("median"), dict):
            return None
        median = value["median"]
        raw_runs = value.get("raw") if isinstance(value.get("raw"), list) else []
        fetch_times = {_text(row.get("fetchTime"), limit=40) for row in raw_runs if isinstance(row, dict) and row.get("fetchTime")}
        degraded = bool(value.get("high_variance")) or (len(raw_runs) > 1 and len(fetch_times) < len(raw_runs))
        return {
            "data_status": "DEGRADED" if degraded else _status(value.get("data_status")),
            "performance": _num(median.get("performance"), integer=True),
            "fcp_ms": _num(median.get("fcp_ms"), integer=True),
            "lcp_ms": _num(median.get("lcp_ms"), integer=True),
            "cls": _num(median.get("cls")),
            "tbt_ms": _num(median.get("tbt_ms"), integer=True),
            "speed_index_ms": _num(median.get("speed_index_ms"), integer=True),
            "payload_kb": _num(median.get("total_payload_kb"), integer=True),
            "request_count": _num(median.get("request_count"), integer=True),
            "run_count": len(raw_runs),
            "unique_fetch_times": len(fetch_times),
            "high_variance": bool(value.get("high_variance")),
        }

    tested_at = _text(snapshot.get("collected_at"), limit=40)
    mobile = project("mobile")
    desktop = project("desktop")
    overall = "REAL" if mobile and desktop and mobile["data_status"] == desktop["data_status"] == "REAL" else "DEGRADED"
    return {
        "source": "Google PageSpeed Insights API v5（Lighthouse lab）",
        "data_status": overall,
        "data_window": tested_at,
        "known_limitations": ["实验室数据不是 CrUX 真实用户数据", "TBT 不能替代真实用户 INP", "重复 fetchTime 不视为独立实验"],
        "cross_validation": "同策略多次运行；保留重复时间与高方差标记",
        "tested_at": tested_at,
        "mobile": mobile,
        "desktop": desktop,
    }


def _technical_section(live: dict[str, Any] | None, database: dict[str, Any] | None) -> dict[str, Any]:
    result: dict[str, Any] = {
        **_empty_source("HTTPS crawl + sitemap + remote SQLite read-only", "安全快照不可用"),
        "robots_status": None,
        "sitemap_status": None,
        "sitemap_urls": None,
        "crawled_urls": None,
        "http_200": None,
        "canonical_conflicts": None,
        "missing_titles": None,
        "missing_descriptions": None,
        "duplicate_title_groups": None,
        "suspected_broken_links": None,
        "indexing": {"data_status": "UNAVAILABLE", "indexed_urls": None, "reason": "URL Inspection 本轮未形成有效快照；sitemap URL 不等于已索引 URL"},
        "content": {"data_status": "UNAVAILABLE", "total": None, "published": None, "draft": None},
    }
    live_ok = bool(live and _site_matches((live.get("sitemap") or {}).get("urls", [""])[0] if isinstance((live.get("sitemap") or {}).get("urls"), list) and (live.get("sitemap") or {}).get("urls") else _PUBLIC_SITE_URL))
    if live_ok and live:
        pages = live.get("pages") if isinstance(live.get("pages"), list) else []
        safe_pages = [row for row in pages if isinstance(row, dict) and _site_matches(row.get("url"))]
        broken = live.get("broken_internal") if isinstance(live.get("broken_internal"), list) else []
        broken_targets = {_text(row.get("target"), limit=250) for row in broken if isinstance(row, dict)}
        result.update({
            "source": "直接 HTTPS crawl + sitemap + robots + remote SQLite read-only",
            "data_status": _status(live.get("data_status"), "REAL"),
            "data_window": _text(live.get("collected_at"), limit=40),
            "known_limitations": ["Cloudflare 邮件保护路径可能产生断链假阳性", "URL Inspection 未完成", "内容数据库未与 CMS 界面交叉验证"],
            "cross_validation": "sitemap 与页面 HTTPS 状态交叉检查",
            "robots_status": _num((live.get("robots") or {}).get("status"), integer=True),
            "sitemap_status": _num((live.get("sitemap") or {}).get("status"), integer=True),
            "sitemap_urls": _num((live.get("sitemap") or {}).get("url_count"), integer=True),
            "crawled_urls": len(safe_pages),
            "http_200": sum(1 for row in safe_pages if _num(row.get("status"), integer=True) == 200),
            "canonical_conflicts": len(live.get("canonical_conflicts") or {}) if isinstance(live.get("canonical_conflicts"), dict) else None,
            "missing_titles": sum(1 for row in safe_pages if not _text(row.get("title"))),
            "missing_descriptions": sum(1 for row in safe_pages if not _text(row.get("description"))),
            "duplicate_title_groups": len(live.get("duplicate_titles") or {}) if isinstance(live.get("duplicate_titles"), dict) else None,
            "suspected_broken_links": {
                "data_status": "DISPUTED" if broken else "REAL",
                "source_rows": len(broken),
                "unique_targets": len(broken_targets),
                "reason": "多个来源集中指向 Cloudflare 邮件保护目标，需浏览器抽样复测" if broken else "本轮未记录疑似断链",
            },
        })
    if database and _site_matches(_PUBLIC_SITE_URL):
        queries = database.get("queries") if isinstance(database.get("queries"), dict) else {}
        blog = queries.get("blogposts") if isinstance(queries.get("blogposts"), dict) else {}
        rows = blog.get("rows") if blog.get("code") == 0 and isinstance(blog.get("rows"), list) else None
        if rows is not None:
            statuses = [_text(row.get("status"), limit=20).lower() for row in rows if isinstance(row, dict)]
            result["content"] = {
                "data_status": "REAL",
                "total": len(statuses),
                "published": sum(1 for value in statuses if value == "published"),
                "draft": sum(1 for value in statuses if value == "draft"),
            }
    return result


def _sqlite_rows(path: Path, query: str, *, limit: int) -> list[sqlite3.Row]:
    """Execute a fixed SELECT through SQLite's read-only URI mode."""
    if not path.is_file():
        return []
    conn: sqlite3.Connection | None = None
    try:
        conn = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True, timeout=2)
        conn.row_factory = sqlite3.Row
        return list(conn.execute(query, (limit,)).fetchall())
    except (sqlite3.Error, OSError):
        return []
    finally:
        if conn is not None:
            conn.close()


def _workflow_projection(data_dir: Path) -> dict[str, Any]:
    rows = _sqlite_rows(
        data_dir / "workflows.db",
        "SELECT payload FROM wf_instances ORDER BY updated_at DESC LIMIT ?",
        limit=30,
    )
    items: list[dict[str, Any]] = []
    for row in rows:
        try:
            item = json.loads(row["payload"])
        except (KeyError, TypeError, json.JSONDecodeError):
            continue
        if not isinstance(item, dict) or item.get("template_id") not in _ALLOWED_WORKFLOW_TEMPLATES:
            continue
        runs = item.get("runs") if isinstance(item.get("runs"), dict) else {}
        safe_runs = [value for value in runs.values() if isinstance(value, dict)]
        state_counts: dict[str, int] = {}
        for run in safe_runs:
            state = _text(run.get("state"), limit=30).upper() or "UNKNOWN"
            state_counts[state] = state_counts.get(state, 0) + 1
        active = next((run for run in safe_runs if _text(run.get("state"), limit=30).upper() in {"RUNNING", "READY", "WAITING_HUMAN", "AWAITING_ACCEPTANCE"}), None)
        run_id = _safe_id((active or {}).get("runtime_run_id"))
        runtime_status = _text((active or {}).get("runtime_status"), limit=40).upper()
        status = _text(item.get("status"), limit=30).upper() or "UNKNOWN"
        evidence_present = any(bool(_text(run.get("evidence"), limit=1)) for run in safe_runs if _text(run.get("state"), limit=30).upper() == "DONE")
        blocked_evidence = any(
            any(marker in _text(run.get("evidence"), limit=800).lower() for marker in ("未发送", "blocked", "缺少具名审批", "未验证"))
            for run in safe_runs
        )
        if blocked_evidence:
            business_status = "BLOCKED"
        elif status == "PAUSED":
            business_status = "PAUSED"
        elif status == "DONE" and evidence_present:
            business_status = "EVIDENCE_PRESENT"
        elif status == "DONE":
            business_status = "AWAITING_ACCEPTANCE"
        else:
            business_status = "IN_PROGRESS"
        snapshot = item.get("template_snapshot") if isinstance(item.get("template_snapshot"), dict) else {}
        name = _text(item.get("title") or snapshot.get("name") or item.get("template_id"), limit=100)
        items.append({
            "instance_id": _safe_id(item.get("instance_id")),
            "template_id": _safe_id(item.get("template_id")),
            "name": name,
            "system_status": status,
            "business_status": business_status,
            "completed_nodes": state_counts.get("DONE", 0),
            "total_nodes": len(safe_runs),
            "current_node": _safe_id((active or {}).get("node_id")),
            "hermes_run_id": run_id,
            "runtime_status": runtime_status,
            "evidence_present": evidence_present,
            "updated_at": _text(item.get("updated_at"), limit=40),
        })
    return {
        "source": "workflows.db read-only projection",
        "data_status": "REAL" if rows else "UNAVAILABLE",
        "items": items[:8],
    }


def _timeline_projection(data_dir: Path) -> dict[str, Any]:
    rows = _sqlite_rows(
        data_dir / "timeline.db",
        "SELECT payload FROM timeline_nodes ORDER BY scheduled_at DESC LIMIT ?",
        limit=100,
    )
    items: list[dict[str, Any]] = []
    for row in rows:
        try:
            item = json.loads(row["payload"])
        except (KeyError, TypeError, json.JSONDecodeError):
            continue
        if not isinstance(item, dict) or not _site_matches(item.get("subject_ref")):
            continue
        context = item.get("context") if isinstance(item.get("context"), dict) else {}
        items.append({
            "node_id": _safe_id(item.get("node_id")),
            "kind": _text(item.get("kind"), limit=30).upper(),
            "state": _text(item.get("state"), limit=30).upper(),
            "intent": _text(item.get("intent"), limit=120),
            "scheduled_at": _text(item.get("scheduled_at"), limit=40),
            "runtime_state": _text(context.get("runtime_state"), limit=30).upper(),
            "hermes_run_id": _safe_id(context.get("hermes_run_id")),
        })
    return {
        "source": "timeline.db read-only projection",
        "data_status": "REAL" if rows else "UNAVAILABLE",
        "items": items[:8],
    }


def _report_section() -> dict[str, Any]:
    return {
        "source": "Asset Hub + Feishu delivery references",
        "data_status": "REAL",
        "data_window": _REPORT_DATE,
        "known_limitations": ["URL Inspection 与部分 GA4 对照窗口仍不可用", "公开聚合不在线读取飞书正文"],
        "cross_validation": "Asset Hub exists 已确认；飞书链接由交付记录提供",
        "status": "COMPLETE_WITH_UNAVAILABLE",
        "report_date": _REPORT_DATE,
        "asset_id": _REPORT_ASSET_ID,
        "asset_status": "REAL",
        "feishu_url": _REPORT_URL,
        "feishu_status": "LINK_PROVIDED",
        "gates": [
            {"name": "GSC / GA4 采集", "status": "COMPLETE"},
            {"name": "PSI / 技术 crawl", "status": "COMPLETE_WITH_DEGRADED"},
            {"name": "URL Inspection", "status": "UNAVAILABLE"},
            {"name": "结论与行动", "status": "COMPLETE"},
            {"name": "Asset Hub 归档", "status": "COMPLETE"},
            {"name": "飞书交付链接", "status": "LINK_PROVIDED"},
        ],
    }


@router.get("/overview")
def public_seo_control_tower_overview() -> dict[str, Any]:
    """Return one fixed-site, safe aggregate.  No query can widen its scope."""
    official = _load_json(_snapshot_path("SEO_CONTROL_TOWER_OFFICIAL_JSON", "/tmp/spain2-daily-official.json"))
    psi = _load_json(_snapshot_path("SEO_CONTROL_TOWER_PSI_JSON", "/tmp/spain2-daily-psi.json"))
    live = _load_json(_snapshot_path("SEO_CONTROL_TOWER_LIVE_JSON", "/tmp/spain2-daily-live.json"))
    database = _load_json(_snapshot_path("SEO_CONTROL_TOWER_DB_JSON", "/tmp/spain2-daily-db.json"))
    data_dir = Path(os.environ.get("SEO_CONTROL_TOWER_DATA_DIR", "/data/seo-stack/seoagents-data")).expanduser()
    return {
        "schema_version": "seo-control-tower.public.v2",
        "generated_at": _utc_now(),
        "site": {"hostname": _PUBLIC_SITE, "site_url": _PUBLIC_SITE_URL, "market": "Spain", "timezone": "UTC"},
        "gsc": _gsc_section(official),
        "ga4": _ga4_section(official),
        "psi": _psi_section(psi),
        "technical": _technical_section(live, database),
        "report": _report_section(),
        "execution": {
            "workflow": _workflow_projection(data_dir),
            "timeline": _timeline_projection(data_dir),
        },
        "aeo": {
            "source": "未配置真实探测器",
            "data_status": "UNAVAILABLE",
            "data_window": "",
            "known_limitations": ["不展示分数，不生成趋势"],
            "cross_validation": "不适用",
        },
    }


@router.head("/overview")
def public_seo_control_tower_overview_head() -> Response:
    """Cheap availability probe; do not read snapshots or serialize a body."""
    return Response(status_code=200, headers={"Cache-Control": "no-store"})


__all__ = ["router", "public_seo_control_tower_overview"]
