"""Self-managed agent time.

The interesting cases are the ones where nothing happened: a reminder that
never fired, one that fired into a dead gateway, and a backlog that must be
decided rather than quietly dropped.
"""
from __future__ import annotations

import datetime as dt
import tempfile

import pytest

from dojocore.timeline import (
    NodeKind,
    NodeState,
    OnMiss,
    PlanLimits,
    TimelineError,
    TimelineService,
    TimelineStore,
)


@pytest.fixture()
def svc() -> TimelineService:
    return TimelineService(TimelineStore(tempfile.mkdtemp()), owner="hermes-seo")


def _now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


# ── planning reads before it writes ──────────────────────────────────────
def test_agenda_reports_existing_commitments(svc: TimelineService):
    """New work is fitted around what was already promised, not declared blind."""
    now = _now()
    svc.plan_task(intent="写文章", subject_ref="T-1",
                  start_at=now + dt.timedelta(hours=1), expected_minutes=60,
                  checkpoint_after_minutes=None)
    agenda = svc.agenda(hours_ahead=24, now=now)
    assert agenda["committed_minutes"] == 60
    assert len(agenda["upcoming"]) == 1
    assert agenda["next_free_slot"]


def test_overlapping_work_is_refused_with_a_free_slot(svc: TimelineService):
    now = _now()
    svc.plan_task(intent="审计", subject_ref="T-1",
                  start_at=now + dt.timedelta(hours=1), expected_minutes=60,
                  checkpoint_after_minutes=None)
    with pytest.raises(TimelineError, match="冲突"):
        svc.schedule({
            "scheduled_at": (now + dt.timedelta(hours=1, minutes=30)).isoformat(),
            "kind": "START", "intent": "另一件事", "expected_minutes": 30,
        })


def test_planning_a_task_also_plans_the_follow_up(svc: TimelineService):
    """"Start it" without "check on it" is how work quietly stops."""
    nodes = svc.plan_task(intent="发布文章", subject_ref="T-9",
                          start_at=_now() + dt.timedelta(minutes=30))
    assert [n.kind for n in nodes] == [NodeKind.START, NodeKind.CHECKPOINT]
    check = nodes[1]
    assert check.parent_node == nodes[0].node_id
    # A late progress check is worthless, but the intent behind it is not.
    assert check.on_miss is OnMiss.RESCHEDULE


def test_checkpoint_must_name_what_it_checks(svc: TimelineService):
    with pytest.raises(TimelineError, match="检查对象"):
        svc.schedule({
            "scheduled_at": (_now() + dt.timedelta(minutes=30)).isoformat(),
            "kind": "CHECKPOINT", "intent": "看一下",
        })


def test_node_requires_an_intent_its_future_self_can_read(svc: TimelineService):
    with pytest.raises(TimelineError, match="intent"):
        svc.schedule({
            "scheduled_at": (_now() + dt.timedelta(minutes=30)).isoformat(),
            "kind": "START", "intent": "   ",
        })


# ── runaway guards ───────────────────────────────────────────────────────
def test_endless_check_chains_are_capped(svc: TimelineService):
    """"Check again" chaining forever is a stall, and should be escalated."""
    svc.limits = PlanLimits(max_chain_depth=3)
    with pytest.raises(TimelineError, match="上报"):
        svc.schedule({
            "scheduled_at": (_now() + dt.timedelta(minutes=30)).isoformat(),
            "kind": "CHECKPOINT", "intent": "再看一眼", "subject_ref": "T-1",
            "chain_depth": 4,
        })


def test_daily_node_cap(svc: TimelineService):
    svc.limits = PlanLimits(max_nodes_per_day=2, min_gap_minutes=1)
    base = _now() + dt.timedelta(minutes=10)
    for i in range(2):
        svc.schedule({
            "scheduled_at": (base + dt.timedelta(hours=i)).isoformat(),
            "kind": "START", "intent": f"任务{i}", "expected_minutes": 5,
        })
    with pytest.raises(TimelineError, match="上限"):
        svc.schedule({
            "scheduled_at": (base + dt.timedelta(hours=5)).isoformat(),
            "kind": "START", "intent": "第三个", "expected_minutes": 5,
        })


def test_far_future_belongs_on_a_task_card_not_the_timeline(svc: TimelineService):
    with pytest.raises(TimelineError, match="视野"):
        svc.schedule({
            "scheduled_at": (_now() + dt.timedelta(days=90)).isoformat(),
            "kind": "START", "intent": "很久以后",
        })


# ── firing is not handling ───────────────────────────────────────────────
def test_fired_and_acked_are_separate_events(svc: TimelineService):
    """A reminder delivered into a dead gateway must not look like a handled one."""
    node = svc.plan_task(intent="采集 GSC", subject_ref="T-2",
                         start_at=_now() + dt.timedelta(minutes=1),
                         checkpoint_after_minutes=None)[0]
    fired = svc.fire(node.node_id)
    assert fired.state is NodeState.FIRED and fired.fired_at and not fired.acked_at

    acked = svc.ack(node.node_id, outcome="已采集 47 条,写入历史库")
    assert acked.state is NodeState.ACKED and acked.acked_at and acked.outcome


def test_ack_without_an_outcome_is_not_an_ack(svc: TimelineService):
    node = svc.plan_task(intent="任务", subject_ref="T-3",
                         start_at=_now() + dt.timedelta(minutes=1),
                         checkpoint_after_minutes=None)[0]
    svc.fire(node.node_id)
    with pytest.raises(TimelineError, match="outcome"):
        svc.ack(node.node_id, outcome="")


