"""L2 evolution cron — full closed loop in mock mode + skill compilation trigger."""
from __future__ import annotations

from seoagents.agent.runtime import Runtime
from seoagents.config import ConfigStore
from seoagents.cron.seo_evo_jobs import FIX_SKILL_ID, run_seo_self_evolution_pipeline


async def test_pipeline_produces_scores_and_persists(runtime: Runtime):
    summary = await run_seo_self_evolution_pipeline(runtime)

    assert summary["trace_len"] >= 5
    assert summary["clicks"] > 0            # mock GSC clicks parsed
    assert 0 < summary["index_ratio"] <= 1
    assert summary["dead_links"] >= 1       # demo snapshot seeds dead links
    assert summary["links_fixed"] == summary["dead_links"]
    assert summary["v_t"] is not None

    runs = runtime.store.recent_audit_runs()
    assert len(runs) == 1
    assert runs[0]["m_t"] == summary["m_t"]
    assert runtime.store.latest_serp_positions()      # SERP rows persisted
    assert runtime.store.latest_aeo_visibility()      # AEO rows persisted


async def test_high_score_compiles_skill(runtime: Runtime):
    # Force a low threshold so the mock-mode M_t crosses it deterministically.
    ConfigStore.get_instance().update({"scoring": {"skill_compile_threshold": 1.0}})
    rt = Runtime.from_config_store(ConfigStore.get_instance())

    summary = await run_seo_self_evolution_pipeline(rt)
    assert summary["m_t"] > 1.0
    assert summary["compiled_skill"] == FIX_SKILL_ID
    assert rt.skill_manager.get(FIX_SKILL_ID) is not None
    assert any(s["skill_id"] == FIX_SKILL_ID for s in rt.store.skill_compilations())


async def test_low_score_skips_compilation(runtime: Runtime):
    ConfigStore.get_instance().update({"scoring": {"skill_compile_threshold": 99999.0}})
    rt = Runtime.from_config_store(ConfigStore.get_instance())
    summary = await run_seo_self_evolution_pipeline(rt)
    assert summary["compiled_skill"] is None
