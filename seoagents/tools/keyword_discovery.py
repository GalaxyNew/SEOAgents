"""KeywordDiscoverySpec (L4) —— 追踪词由系统发现,不该由人填。

原先 ``tracked_keywords`` 是手填的,IGOR IPTV 只填了一个品牌词 ``IGOR IPTV``。
后果不只是「少几个词」:SERP 在追自己的品牌词、AEO 拿品牌词去问 AI(复述即命中,
可见度恒 100%)、趋势分析没有品类词可分析。一个自动化 SEO 系统让人定「追什么词」,
本身就说不通。

三路来源合并:

1. **GSC 实际查询词** —— 真实有展现的词。排名 11-30 那批最有价值:
   已经被 Google 认可到第二三页,推一把就能进首页。这是**唯一零成本且
   零猜测**的来源,权重最高。
2. **DataForSEO 拓词** —— 从种子词与竞品域名拓展,带搜索量。
   用来发现「我们还没有任何展现」的空白词。
3. **站点内容** —— 爬虫已经拿到的页面标题。反映「我们自认为在做什么」,
   用来校验前两路是否跑偏。

机会分只用真实数据算,不引入任何主观权重表。取不到某一路就少一路,
如实标注 sources,绝不用估算补位。
"""
from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlparse

import httpx

from dojocore.logging import LOGGER
from dojocore.quality import degraded, real, unavailable
from seoagents.config.models import SeoAgentsConfig
from seoagents.tools.base import BaseToolSpec

# 排名区间:进了索引但还没进首页,推动成本最低
_STRIKING_MIN, _STRIKING_MAX = 11.0, 30.0
_MAX_CANDIDATES = 60
_STOPWORDS = {
    "de", "la", "el", "en", "y", "a", "los", "las", "del", "un", "una", "para",
    "con", "por", "que", "es", "the", "and", "for", "of", "to", "in", "on",
}


def _norm(kw: str) -> str:
    return re.sub(r"\s+", " ", (kw or "").strip().lower())


def _tokens(kw: str) -> set[str]:
    return {t for t in re.split(r"[^\w\u00c0-\u017f]+", _norm(kw))
            if len(t) >= 3 and t not in _STOPWORDS}


def _business_tokens(gsc_rows: list[dict[str, Any]], site_terms: list[str]) -> set[str]:
    """从真实查询词里归纳出这门生意的核心词元。

    拓词接口会返回一堆高搜索量的泛词(实测 mejorsiptv 拿到 pirlo tv、twitch tv、
    omegle tv —— 搜索量 82 万,和「西班牙合法 IPTV 订阅」毫无关系)。
    没有这道过滤,机会分只会把生意做成流量投机。
    """
    counter: dict[str, int] = {}
    for r in gsc_rows:
        for t in _tokens(r.get("keyword", "")):
            counter[t] = counter.get(t, 0) + 1
    for t in site_terms:
        for tok in _tokens(t):
            counter[tok] = counter.get(tok, 0) + 1
    if not counter:
        return set()
    # 出现两次以上的才算核心词元;只出现一次的多半是长尾里的偶然词
    core = {t for t, n in counter.items() if n >= 2}
    return core or set(sorted(counter, key=lambda t: -counter[t])[:3])


