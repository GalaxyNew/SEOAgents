"""关键词候选与写回 (L2)。

`keyword_discovery` 工具能找出临门词(排名 11–30,推一把就进首页),但它只
产出候选,没有落到 `tracked_keywords` —— 等于发现了却没纳入监控,临门一脚
没踢。这一层把最后一步补上。

三个刻意的决定:

* **必须人工确认,不自动写回**。拓词有跑偏风险:首版曾推荐出 `pirlo tv`、
  `twitch tv` 这类与「西班牙合法 IPTV 订阅」毫无关系的高流量泛词。业务词元
  闸门已经拦掉大部分,但拦不干净的那部分只有人能判。

* **被否决的词要记住**。否则每跑一次发现,同一批垃圾词又推一遍,人看两次
  就不看了 —— 那样这个功能等于没有。

* **写回落到具体站点**。每个 `monitored_sites[]` 有自己的 `tracked_keywords`,
  写进全局那份没有意义:A 站的临门词拿去监控 B 站,数据全是噪声。
"""
from __future__ import annotations

import datetime as _dt
import json
import os
import sqlite3
import threading
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from dojocore.logging import LOGGER
from seoagents.agent.runtime import get_runtime
from seoagents.config import ConfigStore
from seoagents.agent.models import ToolCall

_lock = threading.Lock()


def _db_path() -> str:
    return os.environ.get(
        "SEOAGENTS_KEYWORDS_DB", "/data/seo-stack/seoagents-data/keywords.db"
    )


_SCHEMA = """
CREATE TABLE IF NOT EXISTS keyword_candidates (
    site         TEXT NOT NULL,
    keyword      TEXT NOT NULL,
    tier         INTEGER NOT NULL,
    opportunity  REAL,
    position     REAL,
    impressions  INTEGER,
    search_volume INTEGER,
    sources      TEXT NOT NULL DEFAULT '',
    status       TEXT NOT NULL DEFAULT 'pending'
                 CHECK (status IN ('pending','approved','rejected')),
    discovered_at TEXT NOT NULL,
    decided_at   TEXT,
    decided_by   TEXT,
    PRIMARY KEY (site, keyword)
);
CREATE INDEX IF NOT EXISTS idx_kw_site ON keyword_candidates(site, status, tier DESC);
"""


def _conn() -> sqlite3.Connection:
    os.makedirs(os.path.dirname(_db_path()), exist_ok=True)
    c = sqlite3.connect(_db_path(), timeout=15)
    c.row_factory = sqlite3.Row
    c.executescript(_SCHEMA)
    return c


def _now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).isoformat()


def _user(request: Request) -> str:
    return getattr(request.state, "user", None) or "unknown"


router = APIRouter(prefix="/api/keywords", tags=["keywords"])


class DiscoverIn(BaseModel):
    site_url: str
    expand: bool = True


@router.post("/discover")
async def discover(body: DiscoverIn) -> dict[str, Any]:
    """跑一次发现,把候选写进待办池。

    已经批准或否决过的词不会被重新塞回 pending —— 人做过的判断要留住。
    """
    rt = get_runtime()
    try:
        res = await rt.executor.execute_one(
            ToolCall(name="keyword_discovery",
                     arguments={"site_url": body.site_url, "expand": body.expand}),
            session_id="api:keyword_discover",
        )
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(502, f"发现工具执行失败: {exc}") from exc
    if not res.ok:
        raise HTTPException(502, f"发现工具返回失败: {res.error}")

    try:
        result = json.loads(res.content)
    except json.JSONDecodeError as exc:
        raise HTTPException(502, f"发现工具返回的不是 JSON: {res.content[:200]}") from exc

    if result.get("data_status") != "REAL":
        raise HTTPException(502, detail={
            "code": "DISCOVERY_UNAVAILABLE",
            "message": result.get("reason") or "发现工具返回非 REAL",
        })

    # 信封是**扁平**的:candidates / recommended 等就在顶层,不在 data 之下。
    # 我第一版按嵌套解析,拿到的永远是空 —— 所以这里照实测的形状写。
    data = result
    candidates = data.get("candidates") or []
    site = body.site_url.rstrip("/")
    added = kept = 0
    with _lock, _conn() as c:
        for k in candidates:
            kw = str(k.get("keyword") or "").strip()
            if not kw:
                continue
            row = c.execute(
                "SELECT status FROM keyword_candidates WHERE site=? AND keyword=?",
                (site, kw),
            ).fetchone()
            if row and row["status"] in ("approved", "rejected"):
                kept += 1          # 人已经判过,不要再翻出来问一遍
                continue
            c.execute(
                "INSERT INTO keyword_candidates"
                " (site,keyword,tier,opportunity,position,impressions,search_volume,"
                "  sources,status,discovered_at)"
                " VALUES (?,?,?,?,?,?,?,?,'pending',?)"
                " ON CONFLICT(site,keyword) DO UPDATE SET"
                "  tier=excluded.tier, opportunity=excluded.opportunity,"
                "  position=excluded.position, impressions=excluded.impressions,"
                "  search_volume=excluded.search_volume, sources=excluded.sources,"
                "  discovered_at=excluded.discovered_at",
                (site, kw, int(k.get("tier") or 1), k.get("opportunity"),
                 k.get("position"), k.get("impressions"), k.get("search_volume"),
                 str(k.get("source") or k.get("expansion_source") or ""), _now()),
            )
            added += 1
    return {
        "ok": True, "site": site, "discovered": len(candidates),
        "pending_added": added, "skipped_already_decided": kept,
        "dropped_irrelevant": data.get("dropped_irrelevant") or [],
    }


