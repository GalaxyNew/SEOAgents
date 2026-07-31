"""SQLite history persistence (L7) — audit runs, SERP positions, dead links, AEO visibility.

The manual's L7 mandate: "持久化存储技术审计的死链与收录历史数据" backed by SQLite.
Thread-safe via one connection per call; WAL mode for concurrent dashboard reads.
"""
from __future__ import annotations

import json
import os
import sqlite3
import time
from pathlib import Path
from typing import Any

_SCHEMA = """
CREATE TABLE IF NOT EXISTS audit_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts REAL NOT NULL,
    site TEXT NOT NULL,
    m_t REAL,
    clicks REAL,
    index_ratio REAL,
    error_count INTEGER,
    breakdown_json TEXT
);
CREATE TABLE IF NOT EXISTS serp_positions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts REAL NOT NULL,
    keyword TEXT NOT NULL,
    position REAL,
    url TEXT,
    engine TEXT DEFAULT 'google'
);
CREATE TABLE IF NOT EXISTS dead_links (
    url TEXT PRIMARY KEY,
    status_code INTEGER,
    first_seen REAL NOT NULL,
    last_seen REAL NOT NULL,
    fixed_at REAL,
    source_page TEXT
);
CREATE TABLE IF NOT EXISTS aeo_visibility (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts REAL NOT NULL,
    engine TEXT NOT NULL,
    mention_rate REAL NOT NULL,
    brand TEXT
);
CREATE TABLE IF NOT EXISTS skill_compilations (
    skill_id TEXT PRIMARY KEY,
    compiled_at REAL NOT NULL,
    m_t_at_compile REAL,
    trace_len INTEGER
);
CREATE INDEX IF NOT EXISTS idx_serp_kw_ts ON serp_positions (keyword, ts);
CREATE INDEX IF NOT EXISTS idx_audit_ts ON audit_runs (ts);
CREATE INDEX IF NOT EXISTS idx_aeo_ts ON aeo_visibility (ts);
"""


