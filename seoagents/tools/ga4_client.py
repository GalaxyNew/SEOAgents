"""GA4 Data API 客户端 (L4) — 复用 GSC 的 service account，REST 直调零新依赖。

设计要点：
* 认证走 google-auth 的 AuthorizedSession（GSC 依赖链里已有），不引入
  google-analytics-data 包 —— 探针已实测 REST runReport 可用。
* 15 分钟内存缓存：GA4 配额按 property tokens 计，dashboard 30s 轮询
  绝不能直通 API。缓存键 = (property_id, 报表名, days)。
* 降级契约：凭证缺失 / property 未配置 / API 4xx-5xx → 抛 Ga4Unavailable，
  由 API 层转成 {"available": false, "reason": ...}，前端渲染空态不报错。
* GA4 数据天然延迟 24-48h，last_refresh 如实回传给前端标注新鲜度。
"""
from __future__ import annotations

import time
from typing import Any

from dojocore.logging import LOGGER

_SCOPES = ["https://www.googleapis.com/auth/analytics.readonly"]
_BASE = "https://analyticsdata.googleapis.com/v1beta"
_CACHE_TTL = 900  # 15 min

_cache: dict[tuple, tuple[float, Any]] = {}


class Ga4Unavailable(Exception):
    """GA4 不可用（未配置 / 无权限 / API 错误）——调用方转空态。"""


def _session(sa_path: str):
    try:
        from google.oauth2 import service_account
        from google.auth.transport.requests import AuthorizedSession
    except ImportError as e:  # pragma: no cover
        raise Ga4Unavailable(f"google-auth 未安装: {e}") from e
    try:
        creds = service_account.Credentials.from_service_account_file(sa_path, scopes=_SCOPES)
    except Exception as e:
        raise Ga4Unavailable(f"SA 凭证载入失败: {e}") from e
    return AuthorizedSession(creds)


def run_report(
    sa_path: str,
    property_id: str,
    *,
    metrics: list[str],
    dimensions: list[str] | None = None,
    days: int = 28,
    order_by_metric: str | None = None,
    limit: int = 50,
) -> dict[str, Any]:
    """runReport 封装（带缓存）。返回原始 rows 结构的轻量化版本。"""
    if not property_id or not str(property_id).strip():
        raise Ga4Unavailable("GA4 property_id 未配置")
    pid = str(property_id).strip().removeprefix("properties/")

    key = (pid, tuple(metrics), tuple(dimensions or []), days, order_by_metric, limit)
    now = time.time()
    hit = _cache.get(key)
    if hit and now - hit[0] < _CACHE_TTL:
        return hit[1]

    body: dict[str, Any] = {
        "dateRanges": [{"startDate": f"{days}daysAgo", "endDate": "today"}],
        "metrics": [{"name": m} for m in metrics],
        "limit": limit,
    }
    if dimensions:
        body["dimensions"] = [{"name": d} for d in dimensions]
    if order_by_metric:
        body["orderBys"] = [{"metric": {"metricName": order_by_metric}, "desc": True}]

    sess = _session(sa_path)
    try:
        resp = sess.post(f"{_BASE}/properties/{pid}:runReport", json=body, timeout=30)
    except Exception as e:
        raise Ga4Unavailable(f"GA4 请求失败: {e}") from e
    if resp.status_code != 200:
        try:
            msg = resp.json().get("error", {}).get("message", "")[:200]
        except Exception:
            msg = resp.text[:200]
        raise Ga4Unavailable(f"GA4 API {resp.status_code}: {msg}")

    data = resp.json()
    rows = []
    for r in data.get("rows") or []:
        rows.append({
            "dims": [d.get("value") for d in r.get("dimensionValues") or []],
            "metrics": [m.get("value") for m in r.get("metricValues") or []],
        })
    out = {"rows": rows, "row_count": data.get("rowCount", len(rows)), "fetched_at": now}
    _cache[key] = (now, out)
    return out


def clear_cache() -> None:
    _cache.clear()
