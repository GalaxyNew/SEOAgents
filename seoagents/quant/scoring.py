"""Self-evolution scoring engine (L6) — manual §6.1 formalized.

Daily SEO performance score::

    M_t = α·C_t + β·I_t + γ·Σ_i (W_i / R_{i,t}) − δ·E_t

  C_t  organic click delta from Search Console
  I_t  index coverage ratio (0..1)
  R_it measured SERP position of keyword i (1 = top; missing -> penalty position)
  W_i  trend weight of keyword i from Google Trends
  E_t  accumulated technical error penalty (dead links, CWV failures)

GEO/AEO brand visibility score::

    V_t = Σ_{e ∈ E} S_e · M_e

  E    AI engine set {chatgpt, claude, perplexity, google_aio}
  S_e  engine market-share weight
  M_e  brand mention rate in engine e's first-screen answers (0..1)
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field

from dojocore.quality import DataStatus, all_real, worst_status
from seoagents.config.models import ScoringConfig

MISSING_POSITION = 100.0  # keyword not found in SERP -> treated as position 100


@dataclass(frozen=True)
class ScoreBreakdown:
    """A score, or an explicit refusal to produce one.

    ``m_t is None`` with ``status="PARTIAL"`` means at least one input was not
    ``REAL``. That is deliberately not a number: an M_t computed from a mock
    SERP position or an offline Lighthouse estimate looks exactly like a real
    one, and would then be persisted, charted, and used to decide whether a
    remediation "worked".
    """

    m_t: float | None
    clicks_term: float
    index_term: float
    serp_term: float
    error_penalty: float
    inputs: dict = field(default_factory=dict)
    status: str = "OK"                       # OK | PARTIAL
    excluded: tuple[str, ...] = ()           # inputs that blocked scoring

    @property
    def scorable(self) -> bool:
        return self.m_t is not None

    def to_dict(self) -> dict:
        return {
            "m_t": round(self.m_t, 4) if self.m_t is not None else None,
            "status": self.status,
            "excluded": list(self.excluded),
            "clicks_term": round(self.clicks_term, 4),
            "index_term": round(self.index_term, 4),
            "serp_term": round(self.serp_term, 4),
            "error_penalty": round(self.error_penalty, 4),
            "inputs": self.inputs,
        }


class SeoScoreEngine:
    def __init__(self, config: ScoringConfig) -> None:
        self.config = config

    def compute_m_t(
        self,
        *,
        clicks: float,
        index_ratio: float,
        positions: Mapping[str, float | None],
        trend_weights: Mapping[str, float] | None = None,
        error_count: int = 0,
        sources: Mapping[str, str] | None = None,
    ) -> ScoreBreakdown:
        """Gate 2 of the data-integrity contract.

        ``sources`` maps each contributing input to its ``data_status``. If any
        of them is not ``REAL`` the method returns a PARTIAL breakdown with
        ``m_t=None`` rather than a number computed from untrustworthy inputs.
        """
        cfg = self.config
        if sources is not None and not all_real(sources):
            excluded = tuple(
                sorted(name for name, st in sources.items() if DataStatus(st) is not DataStatus.REAL)
            )
            return ScoreBreakdown(
                m_t=None,
                clicks_term=0.0,
                index_term=0.0,
                serp_term=0.0,
                error_penalty=0.0,
                status="PARTIAL",
                excluded=excluded,
                inputs={
                    "sources": dict(sources),
                    "worst_status": worst_status(sources.values()).value,
                    "reason": (
                        "M_t 拒绝计算:以下输入非 REAL —— " + ", ".join(excluded)
                    ),
                },
            )
        index_ratio = min(max(float(index_ratio), 0.0), 1.0)
        trend_weights = dict(trend_weights or {})

        serp_sum = 0.0
        for kw, pos in positions.items():
            w_i = float(trend_weights.get(kw, 1.0))
            r_it = float(pos) if pos and pos > 0 else MISSING_POSITION
            serp_sum += w_i / r_it

        clicks_term = cfg.alpha * float(clicks)
        index_term = cfg.beta * index_ratio
        serp_term = cfg.gamma * serp_sum
        error_penalty = cfg.delta * float(error_count)
        m_t = clicks_term + index_term + serp_term - error_penalty

        return ScoreBreakdown(
            m_t=m_t,
            clicks_term=clicks_term,
            index_term=index_term,
            serp_term=serp_term,
            error_penalty=error_penalty,
            inputs={
                "clicks": clicks,
                "index_ratio": index_ratio,
                "positions": {k: (v if v is not None else MISSING_POSITION) for k, v in positions.items()},
                "trend_weights": trend_weights,
                "error_count": error_count,
                "weights": {"alpha": cfg.alpha, "beta": cfg.beta, "gamma": cfg.gamma, "delta": cfg.delta},
            },
        )

    @staticmethod
    def compute_aeo_visibility(
        engine_shares: Mapping[str, float], mention_rates: Mapping[str, float]
    ) -> dict:
        """V_t = Σ_e S_e · M_e over the configured engine set."""
        total_share = sum(engine_shares.values()) or 1.0
        v_t = 0.0
        per_engine: dict[str, dict[str, float]] = {}
        for engine, share in engine_shares.items():
            s_e = share / total_share
            m_e = min(max(float(mention_rates.get(engine, 0.0)), 0.0), 1.0)
            contribution = s_e * m_e
            v_t += contribution
            per_engine[engine] = {
                "share": round(s_e, 4),
                "mention_rate": round(m_e, 4),
                "contribution": round(contribution, 4),
            }
        return {"v_t": round(v_t, 4), "per_engine": per_engine}

    def should_compile_skill(
        self, m_t: float | None, *, previous_m_t: float | None = None
    ) -> bool:
        """这一轮的做法值不值得固化成技能。

        判据优先看**相对改善**,而不是绝对分高。「自进化」要固化的是
        *让指标变好的做法*,不是*恰好赶上一个好分数的那一轮*。绝对阈值只在
        没有历史基线时兜底 —— 首轮无从比较,只能问「这一轮本身够不够体面」。

        噪声护栏:改善必须超过 ``skill_improve_delta``,否则第 3 位小数的抖动
        也会被当成进步,天天固化出一堆等价技能。
        """
        if m_t is None:
            return False
        if previous_m_t is not None:
            return (m_t - previous_m_t) > self.config.skill_improve_delta
        return m_t > self.config.skill_compile_threshold


__all__ = ["MISSING_POSITION", "ScoreBreakdown", "SeoScoreEngine"]
