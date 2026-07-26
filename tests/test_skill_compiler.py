"""L5 skills — distillation, listing, LLM-free replay."""
from __future__ import annotations

import pytest

from seoagents.agent.runtime import Runtime

TRACE = [
    {"action": "gsc_indexing_ops.create_301_mapping", "tool": "gsc_indexing_ops",
     "arguments": {"action": "create_301_mapping",
                   "redirects": [{"from_path": "/old-page", "to_path": "/"}]},
     "output": "ok", "ok": True},
    {"action": "gsc_indexing_ops.build_sitemap", "tool": "gsc_indexing_ops",
     "arguments": {"action": "build_sitemap", "urls": ["https://example.com"]},
     "output": "ok", "ok": True},
    {"action": "gsc_indexing_ops.submit_indexing", "tool": "gsc_indexing_ops",
     "arguments": {"action": "submit_indexing"}, "output": "ok", "ok": True},
    {"action": "broken_step", "tool": "gsc_indexing_ops",
     "arguments": {"action": "submit_indexing"}, "output": "boom", "ok": False},
]


def test_distill_writes_skill_yaml(runtime: Runtime):
    path = runtime.skill_compiler.auto_distill_trace(
        skill_id="FixDeadLinkWithAutoIndexSkill", trace_history=TRACE, m_t=222.2
    )
    skill = runtime.skill_manager.get("FixDeadLinkWithAutoIndexSkill")
    assert skill is not None
    assert skill["_path"] == path
    # failed step filtered out
    assert len(skill["steps"]) == 3
    assert skill["source"]["m_t"] == 222.2


def test_distill_rejects_empty_trace(runtime: Runtime):
    with pytest.raises(ValueError):
        runtime.skill_compiler.auto_distill_trace(skill_id="Empty", trace_history=[])


def test_built_in_skills_listed(runtime: Runtime):
    listed = {s["id"] for s in runtime.skill_manager.list_skills()}
    assert "EEATSignalRules" in listed
    assert "SchemaTemplates" in listed


async def test_replay_executes_real_tools(runtime: Runtime):
    runtime.skill_compiler.auto_distill_trace(
        skill_id="FixDeadLinkWithAutoIndexSkill", trace_history=TRACE
    )
    results = await runtime.skill_compiler.execute_skill(
        "FixDeadLinkWithAutoIndexSkill", runtime.executor
    )
    assert len(results) == 3
    assert all(r["ok"] for r in results)
    # replay bumps usage stats
    skill = runtime.skill_manager.get("FixDeadLinkWithAutoIndexSkill")
    assert skill["stats"]["usage_count"] == 1


async def test_replay_unknown_skill_raises(runtime: Runtime):
    with pytest.raises(KeyError):
        await runtime.skill_compiler.execute_skill("NoSuchSkill", runtime.executor)
