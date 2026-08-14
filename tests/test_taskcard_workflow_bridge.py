"""G1-J workflow ↔ task card bridge.

Two invariants carry the module: automation may report but not accept, and
bookkeeping may fail without taking the pipeline down.
"""
from __future__ import annotations

import pytest

from dojocore.taskcard.models import CardError, CardStatus
from dojocore.taskcard.service import TaskCardService
from dojocore.taskcard.store import TaskCardStore
from dojocore.taskcard.workflow_bridge import WorkflowCardBridge
from dojocore.workflow import (
    WorkflowEngine,
    WorkflowInstance,
    WorkflowTemplate,
)
from dojocore.workflow.instance import InstanceStatus, NodeState


def node(nid, ntype="agent_task", deps=(), acceptance=("ok",), **config):
    cfg = config or ({"instruction": "do it"} if ntype == "agent_task" else {})
    return {
        "id": nid, "type": ntype, "title": nid, "depends_on": list(deps),
        "acceptance": list(acceptance), "config": cfg,
    }


def template(*nodes, tid="t_bridge"):
    return WorkflowTemplate.from_dict(
        {"id": tid, "name": "桥接测试产线", "nodes": list(nodes)}
    )


def started(tpl: WorkflowTemplate) -> WorkflowInstance:
    inst = WorkflowInstance.start(tpl, title="每日 GSC 抓取")
    inst.context["start_authorized"] = True
    WorkflowEngine(tpl).refresh(inst)
    return inst


@pytest.fixture()
def cards(tmp_path):
    return TaskCardService(TaskCardStore(tmp_path, dept="seo"), dept="seo")


@pytest.fixture()
def bridge(cards):
    return WorkflowCardBridge(cards)


@pytest.fixture()
def simple():
    return template(node("fetch"), node("report", deps=["fetch"]))


# ── 开卡与挂钩 ────────────────────────────────────────────────────────────
class TestStart:
    def test_start_opens_a_card_and_backfills_parent_task(self, bridge, simple):
        inst = started(simple)
        assert inst.parent_task == ""
        card_id = bridge.on_start(inst, actor="hermes")
        assert card_id and inst.parent_task == card_id

    def test_opened_card_records_the_instance(self, bridge, cards, simple):
        inst = started(simple)
        cid = bridge.on_start(inst, actor="hermes")
        card = cards.store.require(cid)
        assert card.meta["workflow_instance"] == inst.instance_id
        assert card.meta["workflow_template"] == "t_bridge"
        assert card.dept == "seo"

    def test_owner_given_means_card_starts_working(self, bridge, cards, simple):
        inst = started(simple)
        cid = bridge.on_start(inst, actor="hermes", owner="seo-tech")
        card = cards.store.require(cid)
        assert card.status is CardStatus.IN_PROGRESS
        assert card.owner == "seo-tech"

    def test_without_owner_the_card_stays_draft(self, bridge, cards, simple):
        inst = started(simple)
        card = cards.store.require(bridge.on_start(inst, actor="hermes"))
        assert card.status is CardStatus.DRAFT

    def test_can_link_to_an_existing_card_instead(self, bridge, cards, simple):
        existing = cards.open_card(title="母卡", goal="g", acceptance=["a"],
                                   actor="hermes")
        inst = started(simple)
        returned = bridge.on_start(inst, card_id=existing.card_id, actor="hermes")
        assert returned == existing.card_id
        assert inst.parent_task == existing.card_id
        note = cards.store.require(existing.card_id).evidence[-1].note
        assert inst.instance_id in note

    def test_default_acceptance_is_written_when_none_given(self, bridge, cards, simple):
        inst = started(simple)
        card = cards.store.require(bridge.on_start(inst))
        assert card.acceptance  # 无验收标准的卡会被审计标红，桥接不能留空

    def test_linking_to_a_missing_card_does_not_raise(self, bridge, simple):
        inst = started(simple)
        assert bridge.on_start(inst, card_id="TSEO20260101-99") == ""


