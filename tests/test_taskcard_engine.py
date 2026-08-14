"""G1-I taskcard engine — the gates that make PASSED mean something.

The tests are organised around the three failures of the retired markdown
ledger: status drift, acceptance by assertion, and self-review.
"""
from __future__ import annotations

import datetime as _dt

import pytest

from dojocore.taskcard.models import (
    CardError,
    CardLevel,
    CardStatus,
    TaskCard,
    new_card_id,
)
from dojocore.taskcard.service import TaskCardService
from dojocore.taskcard.store import TaskCardStore


@pytest.fixture()
def store(tmp_path):
    return TaskCardStore(tmp_path, dept="seo")


@pytest.fixture()
def svc(store):
    return TaskCardService(store, dept="seo")


def _open(svc, **kw):
    kw.setdefault("title", "测试卡")
    kw.setdefault("goal", "验证任务卡引擎")
    kw.setdefault("acceptance", ["端点返回 200"])
    return svc.open_card(actor="hermes", **kw)


def _to_review(svc, card_id, owner="seo-tech"):
    svc.assign(card_id, owner, actor="hermes")
    svc.move(card_id, CardStatus.IN_PROGRESS, actor=owner)
    svc.submit_for_review(card_id, actor=owner)


# ── 卡号 ──────────────────────────────────────────────────────────────────
class TestCardId:
    def test_format(self):
        when = _dt.datetime(2026, 8, 14, tzinfo=_dt.timezone.utc)
        assert new_card_id("seo", 1, when) == "TSEO20260814-01"
        assert new_card_id("seo", 12, when) == "TSEO20260814-12"

    def test_rejects_empty_dept(self):
        with pytest.raises(CardError, match="部门标识非法"):
            new_card_id("---", 1)

    def test_sequence_increments_per_day(self, store):
        first = store.next_card_id("seo")
        store.put(TaskCard.create(card_id=first, dept="seo", title="a", goal="g"))
        assert store.next_card_id("seo").endswith("-02")

    def test_departments_do_not_share_a_sequence(self, store):
        a = store.next_card_id("seo")
        store.put(TaskCard.create(card_id=a, dept="seo", title="a", goal="g"))
        assert store.next_card_id("creative").endswith("-01")


# ── 校验 ──────────────────────────────────────────────────────────────────
class TestValidation:
    def test_goal_is_mandatory(self):
        with pytest.raises(CardError, match="缺 goal"):
            TaskCard.create(card_id="TSEO20260814-01", dept="seo",
                            title="t", goal="  ")

    def test_bad_id_rejected(self):
        with pytest.raises(CardError, match="card_id 格式错误"):
            TaskCard.create(card_id="T-1", dept="seo", title="t", goal="g")

    def test_creation_writes_an_opening_evidence_line(self, svc):
        card = _open(svc)
        assert card.evidence[0].actor == "hermes"
        assert card.evidence[0].kind == "transition"


# ── 状态机（防漂移）──────────────────────────────────────────────────────
class TestStateMachine:
    def test_illegal_edge_is_refused_with_the_legal_set(self, svc):
        card = _open(svc)
        with pytest.raises(CardError, match="非法状态迁移"):
            svc.move(card.card_id, CardStatus.PASSED, actor="hermes")

    def test_draft_cannot_be_assigned_without_owner(self, svc, store):
        card = _open(svc)
        with pytest.raises(CardError, match="无 owner"):
            svc.move(card.card_id, CardStatus.ASSIGNED, actor="hermes")

    def test_terminal_states_are_final(self, svc):
        card = _open(svc)
        svc.move(card.card_id, CardStatus.CANCELLED, actor="hermes")
        with pytest.raises(CardError, match="非法状态迁移"):
            svc.move(card.card_id, CardStatus.IN_PROGRESS, actor="hermes")

    def test_rejected_cannot_jump_straight_to_passed(self, svc):
        card = _open(svc, level="L1")
        _to_review(svc, card.card_id)
        svc.reject(card.card_id, reviewer="hermes", reason="证据不足")
        with pytest.raises(CardError, match="非法状态迁移"):
            svc.move(card.card_id, CardStatus.PASSED, actor="hermes")

    def test_every_transition_appends_attributed_evidence(self, svc):
        card = _open(svc)
        svc.assign(card.card_id, "seo-tech", actor="hermes")
        moved = svc.move(card.card_id, CardStatus.IN_PROGRESS, actor="seo-tech")
        last = moved.evidence[-1]
        assert last.kind == "transition"
        assert last.actor == "seo-tech"
        assert "进行中" in last.note

    def test_anonymous_change_is_refused(self, svc):
        card = _open(svc)
        with pytest.raises(CardError, match="必须记名"):
            svc.move(card.card_id, CardStatus.CANCELLED, actor="  ")

    def test_reject_demands_a_reason(self, svc):
        card = _open(svc)
        _to_review(svc, card.card_id)
        with pytest.raises(CardError, match="必须写原因"):
            svc.reject(card.card_id, reviewer="hermes", reason="")


