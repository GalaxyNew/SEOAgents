"""SEO v2 数据层 (G1-A) —— 分子化工序的共享缓存与关键词/外链/CWV 台账.

28 号文 §六 的四张表在这里落地，并配一个薄读写层供工具层直接 import。

设计约束（来自 28 号文 §4.1 与母卡 T20260812-01 红线）：

* **数据是粘合剂**：巡检工序把结果写进 ``seo_daily_snapshot``，产线工序开工
  先查表。工序之间不通过函数调用链传递结果，因此本模块不 import 任何
  seoagents 内部模块——保持零耦合，谁都能用。
* **去重靠数据库而不是靠约定**：``UNIQUE(date, site, task_name)`` 是硬约束。
  ``should_skip()`` 让调用方在**发起外部 API 请求之前**就能判断今天是否已经
  跑过，这才是省配额的地方；写入时的 ``ON CONFLICT`` 只是最后一道防线。
* **假数据零容忍**：``data_status`` 是必填的四态枚举
  (REAL/DEGRADED/MOCK/UNAVAILABLE)。写入时校验取值，非法值直接抛错，
  杜绝「忘了标状态 → 下游当真实数据用」这条 v1 病根。

表与既有 ``SeoHistoryStore`` 共用同一个 ``seoagents.sqlite3`` 文件，
互不干扰（表名无重叠），因此不需要迁移历史数据。
"""
from __future__ import annotations

import json
import os
import sqlite3
from datetime import date as _date
from pathlib import Path
from typing import Any, Iterable

__all__ = [
    "DataStatusValue",
    "SnapshotStore",
    "VALID_DATA_STATUS",
    "SCHEMA_SQL",
]

#: 允许的数据可信度取值。与 dojocore.quality.DataStatus 对齐，
#: 但这里刻意用字面量而不 import——数据层不依赖上层。
VALID_DATA_STATUS: frozenset[str] = frozenset(
    {"REAL", "DEGRADED", "MOCK", "UNAVAILABLE"}
)

DataStatusValue = str


SCHEMA_SQL = """
-- 每日快照表（巡检写、产线读，统一缓存层）
CREATE TABLE IF NOT EXISTS seo_daily_snapshot (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date TEXT NOT NULL,
    site TEXT NOT NULL,
    task_name TEXT NOT NULL,
    data_json TEXT NOT NULL,
    data_status TEXT NOT NULL DEFAULT 'REAL',
    created_at TEXT DEFAULT (datetime('now')),
    UNIQUE(date, site, task_name)
);
CREATE INDEX IF NOT EXISTS idx_snapshot_date_site
    ON seo_daily_snapshot (date, site);
CREATE INDEX IF NOT EXISTS idx_snapshot_task
    ON seo_daily_snapshot (task_name, date);

-- 关键词池（持续维护，产线直接查表不调 API）
CREATE TABLE IF NOT EXISTS keyword_pool (
    keyword TEXT NOT NULL,
    site TEXT NOT NULL,
    search_volume INTEGER,
    cpc REAL,
    difficulty REAL,
    intent TEXT,
    cluster TEXT,
    trend_weight REAL DEFAULT 1.0,
    competitor_count INTEGER,
    source TEXT,
    data_status TEXT NOT NULL DEFAULT 'REAL',
    first_seen TEXT DEFAULT (datetime('now')),
    last_updated TEXT DEFAULT (datetime('now')),
    status TEXT DEFAULT 'ACTIVE',
    PRIMARY KEY (keyword, site)
);
CREATE INDEX IF NOT EXISTS idx_keyword_site_status
    ON keyword_pool (site, status);
CREATE INDEX IF NOT EXISTS idx_keyword_volume
    ON keyword_pool (site, search_volume DESC);

-- 外链历史
CREATE TABLE IF NOT EXISTS backlink_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date TEXT NOT NULL,
    site TEXT NOT NULL,
    total_backlinks INTEGER,
    referring_domains INTEGER,
    domain_rating REAL,
    new_links INTEGER,
    lost_links INTEGER,
    toxic_count INTEGER DEFAULT 0,
    data_json TEXT,
    data_status TEXT NOT NULL DEFAULT 'REAL',
    created_at TEXT DEFAULT (datetime('now')),
    UNIQUE(date, site)
);

-- CWV 明细
CREATE TABLE IF NOT EXISTS cwv_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date TEXT NOT NULL,
    url TEXT NOT NULL,
    lcp REAL,
    inp REAL,
    cls REAL,
    fcp REAL,
    ttfb REAL,
    performance INTEGER,
    source TEXT DEFAULT 'pagespeed_api',
    data_status TEXT NOT NULL DEFAULT 'REAL',
    created_at TEXT DEFAULT (datetime('now')),
    UNIQUE(date, url)
);
CREATE INDEX IF NOT EXISTS idx_cwv_url_date ON cwv_history (url, date);
"""


