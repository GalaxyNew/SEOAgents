"""存储配额管理 —— 别让免费额度悄悄超支。

免费额度是按月重置的,超出部分才计费。危险在于:超支不会有任何提示,
等看到账单已经是下个月的事了。所以这里做三件事:

1. **记账**。每次读写都累计到当月用量,落盘持久化。
2. **闸门**。用量到达阈值(默认 90%)自动转只读 —— 停止写入但仍可读取,
   业务降级而不是中断。
3. **预估**。按当月已发生的日均用量线性外推到月底,提前告诉你会不会超。
   有历史月份时用「近三个月同期均值」修正,比纯线性更准。

设计上刻意不做「自动删旧文件腾空间」:那是拿数据安全换额度,
该由人决定删什么。系统只负责说清楚「照这个速度月底会超多少」。
"""
from __future__ import annotations

import calendar
import datetime as _dt
import json
import os
import threading
from pathlib import Path
from typing import Any

from dojocore.logging import LOGGER

_USAGE_PATH = Path(
    os.environ.get("ASSET_HUB_USAGE", "/data/seo-stack/seoagents-data/storage_usage.json")
)
_lock = threading.Lock()

# 计量口径。免费额度按月重置,所以所有计数都按 YYYY-MM 分桶。
METRICS = ("bytes_stored", "bytes_uploaded", "put_count", "get_count", "delete_count")


def _month(ts: _dt.datetime | None = None) -> str:
    return (ts or _dt.datetime.now()).strftime("%Y-%m")


def _load() -> dict[str, Any]:
    if not _USAGE_PATH.is_file():
        return {}
    try:
        return json.loads(_USAGE_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        LOGGER.warning(f"用量账本读取失败,按空处理: {exc}")
        return {}


def _save(data: dict[str, Any]) -> None:
    _USAGE_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = _USAGE_PATH.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, _USAGE_PATH)


def record(node_id: str, *, op: str, size: int = 0) -> None:
    """记一笔。op 取 put / get / delete。

    ``bytes_stored`` 是净增量:put 加、delete 减 —— 它代表「现在占了多少」。
    ``bytes_uploaded`` 只增不减 —— 它代表「这个月传了多少」,是流量口径。
    两者含义不同,合成一个数会让「删了很多但这个月传了很多」这种情况算错。
    """
    with _lock:
        data = _load()
        node = data.setdefault(node_id, {})
        m = node.setdefault(_month(), {k: 0 for k in METRICS})
        if op == "put":
            m["put_count"] += 1
            m["bytes_stored"] += size
            m["bytes_uploaded"] += size
        elif op == "get":
            m["get_count"] += 1
        elif op == "delete":
            m["delete_count"] += 1
            m["put_count"] += 1          # 七牛口径:DELETE 与 PUT 同属写请求
            m["bytes_stored"] = max(0, m["bytes_stored"] - size)
        _save(data)


def usage(node_id: str, month: str = "") -> dict[str, int]:
    return _load().get(node_id, {}).get(month or _month(), {k: 0 for k in METRICS})


def history(node_id: str, limit: int = 6) -> dict[str, dict[str, int]]:
    node = _load().get(node_id, {})
    return {m: node[m] for m in sorted(node)[-limit:]}


# ── 预估 ──────────────────────────────────────────────────────────────
def forecast(node_id: str) -> dict[str, Any]:
    """按当前速度推到月底会用多少。

    当月才过几天时线性外推会很飘,所以:
    * 已过天数 < 3 天 → 明确标注 `confidence: low`,不要拿它做决策
    * 有历史月份 → 用历史均值加权修正(各占一半)
    """
    now = _dt.datetime.now()
    days_in_month = calendar.monthrange(now.year, now.month)[1]
    day = now.day
    cur = usage(node_id)

    hist = history(node_id, limit=4)
    hist.pop(_month(), None)
    hist_avg = {
        k: (sum(v.get(k, 0) for v in hist.values()) / len(hist)) if hist else 0.0
        for k in METRICS
    }

    out: dict[str, Any] = {}
    for k in METRICS:
        linear = (cur.get(k, 0) / day) * days_in_month if day else 0.0
        if hist:
            projected = linear * 0.5 + hist_avg[k] * 0.5
        else:
            projected = linear
        out[k] = round(projected)

    return {
        "month": _month(),
        "day_of_month": day,
        "days_in_month": days_in_month,
        "current": cur,
        "projected_month_end": out,
        "history_months": len(hist),
        "confidence": "low" if day < 3 else ("medium" if not hist else "high"),
        "method": "线性外推" + ("(已用历史均值修正)" if hist else "(无历史,纯线性)"),
    }


# ── 闸门 ──────────────────────────────────────────────────────────────
def check(node: dict[str, Any]) -> dict[str, Any]:
    """这个节点现在还能不能写。

    返回 ``writable`` 与逐项占用率。没配 quota 的节点视为不限量。
    """
    q = node.get("quota") or {}
    if not q:
        return {"writable": True, "reason": "未配置配额,视为不限量", "ratios": {}}

    nid = node["id"]
    cur = usage(nid)
    stop_pct = float(q.get("stop_write_at_pct", 90)) / 100.0

    limits = {
        "bytes_stored": float(q.get("storage_gb", 0)) * 1024 ** 3,
        "bytes_uploaded": float(q.get("upload_gb", 0)) * 1024 ** 3,
        "put_count": float(q.get("put_requests", 0)),
        "get_count": float(q.get("get_requests", 0)),
    }
    ratios, breached = {}, []
    for k, lim in limits.items():
        if lim <= 0:          # 0 或缺省 = 该项不限
            continue
        r = cur.get(k, 0) / lim
        ratios[k] = round(r, 4)
        if r >= stop_pct:
            breached.append(f"{k} 已用 {r:.1%}(阈值 {stop_pct:.0%})")

    if breached:
        return {
            "writable": False,
            "reason": "；".join(breached) + " —— 已转为只读,读取不受影响",
            "ratios": ratios,
        }
    return {"writable": True, "reason": "", "ratios": ratios}


def report(nodes: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """给界面与 hm 看的全景:每个节点的用量、占比、预估、是否还能写。"""
    out = []
    for nid, node in nodes.items():
        c = check(node)
        f = forecast(nid)
        q = node.get("quota") or {}
        warn = []
        if q.get("storage_gb"):
            lim = float(q["storage_gb"]) * 1024 ** 3
            proj = f["projected_month_end"]["bytes_stored"]
            if proj > lim:
                warn.append(
                    f"照当前速度,月底存储将达 {proj / 1024 ** 3:.1f}GB,"
                    f"超出免费额度 {q['storage_gb']}GB"
                )
        if q.get("put_requests"):
            proj = f["projected_month_end"]["put_count"]
            if proj > float(q["put_requests"]):
                warn.append(f"照当前速度,月底写请求将达 {proj:,} 次,超出免费额度 {q['put_requests']:,} 次")
        out.append({
            "node": nid,
            "label": node.get("label"),
            "writable": c["writable"],
            "block_reason": c["reason"] if not c["writable"] else "",
            "quota": q,
            "usage": f["current"],
            "ratios": c["ratios"],
            "forecast": f["projected_month_end"],
            "confidence": f["confidence"],
            "warnings": warn,
        })
    return {
        "month": _month(),
        "nodes": out,
        "any_writable": any(n["writable"] for n in out),
        "warnings_total": sum(len(n["warnings"]) for n in out),
    }


__all__ = ["METRICS", "check", "forecast", "history", "record", "report", "usage"]
