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

    # 多站点后没有「全局 M_t」,断言落到具体站点上。
    assert summary["sites_total"] >= 1
    assert summary["sites_scored"] == 0
    site = summary["results"][0]

    # The loop still runs end to end — tools are called, the trace is recorded.
    assert site["trace_len"] >= 5

    # ...but it produces no score, and says why.
    assert site["m_t"] is None
    assert site["score_status"] == "PARTIAL"
    assert site["excluded_inputs"], "必须列出导致拒绝计分的输入"

    # Every data source is accounted for explicitly.
    assert set(site["data_sources"]) >= {"site_audit", "traffic", "serp", "aeo"}
    assert all(v in {"REAL", "DEGRADED", "UNAVAILABLE", "DISPUTED"}
               for v in site["data_sources"].values())


async def test_unscorable_run_is_not_persisted(runtime: Runtime):
    """A NULL score must not enter the history table.

    It would still be drawn on the trend chart and still be picked up by
    "did it improve?" comparisons.
    """
    await run_seo_self_evolution_pipeline(runtime)
    assert runtime.store.recent_audit_runs() == []


async def test_dead_links_are_proposed_not_fixed(runtime: Runtime):
    """Writing an nginx snippet to a local directory is not a fix."""
    site = (await run_seo_self_evolution_pipeline(runtime))["results"][0]
    assert site["dead_links"] >= 1             # demo snapshot seeds dead links
    assert site["links_proposed"] == site["dead_links"]
    assert site["links_fixed"] == 0            # nothing verified live


async def test_no_skill_compiled_from_unscorable_run(runtime: Runtime):
    """Never distil a "high-performing" trace out of data that could not be scored."""
    ConfigStore.get_instance().update({"scoring": {"skill_compile_threshold": 0.0}})
    rt = Runtime.from_config_store(ConfigStore.get_instance())

    summary = await run_seo_self_evolution_pipeline(rt)
    assert all(r["m_t"] is None for r in summary["results"])
    assert all(r["compiled_skill"] is None for r in summary["results"])
    assert rt.skill_manager.get(FIX_SKILL_ID) is None


async def test_aeo_reports_unavailable_without_probes(runtime: Runtime):
    """AEO visibility cannot be estimated, only measured."""
    summary = await run_seo_self_evolution_pipeline(runtime)
    assert all(r["data_sources"]["aeo"] == "UNAVAILABLE" for r in summary["results"])
    assert all(r["v_t"] is None for r in summary["results"])
