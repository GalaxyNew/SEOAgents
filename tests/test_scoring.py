"""L6 scoring engine — M_t and V_t math."""
from __future__ import annotations

import pytest

from seoagents.config.models import ScoringConfig
from seoagents.quant.scoring import MISSING_POSITION, SeoScoreEngine


@pytest.fixture()
def engine() -> SeoScoreEngine:
    return SeoScoreEngine(ScoringConfig(alpha=0.4, beta=0.2, gamma=0.3, delta=0.1,
                                        skill_compile_threshold=150.0))


def test_m_t_formula_matches_manual(engine: SeoScoreEngine):
    # Manual §6.2 example: 0.4*450 + 0.2*0.98 + 0.3*(1.2/4.2) - 0.1*0
    breakdown = engine.compute_m_t(
        clicks=450.0,
        index_ratio=0.98,
        positions={"kw": 4.2},
        trend_weights={"kw": 1.2},
        error_count=0,
    )
    expected = 0.4 * 450 + 0.2 * 0.98 + 0.3 * (1.2 / 4.2)
    assert breakdown.m_t == pytest.approx(expected)
    assert breakdown.error_penalty == 0.0


def test_error_penalty_reduces_score(engine: SeoScoreEngine):
    base = engine.compute_m_t(clicks=100, index_ratio=1.0, positions={}, error_count=0)
    penalized = engine.compute_m_t(clicks=100, index_ratio=1.0, positions={}, error_count=8)
    assert penalized.m_t == pytest.approx(base.m_t - 0.1 * 8)


def test_missing_position_treated_as_deep_rank(engine: SeoScoreEngine):
    breakdown = engine.compute_m_t(
        clicks=0, index_ratio=0, positions={"kw": None}, trend_weights={"kw": 2.0}
    )
    assert breakdown.serp_term == pytest.approx(0.3 * (2.0 / MISSING_POSITION))


def test_index_ratio_clamped(engine: SeoScoreEngine):
    breakdown = engine.compute_m_t(clicks=0, index_ratio=5.0, positions={})
    assert breakdown.index_term == pytest.approx(0.2 * 1.0)


def test_aeo_visibility_weighted_sum():
    result = SeoScoreEngine.compute_aeo_visibility(
        {"chatgpt": 0.5, "claude": 0.5}, {"chatgpt": 1.0, "claude": 0.0}
    )
    assert result["v_t"] == pytest.approx(0.5)
    assert result["per_engine"]["chatgpt"]["contribution"] == pytest.approx(0.5)


def test_aeo_shares_normalized():
    result = SeoScoreEngine.compute_aeo_visibility(
        {"a": 2.0, "b": 2.0}, {"a": 1.0, "b": 1.0}
    )
    assert result["v_t"] == pytest.approx(1.0)


def test_skill_compile_threshold(engine: SeoScoreEngine):
    assert engine.should_compile_skill(150.1)
    assert not engine.should_compile_skill(150.0)
