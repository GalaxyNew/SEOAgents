"""The framework must support a department it has never seen.

SEOAgents is the first department; a search department is next, with different
capabilities, different tools, different agent roles and a different scoring
formula. If building it requires editing dojocore, the abstraction has failed —
so this file builds a miniature one and checks the framework carries it.
"""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from dojocore import (
    DepartmentBuilder,
    MetricResult,
    capabilities,
    departments,
    score_gate,
)
from dojocore.capability import UnknownCapability
from dojocore.workflow import WorkflowEngine, WorkflowInstance, WorkflowStore


@pytest.fixture()
def clean_registries():
    """Isolate the global registries so a fake department cannot leak."""
    import seoagents.department
    yield
    capabilities.clear()
    departments.clear()
    import importlib
    importlib.reload(seoagents.department)


# ── a department the framework has never heard of ────────────────────────
def _search_department():
    """A miniature 'search' department, per the Search manual's model.

    Its vocabulary, roles and metric share nothing with SEO's.
    """
    return (
        DepartmentBuilder("search", "智能检索部", "元搜索 + AI 爬取 + 索引入库")
        .capability("web_search", "元搜索", result_schema="web_search", sla_hours=1)
        .capability("ai_scrape", "AI 结构化爬取", result_schema="ai_scrape", sla_hours=2)
        .capability("index_ingest", "索引入库", result_schema="index_ingest",
                    sla_hours=4, comparable=False)
        .capability("rerank", "语义重排", result_schema="rerank", sla_hours=1)
        .meta(headline_metric="R_t")
        .build()
    )


def test_a_new_department_needs_no_framework_change(clean_registries):
    search = departments.register(_search_department())
    assert search.capability_ids() == ["ai_scrape", "index_ingest", "rerank", "web_search"]

    # Both departments coexist; neither knows about the other.
    assert {d.id for d in departments.list()} >= {"seo", "search"}
    assert capabilities.has("serp_rank") and capabilities.has("web_search")
    assert capabilities.get("web_search").dept == "search"
    assert capabilities.get("serp_rank").dept == "seo"


def test_capability_lookup_fails_loudly(clean_registries):
    """A typo must not silently produce an empty capability."""
    with pytest.raises(UnknownCapability, match="未知能力"):
        capabilities.get("web_serch")


def test_same_capability_id_must_mean_the_same_thing(clean_registries):
    """Otherwise two departments' results could not be compared."""
    departments.register(_search_department())
    conflicting = (
        DepartmentBuilder("content", "内容部")
        .capability("web_search", "完全不同的东西", result_schema="something_else")
        .build()
    )
    with pytest.raises(ValueError, match="定义不同"):
        conflicting.install()


# ── the scoring gate is shared, the formula is not ───────────────────────
def test_score_gate_is_department_agnostic():
    """SEO's M_t and search's R_t share only the refusal to score fake inputs."""
    assert score_gate({"clicks": "REAL", "serp": "REAL"}) is None

    refusal = score_gate({"latency": "REAL", "similarity": "DEGRADED"}, name="R_t")
    assert isinstance(refusal, MetricResult)
    assert refusal.value is None and refusal.status == "PARTIAL"
    assert refusal.excluded == ("similarity",)
    assert "R_t" in refusal.breakdown["reason"]


def test_a_department_metric_engine_uses_the_shared_gate():
    class RetrievalScore:
        """Search's formula — nothing to do with M_t."""

        name = "R_t"

        def compute(self, *, sources=None, click_retention=0.0, similarity=0.0,
                    latency_s=0.0, crash_rate=0.0):
            refused = score_gate(sources, name=self.name)
            if refused is not None:
                return refused
            value = click_retention + similarity - 0.1 * latency_s - crash_rate
            return MetricResult(value=value, name=self.name,
                                breakdown={"latency_s": latency_s})

        def should_distil_skill(self, result):
            return result.scorable and result.value > 1.0

    engine = RetrievalScore()
    good = engine.compute(sources={"a": "REAL"}, click_retention=0.9,
                          similarity=0.8, latency_s=2.0)
    assert good.scorable and engine.should_distil_skill(good)

    bad = engine.compute(sources={"a": "UNAVAILABLE"}, click_retention=0.9)
    assert not bad.scorable
    # An unscorable run must never freeze a "high-performing" trace into a skill.
    assert engine.should_distil_skill(bad) is False


# ── the workflow engine carries a foreign pipeline ───────────────────────
def test_workflow_engine_runs_a_search_pipeline(clean_registries, tmp_path):
    """Scout → Verify → Ingest, the Search manual's roles — no SEO anywhere."""
    dept_templates = tmp_path / "search_workflows"
    dept_templates.mkdir()
    (dept_templates / "crawl_chain.yaml").write_text(
        yaml.safe_dump(
            {
                "id": "crawl_chain", "name": "抓取入库链", "dept": "search",
                "nodes": [
                    {"id": "scout", "type": "agent_task", "title": "Scout 探测",
                     "acceptance": ["候选源 ≥ 5 且各带出处"],
                     "config": {"instruction": "用元搜索找候选源"}},
                    {"id": "verify", "type": "agent_task", "title": "Verify 核实",
                     "depends_on": ["scout"], "acceptance": ["每条声明可溯源"],
                     "config": {"instruction": "交叉核实候选源"}},
                    {"id": "ingest", "type": "tool_call", "title": "Ingest 入库",
                     "depends_on": ["verify"], "acceptance": ["索引条数与去重后一致"],
                     "config": {"tool": "meilisearch_ingest"}},
                ],
            },
            allow_unicode=True,
        ),
        encoding="utf-8",
    )
    profile = (
        DepartmentBuilder("search", "智能检索部")
        .capability("web_search", "元搜索")
        .templates(dept_templates)
        .build()
    )
    departments.register(profile, activate=True)

    store = WorkflowStore(str(tmp_path / "data"))
    tpl = store.template("crawl_chain")
    assert tpl is not None and tpl.dept == "search"
    assert tpl.layers() == [["scout"], ["verify"], ["ingest"]]

    engine = WorkflowEngine(tpl)
    inst = WorkflowInstance.start(tpl)
    engine.begin(inst, "scout")
    engine.complete(inst, "scout", acceptance_met=[True])
    assert [n.id for n in engine.ready_nodes(inst)] == ["verify"]


def test_framework_does_not_import_any_department():
    """dojocore must never depend on a department package.

    If it does, the next department cannot use the framework without dragging
    this one along.
    """
    root = Path(__file__).resolve().parents[1] / "dojocore"
    offenders = []
    for path in root.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        for marker in ("import seoagents", "from seoagents"):
            if marker in text:
                offenders.append(f"{path.relative_to(root)}: {marker}")
    assert not offenders, f"框架反向依赖了部门包: {offenders}"
