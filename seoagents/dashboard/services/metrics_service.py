"""Metrics aggregation service (L2) — history store -> dashboard payloads."""
from __future__ import annotations

from typing import Any

from seoagents.agent.runtime import Runtime
from seoagents.quant.scoring import SeoScoreEngine


class MetricsService:
    def __init__(self, runtime: Runtime) -> None:
        self.rt = runtime

    def summary(self) -> dict[str, Any]:
        store = self.rt.store
        runs = store.recent_audit_runs(limit=30)
        m_t_history = [
            {"ts": r["ts"], "m_t": r["m_t"], "error_count": r["error_count"]}
            for r in reversed(runs)
        ]
        latest = runs[0] if runs else None

        aeo_rows = store.latest_aeo_visibility()
        v_t = None
        if aeo_rows:
            shares = dict(self.rt.config.aeo.engine_shares)
            rates = {r["engine"]: r["mention_rate"] for r in aeo_rows}
            v_t = SeoScoreEngine.compute_aeo_visibility(shares, rates)["v_t"]

        return {
            "site": self.rt.config.sites.site_url,
            "latest_m_t": latest["m_t"] if latest else None,
            "m_t_history": m_t_history,
            "serp_positions": store.latest_serp_positions(),
            "aeo_visibility": aeo_rows,
            "v_t": v_t,
            "open_dead_links": len(store.open_dead_links()),
            "skills": self.rt.skill_manager.list_skills(),
            "provider": self.rt.provider.name,
        }

    def serp_history(self, keyword: str) -> list[dict[str, Any]]:
        return self.rt.store.serp_history(keyword)

    def dead_links(self) -> list[dict[str, Any]]:
        return self.rt.store.open_dead_links()
