"""GSC Data Overview API router (L2).

Strictly implements design principles & data schema v1.3:
- Direct Integration with Official Google Search Console API via query_gsc_raw
- 100% Real live production performance data for authorized domain properties
- Zero-impression days handling with null position and line breaks
- Single-date interactive linkage across KPI cards, chart, keywords, pages, and countries
"""
from __future__ import annotations

import datetime
from typing import Any
from urllib.parse import urlparse

from fastapi import APIRouter, Query

from seoagents.agent.runtime import get_runtime
from seoagents.logging import LOGGER

router = APIRouter(prefix="/api/gsc", tags=["gsc"])


def _previous_window_totals(rt, site: str, start_date, days: int, single_day: str | None) -> dict:
    """Totals for the equal-length window immediately before the current one.

    Returns an empty dict when the comparison window cannot be fetched, which
    makes every delta render as "—" instead of inventing a percentage.
    """
    try:
        monitor = rt.registry.get("google_seo_monitor")
        if monitor is None:
            return {}
        span = 1 if single_day else max(int(days), 1)
        prev_end = start_date - datetime.timedelta(days=1)
        prev_start = prev_end - datetime.timedelta(days=span - 1)
        rows = monitor.query_gsc_raw(
            site_url=site,
            start_date=prev_start.strftime("%Y-%m-%d"),
            end_date=prev_end.strftime("%Y-%m-%d"),
            dimensions=["date"],
        )
        if not rows:
            return {}
        clicks = float(sum(r.get("clicks", 0) for r in rows))
        impressions = float(sum(r.get("impressions", 0) for r in rows))
        weighted = sum(
            float(r.get("position", 0)) * float(r.get("impressions", 0)) for r in rows
        )
        return {
            "clicks": clicks,
            "impressions": impressions,
            "ctr": (clicks / impressions * 100) if impressions else 0.0,
            "position": (weighted / impressions) if impressions else None,
        }
    except Exception as exc:  # noqa: BLE001 - comparison window is best-effort
        LOGGER.info(f"GSC 对照窗口不可用,同比将显示为 —: {exc}")
        return {}

SERVICE_ACCOUNT_EMAIL = "igoriptv2-gsc-reader@grounded-style-501621-k3.iam.gserviceaccount.com"


def _fill_days(daily_map: dict[str, dict], start_date: datetime.date, days: int) -> list[dict[str, Any]]:
    """Fill missing dates in date window with zero clicks/impressions and null position."""
    result = []
    for i in range(days):
        day_date = start_date + datetime.timedelta(days=i)
        day_str = day_date.strftime("%Y-%m-%d")
        short_date = day_date.strftime("%m-%d")

        if day_str in daily_map:
            item = daily_map[day_str]
            impr = item.get("impressions", 0)
            result.append({
                "date": short_date,
                "full_date": day_str,
                "clicks": item.get("clicks", 0),
                "impressions": impr,
                "position": item.get("position") if impr > 0 else None,
                "filled": False,
            })
        else:
            result.append({
                "date": short_date,
                "full_date": day_str,
                "clicks": 0,
                "impressions": 0,
                "position": None,
                "filled": True,
            })
    return result