def _today() -> str:
    return _date.today().isoformat()


def _check_status(value: str) -> str:
    """校验 data_status。

    非法取值直接抛 ``ValueError``——沉默地写入一个拼错的状态，等于把
    「这条数据可不可信」这个问题永久丢失，下游只能当它是真的。
    """
    v = (value or "").strip().upper()
    if v not in VALID_DATA_STATUS:
        raise ValueError(
            f"非法 data_status={value!r}；合法取值：{sorted(VALID_DATA_STATUS)}"
        )
    return v


class SnapshotStore:
    """四张 v2 表的读写层。

    用法::

        store = SnapshotStore("/data/seo-stack/seoagents-data")
        if store.should_skip(site="https://x.com", task_name="seo.gsc_performance"):
            return {"skipped": True, "reason": "cached_today"}
        ...  # 真正调外部 API
        store.write_snapshot(site=..., task_name=..., data={...}, data_status="REAL")
    """

    DB_FILENAME = "seoagents.sqlite3"

    def __init__(self, data_dir: str | os.PathLike[str]) -> None:
        self.dir = Path(os.path.expanduser(str(data_dir)))
        self.dir.mkdir(parents=True, exist_ok=True)
        self.db_path = self.dir / self.DB_FILENAME
        with self._conn() as conn:
            conn.executescript(SCHEMA_SQL)

    # -- infra -------------------------------------------------------------
    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=30000")
        return conn

    @staticmethod
    def _rows(cursor: sqlite3.Cursor) -> list[dict[str, Any]]:
        return [dict(r) for r in cursor.fetchall()]

    # -- seo_daily_snapshot ------------------------------------------------
    def should_skip(
        self, *, site: str, task_name: str, date: str | None = None
    ) -> bool:
        """今天这个站的这个工序是否已经跑过。

        这是**省 API 配额的关键**：调用方必须在发起外部请求之前问这一句。
        只认 ``REAL``/``DEGRADED``——``UNAVAILABLE`` 意味着上次根本没拿到
        数据，重试是应该的，不能拿一条失败记录把当天的机会堵死。
        """
        d = date or _today()
        with self._conn() as conn:
            row = conn.execute(
                "SELECT data_status FROM seo_daily_snapshot"
                " WHERE date=? AND site=? AND task_name=?",
                (d, site, task_name),
            ).fetchone()
        if row is None:
            return False
        return str(row["data_status"]).upper() in {"REAL", "DEGRADED"}

    def write_snapshot(
        self,
        *,
        site: str,
        task_name: str,
        data: Any,
        data_status: DataStatusValue = "REAL",
        date: str | None = None,
        overwrite: bool = True,
    ) -> dict[str, Any]:
        """写入一条工序结果。

        ``overwrite=True``（默认）时同日同站同工序覆盖——重跑一个已 skip 的
        工序通常是人为强制刷新，应该拿到新值。``overwrite=False`` 时保留
        首条，返回 ``{"written": False}``，用于严格幂等场景。
        """
        d = date or _today()
        status = _check_status(data_status)
        payload = data if isinstance(data, str) else json.dumps(
            data, ensure_ascii=False, default=str
        )
        sql = (
            "INSERT INTO seo_daily_snapshot (date, site, task_name, data_json, data_status)"
            " VALUES (?,?,?,?,?)"
        )
        if overwrite:
            sql += (
                " ON CONFLICT(date, site, task_name) DO UPDATE SET"
                " data_json=excluded.data_json,"
                " data_status=excluded.data_status,"
                " created_at=datetime('now')"
            )
        else:
            sql += " ON CONFLICT(date, site, task_name) DO NOTHING"
        with self._conn() as conn:
            cur = conn.execute(sql, (d, site, task_name, payload, status))
            written = cur.rowcount > 0
        return {
            "written": written,
            "date": d,
            "site": site,
            "task_name": task_name,
            "data_status": status,
        }

    def read_snapshot(
        self, *, site: str, task_name: str, date: str | None = None
    ) -> dict[str, Any] | None:
        """读一条工序结果；``data`` 字段已解析为 Python 对象。"""
        d = date or _today()
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM seo_daily_snapshot"
                " WHERE date=? AND site=? AND task_name=?",
                (d, site, task_name),
            ).fetchone()
        if row is None:
            return None
        rec = dict(row)
        rec["data"] = _loads(rec.get("data_json"))
        return rec

    def latest_snapshot(
        self, *, site: str, task_name: str, max_age_days: int = 7
    ) -> dict[str, Any] | None:
        """取最近一条（不限当天），用于「今天没跑，但昨天的数据还能用」。"""
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM seo_daily_snapshot"
                " WHERE site=? AND task_name=? AND date >= date('now', ?)"
                " ORDER BY date DESC LIMIT 1",
                (site, task_name, f"-{int(max_age_days)} days"),
            ).fetchone()
        if row is None:
            return None
        rec = dict(row)
        rec["data"] = _loads(rec.get("data_json"))
        return rec

    def list_snapshots(
        self, *, date: str | None = None, site: str | None = None
    ) -> list[dict[str, Any]]:
        """列出某天（默认今天）的全部工序，用于巡检总览与 M_t 汇总。"""
        d = date or _today()
        sql = "SELECT date, site, task_name, data_status, created_at FROM seo_daily_snapshot WHERE date=?"
        params: list[Any] = [d]
        if site:
            sql += " AND site=?"
            params.append(site)
        sql += " ORDER BY task_name"
        with self._conn() as conn:
            return self._rows(conn.execute(sql, params))

    # -- keyword_pool ------------------------------------------------------
    def upsert_keywords(
        self, keywords: Iterable[dict[str, Any]], *, site: str,
        data_status: DataStatusValue = "REAL", source: str | None = None,
    ) -> dict[str, int]:
        """批量写入关键词。

        只覆盖**本次真的带来了值**的字段:``COALESCE(excluded.x, keyword_pool.x)``。
        DataForSEO 有些词返回 volume 为 null,若直接覆盖会把上一次拿到的
        真实搜索量抹成 NULL——那比没更新更糟。
        """
        status = _check_status(data_status)
        rows = []
        for kw in keywords:
            name = (kw.get("keyword") or "").strip()
            if not name:
                continue
            rows.append(
                (
                    name,
                    site,
                    _int_or_none(kw.get("search_volume")),
                    _float_or_none(kw.get("cpc")),
                    _float_or_none(kw.get("difficulty")),
                    kw.get("intent"),
                    kw.get("cluster"),
                    _float_or_none(kw.get("trend_weight")) or 1.0,
                    _int_or_none(kw.get("competitor_count")),
                    kw.get("source") or source,
                    status,
                )
            )
        if not rows:
            return {"received": 0, "written": 0}
        sql = """
            INSERT INTO keyword_pool
              (keyword, site, search_volume, cpc, difficulty, intent, cluster,
               trend_weight, competitor_count, source, data_status, last_updated)
            VALUES (?,?,?,?,?,?,?,?,?,?,?, datetime('now'))
            ON CONFLICT(keyword, site) DO UPDATE SET
              search_volume    = COALESCE(excluded.search_volume, keyword_pool.search_volume),
              cpc              = COALESCE(excluded.cpc, keyword_pool.cpc),
              difficulty       = COALESCE(excluded.difficulty, keyword_pool.difficulty),
              intent           = COALESCE(excluded.intent, keyword_pool.intent),
              cluster          = COALESCE(excluded.cluster, keyword_pool.cluster),
              trend_weight     = COALESCE(excluded.trend_weight, keyword_pool.trend_weight),
              competitor_count = COALESCE(excluded.competitor_count, keyword_pool.competitor_count),
              source           = COALESCE(excluded.source, keyword_pool.source),
              data_status      = excluded.data_status,
              last_updated     = datetime('now')
        """
        with self._conn() as conn:
            conn.executemany(sql, rows)
        return {"received": len(rows), "written": len(rows)}

    def query_keywords(
        self,
        *,
        site: str | None = None,
        status: str = "ACTIVE",
        intent: str | None = None,
        cluster: str | None = None,
        min_volume: int | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        sql = "SELECT * FROM keyword_pool WHERE 1=1"
        params: list[Any] = []
        if site:
            sql += " AND site=?"
            params.append(site)
        if status:
            sql += " AND status=?"
            params.append(status)
        if intent:
            sql += " AND intent=?"
            params.append(intent)
        if cluster:
            sql += " AND cluster=?"
            params.append(cluster)
        if min_volume is not None:
            sql += " AND search_volume >= ?"
            params.append(int(min_volume))
        sql += " ORDER BY search_volume DESC NULLS LAST, keyword LIMIT ?"
        params.append(int(limit))
        with self._conn() as conn:
            return self._rows(conn.execute(sql, params))

    def archive_keywords(self, keywords: Iterable[str], *, site: str) -> int:
        names = [k for k in keywords if k]
        if not names:
            return 0
        with self._conn() as conn:
            cur = conn.executemany(
                "UPDATE keyword_pool SET status='ARCHIVED', last_updated=datetime('now')"
                " WHERE keyword=? AND site=?",
                [(k, site) for k in names],
            )
            return cur.rowcount

    # -- backlink_history --------------------------------------------------
    def write_backlinks(
        self,
        *,
        site: str,
        total_backlinks: int | None = None,
        referring_domains: int | None = None,
        domain_rating: float | None = None,
        new_links: int | None = None,
        lost_links: int | None = None,
        toxic_count: int = 0,
        data: Any = None,
        data_status: DataStatusValue = "REAL",
        date: str | None = None,
    ) -> dict[str, Any]:
        d = date or _today()
        status = _check_status(data_status)
        payload = None
        if data is not None:
            payload = data if isinstance(data, str) else json.dumps(
                data, ensure_ascii=False, default=str
            )
        with self._conn() as conn:
            conn.execute(
                """INSERT INTO backlink_history
                     (date, site, total_backlinks, referring_domains, domain_rating,
                      new_links, lost_links, toxic_count, data_json, data_status)
                   VALUES (?,?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(date, site) DO UPDATE SET
                     total_backlinks=excluded.total_backlinks,
                     referring_domains=excluded.referring_domains,
                     domain_rating=excluded.domain_rating,
                     new_links=excluded.new_links,
                     lost_links=excluded.lost_links,
                     toxic_count=excluded.toxic_count,
                     data_json=excluded.data_json,
                     data_status=excluded.data_status""",
                (
                    d, site, _int_or_none(total_backlinks), _int_or_none(referring_domains),
                    _float_or_none(domain_rating), _int_or_none(new_links),
                    _int_or_none(lost_links), int(toxic_count or 0), payload, status,
                ),
            )
        return {"date": d, "site": site, "data_status": status}

    def backlink_history(self, *, site: str, limit: int = 30) -> list[dict[str, Any]]:
        with self._conn() as conn:
            return self._rows(conn.execute(
                "SELECT * FROM backlink_history WHERE site=? ORDER BY date DESC LIMIT ?",
                (site, int(limit)),
            ))

    # -- cwv_history -------------------------------------------------------
    def write_cwv(
        self,
        *,
        url: str,
        lcp: float | None = None,
        inp: float | None = None,
        cls: float | None = None,
        fcp: float | None = None,
        ttfb: float | None = None,
        performance: int | None = None,
        source: str = "pagespeed_api",
        data_status: DataStatusValue = "REAL",
        date: str | None = None,
    ) -> dict[str, Any]:
        d = date or _today()
        status = _check_status(data_status)
        with self._conn() as conn:
            conn.execute(
                """INSERT INTO cwv_history
                     (date, url, lcp, inp, cls, fcp, ttfb, performance, source, data_status)
                   VALUES (?,?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(date, url) DO UPDATE SET
                     lcp=excluded.lcp, inp=excluded.inp, cls=excluded.cls,
                     fcp=excluded.fcp, ttfb=excluded.ttfb,
                     performance=excluded.performance, source=excluded.source,
                     data_status=excluded.data_status""",
                (
                    d, url, _float_or_none(lcp), _float_or_none(inp), _float_or_none(cls),
                    _float_or_none(fcp), _float_or_none(ttfb), _int_or_none(performance),
                    source, status,
                ),
            )
        return {"date": d, "url": url, "data_status": status}

    def cwv_history(self, *, url: str, limit: int = 30) -> list[dict[str, Any]]:
        with self._conn() as conn:
            return self._rows(conn.execute(
                "SELECT * FROM cwv_history WHERE url=? ORDER BY date DESC LIMIT ?",
                (url, int(limit)),
            ))

    # -- ops ---------------------------------------------------------------
    def table_names(self) -> list[str]:
        with self._conn() as conn:
            return [
                r[0] for r in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
                )
            ]

    def counts(self) -> dict[str, int]:
        out: dict[str, int] = {}
        with self._conn() as conn:
            for t in ("seo_daily_snapshot", "keyword_pool", "backlink_history", "cwv_history"):
                out[t] = conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
        return out


def _loads(raw: Any) -> Any:
    if raw in (None, ""):
        return None
    if not isinstance(raw, str):
        return raw
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return raw


def _int_or_none(v: Any) -> int | None:
    if v is None or v == "":
        return None
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return None


def _float_or_none(v: Any) -> float | None:
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None