@router.get("/candidates")
def candidates(site_url: str = "", status: str = "pending",
               limit: int = 200) -> dict[str, Any]:
    where, args = ["status = ?"], [status]
    if site_url:
        where.append("site = ?")
        args.append(site_url.rstrip("/"))
    args.append(limit)
    with _conn() as c:
        rows = [dict(r) for r in c.execute(
            f"SELECT * FROM keyword_candidates WHERE {' AND '.join(where)}"  # noqa: S608
            " ORDER BY tier DESC, opportunity DESC LIMIT ?", args)]
        counts = {
            s: c.execute(
                "SELECT COUNT(*) FROM keyword_candidates WHERE status=?" +
                (" AND site=?" if site_url else ""),
                (s, site_url.rstrip("/")) if site_url else (s,),
            ).fetchone()[0]
            for s in ("pending", "approved", "rejected")
        }
    return {"candidates": rows, "total": len(rows), "counts": counts}


class DecideIn(BaseModel):
    site_url: str
    keywords: list[str]
    action: str          # approve | reject


@router.post("/decide")
def decide(body: DecideIn, request: Request) -> dict[str, Any]:
    """批准或否决。批准会真的写进该站点的 tracked_keywords。"""
    if body.action not in ("approve", "reject"):
        raise HTTPException(422, "action 必须是 approve 或 reject")
    site = body.site_url.rstrip("/")
    kws = [k.strip() for k in body.keywords if k.strip()]
    if not kws:
        raise HTTPException(422, "keywords 为空")

    written: list[str] = []
    if body.action == "approve":
        written = _append_tracked_keywords(site, kws)

    new_status = {"approve": "approved", "reject": "rejected"}[body.action]
    with _lock, _conn() as c:
        for kw in kws:
            c.execute(
                "UPDATE keyword_candidates SET status=?, decided_at=?, decided_by=?"
                " WHERE site=? AND keyword=?",
                (new_status, _now(), _user(request), site, kw),
            )
    return {"ok": True, "action": body.action, "site": site,
            "count": len(kws), "written_to_config": written}


def _append_tracked_keywords(site: str, keywords: list[str]) -> list[str]:
    """把关键词并进该站点的 tracked_keywords 并落盘。

    只动匹配到的那个站点。写进全局那份没有意义 —— A 站的临门词拿去监控 B 站,
    数据全是噪声。找不到站点就报错,而不是悄悄写到全局去。
    """
    store = ConfigStore.get_instance()
    raw = store.raw()
    sites = ((raw.get("sites") or {}).get("monitored_sites")) or []
    if not isinstance(sites, list):
        raise HTTPException(500, "配置里的 monitored_sites 不是列表")

    target = None
    for item in sites:
        if isinstance(item, dict) and str(item.get("site_url", "")).rstrip("/") == site:
            target = item
            break
    if target is None:
        raise HTTPException(404, f"配置里没有这个受监控站点: {site}")

    existing = [str(k) for k in (target.get("tracked_keywords") or [])]
    lower = {k.lower() for k in existing}
    added = [k for k in keywords if k.lower() not in lower]
    if not added:
        return []
    target["tracked_keywords"] = existing + added
    store.save_raw(raw)
    # 落盘还不够:运行中的 Runtime 持有装配时的配置快照,不刷新的话
    # 下一轮演化仍按旧关键词跑 —— 界面上看着已经加进去了,实际没生效。
    try:
        get_runtime().reload_config()
    except Exception as exc:  # noqa: BLE001
        LOGGER.warning(f"配置已落盘但 runtime 未能热加载({exc}),重启后生效")
    LOGGER.info(f"{site} 的 tracked_keywords 新增 {len(added)} 个: {added}")
    return added


@router.get("/tracked")
def tracked() -> dict[str, Any]:
    """各站点当前在监控哪些词 —— 写回后用它确认真的进去了。"""
    cfg = get_runtime().config
    return {
        "sites": [
            {"site_url": s.site_url, "brand_name": s.brand_name,
             "tracked_keywords": list(s.tracked_keywords)}
            for s in cfg.sites.monitored_sites
        ]
    }


__all__ = ["router"]