class KeywordDiscoverySpec(BaseToolSpec):
    """自动发现值得追踪的关键词。"""

    def __init__(self, config: SeoAgentsConfig, store: Any = None) -> None:
        self.config = config
        self.store = store
        _k = (config.seo_credentials.dataforseo_api_key or "").strip()
        self.dfs_key = "" if _k.startswith("${") else _k
        self.dfs_base = config.seo_credentials.dataforseo_base_url.rstrip("/")
        self.location_name = (config.sites.serp_location_name or "").strip()
        self.language_code = (config.sites.serp_language_code or "").strip()

    def get_name(self) -> str:
        return "keyword_discovery"

    def get_schema(self) -> dict[str, Any]:
        return {
            "name": "keyword_discovery",
            "description": (
                "自动发现某站点值得追踪的关键词,合并三路真实来源:"
                "GSC 实际查询词(重点是排名 11-30 的临门词)、DataForSEO 拓词与搜索量、"
                "站点页面标题。返回带机会分的候选清单;不产生任何估算词。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "site_url": {"type": "string", "description": "目标站点;缺省用配置主站"},
                    "gsc_property": {"type": "string", "description": "GSC 资源,如 sc-domain:x.com"},
                    "days": {"type": "integer", "default": 28, "description": "GSC 回溯天数"},
                    "limit": {"type": "integer", "default": 30, "description": "返回候选词上限"},
                    "include_expansion": {
                        "type": "boolean",
                        "default": True,
                        "description": "是否调 DataForSEO 拓词(按次计费)",
                    },
                },
                "required": [],
            },
        }

    # ── 第一路:GSC 真实查询词 ────────────────────────────────────────
    def _from_gsc(self, gsc_property: str, days: int) -> tuple[list[dict[str, Any]], str]:
        try:
            from seoagents.tools.seo_trends import GoogleSEOMonitorSpec

            monitor = GoogleSEOMonitorSpec(self.config)
            rows = monitor.query_gsc_raw(gsc_property, days, ["query"])
        except Exception as exc:  # noqa: BLE001
            LOGGER.warning(f"GSC 查询词拉取失败: {exc}")
            return [], f"unavailable: {type(exc).__name__}"
        out = []
        for r in rows or []:
            keys = r.get("keys") or []
            if not keys:
                continue
            out.append({
                "keyword": _norm(str(keys[0])),
                "clicks": float(r.get("clicks", 0)),
                "impressions": float(r.get("impressions", 0)),
                "position": float(r.get("position", 0)) or None,
                "ctr": float(r.get("ctr", 0)),
            })
        return out, "real"

    # ── 第二路:DataForSEO 拓词 ──────────────────────────────────────
    async def _from_dataforseo(self, site_url: str, seeds: list[str]) -> tuple[list[dict[str, Any]], str]:
        if not self.dfs_key:
            return [], "unavailable: 未配置 DataForSEO 凭证"
        if not self.location_name:
            return [], "unavailable: 未配置 serp_location_name —— 拒绝用默认地域(美国)拓词"
        host = urlparse(site_url).hostname or site_url
        found: dict[str, dict[str, Any]] = {}

        async def post(path: str, payload: list[dict[str, Any]]) -> dict[str, Any] | None:
            try:
                async with httpx.AsyncClient(timeout=90.0) as c:
                    resp = await c.post(
                        f"{self.dfs_base}{path}",
                        headers={"Authorization": f"Basic {self.dfs_key}",
                                 "Content-Type": "application/json"},
                        json=payload,
                    )
                    d = resp.json()
            except Exception as exc:  # noqa: BLE001
                LOGGER.warning(f"DataForSEO {path} 失败: {exc}")
                return None
            if int(d.get("status_code", 0)) != 20000:
                LOGGER.warning(f"DataForSEO {path} 返回 {d.get('status_code')}: {d.get('status_message')}")
                return None
            return d

        def collect(d: dict[str, Any] | None, source: str) -> None:
            if not d:
                return
            for task in d.get("tasks") or []:
                for res in task.get("result") or []:
                    for item in (res.get("items") or []):
                        kw = _norm(str(item.get("keyword") or
                                        (item.get("keyword_data") or {}).get("keyword") or ""))
                        if not kw:
                            continue
                        info = item.get("keyword_info") or \
                            (item.get("keyword_data") or {}).get("keyword_info") or {}
                        prev = found.get(kw, {})
                        found[kw] = {
                            "keyword": kw,
                            "search_volume": info.get("search_volume") or prev.get("search_volume"),
                            "competition": info.get("competition") or prev.get("competition"),
                            "expansion_source": source,
                        }

        # 站点已排上的词:竞争力最真实的信号
        collect(await post("/v3/dataforseo_labs/google/ranked_keywords/live",
                           [{"target": host, "location_name": self.location_name,
                             "language_code": self.language_code or "en", "limit": 40}]),
                "ranked_keywords")
        # 种子拓展:发现还没有任何展现的空白词
        if seeds:
            collect(await post("/v3/dataforseo_labs/google/keyword_ideas/live",
                               [{"keywords": seeds[:5], "location_name": self.location_name,
                                 "language_code": self.language_code or "en", "limit": 40}]),
                    "keyword_ideas")
        if not found:
            return [], "unavailable: 两个拓词接口都没有返回数据"
        return list(found.values()), "real"

    # ── 第三路:站点页面标题 ─────────────────────────────────────────
    async def _from_site(self, site_url: str) -> tuple[list[str], str]:
        try:
            from seoagents.agent.runtime import get_runtime

            spec = get_runtime().registry.get("site_technical_auditor")
            if spec is None:
                return [], "unavailable: 站点爬虫未注册"
            rep = await spec.execute({"start_url": site_url}, "keyword_discovery")
        except Exception as exc:  # noqa: BLE001
            return [], f"unavailable: {type(exc).__name__}"
        terms: dict[str, int] = {}
        for u in (rep.get("crawled_urls") or []):
            slug = urlparse(u).path.strip("/").split("/")[-1]
            for w in re.split(r"[-_]+", slug):
                w = _norm(w)
                if len(w) < 3 or w in _STOPWORDS or w.isdigit():
                    continue
                terms[w] = terms.get(w, 0) + 1
        top = sorted(terms, key=lambda k: -terms[k])[:20]
        return top, "real" if top else "unavailable: 站点未提取到主题词"

    # ── 合并与打分 ──────────────────────────────────────────────────
    async def execute(self, arguments: dict[str, Any], session_id: str) -> dict[str, Any]:
        site_url = str(arguments.get("site_url") or self.config.sites.site_url).rstrip("/")
        gsc_property = str(arguments.get("gsc_property") or self.config.sites.gsc_property)
        days = int(arguments.get("days", 28))
        limit = int(arguments.get("limit", 30))
        do_expand = bool(arguments.get("include_expansion", True))

        sources: dict[str, str] = {}
        gsc_rows, sources["gsc"] = self._from_gsc(gsc_property, days)
        site_terms, sources["site_content"] = await self._from_site(site_url)

        # 种子:GSC 里已有展现的词 + 站点主题词,拿去拓展
        seeds = [r["keyword"] for r in sorted(
            gsc_rows, key=lambda r: -r["impressions"])[:3]] or site_terms[:3]
        expanded: list[dict[str, Any]] = []
        if do_expand:
            expanded, sources["dataforseo"] = await self._from_dataforseo(site_url, seeds)
        else:
            sources["dataforseo"] = "skipped: include_expansion=false"

        if not gsc_rows and not expanded:
            return unavailable(
                source="keyword_discovery",
                reason=f"三路来源都没有数据 —— {sources}",
                site=site_url,
                sources=sources,
            )

        core_tokens = _business_tokens(gsc_rows, site_terms)

        # 分层机会分:同层内才比数值。
        # 早先把「展现量」和「搜索量/100」直接相加,量级差三个数量级 ——
        # 排名 11 的临门词(展现 1,得分 6)被搜索量 82 万的泛词(得分 8230)
        # 彻底淹没,临门词一个都进不了推荐。
        #   tier 3 = 已在 11-30 名的临门词:成本最低、最该先推
        #   tier 2 = GSC 有展现的其他词:已被 Google 认可,只是还很远
        #   tier 1 = 拓词:纯机会,尚无任何实测
        merged: dict[str, dict[str, Any]] = {}
        for r in gsc_rows:
            kw = r["keyword"]
            pos = r["position"]
            striking = pos is not None and _STRIKING_MIN <= pos <= _STRIKING_MAX
            merged[kw] = {
                "keyword": kw,
                "from": ["gsc"],
                "impressions": r["impressions"],
                "clicks": r["clicks"],
                "position": pos,
                "striking_distance": striking,
                "tier": 3 if striking else 2,
                "opportunity": round(1.0 + r["impressions"], 3),
            }
        dropped_irrelevant: list[str] = []
        for e in expanded:
            kw = e["keyword"]
            if kw in merged:
                merged[kw]["from"].append("dataforseo")
                merged[kw]["search_volume"] = e.get("search_volume")
                continue
            # 相关性闸门:拓词必须与这门生意的核心词元有交集
            if core_tokens and not (_tokens(kw) & core_tokens):
                dropped_irrelevant.append(kw)
                continue
            sv = e.get("search_volume")
            merged[kw] = {
                "keyword": kw,
                "from": ["dataforseo"],
                "impressions": 0.0,
                "clicks": 0.0,
                "position": None,
                "striking_distance": False,
                "search_volume": sv,
                "expansion_source": e.get("expansion_source"),
                "tier": 1,
                "opportunity": round(float(sv) / 100.0, 3) if sv else 0.1,
            }
        for t in site_terms:
            if t in merged:
                merged[t]["from"].append("site_content")

        ranked = sorted(
            merged.values(), key=lambda x: (-x.get("tier", 1), -x["opportunity"])
        )[:min(limit, _MAX_CANDIDATES)]
        striking = [k["keyword"] for k in ranked if k.get("striking_distance")]
        payload = {
            "site": site_url,
            "gsc_property": gsc_property,
            "sources": sources,
            "total_candidates": len(merged),
            "returned": len(ranked),
            "striking_distance": striking,
            "core_tokens": sorted(core_tokens),
            "dropped_irrelevant": dropped_irrelevant[:20],
            "recommended": [k["keyword"] for k in ranked[:10]],
            "candidates": ranked,
        }
        bad = [k for k, v in sources.items() if not v.startswith("real")]
        if bad:
            return degraded(
                payload, source="keyword_discovery",
                reason=f"部分来源不可用: {[(k, sources[k]) for k in bad]}",
            )
        LOGGER.info(f"关键词发现 {site_url}: {len(merged)} 个候选,{len(striking)} 个临门词")
        return real(payload, source="keyword_discovery")


__all__ = ["KeywordDiscoverySpec"]