# ── 节点证据 ──────────────────────────────────────────────────────────────
class TestNodeEvidence:
    def test_node_completion_lands_in_the_evidence_chain(self, bridge, cards, simple):
        inst = started(simple)
        cid = bridge.on_start(inst, owner="seo-tech", actor="hermes")
        bridge.on_node_done(inst, "fetch", actor="seo-tech", evidence="HTTP 200 OK")
        notes = [e.note for e in cards.store.require(cid).evidence]
        assert any("工序 fetch 完成" in n and "HTTP 200 OK" in n for n in notes)

    def test_evidence_is_attributed_to_the_node_actor(self, bridge, cards, simple):
        inst = started(simple)
        cid = bridge.on_start(inst, owner="seo-tech", actor="hermes")
        bridge.on_node_done(inst, "fetch", actor="seo-analyst")
        assert cards.store.require(cid).evidence[-1].actor == "seo-analyst"

    def test_control_nodes_do_not_pollute_the_chain(self, bridge, cards):
        tpl = template(node("seed", ntype="input", acceptance=("ok",),
                            input_mode="direct"),
                       node("work", deps=["seed"]),
                       node("emit", ntype="output", deps=["work"],
                            acceptance=("ok",), output_mode="end"))
        inst = started(tpl)
        cid = bridge.on_start(inst, owner="seo-tech", actor="hermes")
        before = len(cards.store.require(cid).evidence)
        bridge.on_node_done(inst, "seed", actor="seo-tech")
        assert len(cards.store.require(cid).evidence) == before

    def test_unlinked_instance_is_a_no_op(self, bridge, simple):
        inst = started(simple)
        bridge.on_node_done(inst, "fetch", actor="seo-tech")  # 不抛异常即可

    def test_failed_node_blocks_the_card(self, bridge, cards, simple):
        inst = started(simple)
        cid = bridge.on_start(inst, owner="seo-tech", actor="hermes")
        bridge.on_node_failed(inst, "fetch", error="DataForSEO 返回 429")
        card = cards.store.require(cid)
        assert card.status is CardStatus.BLOCKED
        assert any("429" in e.note for e in card.evidence)

    def test_human_gate_blocks_the_card_with_the_prompt(self, bridge, cards):
        tpl = template(node("draft"),
                       node("approve", ntype="human_gate", deps=["draft"],
                            prompt="发布前需人工确认"))
        inst = started(tpl)
        cid = bridge.on_start(inst, owner="seo-tech", actor="hermes")
        bridge.on_human_gate(inst, "approve", prompt="发布前需人工确认")
        card = cards.store.require(cid)
        assert card.status is CardStatus.BLOCKED
        assert any("等待人工审批" in e.note for e in card.evidence)


# ── 终点：只到 REVIEW，绝不 PASSED ───────────────────────────────────────
class TestFinish:
    def _run_to_done(self, bridge, simple, cards):
        inst = started(simple)
        cid = bridge.on_start(inst, owner="seo-tech", actor="hermes")
        eng = WorkflowEngine(simple)
        for nid in ("fetch", "report"):
            eng.begin(inst, nid)
            eng.complete(inst, nid, acceptance_met=[True], actor="seo-tech")
            bridge.on_node_done(inst, nid, actor="seo-tech")
        return inst, cid

    def test_finished_workflow_sends_card_to_review(self, bridge, cards, simple):
        inst, cid = self._run_to_done(bridge, simple, cards)
        assert inst.status is InstanceStatus.DONE
        bridge.on_finish(inst)
        assert cards.store.require(cid).status is CardStatus.REVIEW

    def test_bridge_never_promotes_to_passed(self, bridge, cards, simple):
        """铁律：自动化只能报告，不能验收。"""
        inst, cid = self._run_to_done(bridge, simple, cards)
        bridge.on_finish(inst)
        bridge.on_finish(inst)  # 重复调用也不得越过 REVIEW
        assert cards.store.require(cid).status is not CardStatus.PASSED

    def test_review_still_requires_a_second_person(self, bridge, cards, simple):
        inst, cid = self._run_to_done(bridge, simple, cards)
        bridge.on_finish(inst)
        with pytest.raises(CardError, match="自审被拒"):
            cards.approve(cid, reviewer="seo-tech", require_verification=False)
        done = cards.approve(cid, reviewer="hermes", require_verification=False)
        assert done.status is CardStatus.PASSED

    def test_blocked_card_is_unblocked_before_review(self, bridge, cards, simple):
        inst = started(simple)
        cid = bridge.on_start(inst, owner="seo-tech", actor="hermes")
        bridge.on_human_gate(inst, "fetch", prompt="待批")
        assert cards.store.require(cid).status is CardStatus.BLOCKED
        eng = WorkflowEngine(simple)
        for nid in ("fetch", "report"):
            eng.begin(inst, nid)
            eng.complete(inst, nid, acceptance_met=[True], actor="seo-tech")
        bridge.on_finish(inst)
        assert cards.store.require(cid).status is CardStatus.REVIEW

    def test_failed_workflow_blocks_the_card_and_names_the_node(
        self, bridge, cards, simple
    ):
        inst = started(simple)
        cid = bridge.on_start(inst, owner="seo-tech", actor="hermes")
        eng = WorkflowEngine(simple)
        eng.begin(inst, "fetch")
        eng.fail(inst, "fetch", error="上游 500")
        bridge.on_finish(inst)
        card = cards.store.require(cid)
        assert card.status is CardStatus.BLOCKED
        assert any("fetch" in e.note for e in card.evidence)


