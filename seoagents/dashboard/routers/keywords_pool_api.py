"""关键词池只读端点 (L2) — 双源：Semrush(主) + DataForSEO(对照)。

数据表：
- keyword_pool_sr  : Semrush es 库 broad-match（用户 2026-08-19 导出，26,616 词，
                     含 intent/trend/kd/cpc，KD 仅高价值词有值 1,838 个）
- keyword_pool     : DataForSEO keyword_ideas（2026-08-18 拉取，1,420 词，全量 KD）

source 参数决定查哪张：
- semrush    （默认）Semrush 口径，量最全
- dataforseo DataForSEO 口径
- both       联合视图：以 Semrush 为主，缺 KD 时补 DataForSEO 的 difficulty

排序语义：
- volume      市场热度（默认）
- difficulty  难度升序 = 最容易啃的词在前（无 KD 的词排最后，不掺沙子）
- keyword     字母序
"""
from __future__ import annotations

import os
import sqlite3
from typing import Any, Literal

from fastapi import APIRouter, HTTPException

router = APIRouter(prefix="/api/keywords", tags=["keywords"])

# Agent 专用别名：/api/v1/ 前缀被 AuthMiddleware 划入服务令牌通道
# （_SERVICE_PREFIXES），SEO HM / cron / 其他 agent 用 x-service-token
# 即可调用，不需要浏览器登录会话。与 /api/keywords/pool 共用同一实现。
router_v1 = APIRouter(prefix="/api/v1/keywords", tags=["keywords"])

_DB_FALLBACK = "/data/seo-stack/seoagents-data/keywords.db"


def _db_path() -> str:
    return os.environ.get("SEOAGENTS_KEYWORDS_DB", _DB_FALLBACK)


# 联合视图：Semrush 为主，KD 用 COALESCE 取 DataForSEO difficulty 补空
_BOTH_SQL = """
SELECT s.keyword AS keyword,
       s.vol     AS search_volume,
       COALESCE(s.kd, d.difficulty) AS difficulty,
       s.intent  AS intent,
       s.cpc     AS cpc,
       CASE WHEN s.kd IS NULL AND d.difficulty IS NOT NULL
            THEN 'semrush+dfseo' ELSE s.source END AS source
FROM keyword_pool_sr s
LEFT JOIN keyword_pool d ON d.keyword = s.keyword
"""


@router.get("/pool")
def pool(
    q: str = "",
    sort: Literal["volume", "difficulty", "keyword"] = "volume",
    source: Literal["semrush", "dataforseo", "both"] = "semrush",
    intent: str = "",
    min_vol: int = 0,
    limit: int = 100,
    offset: int = 0,
) -> dict[str, Any]:
    """关键词池查询。q 模糊匹配；limit 上限 500。"""
    limit = max(1, min(int(limit), 500))
    offset = max(0, int(offset))
    min_vol = max(0, int(min_vol))

    if source == "dataforseo":
        base = "SELECT keyword, search_volume, '' AS intent, cpc, difficulty, source FROM keyword_pool"
        vol_col, diff_col = "search_volume", "difficulty"
    elif source == "both":
        base = _BOTH_SQL
        vol_col, diff_col = "search_volume", "difficulty"
    else:  # semrush
        base = "SELECT keyword, vol AS search_volume, intent, cpc, kd AS difficulty, source FROM keyword_pool_sr"
        vol_col, diff_col = "search_volume", "difficulty"

    order = {
        "volume": f"{vol_col} DESC, {diff_col} ASC",
        # 无 KD 的词排最后：它们不是"零难度"，是"没数据"
        "difficulty": f"CASE WHEN {diff_col} IS NULL THEN 1 ELSE 0 END, {diff_col} ASC, {vol_col} DESC",
        "keyword": "keyword ASC",
    }[sort]

    where, params = ["1=1"], []
    if q.strip():
        where.append("keyword LIKE ?")
        params.append(f"%{q.strip()}%")
    if intent.strip():
        where.append("intent LIKE ?")
        params.append(f"%{intent.strip()}%")
    if min_vol > 0:
        where.append(f"{vol_col} >= ?")
        params.append(min_vol)

    wsql = " AND ".join(where)

    try:
        conn = sqlite3.connect(f"file:{_db_path()}?mode=ro", uri=True, timeout=10)
        conn.row_factory = sqlite3.Row
    except sqlite3.Error as e:
        raise HTTPException(503, f"keywords db 不可用: {e}") from e

    try:
        total = conn.execute(
            f"SELECT COUNT(*) FROM ({base}) WHERE {wsql}", params
        ).fetchone()[0]
        rows = conn.execute(
            f"SELECT * FROM ({base}) WHERE {wsql} ORDER BY {order} LIMIT ? OFFSET ?",
            [*params, limit, offset],
        ).fetchall()
        fresh = conn.execute(
            "SELECT MAX(updated_at) FROM keyword_pool_sr"
        ).fetchone()[0] or conn.execute(
            "SELECT MAX(updated_at) FROM keyword_pool"
        ).fetchone()[0]
    finally:
        conn.close()

    return {
        "total": total,
        "offset": offset,
        "limit": limit,
        "source": source,
        "updated_at": fresh,
        "items": [dict(r) for r in rows],
    }


# Agent 专用端点（服务令牌通道，实现与上面完全一致）
router_v1.get("/pool")(pool)


__all__ = ["router", "router_v1"]
