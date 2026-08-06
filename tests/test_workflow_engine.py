"""Department workflow engine.

Most of these are refusals. A pipeline engine that can be talked out of its own
rules provides documentation, not enforcement.
"""
from __future__ import annotations

import tempfile

import httpx
import pytest
import yaml

from dojocore.workflow import (
    EngineError,
    NodeState,
    NodeValidationError,
    TemplateError,
    WorkflowEngine,
    WorkflowInstance,
    WorkflowNode,
    WorkflowStore,
    WorkflowTemplate,
    reset_workflow_state,
)
from seoagents.dashboard.server import create_app


def node(nid, ntype="agent_task", deps=(), acceptance=("ok",), **config):
    cfg = config or ({"instruction": "do it"} if ntype == "agent_task" else {})
    return {
        "id": nid, "type": ntype, "title": nid, "depends_on": list(deps),
        "acceptance": list(acceptance), "config": cfg,
    }


def template(*nodes, tid="t_demo"):
    return WorkflowTemplate.from_dict({"id": tid, "name": "demo", "nodes": list(nodes)})


def started_instance(tpl: WorkflowTemplate) -> WorkflowInstance:
    """Build an engine-unit instance after the explicit-start authorization gate."""
    inst = WorkflowInstance.start(tpl)
    inst.context["start_authorized"] = True
    WorkflowEngine(tpl).refresh(inst)
    return inst


# ── composition ──────────────────────────────────────────────────────────
def test_node_without_acceptance_is_refused():
    """A node with no criteria can only ever be completed by assertion."""
    with pytest.raises(NodeValidationError, match="acceptance"):
        WorkflowNode.from_dict(
            {"id": "solo", "type": "agent_task", "title": "t",
             "acceptance": [], "config": {"instruction": "x"}}
        )


def test_human_gate_needs_no_acceptance():
    """The person is the criterion."""
    n = WorkflowNode.from_dict(
        {"id": "gate", "type": "human_gate", "title": "批", "acceptance": [],
         "config": {"prompt": "可以发吗"}}
    )
    assert n.type.runs_externally


def test_verify_node_rejects_a_no_op_command():
    with pytest.raises(NodeValidationError, match="空转"):
        WorkflowNode.from_dict(
            {"id": "chk", "type": "verify", "title": "验", "acceptance": ["ok"],
             "config": {"command": "echo done"}}
        )


def test_dept_request_needs_a_spec_asset():
    with pytest.raises(NodeValidationError, match="spec_"):
        WorkflowNode.from_dict(
            {"id": "ask", "type": "dept_request", "title": "配图", "acceptance": ["ok"],
             "config": {"dept": "intel", "capability": "image_sourcing"}}
        )


def test_cycles_and_dangling_edges_are_refused():
    with pytest.raises(TemplateError, match="循环依赖"):
        template(node("aa", deps=["bb"]), node("bb", deps=["aa"]))
    with pytest.raises(TemplateError, match="不存在的节点"):
        template(node("aa", deps=["ghost"]))


# ── ordering ─────────────────────────────────────────────────────────────
def test_layers_expose_what_may_run_together():
    """Order comes from dependencies, not from position in the list."""
    tpl = template(
        node("strategy"), node("audit"), node("serp"),
        node("brief", deps=["strategy"]),
        node("write", deps=["brief", "audit", "serp"]),
    )
    assert tpl.layers() == [["audit", "serp", "strategy"], ["brief"], ["write"]]
    assert tpl.summary()["max_parallel"] == 3


def test_engine_will_not_let_a_step_be_skipped():
    tpl = template(node("first"), node("second", deps=["first"]))
    engine = WorkflowEngine(tpl)
    inst = started_instance(tpl)
    with pytest.raises(EngineError, match="前置未完成"):
        engine.begin(inst, "second")


def test_engine_requires_explicit_start_authorization():
    tpl = template(node("first"))
    engine = WorkflowEngine(tpl)
    inst = WorkflowInstance.start(tpl)

    engine.refresh(inst)
    assert inst.status.value == "PENDING"
    assert inst.runs["first"].state is NodeState.PENDING
    with pytest.raises(EngineError, match="尚未显式启动"):
        engine.begin(inst, "first")

    inst.context["start_authorized"] = True
    engine.refresh(inst)
    assert inst.runs["first"].state is NodeState.READY
    engine.begin(inst, "first")
    assert inst.runs["first"].state is NodeState.RUNNING


