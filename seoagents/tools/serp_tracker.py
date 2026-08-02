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

from dojocore.logging import LOGGER
from dojocore.quality import DataStatus, real, unavailable, window_iso, worst_status
from seoagents.config.models import SeoAgentsConfig
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
        # DataForSEO 为主路径:自建 OpenSERP 走本机出口,极易被 Google 风控封成 429。
        _k = (config.seo_credentials.dataforseo_api_key or "").strip()
        self.dfs_key = "" if _k.startswith("${") else _k
        self.dfs_base = config.seo_credentials.dataforseo_base_url.rstrip("/")
        self.location_name = (config.sites.serp_location_name or "").strip()
        self.language_code = (config.sites.serp_language_code or "").strip()

    def get_name(self) -> str:
        return "serp_rank_tracker"

    def get_schema(self) -> dict[str, Any]:
        return {
            "name": "serp_rank_tracker",
            "description": (
                "抓取目标关键词的谷歌实测排位 R_i,t 并写入历史库。"
                "优先走 DataForSEO(按 sites.serp_location_name 锁定检索国家),"
                "不可用时回退自建 OpenSERP。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "keywords": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "要追踪的关键词列表;缺省用配置关键词",
                    },
                    "site_url": {
                        "type": "string",
                        "description": "查哪个站的排名;多站点场景必须传,不传用配置默认站",
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
        # 多站点:每次调用可指定查哪个站,不传才用配置里的默认站。
        # 不这么做的话,查 A 站的关键词会拿 B 站的域名去比对排名,
        # 结果恒为「未上榜」——错得很安静。
        site_url = str(arguments.get("site_url") or self.site_url).rstrip("/")
        site_host = urlparse(site_url).hostname or self.site_host
        started = window_iso()
        results: dict[str, Any] = {}
        statuses: list[DataStatus] = []

        for kw in keywords:
            entry = await self._track_one(kw, limit, site_host)
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
            "site": site_url,
            "positions": results,
            "engine": "google",
            "measured": sorted(k for k, v in results.items()
                               if v["data_status"] == DataStatus.REAL.value),
        }
        overall = worst_status(statuses) if statuses else DataStatus.UNAVAILABLE
        if overall is DataStatus.REAL:
            return real(payload, source=self._source_label(results), data_window=started)
        if overall is DataStatus.UNAVAILABLE and not payload["measured"]:
            return unavailable(
                source=self._source_label(results),
                reason="全部关键词均未取得实测排名,详见 positions 内每条的 degraded_reason",
                **payload,
            )
        return {
            **payload,
            "data_status": DataStatus.DEGRADED.value,
            "source": self._source_label(results),
            "data_window": started,
            "degraded_reason": "部分关键词未取得实测排名,未测项不得计入评分",
        }

    def _source_label(self, results: dict[str, Any]) -> str:
        """如实标注这批数据实际来自哪个供应商,便于溯源。"""
        provs = {v.get("provider") for v in results.values() if isinstance(v, dict) and v.get("provider")}
        if not provs:
            return f"openserp:{self.endpoint}"
        return " + ".join(sorted(provs))

    async def _track_one(self, keyword: str, limit: int, site_host: str = "") -> dict[str, Any]:
        """先走 DataForSEO(可锁地域、不受本机 IP 风控),不可用再退回 OpenSERP。"""
        if self.dfs_key:
            entry = await self._track_via_dataforseo(keyword, limit, site_host)
            if entry is not None:
                return entry
            LOGGER.info(f"DataForSEO 未取到 '{keyword}',回退 OpenSERP")
        return await self._track_via_openserp(keyword, limit, site_host)

    async def _track_via_dataforseo(self, keyword: str, limit: int, site_host: str = "") -> dict[str, Any] | None:
        """DataForSEO SERP 实时查询。返回 None 表示本路径不可用,交给调用方回退。

        location_name 必须显式传:不传的话 DataForSEO 默认按美国检索,
        且不会报错 —— 数据看着正常,国家却是错的。
        """
        site_host = site_host or self.site_host
        if not self.location_name:
            LOGGER.warning(
                "未配置 sites.serp_location_name,跳过 DataForSEO —— "
                "拒绝用数据商的默认地域(美国)冒充目标市场数据"
            )
            return None
        payload = [{
            "keyword": keyword,
            "location_name": self.location_name,
            "language_code": self.language_code or "en",
            "depth": max(int(limit), 10),
        }]
        url = f"{self.dfs_base}/v3/serp/google/organic/live/advanced"
        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                resp = await client.post(
                    url,
                    headers={"Authorization": f"Basic {self.dfs_key}",
                             "Content-Type": "application/json"},
                    json=payload,
                )
                resp.raise_for_status()
                data = resp.json()
        except Exception as exc:  # noqa: BLE001 - network boundary
            LOGGER.warning(f"DataForSEO 不可达 '{keyword}': {exc}")
            return None

        if int(data.get("status_code", 0)) != 20000:
            LOGGER.warning(f"DataForSEO 返回异常 {data.get('status_code')}: {data.get('status_message')}")
            return None
        tasks = data.get("tasks") or []
        if not tasks or int(tasks[0].get("status_code", 0)) != 20000:
            LOGGER.warning(f"DataForSEO task 异常: {tasks[0].get('status_message') if tasks else '空'}")
            return None
        results = tasks[0].get("result") or []
        items = (results[0].get("items") or []) if results else []
        if not items:
            return None

        src = f"dataforseo:{self.location_name}/{self.language_code or 'en'}"
        for item in items:
            if item.get("type") != "organic":
                continue
            host = (item.get("domain") or "").lower()
            if site_host and (host == site_host or host.endswith("." + site_host)):
                return {
                    "position": float(item.get("rank_absolute") or 0) or None,
                    "url": item.get("url", ""),
                    "ranked": True,
                    "data_status": DataStatus.REAL.value,
                    "provider": src,
                }
        # 测到了,只是没进前 N —— 这是真实观测,可以计入评分
        return {
            "position": None,
            "url": "",
            "ranked": False,
            "checked_top_n": len(items),
            "data_status": DataStatus.REAL.value,
            "provider": src,
        }

    async def _track_via_openserp(self, keyword: str, limit: int, site_host: str = "") -> dict[str, Any]:
        site_host = site_host or self.site_host
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
                "provider": f"openserp:{self.endpoint}",
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
            if site_host and (host == site_host or host.endswith("." + site_host)):
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
