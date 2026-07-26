"""SerpTrackerSpec (L4) — daily Google SERP positions via karust/openserp.

Real mode queries the self-hosted OpenSERP container
(``GET {endpoint}/google/search?text=...&lang=EN&limit=N`` — note the real
upstream default port is 7000, not the 7070 written in early drafts of the
manual). When the endpoint is unreachable the spec emits deterministic mock
positions so the M_t pipeline still closes.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any
from urllib.parse import urlparse

import httpx

from seoagents.config.models import SeoAgentsConfig
from seoagents.logging import LOGGER
from seoagents.storage.sqlite_store import SeoHistoryStore
from seoagents.tools.base import BaseToolSpec


def _stable_position(seed: str) -> float:
    digest = hashlib.sha256(seed.encode("utf-8")).digest()
    return 1 + int.from_bytes(digest[:4], "big") % 20 + (digest[5] % 10) / 10


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

    async def execute(self, arguments: dict[str, Any], session_id: str) -> str:
        keywords = list(arguments.get("keywords") or self.tracked_keywords)
        limit = int(arguments.get("limit", 20))
        results: dict[str, Any] = {}

        for kw in keywords:
            entry = await self._track_one(kw, limit)
            results[kw] = entry
            if self.store is not None:
                self.store.record_serp_position(
                    keyword=kw, position=entry.get("position"), url=entry.get("url", "")
                )
        LOGGER.info(f"SERP tracking finished for {len(keywords)} keywords session={session_id}")
        return json.dumps({"site": self.site_url, "positions": results}, ensure_ascii=False)

    async def _track_one(self, keyword: str, limit: int) -> dict[str, Any]:
        try:
            async with httpx.AsyncClient(timeout=20.0) as client:
                resp = await client.get(
                    f"{self.endpoint}/google/search",
                    params={"text": keyword, "lang": "EN", "limit": limit},
                )
                resp.raise_for_status()
                payload = resp.json()
        except Exception as exc:  # noqa: BLE001 - network degradation path
            LOGGER.warning(f"OpenSERP unreachable ({exc}); mock position for '{keyword}'")
            pos = _stable_position(f"serp::{self.site_host}::{keyword}")
            return {
                "position": round(pos, 1),
                "url": f"{self.site_url}/{keyword.replace(' ', '-')}",
                "source": "mock",
            }

        items = payload.get("results", payload if isinstance(payload, list) else [])
        for item in items:
            url = str(item.get("url", ""))
            host = urlparse(url).hostname or ""
            if self.site_host and (host == self.site_host or host.endswith("." + self.site_host)):
                rank = item.get("rank") or item.get("position", {})
                if isinstance(rank, dict):
                    rank = rank.get("absolute")
                return {"position": float(rank or 0) or None, "url": url, "source": "openserp"}
        return {"position": None, "url": "", "source": "openserp", "note": "site not in top results"}


__all__ = ["SerpTrackerSpec"]