def test_ready_set_advances_layer_by_layer():
    tpl = template(
        node("a1"), node("a2"), node("b1", deps=["a1", "a2"]),
    )
    engine = WorkflowEngine(tpl)
    inst = started_instance(tpl)
    assert {n.id for n in engine.ready_nodes(inst)} == {"a1", "a2"}
    for nid in ("a1", "a2"):
        engine.begin(inst, nid)
        engine.complete(inst, nid, acceptance_met=[True])
    assert [n.id for n in engine.ready_nodes(inst)] == ["b1"]


# ── completion ───────────────────────────────────────────────────────────
def test_unmet_acceptance_blocks_completion():
    tpl = template(node("step", acceptance=("有数据来源", "已复现")))
    engine, inst = WorkflowEngine(tpl), started_instance(tpl)
    engine.begin(inst, "step")
    with pytest.raises(EngineError, match="未满足的验收标准"):
        engine.complete(inst, "step", acceptance_met=[True, False])


def test_acceptance_must_be_answered_item_by_item():
    """A single "done" cannot stand in for several criteria."""
    tpl = template(node("step", acceptance=("a", "b", "c")))
    engine, inst = WorkflowEngine(tpl), started_instance(tpl)
    engine.begin(inst, "step")
    with pytest.raises(EngineError, match="逐条"):
        engine.complete(inst, "step", acceptance_met=[True])


def test_agent_cannot_self_approve_a_human_gate():
    tpl = template(
        node("gate", "human_gate", acceptance=(), prompt="确认发布?"),
    )
    engine, inst = WorkflowEngine(tpl), started_instance(tpl)
    engine.begin(inst, "gate")
    assert inst.runs["gate"].state is NodeState.WAITING_HUMAN
    with pytest.raises(EngineError, match="不得自行通过"):
        engine.complete(inst, "gate", acceptance_met=[], actor="agent")
    engine.complete(inst, "gate", acceptance_met=[], actor="human:galaxy")
    assert inst.runs["gate"].state is NodeState.DONE


def test_verify_node_demands_evidence_not_assertion():
    tpl = template(
        node("chk", "verify", command="curl -sS -o /dev/null -w '%{http_code}' $URL | grep 200"),
    )
    engine, inst = WorkflowEngine(tpl), started_instance(tpl)
    engine.begin(inst, "chk")
    with pytest.raises(EngineError, match="证据"):
        engine.complete(inst, "chk", acceptance_met=[True])
    engine.complete(inst, "chk", acceptance_met=[True], evidence="HTTP 200")
    assert inst.runs["chk"].state is NodeState.DONE


def test_failure_with_stop_policy_skips_the_rest():
    tpl = template(node("first"), node("second", deps=["first"]))
    engine, inst = WorkflowEngine(tpl), started_instance(tpl)
    engine.begin(inst, "first")
    engine.fail(inst, "first", error="数据源不可用")
    assert inst.runs["second"].state is NodeState.SKIPPED
    assert inst.status.value == "FAILED"


def test_failure_needs_a_reason():
    tpl = template(node("only"))
    engine, inst = WorkflowEngine(tpl), started_instance(tpl)
    with pytest.raises(EngineError, match="原因"):
        engine.fail(inst, "only", error="")


# ── external work ────────────────────────────────────────────────────────
def test_dept_request_waits_and_explains_why():
    tpl = template(
        node("spec"),
        node("ask", "dept_request", deps=["spec"], dept="intel",
             capability="image_sourcing", spec_asset_id="AST-DOC-1"),
    )
    engine, inst = WorkflowEngine(tpl), started_instance(tpl)
    engine.begin(inst, "spec")
    engine.complete(inst, "spec", acceptance_met=[True])
    engine.begin(inst, "ask")
    engine.attach_external(inst, "ask", "REQ-SEO-20260801-0001")
    assert inst.runs["ask"].state is NodeState.WAITING_EXTERNAL
    reason = engine.blocked_reason(inst)
    assert reason and reason[0]["kind"] == "external"
    assert "intel" in reason[0]["detail"]


