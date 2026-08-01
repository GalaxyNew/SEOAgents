"""The data-status contract and its three gates."""
from __future__ import annotations

import pytest

from dojocore.quality import (
    DataIntegrityError,
    DataStatus,
    all_real,
    degraded,
    real,
    unavailable,
    validate_tool_output,
    worst_status,
)
from seoagents.config.models import ScoringConfig
from seoagents.quant.scoring import SeoScoreEngine


def test_degraded_requires_a_reason():
    """A caller who cannot say why the data is untrustworthy has not understood
    the failure, and the agent downstream needs that reason verbatim."""
    with pytest.raises(DataIntegrityError):
        degraded({"x": 1}, source="s", reason="")


def test_unavailable_carries_reason_and_no_payload_zeroes():
    out = unavailable(source="gsc", reason="凭证缺失")
    assert out["data_status"] == "UNAVAILABLE"
    assert out["degraded_reason"] == "凭证缺失"
    assert "value" not in out          # nothing invented to fill the gap


def test_gate_one_rejects_results_without_status():
    with pytest.raises(DataIntegrityError):
        validate_tool_output("mystery", '{"position": 3}')
    assert validate_tool_output("ok", real({"a": 1}, source="s")) is DataStatus.REAL


def test_gate_two_refuses_to_score_non_real_inputs():
    engine = SeoScoreEngine(ScoringConfig())
    good = engine.compute_m_t(
        clicks=10, index_ratio=0.9, positions={"k": 5.0},
        sources={"traffic": "REAL", "serp": "REAL"},
    )
    assert good.scorable and good.status == "OK"

    bad = engine.compute_m_t(
        clicks=10, index_ratio=0.9, positions={"k": 5.0},
        sources={"traffic": "REAL", "serp": "DEGRADED"},
    )
    assert bad.m_t is None
    assert bad.status == "PARTIAL"
    assert bad.excluded == ("serp",)


def test_unscorable_run_never_compiles_a_skill():
    engine = SeoScoreEngine(ScoringConfig(skill_compile_threshold=0.0))
    assert engine.should_compile_skill(None) is False


def test_worst_status_and_all_real():
    assert worst_status(["REAL", "DEGRADED"]) is DataStatus.DEGRADED
    assert worst_status(["DEGRADED", "UNAVAILABLE"]) is DataStatus.UNAVAILABLE
    assert all_real({"a": "REAL"}) and not all_real({"a": "REAL", "b": "DISPUTED"})
