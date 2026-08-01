"""AeoVisibilitySpec (L4) — GEO/AEO brand visibility across AI answer engines.

Implements the V_t model::

    V_t = Σ_e S_e · M_e     e ∈ {chatgpt, claude, perplexity, google_aio}

**What changed and why.** The previous implementation derived every mention rate
from ``sha256(engine + brand + query)`` plus ``drift = (day_bucket % 30) * 0.005``
— a hash with a built-in daily upward trend. It reported ``"source": "mock_probe"``
in its own payload, but that field was dropped as the number travelled into the
M_t summary and the Feishu digest. The visible effect was an "AI visibility"
metric that improved every single day regardless of anything anyone did.

There is no acceptable synthetic substitute for this measurement, so there is no
fallback any more. Without a configured probe the tool reports UNAVAILABLE.

Real probes plug in through :class:`EngineProbe`. Each probe must return the
brand mention rate *and* the evidence needed to re-check it later: AI answers
change fast, so a rate without a model version and a timestamp is not a
measurement, it is a rumour.
"""
from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from dojocore.logging import LOGGER
from dojocore.quality import DataStatus, real, unavailable, window_iso, worst_status
from seoagents.config.models import SeoAgentsConfig
from seoagents.quant.scoring import SeoScoreEngine
from seoagents.storage.sqlite_store import SeoHistoryStore
from seoagents.tools.base import BaseToolSpec


class ProbeUnavailable(RuntimeError):
    """Raised by a probe that cannot measure right now (no creds, quota, outage)."""


@runtime_checkable
class EngineProbe(Protocol):
    """One AI answer engine's visibility probe.

    Implementations live outside this module (DataForSEO AI Overview parsing,
    OpenAI / Perplexity / Gemini APIs with a fixed prompt set, ...).
    """

    engine: str
    model_version: str

    async def measure(self, brand: str, queries: list[str]) -> dict[str, Any]:
        """Return ``{"mention_rate": float, "hits": int, "total": int, "evidence": {...}}``.

        Raise :class:`ProbeUnavailable` when the measurement cannot be taken.
        """
        ...


class AeoVisibilitySpec(BaseToolSpec):
    """AI 搜索引擎品牌可见度探测 (AEO/GEO 监控)."""

    def __init__(
        self,
        config: SeoAgentsConfig,
        store: SeoHistoryStore | None = None,
        probes: dict[str, EngineProbe] | None = None,
    ) -> None:
        self.brand = config.sites.brand_name
        self.keywords = list(config.sites.tracked_keywords)
        self.engine_shares = dict(config.aeo.engine_shares)
        self.store = store
        self.probes: dict[str, EngineProbe] = dict(probes or {})

    def get_name(self) -> str:
        return "aeo_visibility_monitor"

    def get_schema(self) -> dict[str, Any]:
        configured = sorted(self.probes) or ["(none configured)"]
        return {
            "name": "aeo_visibility_monitor",
            "description": (
                "探测品牌在 ChatGPT/Claude/Perplexity/Google AIO 等 AI 引擎首屏摘要中的"
                "提及展现率 M_e,并按市场占有率权重 S_e 计算综合可见度 V_t = Σ S_e·M_e。"
                f" 当前已配置探测器: {', '.join(configured)}。"
                " 未配置探测器时返回 DATA_UNAVAILABLE,不产生任何估算值。"
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

    def register_probe(self, probe: EngineProbe) -> None:
        """Attach a real engine probe. Called during runtime composition."""
        self.probes[probe.engine] = probe
        LOGGER.info(f"AEO probe registered: {probe.engine} ({probe.model_version})")

    async def execute(self, arguments: dict[str, Any], session_id: str) -> dict[str, Any]:
        brand = str(arguments.get("brand") or self.brand)
        queries = list(arguments.get("queries") or [f"best {kw}" for kw in self.keywords])

        if not self.probes:
            LOGGER.warning("AEO visibility requested but no engine probes are configured")
            return unavailable(
                source="aeo_visibility_monitor",
                reason=(
                    "未配置任何 AI 引擎探测器。AEO 可见度无法估算,只能实测。"
                    "接入方式见方案 07 号文 §5(Google AIO 走 DataForSEO SERP;"
                    "ChatGPT/Perplexity/Gemini 走各自 API + 固定 prompt 集)。"
                ),
                brand=brand,
                queries=queries,
                engines_expected=sorted(self.engine_shares),
            )

        started = window_iso()
        mention_rates: dict[str, float] = {}
        per_engine_meta: dict[str, dict[str, Any]] = {}
        statuses: list[DataStatus] = []

        for engine in self.engine_shares:
            probe = self.probes.get(engine)
            if probe is None:
                per_engine_meta[engine] = {
                    "data_status": DataStatus.UNAVAILABLE.value,
                    "reason": "该引擎无探测器",
                }
                statuses.append(DataStatus.UNAVAILABLE)
                continue
            try:
                measured = await probe.measure(brand, queries)
            except ProbeUnavailable as exc:
                per_engine_meta[engine] = {
                    "data_status": DataStatus.UNAVAILABLE.value,
                    "reason": str(exc),
                }
                statuses.append(DataStatus.UNAVAILABLE)
                continue
            except Exception as exc:  # noqa: BLE001 - probe boundary
                LOGGER.exception(f"AEO probe '{engine}' failed")
                per_engine_meta[engine] = {
                    "data_status": DataStatus.UNAVAILABLE.value,
                    "reason": f"探测异常: {exc}",
                }
                statuses.append(DataStatus.UNAVAILABLE)
                continue

            rate = float(measured["mention_rate"])
            mention_rates[engine] = rate
            per_engine_meta[engine] = {
                "data_status": DataStatus.REAL.value,
                "hits": measured.get("hits"),
                "total": measured.get("total"),
                "model_version": probe.model_version,
                "evidence": measured.get("evidence", {}),
            }
            statuses.append(DataStatus.REAL)
            if self.store is not None:
                self.store.record_aeo_visibility(engine=engine, mention_rate=rate, brand=brand)

        if not mention_rates:
            return unavailable(
                source="aeo_visibility_monitor",
                reason="所有已配置的探测器均不可用,详见 per_engine",
                brand=brand,
                per_engine=per_engine_meta,
            )

        # Only engines that actually reported are weighted, so a dead probe does
        # not silently drag V_t toward zero.
        measured_shares = {e: s for e, s in self.engine_shares.items() if e in mention_rates}
        visibility = SeoScoreEngine.compute_aeo_visibility(measured_shares, mention_rates)
        overall = worst_status(statuses)
        payload = {
            "brand": brand,
            "queries": queries,
            "mention_rates": mention_rates,
            "per_engine": per_engine_meta,
            "engines_measured": sorted(mention_rates),
            "engines_missing": sorted(set(self.engine_shares) - set(mention_rates)),
            **visibility,
        }

        if overall is DataStatus.REAL:
            return real(payload, source="aeo_visibility_monitor", data_window=started)
        return {
            **payload,
            "data_status": DataStatus.DEGRADED.value,
            "source": "aeo_visibility_monitor",
            "data_window": started,
            "degraded_reason": (
                "部分引擎无数据,V_t 仅覆盖 "
                f"{sorted(mention_rates)};缺失 {sorted(set(self.engine_shares) - set(mention_rates))}"
            ),
        }


__all__ = ["AeoVisibilitySpec", "EngineProbe", "ProbeUnavailable"]
