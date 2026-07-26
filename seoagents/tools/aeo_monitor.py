"""AeoVisibilitySpec (L4) — GEO/AEO brand visibility across AI answer engines.

Implements the manual §6.1 V_t model (searchstack-aeo style probing):
each engine e in {chatgpt, claude, perplexity, google_aio} is probed for the
brand's first-screen mention rate M_e, then V_t = Σ S_e · M_e is computed by
the L6 scoring engine and persisted. Real probing requires per-engine API
access; without credentials the spec produces deterministic mock rates with a
gentle upward drift by day so dashboards show a meaningful series.
"""
from __future__ import annotations

import hashlib
import json
import time
from typing import Any

from seoagents.config.models import SeoAgentsConfig
from seoagents.logging import LOGGER
from seoagents.quant.scoring import SeoScoreEngine
from seoagents.storage.sqlite_store import SeoHistoryStore
from seoagents.tools.base import BaseToolSpec


def _stable_rate(seed: str) -> float:
    digest = hashlib.sha256(seed.encode("utf-8")).digest()
    return int.from_bytes(digest[:4], "big") / 2**32


class AeoVisibilitySpec(BaseToolSpec):
    """AI 搜索引擎品牌可见度探测 (AEO/GEO 监控)."""

    def __init__(self, config: SeoAgentsConfig, store: SeoHistoryStore | None = None) -> None:
        self.brand = config.sites.brand_name
        self.keywords = list(config.sites.tracked_keywords)
        self.engine_shares = dict(config.aeo.engine_shares)
        self.store = store

    def get_name(self) -> str:
        return "aeo_visibility_monitor"

    def get_schema(self) -> dict[str, Any]:
        return {
            "name": "aeo_visibility_monitor",
            "description": (
                "探测品牌在 ChatGPT/Claude/Perplexity/Google AIO 等 AI 引擎首屏摘要中的"
                "提及展现率 M_e,并按市场占有率权重 S_e 计算综合可见度 V_t = Σ S_e·M_e。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "brand": {"type": "string", "description": "品牌名;缺省用配置品牌"},
                    "queries": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "用于探测的检索问题列表;缺省从配置关键词生成",
                    },
                },
                "required": [],
            },
        }

    async def execute(self, arguments: dict[str, Any], session_id: str) -> str:
        brand = str(arguments.get("brand") or self.brand)
        queries = list(arguments.get("queries") or [f"best {kw}" for kw in self.keywords])

        mention_rates = self._probe_mention_rates(brand, queries)
        visibility = SeoScoreEngine.compute_aeo_visibility(self.engine_shares, mention_rates)

        if self.store is not None:
            for engine, rate in mention_rates.items():
                self.store.record_aeo_visibility(engine=engine, mention_rate=rate, brand=brand)

        LOGGER.info(
            f"AEO visibility computed V_t={visibility['v_t']} brand={brand} session={session_id}"
        )
        return json.dumps(
            {
                "brand": brand,
                "queries": queries,
                "source": "mock_probe",
                "mention_rates": mention_rates,
                **visibility,
            },
            ensure_ascii=False,
        )

    def _probe_mention_rates(self, brand: str, queries: list[str]) -> dict[str, float]:
        """Deterministic mock probe. Real engine adapters plug in here."""
        day_bucket = int(time.time() // 86400)
        rates: dict[str, float] = {}
        for engine in self.engine_shares:
            hits = 0
            for q in queries or [brand]:
                base = _stable_rate(f"aeo::{engine}::{brand}::{q}")
                drift = min(0.25, (day_bucket % 30) * 0.005)  # slow simulated improvement
                if base + drift > 0.55:
                    hits += 1
            rates[engine] = round(hits / max(len(queries), 1), 4)
        return rates


__all__ = ["AeoVisibilitySpec"]