# ── 双验收位（防自审）────────────────────────────────────────────────────
class TestReviewGate:
    def test_self_review_is_refused(self, svc):
        card = _open(svc, level="L1")
        _to_review(svc, card.card_id, owner="seo-tech")
        with pytest.raises(CardError, match="自审被拒"):
            svc.approve(card.card_id, reviewer="seo-tech")

    def test_other_reviewer_passes(self, svc):
        card = _open(svc, level="L1")
        _to_review(svc, card.card_id, owner="seo-tech")
        done = svc.approve(card.card_id, reviewer="hermes")
        assert done.status is CardStatus.PASSED
        assert done.reviewed_by == "hermes"

    def test_l3_same_provider_is_refused(self, svc):
        card = _open(svc, level="L3", owner_provider="zhipu")
        _to_review(svc, card.card_id, owner="seo-tech")
        with pytest.raises(CardError, match="异构评审门禁未过"):
            svc.approve(card.card_id, reviewer="hermes", reviewer_provider="ZhiPu")

    def test_l3_requires_declaring_reviewer_provider(self, svc):
        card = _open(svc, level="L3", owner_provider="zhipu")
        _to_review(svc, card.card_id, owner="seo-tech")
        with pytest.raises(CardError, match="须声明 reviewer_provider"):
            svc.approve(card.card_id, reviewer="hermes")

    def test_l3_different_provider_passes(self, svc):
        card = _open(svc, level="L3", owner_provider="zhipu")
        _to_review(svc, card.card_id, owner="seo-tech")
        done = svc.approve(card.card_id, reviewer="hermes",
                           reviewer_provider="anthropic")
        assert done.status is CardStatus.PASSED

    def test_l2_does_not_need_heterogeneous_review(self, svc):
        card = _open(svc, level="L2", owner_provider="zhipu")
        _to_review(svc, card.card_id, owner="seo-tech")
        assert svc.approve(card.card_id, reviewer="hermes").status is CardStatus.PASSED

    def test_provider_comparison_ignores_spacing_and_case(self):
        assert CardLevel.L3.needs_heterogeneous_review
        card = TaskCard.create(card_id="TSEO20260814-01", dept="seo", title="t",
                               goal="g", level=CardLevel.L3, owner="a",
                               owner_provider="zhi_pu")
        card.status = CardStatus.REVIEW
        with pytest.raises(CardError, match="异构评审门禁未过"):
            card.transition(CardStatus.PASSED, "b", reviewer_provider="ZHI PU")


# ── 验证执行（防口头验收）────────────────────────────────────────────────
class TestVerification:
    def test_verify_actually_runs_the_command(self, svc):
        card = _open(svc, verify_cmd="exit 0")
        result = svc.verify(card.card_id)
        assert result.passed and result.exit_code == 0
        assert svc.store.require(card.card_id).has_passing_verification

    def test_failing_command_is_recorded_as_failure(self, svc):
        card = _open(svc, verify_cmd="exit 3")
        result = svc.verify(card.card_id)
        assert not result.passed and result.exit_code == 3
        assert not svc.store.require(card.card_id).has_passing_verification

    def test_stdout_is_captured_into_evidence(self, svc):
        card = _open(svc, verify_cmd="echo HTTP_200_OK")
        svc.verify(card.card_id)
        note = svc.store.require(card.card_id).evidence_of("verify")[-1].note
        assert "HTTP_200_OK" in note

    def test_card_without_verify_cmd_refuses_to_verify(self, svc):
        card = _open(svc)
        with pytest.raises(CardError, match="未定义 verify_cmd"):
            svc.verify(card.card_id)

    def test_approve_blocked_until_verification_passes(self, svc):
        card = _open(svc, level="L1", verify_cmd="exit 1")
        _to_review(svc, card.card_id)
        with pytest.raises(CardError, match="无成功验证记录"):
            svc.approve(card.card_id, reviewer="hermes")

    def test_approve_allowed_after_verification_passes(self, svc):
        card = _open(svc, level="L1", verify_cmd="exit 0")
        _to_review(svc, card.card_id)
        svc.verify(card.card_id)
        assert svc.approve(card.card_id, reviewer="hermes").status is CardStatus.PASSED

    def test_failed_then_fixed_then_approved(self, svc):
        card = _open(svc, level="L1", verify_cmd="exit 0")
        _to_review(svc, card.card_id)
        svc.reject(card.card_id, reviewer="hermes", reason="端点仍 500")
        svc.move(card.card_id, CardStatus.REVIEW, actor="seo-tech", note="已修")
        svc.verify(card.card_id)
        assert svc.approve(card.card_id, reviewer="hermes").status is CardStatus.PASSED


