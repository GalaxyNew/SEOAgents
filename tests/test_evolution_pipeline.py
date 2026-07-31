"""L2 evolution cron — the closed loop, and its refusal to close on bad data.

The central behaviour under test is the *absence* of a score. With no
credentials configured the pipeline must reach the end and report
``m_t is None``, because every measurement it depends on is UNAVAILABLE.

The previous implementation produced a number here — assembled from a hashed
SERP position, a hashed AEO rate with a daily upward drift, and an offline
Lighthouse estimate — and then persisted it, charted it, and used it to decide
whether a remediation had "worked".
"""
from __future__ import annotations

from seoagents.agent.runtime import Runtime
from seoagents.config import ConfigStore
from seoagents.cron.seo_evo_jobs import FIX_SKILL_ID, run_seo_self_evolution_pipeline


async def test_pipeline_refuses_to_score_without_real_data(runtime: Runtime):
    summary = await run_seo_self_evolution_pipeline(runtime)

    # The loop still runs end to end — tools are called, the trace is recorded.
    assert summary["trace_len"] >= 5

    # ...but it produces no score, and says why.
    assert summary["m_t"] is None
    assert summary["score_status"] == "PARTIAL"
    assert summary["excluded_inputs"], "必须列出导致拒绝计分的输入"

    # Every data source is accounted for explicitly.
    assert set(summary["data_sources"]) >= {"site_audit", "traffic", "serp", "aeo"}
    assert all(v in {"REAL", "DEGRADED", "UNAVAILABLE", "DISPUTED"}
               for v in summary["data_sources"].values())


async def test_unscorable_run_is_not_persisted(runtime: Runtime):
    """A NULL score must not enter the history table.

    It would still be drawn on the trend chart and still be picked up by
    "did it improve?" comparisons.
    """
    await run_seo_self_evolution_pipeline(runtime)
    assert runtime.store.recent_audit_runs() == []


async def test_dead_links_are_proposed_not_fixed(runtime: Runtime):
    """Writing an nginx snippet to a local directory is not a fix."""
    summary = await run_seo_self_evolution_pipeline(runtime)
    assert summary["dead_links"] >= 1          # demo snapshot seeds dead links
    assert summary["links_proposed"] == summary["dead_links"]
    assert summary["links_fixed"] == 0         # nothing verified live


async def test_no_skill_compiled_from_unscorable_run(runtime: Runtime):
    """Never distil a "high-performing" trace out of data that could not be scored."""
    ConfigStore.get_instance().update({"scoring": {"skill_compile_threshold": 0.0}})
    rt = Runtime.from_config_store(ConfigStore.get_instance())

    summary = await run_seo_self_evolution_pipeline(rt)
    assert summary["m_t"] is None
    assert summary["compiled_skill"] is None
    assert rt.skill_manager.get(FIX_SKILL_ID) is None


async def test_aeo_reports_unavailable_without_probes(runtime: Runtime):
    """AEO visibility cannot be estimated, only measured."""
    summary = await run_seo_self_evolution_pipeline(runtime)
    assert summary["data_sources"]["aeo"] == "UNAVAILABLE"
    assert summary["v_t"] is None