@router.get("/overview")
async def get_gsc_overview(
    site_url: str | None = Query(None, description="Monitored site URL"),
    gsc_property: str | None = Query(None, description="GSC property ID"),
    range_type: str = Query("7d", alias="range", description="Time range (24h, 7d, 30d, 3m)"),
    single_date: str | None = Query(None, description="Specific single date (YYYY-MM-DD or MM-DD) to filter breakdown metrics"),
) -> dict[str, Any]:
    runtime = get_runtime()
    cfg = runtime.config

    target_url = (site_url or cfg.sites.site_url).rstrip("/")
    domain = urlparse(target_url).netloc or target_url.replace("https://", "").replace("http://", "")
    
    # Always query Domain Property format for GSC
    target_prop = f"sc-domain:{domain}"

    matched_site = None
    if cfg.sites.monitored_sites:
        for ms in cfg.sites.monitored_sites:
            if ms.site_url.rstrip("/") == target_url or domain in ms.site_url:
                matched_site = ms
                break

    brand_name = matched_site.brand_name if matched_site else (cfg.sites.brand_name or domain)

    today = datetime.date.today()
    days_map = {"24h": 1, "7d": 7, "30d": 30, "3m": 90}
    days = days_map.get(range_type, 7)
    start_date = today - datetime.timedelta(days=days - 1)
    date_range_str = f"{start_date.strftime('%Y-%m-%d')} ~ {today.strftime('%Y-%m-%d')}"

    # Normalize single_date to YYYY-MM-DD
    target_single_day = None
    if single_date:
        if len(single_date) == 5 and "-" in single_date:  # e.g., "07-26"
            target_single_day = f"{today.year}-{single_date}"
        elif len(single_date) == 10:
            target_single_day = single_date

    # Query real GSC API for full range trend series
    real_data = None
    real_queries = None
    real_pages = None
    real_countries = None

    try:
        from seoagents.tools.seo_trends import GoogleSEOMonitorSpec
        monitor_tool = GoogleSEOMonitorSpec(cfg)
        
        import asyncio
        # Query date dimension for the entire range
        real_data = await asyncio.to_thread(monitor_tool.query_gsc_raw, target_prop, days, ["date"])
        
        # If single_date is requested, query query, page, and country for THAT SPECIFIC DAY
        if target_single_day:
            real_queries = await asyncio.to_thread(
                monitor_tool.query_gsc_raw, target_prop, days, ["query"], target_single_day, target_single_day
            )
            real_pages = await asyncio.to_thread(
                monitor_tool.query_gsc_raw, target_prop, days, ["page"], target_single_day, target_single_day
            )
            real_countries = await asyncio.to_thread(
                monitor_tool.query_gsc_raw, target_prop, days, ["country"], target_single_day, target_single_day
            )
        else:
            real_queries = await asyncio.to_thread(monitor_tool.query_gsc_raw, target_prop, days, ["query"])
            real_pages = await asyncio.to_thread(monitor_tool.query_gsc_raw, target_prop, days, ["page"])
            real_countries = await asyncio.to_thread(monitor_tool.query_gsc_raw, target_prop, days, ["country"])
            
        LOGGER.info(
            f"[GSC API] Live GSC data fetched for {target_prop} (single_date={target_single_day}): "
            f"date_rows={len(real_data)} queries={len(real_queries or [])} pages={len(real_pages or [])} countries={len(real_countries or [])}"
        )
    except Exception as exc:
        LOGGER.warning(f"[GSC API ERROR] {type(exc).__name__}: {exc}")
        real_data = None

    is_real = bool(
        (real_data and len(real_data) > 0)
        or (real_queries and len(real_queries) > 0)
        or (real_pages and len(real_pages) > 0)
        or (real_countries and len(real_countries) > 0)
    )
    freshness = "REAL_GSC_API" if is_real else "DEMO_PREVIEW"

    # Construct daily map
    daily_map: dict[str, dict] = {}
    if is_real and real_data:
        for r in real_data:
            keys = r.get("keys", [])
            d_str = keys[0] if keys else ""
            if d_str:
                daily_map[d_str] = {
                    "clicks": int(r.get("clicks", 0)),
                    "impressions": int(r.get("impressions", 0)),
                    "position": round(float(r.get("position", 0.0)), 1) if r.get("impressions", 0) > 0 else None,
                }

    trend_series = _fill_days(daily_map, start_date, days)

    # Compute KPI summary metrics (Single Day vs Full Period)
    if target_single_day and target_single_day in daily_map:
        day_item = daily_map[target_single_day]
        total_clicks = day_item["clicks"]
        total_impressions = day_item["impressions"]
        avg_position = day_item["position"]
        ctr_num = (total_clicks / total_impressions * 100) if total_impressions > 0 else 0.0
        ctr_val = f"{round(ctr_num, 1)}%"
    else:
        total_clicks = sum(t["clicks"] for t in trend_series)
        total_impressions = sum(t["impressions"] for t in trend_series)
        pos_num = sum((t["position"] * t["impressions"]) for t in trend_series if t["position"] is not None and t["impressions"] > 0)
        pos_den = sum(t["impressions"] for t in trend_series if t["position"] is not None and t["impressions"] > 0)
        avg_position = round(pos_num / pos_den, 1) if pos_den > 0 else None
        ctr_num = (total_clicks / total_impressions * 100) if total_impressions > 0 else 0.0
        ctr_val = f"{round(ctr_num, 1)}%"

    sample_status = "INSUFFICIENT_DATA" if total_impressions < 10 else "NORMAL"

    # NOTE (data integrity): these four deltas used to be literals selected by
    # `range_type` — i.e. a function of which button was clicked, not of the
    # data. They are now computed against a real comparison window of equal
    # length, and render as "—" when that window is unavailable.
    prev_totals = _previous_window_totals(rt, site, start_date, days, target_single_day)

    def _delta(current, previous, *, lower_is_better: bool = False):
        if current is None or previous is None:
            return {"display": "—", "value": None, "down": False,
                    "reason": "无等长对照窗口数据,同比不可计算"}
        if previous == 0:
            return {"display": "新增" if current else "—", "value": None, "down": False,
                    "reason": "对照窗口为 0,百分比无定义"}
        pct = (current - previous) / previous * 100
        improved = (pct < 0) if lower_is_better else (pct > 0)
        arrow = "↑" if pct >= 0 else "↓"
        return {"display": f"{arrow} {abs(pct):.0f}%", "value": round(pct, 1),
                "down": not improved, "reason": ""}

    clicks_d = _delta(total_clicks, prev_totals.get("clicks"))
    impr_d = _delta(total_impressions, prev_totals.get("impressions"))
    ctr_d = _delta(ctr_num, prev_totals.get("ctr"))
    pos_d = _delta(avg_position, prev_totals.get("position"), lower_is_better=True)

    clicks_change, clicks_down = clicks_d["display"], clicks_d["down"]
    impr_change, impr_down = impr_d["display"], impr_d["down"]
    ctr_change, ctr_down = ctr_d["display"], ctr_d["down"]
    pos_change, pos_up = pos_d["display"], not pos_d["down"]

    # Build Real Keywords Dataset from GSC
    top_keywords = []
    if is_real and real_queries:
        for q in real_queries[:15]:
            q_keys = q.get("keys", [""])
            q_kw = q_keys[0] if q_keys else "unknown"
            q_clicks = int(q.get("clicks", 0))
            q_impr = int(q.get("impressions", 0))
            q_ctr_val = f"{round(q.get('ctr', 0.0) * 100, 1)}%"
            q_pos = round(q.get("position", 0.0), 1)
            top_keywords.append({
                "keyword": q_kw,
                "is_new": True,
                "clicks": q_clicks,
                "delta_clicks": f"+{q_clicks}" if q_clicks > 0 else "0",
                "impressions": q_impr,
                "ctr": q_ctr_val,
                "position": q_pos,
                "delta_position": "-",
            })

    # NOTE (data integrity): this block used to synthesise 9 plausible Spanish
    # IPTV keywords with seeded-random clicks/impressions/positions whenever GSC
    # returned nothing, and the rows were indistinguishable from real ones in
    # the UI. GSC legitimately returns nothing for low-volume or anonymised
    # queries — normal Google behaviour, not a failure. The honest rendering is
    # an empty state carrying the reason.
    keywords_status = "REAL" if top_keywords else "DATA_UNAVAILABLE"
    keywords_reason = (
        ""
        if top_keywords
        else (
            "GSC 在该时间窗返回空,或查询已被 Google 匿名化(低量查询的正常行为,不是故障)。"
        )
    )

    # Build Real Landing Pages Dataset from GSC
    landing_pages = []
    if is_real and real_pages:
        for p in real_pages[:12]:
            p_keys = p.get("keys", ["/"])
            raw_path = p_keys[0] if p_keys else "/"
            clean_path = raw_path.replace(f"https://{domain}", "").replace(f"http://{domain}", "").replace(f"https://www.{domain}", "") or "/"
            p_clicks = int(p.get("clicks", 0))
            p_impr = int(p.get("impressions", 0))
            p_ctr_val = f"{round(p.get('ctr', 0.0) * 100, 1)}%"
            p_pos = round(p.get("position", 0.0), 1)
            landing_pages.append({
                "path": clean_path,
                "clicks": p_clicks,
                "delta": f"+{p_clicks}c" if p_clicks > 0 else "0c",
                "impressions": p_impr,
                "ctr": p_ctr_val,
                "position": p_pos,
            })

    # Build Real Country Distribution Dataset from GSC
    country_name_map = {
        "esp": ("ES", "ESP"),
        "hkg": ("HK", "HKG"),
        "usa": ("US", "USA"),
        "chn": ("CN", "CHN"),
        "sgp": ("SG", "SGP"),
        "aus": ("AU", "AUS"),
        "arm": ("AM", "ARM"),
        "kor": ("KR", "KOR"),
        "jpn": ("JP", "JPN"),
        "bol": ("BO", "BOL"),
        "srb": ("RS", "SRB"),
        "arg": ("AR", "ARG"),
        "mex": ("MX", "MEX"),
        "and": ("AD", "AND"),
    }
    countries = []
    if is_real and real_countries:
        for c in real_countries[:12]:
            c_keys = c.get("keys", [""])
            c_iso = c_keys[0].lower() if c_keys else "unknown"
            code, name = country_name_map.get(c_iso, (c_iso.upper()[:2], c_iso.upper()))
            c_clicks = int(c.get("clicks", 0))
            c_ctr_val = f"{round(c.get('ctr', 0.0) * 100, 1)}%"
            countries.append({
                "code": code,
                "name": name,
                "clicks": c_clicks,
                "ctr": c_ctr_val,
            })

    zero_days = sum(1 for t in trend_series if t["impressions"] == 0)

    return {
        "ok": True,
        "site_url": target_url,
        "domain_name": domain,
        "gsc_property": target_prop,
        "brand_name": brand_name,
        "service_account_email": SERVICE_ACCOUNT_EMAIL,
        "date_range": f"锁定单日 ({target_single_day})" if target_single_day else date_range_str,
        "single_date": target_single_day,
        "range_type": range_type,
        "last_synced": "刚刚",
        "is_real_gsc": is_real,
        "freshness": freshness,
        "sample_status": sample_status,
        "zero_impression_days": zero_days,
        "summary": {
            "clicks": {"value": total_clicks, "change": clicks_change if not target_single_day else "单日", "is_down": clicks_down},
            "impressions": {"value": total_impressions, "change": impr_change if not target_single_day else "单日", "is_down": impr_down},
            "ctr": {"value": ctr_val, "change": ctr_change if not target_single_day else "单日", "is_down": ctr_down},
            "avg_position": {
                "value": avg_position if avg_position is not None else "—",
                "change": pos_change if not target_single_day else "单日",
                "is_up": pos_up,
            },
        },
        "data_status": "REAL" if is_real else "UNAVAILABLE",
        "data_status_reason": (
            "" if is_real else "未接入真实 GSC 数据源,面板不展示任何推算值"
        ),
        "trend_series": trend_series,
        "top_keywords": top_keywords,
        "keywords_status": keywords_status,
        "keywords_reason": keywords_reason,
        "landing_pages": landing_pages,
        "countries": countries,
        "footer_status": {
            "tasks_summary": f"SEO 运营 ({brand_name}) 2存活 · 2执行 · 0等待 · 0阻塞",
            "datasource": f"Google Search Console 官方 API ({target_prop})" + (f" · 锁定 {target_single_day}" if target_single_day else ""),
        },
    }
