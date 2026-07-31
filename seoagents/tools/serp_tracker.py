"""SerpTrackerSpec (L4) — daily Google SERP positions via karust/openserp.

Queries the self-hosted OpenSERP container
(``GET {endpoint}/google/search?text=...&lang=EN&limit=N`` — the real upstream
default port is 7000, not the 7070 written in early drafts of the manual).

**What changed and why.** Unreachable endpoints used to fall back to
``_stable_position()``, a sha256 of the keyword mapped into 1..20. Two separate
problems came out of that: the fabricated rank was indistinguishable from a
measured one downstream, and — more insidiously — a *parse* failure produced an
empty result set, which the caller reads as "we looked and the site was not
ranking", i.e. position 100. One Google front-end change would therefore be
recorded as a ranking collapse.

Now: unreachable or unparseable means UNAVAILABLE. "Measured but not ranking" is
a distinct, explicitly flagged outcome (``ranked: false``), because only the
latter should ever be penalised by the score.
"""
from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

import httpx

from seoagents.config.models import SeoAgentsConfig
from seoagents.logging import LOGGER
from seoagents.quality import DataStatus, real, unavailable, window_iso, worst_status
from seoagents.storage.sqlite_store import SeoHistoryStore
from seoagents.tools.base import BaseToolSpec


class SerpTrackerSpec(BaseToolSpec):
    """抓取目标关键词的谷歌实测 SERP 排位 (OpenSERP 自建容器 / mock 双模)."""

    def __init__(self, config: SeoAgentsConfig, store: SeoHistoryStore | None = None) -> None:
        self.endpoint = config.seo_credentials.openserp_endpoint.rstrip("/")
        self.site_url = config.sites.site_url
        self.site_host = urlparse(config.sites.site_url).hostname or ""
        self.tracked_keywords = list(config.sites.tracked_keywords)
        self.store = store

    def get_name(self) -> str:
        return "serp_rank_tracker"

    def get_schema(self) -> dict[str, Any]:
        return {
            "name": "serp_rank_tracker",
            "description": (
                "通过自建 OpenSERP 服务抓取目标关键词的谷歌搜索结果,"
                "定位本站 URL 的实测排位 R_i,t 并写入历史库。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "keywords": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "要追踪的关键词列表;缺省用配置关键词",
                    },
                    "limit": {
                        "type": "integer",
                        "default": 20,
                        "description": "每个关键词抓取的搜索结果条数上限",
                    },
                },
                "required": [],
            },
        }

    async def execute(self, arguments: dict[str, Any], session_id: str) -> dict[str, Any]:
        keywords = list(arguments.get("keywords") or self.tracked_keywords)
        limit = int(arguments.get("limit", 20))
        started = window_iso()
        results: dict[str, Any] = {}
        statuses: list[DataStatus] = []

        for kw in keywords:
            entry = await self._track_one(kw, limit)
            statuses.append(DataStatus(entry["data_status"]))
            results[kw] = entry
            # Only persist genuinely measured observations. Writing an
            # unmeasured keyword into the history table would pollute every
            # later trend comparison.
            if self.store is not None and entry["data_status"] == DataStatus.REAL.value:
                self.store.record_serp_position(
                    keyword=kw, position=entry.get("position"), url=entry.get("url", "")
                )
        LOGGER.info(f"SERP tracking finished for {len(keywords)} keywords session={session_id}")

        payload = {
            "site": self.site_url,
            "positions": results,
            "engine": "google",
            "measured": sorted(k for k, v in results.items()
                               if v["data_status"] == DataStatus.REAL.value),
        }
        overall = worst_status(statuses) if statuses else DataStatus.UNAVAILABLE
        if overall is DataStatus.REAL:
            return real(payload, source=f"openserp:{self.endpoint}", data_window=started)
        if overall is DataStatus.UNAVAILABLE and not payload["measured"]:
            return unavailable(
                source=f"openserp:{self.endpoint}",
                reason="全部关键词均未取得实测排名,详见 positions 内每条的 degraded_reason",
                **payload,
            )
        return {
            **payload,
            "data_status": DataStatus.DEGRADED.value,
            "source": f"openserp:{self.endpoint}",
            "data_window": started,
            "degraded_reason": "部分关键词未取得实测排名,未测项不得计入评分",
        }

    async def _track_one(self, keyword: str, limit: int) -> dict[str, Any]:
        try:
            async with httpx.AsyncClient(timeout=20.0) as client:
                resp = await client.get(
                    f"{self.endpoint}/google/search",
                    params={"text": keyword, "lang": "EN", "limit": limit},
                )
                resp.raise_for_status()
                payload = resp.json()
        except Exception as exc:  # noqa: BLE001 - network boundary
            LOGGER.warning(f"OpenSERP unreachable for '{keyword}': {exc}")
            return {
                "position": None,
                "url": "",
                "ranked": None,
                "data_status": DataStatus.UNAVAILABLE.value,
                "degraded_reason": f"OpenSERP 端点不可达: {exc}",
            }

        items = payload.get("results", payload if isinstance(payload, list) else [])
        if not items:
            # An empty result set is ambiguous: either the parser broke or the
            # query genuinely returned nothing. Never let it mean "rank 100".
            return {
                "position": None,
                "url": "",
                "ranked": None,
                "data_status": DataStatus.UNAVAILABLE.value,
                "degraded_reason": "SERP 返回空结果集,无法区分「解析失败」与「确实无结果」",
            }
        for item in items:
            url = str(item.get("url", ""))
            host = urlparse(url).hostname or ""
            if self.site_host and (host == self.site_host or host.endswith("." + self.site_host)):
                rank = item.get("rank") or item.get("position", {})
                if isinstance(rank, dict):
                    rank = rank.get("absolute")
                return {
                    "position": float(rank or 0) or None,
                    "url": url,
                    "ranked": True,
                    "data_status": DataStatus.REAL.value,
                }
        # Measured successfully, site simply is not in the top N. This is a real
        # observation and the only case the score may penalise.
        return {
            "position": None,
            "url": "",
            "ranked": False,
            "checked_top_n": len(items),
            "data_status": DataStatus.REAL.value,
        }


__all__ = ["SerpTrackerSpec"]