# ── 对账 ──────────────────────────────────────────────────────────────────
class TestReconcile:
    def test_unlinked_instance_reports_not_linked(self, bridge, simple):
        assert bridge.reconcile(started(simple))["linked"] is False

    def test_in_step_pair_has_no_drift(self, bridge, cards, simple):
        inst = started(simple)
        bridge.on_start(inst, owner="seo-tech", actor="hermes")
        assert bridge.reconcile(inst)["drift"] == []

    def test_done_workflow_with_in_progress_card_is_drift(
        self, bridge, cards, simple
    ):
        """漏事件的场景：工作流完成了但卡没跟上。"""
        inst = started(simple)
        bridge.on_start(inst, owner="seo-tech", actor="hermes")
        eng = WorkflowEngine(simple)
        for nid in ("fetch", "report"):
            eng.begin(inst, nid)
            eng.complete(inst, nid, acceptance_met=[True], actor="seo-tech")
        # 故意不调 on_finish
        drift = bridge.reconcile(inst)["drift"]
        assert any("状态漂移" in d for d in drift)

    def test_passed_card_with_unfinished_workflow_is_flagged(
        self, bridge, cards, simple
    ):
        inst = started(simple)
        cid = bridge.on_start(inst, owner="seo-tech", actor="hermes")
        cards.move(cid, CardStatus.REVIEW, actor="seo-tech")
        cards.approve(cid, reviewer="hermes", require_verification=False)
        drift = bridge.reconcile(inst)["drift"]
        assert any("假完成候选" in d for d in drift)


# ── 铁律：桥接故障不得拖垮工作流 ─────────────────────────────────────────
class TestResilience:
    def test_ledger_failure_does_not_break_the_pipeline(self, cards, simple):
        class Broken(TaskCardService):
            def open_card(self, **kw):
                raise RuntimeError("账本不可达")

        broken = Broken(cards.store, dept="seo")
        bridge = WorkflowCardBridge(broken)
        inst = started(simple)
        assert bridge.on_start(inst, actor="hermes") == ""

        eng = WorkflowEngine(simple)
        for nid in ("fetch", "report"):
            eng.begin(inst, nid)
            eng.complete(inst, nid, acceptance_met=[True], actor="seo-tech")
            bridge.on_node_done(inst, nid, actor="seo-tech")
        bridge.on_finish(inst)
        assert inst.status is InstanceStatus.DONE
        assert all(r.state is NodeState.DONE for r in inst.runs.values())

    def test_evidence_write_failure_is_swallowed(self, cards, simple, monkeypatch):
        bridge = WorkflowCardBridge(cards)
        inst = started(simple)
        bridge.on_start(inst, owner="seo-tech", actor="hermes")

        def boom(*a, **kw):
            raise RuntimeError("磁盘满")

        monkeypatch.setattr(cards, "add_evidence", boom)
        bridge.on_node_done(inst, "fetch", actor="seo-tech")  # 不得抛出
