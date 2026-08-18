"""关键词池只读端点 (L2) — DataForSEO 全量词表。

`keyword_pool` 表由独立的拉取脚本维护（一次性全量 + 定期刷新），这一层
只读。与 `keyword_candidates`（人工确认流）刻意解耦：池子是"市场上存在
哪些词"，候选是"哪些词值得本站追"。

排序语义：默认 `volume`（市场热度），`difficulty` 升序时是"最容易啃的
词在前"——运营选词时两种视角都要。
"""
from __future__ import annotations

import os
import sqlite3
from typing import Any, Literal

from fastapi import APIRouter, HTTPException

router = APIRouter(prefix="/api/keywords", tags=["keywords"])

_DB_FALLBACK = "/data/seo-stack/seoagents-data/keywords.db"


def _db_path() -> str:
    return os.environ.get("SEOAGENTS_KEYWORDS_DB", _DB_FALLBACK)


@router.get("/pool")
def pool(
    q: str = "",
    sort: Literal["volume", "difficulty", "keyword"] = "volume",
    limit: int = 100,
    offset: int = 0,
) -> dict[str, Any]:
    """全量关键词池。q 模糊匹配；limit 上限 500。"""
    limit = max(1, min(int(limit), 500))
    offset = max(0, int(offset))
    order = {
        "volume": "search_volume DESC, difficulty ASC",
        "difficulty": "difficulty ASC, search_volume DESC",
        "keyword": "keyword ASC",
    }[sort]

    where, params = "1=1", []
    if q.strip():
        where = "keyword LIKE ?"
        params.append(f"%{q.strip()}%")

    try:
        conn = sqlite3.connect(f"file:{_db_path()}?mode=ro", uri=True, timeout=10)
        conn.row_factory = sqlite3.Row
    except sqlite3.Error as e:
        raise HTTPException(503, f"keywords db 不可用: {e}") from e

    try:
        total = conn.execute(
            f"SELECT COUNT(*) FROM keyword_pool WHERE {where}", params
        ).fetchone()[0]
        rows = conn.execute(
            f"SELECT keyword, search_volume, cpc, competition, difficulty, updated_at "
            f"FROM keyword_pool WHERE {where} ORDER BY {order} LIMIT ? OFFSET ?",
            [*params, limit, offset],
        ).fetchall()
        fresh = conn.execute(
            "SELECT MAX(updated_at) FROM keyword_pool"
        ).fetchone()[0]
    finally:
        conn.close()

    return {
        "total": total,
        "offset": offset,
        "limit": limit,
        "updated_at": fresh,
        "items": [dict(r) for r in rows],
    }


__all__ = ["router"]