# ── detecting what silently did not happen ───────────────────────────────
def test_sweep_separates_a_dead_scheduler_from_a_dead_agent(svc: TimelineService):
    """The two faults point at different components, so they stay distinct."""
    now = _now()
    never_fired = svc.plan_task(intent="A", subject_ref="T-4",
                                start_at=now + dt.timedelta(minutes=10),
                                expected_minutes=15,
                                checkpoint_after_minutes=None)[0]
    fired_ignored = svc.plan_task(intent="B", subject_ref="T-5",
                                  start_at=now + dt.timedelta(minutes=40),
                                  expected_minutes=15,
                                  checkpoint_after_minutes=None)[0]
    svc.fire(fired_ignored.node_id, now=now + dt.timedelta(minutes=40))

    result = svc.sweep(grace_minutes=10, now=now + dt.timedelta(hours=3))
    assert [n.node_id for n in result["missed"]] == [never_fired.node_id]
    assert [n.node_id for n in result["unacked"]] == [fired_ignored.node_id]
    assert {n.node_id for n in svc.unread()} == {never_fired.node_id, fired_ignored.node_id}


# ── recovery: decide, never ignore ───────────────────────────────────────
def test_triage_demands_a_reason_for_every_decision(svc: TimelineService):
    """Silently dropping a missed reminder is how a stalled task stays stalled."""
    now = _now()
    node = svc.plan_task(intent="任务", subject_ref="T-6",
                         start_at=now + dt.timedelta(minutes=1),
                         checkpoint_after_minutes=None)[0]
    svc.sweep(grace_minutes=0, now=now + dt.timedelta(hours=2))
    with pytest.raises(TimelineError, match="理由"):
        svc.triage([{"node_id": node.node_id, "action": "discard"}])


def test_triage_refuses_to_defer_the_judgement_again(svc: TimelineService):
    """on_miss=ask means "decide when it happens" — and it has happened."""
    now = _now()
    node = svc.schedule({
        "scheduled_at": (now + dt.timedelta(minutes=1)).isoformat(),
        "kind": "START", "intent": "待定策略的任务", "on_miss": "ask",
    })
    svc.sweep(grace_minutes=0, now=now + dt.timedelta(hours=2))
    with pytest.raises(TimelineError, match="具体动作"):
        svc.triage([{"node_id": node.node_id, "action": "ask", "reason": "回头再说"}])


def test_catchup_and_discard_are_recorded_with_reasons(svc: TimelineService):
    now = _now()
    a = svc.plan_task(intent="补得回来的活", subject_ref="T-7",
                      start_at=now + dt.timedelta(minutes=10), expected_minutes=15,
                      checkpoint_after_minutes=None)[0]
    b = svc.plan_task(intent="过期就没用的提醒", subject_ref="T-8",
                      start_at=now + dt.timedelta(minutes=40), expected_minutes=15,
                      checkpoint_after_minutes=None)[0]
    svc.sweep(grace_minutes=0, now=now + dt.timedelta(hours=4))

    out = svc.triage([
        {"node_id": a.node_id, "action": "catchup", "reason": "任务本身还在,晚做也有效"},
        {"node_id": b.node_id, "action": "discard", "reason": "该时点已过,提醒无意义"},
    ], now=now + dt.timedelta(hours=4))

    assert svc.store.get(a.node_id).state is NodeState.CATCHUP
    assert svc.store.get(b.node_id).state is NodeState.DISCARDED
    assert all(n["triage_reason"] for n in out["applied"])
    assert out["remaining_unread"] == []


def test_reschedule_keeps_the_intent_and_drops_the_moment(svc: TimelineService):
    """A four-hour-late progress check tells you nothing; the question still stands."""
    now = _now()
    nodes = svc.plan_task(intent="发布文章", subject_ref="T-10",
                          start_at=now + dt.timedelta(minutes=1))
    check = nodes[1]
    svc.sweep(grace_minutes=0, now=now + dt.timedelta(hours=4))

    out = svc.triage([{
        "node_id": check.node_id, "action": "reschedule",
        "reason": "检查时点已过,但仍需确认是否完成", "reschedule_in_minutes": 10,
    }], now=now + dt.timedelta(hours=4))

    assert svc.store.get(check.node_id).state is NodeState.DISCARDED
    assert len(out["rescheduled"]) == 1
    fresh = out["rescheduled"][0]
    assert fresh["intent"] == check.intent
    assert fresh["context"]["rescheduled_from"] == check.node_id
    assert fresh["chain_depth"] == check.chain_depth + 1


def test_a_catchup_node_can_then_be_acked(svc: TimelineService):
    now = _now()
    node = svc.plan_task(intent="补做的活", subject_ref="T-11",
                         start_at=now + dt.timedelta(minutes=1),
                         checkpoint_after_minutes=None)[0]
    svc.sweep(grace_minutes=0, now=now + dt.timedelta(hours=2))
    svc.triage([{"node_id": node.node_id, "action": "catchup", "reason": "仍需完成"}])
    done = svc.ack(node.node_id, outcome="已补做完成")
    assert done.state is NodeState.ACKED


# ── follow-up chaining ───────────────────────────────────────────────────
def test_unfinished_work_chains_another_check(svc: TimelineService):
    nodes = svc.plan_task(intent="长任务", subject_ref="T-12",
                          start_at=_now() + dt.timedelta(minutes=1))
    check = nodes[1]
    nxt = svc.follow_up(check, after_minutes=20)
    assert nxt.chain_depth == check.chain_depth + 1
    assert nxt.subject_ref == check.subject_ref