# ── 审计（假完成扫描）────────────────────────────────────────────────────
class TestAudit:
    def test_clean_card_has_no_flags(self, svc):
        card = _open(svc, level="L1", verify_cmd="exit 0")
        _to_review(svc, card.card_id)
        svc.verify(card.card_id)
        assert svc.approve(card.card_id, reviewer="hermes").audit_flags() == []

    def test_passed_without_verification_is_flagged(self, svc):
        card = _open(svc, level="L1", verify_cmd="exit 0")
        _to_review(svc, card.card_id)
        done = svc.approve(card.card_id, reviewer="hermes",
                           require_verification=False)
        assert any("假完成候选" in f for f in done.audit_flags())

    def test_missing_acceptance_is_flagged(self, svc):
        card = _open(svc, acceptance=[])
        assert any("缺验收标准" in f for f in card.audit_flags())

    def test_active_without_owner_is_flagged(self, svc):
        card = _open(svc)
        card.status = CardStatus.IN_PROGRESS
        assert any("无人负责" in f for f in card.audit_flags())

    def test_audit_collects_flagged_cards(self, svc):
        _open(svc, acceptance=[])
        _open(svc, title="干净卡", verify_cmd="exit 0")
        flagged = svc.audit()
        assert len(flagged) >= 1
        assert all(f["flags"] for f in flagged)


# ── 存储与查询 ────────────────────────────────────────────────────────────
class TestStore:
    def test_roundtrip_preserves_evidence_chain(self, svc, store):
        card = _open(svc, verify_cmd="exit 0")
        svc.verify(card.card_id)
        again = store.require(card.card_id)
        assert len(again.evidence) == len(card.evidence) + 1
        assert again.evidence_of("verify")[-1].exit_code == 0

    def test_active_excludes_terminal_cards(self, svc, store):
        keep = _open(svc)
        svc.assign(keep.card_id, "seo-tech", actor="hermes")
        gone = _open(svc, title="取消卡")
        svc.move(gone.card_id, CardStatus.CANCELLED, actor="hermes")
        ids = {c.card_id for c in store.active()}
        assert keep.card_id in ids and gone.card_id not in ids

    def test_by_owner_filters(self, svc, store):
        a = _open(svc)
        svc.assign(a.card_id, "seo-tech", actor="hermes")
        b = _open(svc, title="别人的")
        svc.assign(b.card_id, "seo-analyst", actor="hermes")
        assert [c.card_id for c in store.by_owner("seo-tech")] == [a.card_id]

    def test_children_and_collab_links(self, svc, store):
        parent = _open(svc, title="母卡")
        child = _open(svc, title="子卡", parent_card=parent.card_id,
                      collab_req="REQ-001")
        assert [c.card_id for c in store.children(parent.card_id)] == [child.card_id]
        assert [c.card_id for c in store.by_collab_req("REQ-001")] == [child.card_id]

    def test_stalled_finds_untouched_active_cards(self, svc, store):
        fresh = _open(svc)
        svc.assign(fresh.card_id, "seo-tech", actor="hermes")
        old = _open(svc, title="停滞卡")
        svc.assign(old.card_id, "seo-tech", actor="hermes")
        stale = store.require(old.card_id)
        stale.updated_at = (
            _dt.datetime.now(_dt.timezone.utc) - _dt.timedelta(hours=5)
        ).isoformat()
        store.put(stale)
        ids = {c.card_id for c in store.stalled(hours=2)}
        assert old.card_id in ids and fresh.card_id not in ids

    def test_summary_reports_real_counts(self, svc):
        card = _open(svc)
        svc.assign(card.card_id, "seo-tech", actor="hermes")
        s = svc.summary()
        assert s["data_status"] == "REAL"
        assert s["total"] == 1 and s["active"] == 1

    def test_serialisation_roundtrip(self, svc):
        card = _open(svc, verify_cmd="exit 0", github_issue=10)
        restored = TaskCard.from_dict(card.to_dict())
        assert restored.card_id == card.card_id
        assert restored.github_issue == 10
        assert restored.level is card.level
        assert len(restored.evidence) == len(card.evidence)
