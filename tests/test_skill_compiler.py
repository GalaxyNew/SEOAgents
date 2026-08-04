"""L5 skills —— 提案制蒸馏、签字固化、无 LLM 重放。

契约在 2026-08-04 改过一次:蒸馏不再直接产出可执行技能,而是产出**提案**,
由 HM 参数化后签字固化(02 号文 §5.3)。原因是自动固化有个真实风险 ——
一次偶然跑通的轨迹会被当成经验永久保留,之后每次重放都在复制那次偶然。

因此本文件最重要的一条是 `test_proposal_cannot_be_replayed`:门禁必须在
**重放路径上**成立,而不只是文件里有个 status 字段。
"""
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
SKILL = "FixDeadLinkWithAutoIndexSkill"


def test_distill_produces_a_proposal_not_a_live_skill(runtime: Runtime):
    path = runtime.skill_compiler.auto_distill_trace(
        skill_id=SKILL, trace_history=TRACE, m_t=222.2
    )
    assert "proposals" in path, "提案必须落在 proposals/ 下,否则会被当成可执行技能扫到"

    proposals = {p["id"]: p for p in runtime.skill_manager.list_proposals()}
    assert SKILL in proposals
    assert proposals[SKILL]["status"] == "proposed"
    assert proposals[SKILL]["source"]["m_t"] == 222.2
    # 失败的那一步不该被固化进来
    assert len(proposals[SKILL]["steps"]) == 3

    # 关键:签字前它不在可执行清单里
    assert runtime.skill_manager.get(SKILL) is None


async def test_proposal_cannot_be_replayed(runtime: Runtime):
    """门禁的核心。提案在签字前不可执行 —— 这条不过,提案制就是摆设。"""
    runtime.skill_compiler.auto_distill_trace(skill_id=SKILL, trace_history=TRACE)
    with pytest.raises(KeyError):
        await runtime.skill_compiler.execute_skill(SKILL, runtime.executor)


def test_approve_makes_it_executable_and_records_who_signed(runtime: Runtime):
    runtime.skill_compiler.auto_distill_trace(skill_id=SKILL, trace_history=TRACE)
    path = runtime.skill_compiler.approve_proposal(SKILL, approved_by="hm")

    skill = runtime.skill_manager.get(SKILL)
    assert skill is not None
    assert skill["_path"] == path
    assert skill["status"] == "active"
    assert skill["approved_by"] == "hm"      # 谁签的字必须留痕
    assert runtime.skill_manager.list_proposals() == []


def test_approve_applies_parameterization(runtime: Runtime):
    """签字时可以把轨迹里写死的实参换掉 —— 这就是方案说的「参数化」。"""
    runtime.skill_compiler.auto_distill_trace(skill_id=SKILL, trace_history=TRACE)
    runtime.skill_compiler.approve_proposal(
        SKILL, approved_by="hm",
        overrides={"gsc_indexing_ops": {"action": "build_sitemap"}},
    )
    skill = runtime.skill_manager.get(SKILL)
    assert all(s["arguments"]["action"] == "build_sitemap" for s in skill["steps"])
    assert skill["parameterized"] == {"gsc_indexing_ops": {"action": "build_sitemap"}}


def test_reject_removes_the_proposal(runtime: Runtime):
    runtime.skill_compiler.auto_distill_trace(skill_id=SKILL, trace_history=TRACE)
    runtime.skill_compiler.reject_proposal(SKILL, rejected_by="hm", reason="步骤太具体")
    assert runtime.skill_manager.list_proposals() == []
    assert runtime.skill_manager.get(SKILL) is None


def test_approve_unknown_proposal_raises(runtime: Runtime):
    with pytest.raises(KeyError):
        runtime.skill_compiler.approve_proposal("NoSuchProposal", approved_by="hm")


def test_distill_rejects_empty_trace(runtime: Runtime):
    with pytest.raises(ValueError):
        runtime.skill_compiler.auto_distill_trace(skill_id="Empty", trace_history=[])


def test_built_in_skills_listed(runtime: Runtime):
    listed = {s["id"] for s in runtime.skill_manager.list_skills()}
    assert "EEATSignalRules" in listed
    assert "SchemaTemplates" in listed


async def test_replay_executes_real_tools_after_approval(runtime: Runtime):
    runtime.skill_compiler.auto_distill_trace(skill_id=SKILL, trace_history=TRACE)
    runtime.skill_compiler.approve_proposal(SKILL, approved_by="hm")

    results = await runtime.skill_compiler.execute_skill(SKILL, runtime.executor)
    assert len(results) == 3
    assert all(r["ok"] for r in results)
    # 重放会累计使用次数
    assert runtime.skill_manager.get(SKILL)["stats"]["usage_count"] == 1


async def test_replay_unknown_skill_raises(runtime: Runtime):
    with pytest.raises(KeyError):
        await runtime.skill_compiler.execute_skill("NoSuchSkill", runtime.executor)