class SeoHistoryStore:
    def __init__(self, data_dir: str | os.PathLike[str]) -> None:
        self.dir = Path(os.path.expanduser(str(data_dir)))
        self.dir.mkdir(parents=True, exist_ok=True)
        self.db_path = self.dir / "seoagents.sqlite3"
        with self._conn() as conn:
            conn.executescript(_SCHEMA)

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=15)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    # -- writers -----------------------------------------------------------
    def previous_clicks(self, *, site: str) -> float | None:
        """Clicks recorded for the most recent scored run of ``site``.

        Returns None when there is no baseline yet. The caller must treat that
        as "C_t not computable" rather than substituting zero — a first run
        would otherwise report its entire traffic as growth.
        """
        with self._conn() as conn:
            row = conn.execute(
                "SELECT clicks FROM audit_runs WHERE site = ? AND m_t IS NOT NULL"
                " ORDER BY ts DESC LIMIT 1",
                (site,),
            ).fetchone()
        if row is None:
            return None
        try:
            return float(row[0])
        except (TypeError, ValueError):
            return None

    def record_audit_run(
        self,
        *,
        site: str,
        m_t: float,
        clicks: float,
        index_ratio: float,
        error_count: int,
        breakdown: dict[str, Any] | None = None,
        ts: float | None = None,
    ) -> None:
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO audit_runs (ts, site, m_t, clicks, index_ratio, error_count, breakdown_json)"
                " VALUES (?,?,?,?,?,?,?)",
                (
                    ts or time.time(),
                    site,
                    m_t,
                    clicks,
                    index_ratio,
                    error_count,
                    json.dumps(breakdown or {}, ensure_ascii=False),
                ),
            )

    def record_serp_position(
        self, *, keyword: str, position: float | None, url: str = "", engine: str = "google",
        ts: float | None = None,
    ) -> None:
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO serp_positions (ts, keyword, position, url, engine) VALUES (?,?,?,?,?)",
                (ts or time.time(), keyword, position, url, engine),
            )

    def record_dead_link(self, *, url: str, status_code: int, source_page: str = "") -> None:
        now = time.time()
        with self._conn() as conn:
            conn.execute(
                """INSERT INTO dead_links (url, status_code, first_seen, last_seen, source_page)
                   VALUES (?,?,?,?,?)
                   ON CONFLICT(url) DO UPDATE SET
                     status_code=excluded.status_code, last_seen=excluded.last_seen, fixed_at=NULL""",
                (url, status_code, now, now, source_page),
            )

    def mark_dead_link_fixed(self, url: str) -> None:
        with self._conn() as conn:
            conn.execute("UPDATE dead_links SET fixed_at=? WHERE url=?", (time.time(), url))

    def record_aeo_visibility(self, *, engine: str, mention_rate: float, brand: str,
                              ts: float | None = None) -> None:
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO aeo_visibility (ts, engine, mention_rate, brand) VALUES (?,?,?,?)",
                (ts or time.time(), engine, mention_rate, brand),
            )

    def record_skill_compilation(self, *, skill_id: str, m_t: float, trace_len: int) -> None:
        with self._conn() as conn:
            conn.execute(
                """INSERT INTO skill_compilations (skill_id, compiled_at, m_t_at_compile, trace_len)
                   VALUES (?,?,?,?)
                   ON CONFLICT(skill_id) DO UPDATE SET
                     compiled_at=excluded.compiled_at, m_t_at_compile=excluded.m_t_at_compile,
                     trace_len=excluded.trace_len""",
                (skill_id, time.time(), m_t, trace_len),
            )

    # -- readers -----------------------------------------------------------
    @staticmethod
    def _rows(cursor: sqlite3.Cursor) -> list[dict[str, Any]]:
        return [dict(r) for r in cursor.fetchall()]

    def recent_audit_runs(self, limit: int = 30) -> list[dict[str, Any]]:
        with self._conn() as conn:
            rows = self._rows(
                conn.execute("SELECT * FROM audit_runs ORDER BY ts DESC LIMIT ?", (limit,))
            )
        for r in rows:
            try:
                r["breakdown"] = json.loads(r.pop("breakdown_json") or "{}")
            except json.JSONDecodeError:
                r["breakdown"] = {}
        return rows

    def latest_serp_positions(self) -> list[dict[str, Any]]:
        with self._conn() as conn:
            return self._rows(conn.execute(
                """SELECT sp.* FROM serp_positions sp
                   JOIN (SELECT keyword, MAX(ts) AS mts FROM serp_positions GROUP BY keyword) latest
                     ON sp.keyword = latest.keyword AND sp.ts = latest.mts
                   ORDER BY sp.keyword"""
            ))

    def serp_history(self, keyword: str, limit: int = 60) -> list[dict[str, Any]]:
        with self._conn() as conn:
            return self._rows(conn.execute(
                "SELECT ts, position FROM serp_positions WHERE keyword=? ORDER BY ts DESC LIMIT ?",
                (keyword, limit),
            ))

    def open_dead_links(self) -> list[dict[str, Any]]:
        with self._conn() as conn:
            return self._rows(conn.execute(
                "SELECT * FROM dead_links WHERE fixed_at IS NULL ORDER BY last_seen DESC"
            ))

    def latest_aeo_visibility(self) -> list[dict[str, Any]]:
        with self._conn() as conn:
            return self._rows(conn.execute(
                """SELECT av.* FROM aeo_visibility av
                   JOIN (SELECT engine, MAX(ts) AS mts FROM aeo_visibility GROUP BY engine) latest
                     ON av.engine = latest.engine AND av.ts = latest.mts
                   ORDER BY av.engine"""
            ))

    def skill_compilations(self) -> list[dict[str, Any]]:
        with self._conn() as conn:
            return self._rows(conn.execute(
                "SELECT * FROM skill_compilations ORDER BY compiled_at DESC"
            ))


__all__ = ["SeoHistoryStore"]
