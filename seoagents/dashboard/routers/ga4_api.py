"""GA4 只读端点 (L2) — 决策台 KPI 行 2 / 流量渠道 / 落地页 / 明细抽屉。

降级契约（与前端约定）：GA4 不可用时一律 200 + {"available": false, "reason"}，
前端渲染「未接入」空态。绝不 500 —— GA4 授权是外部依赖，
它挂了不能把决策台首页拖垮。

site 参数：域名（如 mejorsiptv.shop），映射到 config.seo_credentials.ga4_properties；
不传取映射表第一个。
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from dojocore.logging import LOGGER
from seoagents.agent.runtime import get_runtime
from seoagents.tools.ga4_client import Ga4Unavailable, run_report

router = APIRouter(prefix="/api/ga4", tags=["ga4"])
router_v1 = APIRouter(prefix="/api/v1/ga4", tags=["ga4"])  # agent 服务令牌通道


def _resolve(site: str) -> tuple[str, str]:
    """返回 (sa_path, property_id)；未配置抛 Ga4Unavailable。"""
    cfg = get_runtime().config
    props = dict(cfg.seo_credentials.ga4_properties or {})
    if not props:
        raise Ga4Unavailable("ga4_properties 未配置")
    key = (site or "").strip().removeprefix("https://").removeprefix("http://").strip("/")
    pid = props.get(key) or (next(iter(props.values())) if not key else None)
    if not pid:
        raise Ga4Unavailable(f"站点 {key} 无 GA4 property 映射")
    sa = cfg.seo_credentials.google_search_console.service_account_path
    return sa, pid


def _unavailable(reason: str) -> dict[str, Any]:
    return {"available": False, "reason": reason}


def _f(v: Any) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


@router.get("/overview")
def overview(site: str = "", days: int = 28) -> dict[str, Any]:
    """KPI 行 2：活跃用户 / 会话 / 互动率 / 关键事件 + 日趋势。"""
    days = max(1, min(int(days), 90))
    try:
        sa, pid = _resolve(site)
        totals = run_report(sa, pid, metrics=["activeUsers", "sessions", "engagementRate", "keyEvents"], days=days)
        daily = run_report(sa, pid, metrics=["activeUsers", "keyEvents"], dimensions=["date"], days=days, limit=100)
        organic = run_report(
            sa, pid, metrics=["sessions"], dimensions=["sessionDefaultChannelGroup"], days=days, limit=20,
        )
    except Ga4Unavailable as e:
        LOGGER.info(f"GA4 overview 不可用: {e}")
        return _unavailable(str(e))

    row = (totals["rows"] or [{}])[0].get("metrics", [])
    organic_sessions = 0.0
    for r in organic["rows"]:
        if (r["dims"] or [""])[0] == "Organic Search":
            organic_sessions = _f(r["metrics"][0])
    trend = sorted(
        ({"date": r["dims"][0], "users": _f(r["metrics"][0]), "key_events": _f(r["metrics"][1])} for r in daily["rows"]),
        key=lambda x: x["date"],
    )
    return {
        "available": True,
        "days": days,
        "active_users": _f(row[0]) if len(row) > 0 else 0,
        "sessions": _f(row[1]) if len(row) > 1 else 0,
        "engagement_rate": _f(row[2]) if len(row) > 2 else 0,
        "key_events": _f(row[3]) if len(row) > 3 else 0,
        "organic_sessions": organic_sessions,
        "trend": trend,
    }


@router.get("/channels")
def channels(site: str = "", days: int = 28) -> dict[str, Any]:
    """流量渠道分布（会话/互动率/关键事件）。"""
    days = max(1, min(int(days), 90))
    try:
        sa, pid = _resolve(site)
        rep = run_report(
            sa, pid,
            metrics=["sessions", "engagementRate", "keyEvents"],
            dimensions=["sessionDefaultChannelGroup"],
            days=days, order_by_metric="sessions", limit=12,
        )
    except Ga4Unavailable as e:
        return _unavailable(str(e))
    items = [
        {
            "channel": (r["dims"] or ["?"])[0],
            "sessions": _f(r["metrics"][0]),
            "engagement_rate": _f(r["metrics"][1]) if len(r["metrics"]) > 1 else 0,
            "key_events": _f(r["metrics"][2]) if len(r["metrics"]) > 2 else 0,
        }
        for r in rep["rows"]
    ]
    return {"available": True, "days": days, "items": items}


@router.get("/pages")
def pages(site: str = "", days: int = 28, limit: int = 20) -> dict[str, Any]:
    """落地页表现（会话/互动率/关键事件）。"""
    days = max(1, min(int(days), 90))
    limit = max(1, min(int(limit), 100))
    try:
        sa, pid = _resolve(site)
        rep = run_report(
            sa, pid,
            metrics=["sessions", "engagementRate", "keyEvents"],
            dimensions=["landingPagePlusQueryString"],
            days=days, order_by_metric="sessions", limit=limit,
        )
    except Ga4Unavailable as e:
        return _unavailable(str(e))
    items = [
        {
            "page": (r["dims"] or ["?"])[0],
            "sessions": _f(r["metrics"][0]),
            "engagement_rate": _f(r["metrics"][1]) if len(r["metrics"]) > 1 else 0,
            "key_events": _f(r["metrics"][2]) if len(r["metrics"]) > 2 else 0,
        }
        for r in rep["rows"]
    ]
    return {"available": True, "days": days, "items": items}


@router.get("/detail/users")
def detail_users(site: str = "", days: int = 28) -> dict[str, Any]:
    """用户明细抽屉：新老客 / 设备 / 地区。"""
    days = max(1, min(int(days), 90))
    try:
        sa, pid = _resolve(site)
        newret = run_report(sa, pid, metrics=["activeUsers"], dimensions=["newVsReturning"], days=days, limit=5)
        device = run_report(sa, pid, metrics=["activeUsers"], dimensions=["deviceCategory"], days=days, order_by_metric="activeUsers", limit=5)
        country = run_report(sa, pid, metrics=["activeUsers"], dimensions=["country"], days=days, order_by_metric="activeUsers", limit=8)
    except Ga4Unavailable as e:
        return _unavailable(str(e))
    pack = lambda rep: [{"name": (r["dims"] or ["?"])[0], "users": _f(r["metrics"][0])} for r in rep["rows"]]  # noqa: E731
    return {
        "available": True, "days": days,
        "new_vs_returning": pack(newret),
        "devices": pack(device),
        "countries": pack(country),
    }


# agent 通道复用同一实现
router_v1.get("/overview")(overview)
router_v1.get("/channels")(channels)
router_v1.get("/pages")(pages)
router_v1.get("/detail/users")(detail_users)

__all__ = ["router", "router_v1"]