# ── the shipped template ─────────────────────────────────────────────────
def test_builtin_blog_chain_is_valid_and_mostly_serial():
    """The content chain is serial by design — that is the whole point."""
    import seoagents.department  # noqa: F401 - explicitly activate shipped SEO templates
    store = WorkflowStore(tempfile.mkdtemp())
    tpl = store.template("blog_content_chain")
    assert tpl is not None
    summary = tpl.summary()
    assert summary["node_count"] == 12
    assert summary["max_parallel"] == 2          # only the imaging branch forks
    assert summary["human_gates"] == ["approve_publish"]
    assert summary["external_deps"][0]["dept"] == "intel"

    # publish must come after review, render and human approval — never before
    order = {nid: i for i, layer in enumerate(tpl.layers()) for nid in layer}
    for earlier in ("seo_review", "render", "approve_publish"):
        assert order[earlier] < order["publish"]
    assert order["publish"] < order["verify_live"]


def test_instance_pins_the_template_version():
    """Otherwise 'did the revised process work better' is unanswerable."""
    tpl = template(node("only"))
    inst = WorkflowInstance.start(tpl)
    assert inst.template_version == tpl.version


def test_user_template_overrides_builtin_of_same_id():
    tmp = tempfile.mkdtemp()
    store = WorkflowStore(tmp)
    custom = WorkflowTemplate.from_dict(
        {"id": "blog_content_chain", "name": "精简版", "version": "2.0",
         "nodes": [node("write"), node("publish_it", deps=["write"])]}
    )
    store.save_template(custom)
    assert store.template("blog_content_chain").version == "2.0"


def test_broken_template_file_is_reported_not_silently_dropped(caplog):
    tmp = tempfile.mkdtemp()
    store = WorkflowStore(tmp)
    (store.user_templates / "broken.yaml").write_text(
        yaml.safe_dump({"id": "broken", "name": "x", "nodes": [{"id": "n1", "type": "nope"}]}),
        encoding="utf-8",
    )
    ids = [t.id for t in store.templates()]
    assert "broken" not in ids
    assert any("模板加载失败" in r.message for r in caplog.records)


# ── HTTP ─────────────────────────────────────────────────────────────────
@pytest.fixture()
async def client(runtime):
    reset_workflow_state()
    app = create_app()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    reset_workflow_state()


async def test_node_palette_is_a_closed_set(client: httpx.AsyncClient):
    body = (await client.get("/api/workflows/node-types")).json()
    assert {t["id"] for t in body["types"]} == {
        "input", "agent_task", "tool_call", "dept_request", "human_gate", "verify", "output"
    }
    assert all(t["hint"] for t in body["types"])


async def test_template_validation_is_available_before_saving(client: httpx.AsyncClient):
    bad = {"id": "loopy", "name": "x",
           "nodes": [node("aa", deps=["bb"]), node("bb", deps=["aa"])]}
    body = (await client.post("/api/workflows/templates/validate", json=bad)).json()
    assert body["valid"] is False and "循环" in body["error"]


async def test_unknown_department_does_not_guess(client: httpx.AsyncClient):
    """A capability list invented here becomes a BLOCK once the pipeline runs."""
    body = (await client.get("/api/workflows/departments/ghost/capabilities")).json()
    assert body["capabilities"] == []
    assert "未注册" in body["error"]


async def test_instance_lifecycle_over_http(client: httpx.AsyncClient):
    res = await client.post(
        "/api/workflows/instances",
        json={"template_id": "blog_content_chain", "title": "D3 文章"},
    )
    assert res.status_code == 201
    inst = res.json()
    assert inst["template_version"] == "1.1"
    assert inst["status"] == "PENDING"
    assert not inst["context"].get("start_authorized")

    detail = (await client.get(f"/api/workflows/instances/{inst['instance_id']}")).json()
    assert {run["state"] for run in detail["runs"].values()} == {"PENDING"}

    # Create-only is not authorization to begin any node, let alone publishing.
    res = await client.post(
        f"/api/workflows/instances/{inst['instance_id']}/nodes/publish/begin"
    )
    assert res.status_code == 409
    assert "尚未显式启动" in res.json()["detail"]
