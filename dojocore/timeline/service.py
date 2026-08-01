"""Timeline service — planning, firing, acknowledging, and recovering.

The sequence an agent follows for every incoming task:

    agenda()          read what is already committed to
    plan_task()       judge where the new work fits, write START + CHECKPOINT
    due()             the scheduler asks what should fire now
    fire()            delivered
    ack()             the agent actually handled it
    sweep()           after the fact: what never fired, what fired unhandled
    triage()          after recovery: catch up or drop, in one pass, with reasons

Firing and acknowledging are deliberately two events. A reminder delivered into
a dead gateway looks identical to one that worked unless the two are recorded
separately, and "the reminder silently never happened" is precisely the failure
that lets work stall unnoticed.
"""
from __future__ import annotations

import datetime as _dt
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from dojocore.logging import LOGGER
from dojocore.timeline.models import (
    UNREAD_STATES,
    NodeKind,
    NodeState,
    OnMiss,
    TimelineError,
    TimelineNode,
    new_node_id,
)
from dojocore.timeline.store import TimelineStore

__all__ = ["PlanLimits", "TimelineService"]


def _now() -> _dt.datetime:
    return _dt.datetime.now(_dt.timezone.utc)


@dataclass(frozen=True)
class PlanLimits:
    """Guards against an agent scheduling itself into a corner.

    A checkpoint that schedules another checkpoint is the natural shape of
    "keep an eye on this", and also the natural shape of an infinite loop. The
    depth cap is what separates the two.
    """

    max_nodes_per_day: int = 60
    max_chain_depth: int = 8
    min_gap_minutes: int = 5
    max_horizon_days: int = 30


class TimelineService:
    def __init__(
        self, store: TimelineStore, *, owner: str = "hm", limits: PlanLimits | None = None
    ) -> None:
        self.store = store
        self.owner = owner
        self.limits = limits or PlanLimits()

    # -- reading before planning ------------------------------------------
    def agenda(
        self, *, hours_ahead: int = 24, now: _dt.datetime | None = None
    ) -> dict[str, Any]:
        """What the agent has already committed to.

        Called *before* planning anything new — the point of a timeline is that
        new work is fitted around existing commitments rather than declared into
        a vacuum.
        """
        now = now or _now()
        horizon = now + _dt.timedelta(hours=hours_ahead)
        upcoming = [
            n for n in self.store.between(now, horizon)
            if n.state is NodeState.SCHEDULED
        ]
        unread = self.store.by_states(UNREAD_STATES)
        in_flight = self.store.by_states({NodeState.FIRED})
        committed = sum(n.expected_minutes for n in upcoming)
        return {
            "now": now.isoformat(),
            "horizon_hours": hours_ahead,
            "upcoming": [n.to_dict() for n in upcoming],
            "in_flight": [n.to_dict() for n in in_flight],
            "unread_count": len(unread),
            "committed_minutes": committed,
            "load_ratio": round(committed / (hours_ahead * 60), 3) if hours_ahead else 0.0,
            "next_free_slot": self._next_free_slot(upcoming, now).isoformat(),
        }

    def _next_free_slot(
        self, upcoming: Iterable[TimelineNode], now: _dt.datetime, need_minutes: int = 15
    ) -> _dt.datetime:
        cursor = now + _dt.timedelta(minutes=self.limits.min_gap_minutes)
        for node in sorted(upcoming, key=lambda n: n.due()):
            if node.due() - cursor >= _dt.timedelta(minutes=need_minutes):
                return cursor
            cursor = max(cursor, node.ends_at() + _dt.timedelta(minutes=self.limits.min_gap_minutes))
        return cursor

    def conflicts(self, candidate: TimelineNode) -> list[TimelineNode]:
        window_start = candidate.due() - _dt.timedelta(hours=6)
        window_end = candidate.ends_at() + _dt.timedelta(hours=6)
        return [
            n for n in self.store.between(window_start, window_end)
            if n.state is NodeState.SCHEDULED and n.node_id != candidate.node_id
            and n.overlaps(candidate)
        ]

    # -- planning ----------------------------------------------------------
    def schedule(self, payload: Mapping[str, Any], *, allow_conflict: bool = False) -> TimelineNode:
        node = TimelineNode.from_dict({**payload, "node_id": payload.get("node_id") or new_node_id()})
        node.created_at = node.created_at or _now().isoformat()
        node.created_by = node.created_by or self.owner

        horizon = _now() + _dt.timedelta(days=self.limits.max_horizon_days)
        if node.due() > horizon:
            raise TimelineError(
                f"排期超出 {self.limits.max_horizon_days} 天视野 —— "
                f"太远的计划应留给任务卡,不是时间线"
            )
        if node.chain_depth > self.limits.max_chain_depth:
            raise TimelineError(
                f"检查链深度 {node.chain_depth} 超过上限 {self.limits.max_chain_depth} —— "
                f"连续 {self.limits.max_chain_depth} 次「再看一眼」说明这件事卡住了,"
                f"应当上报而不是继续排下一个检查"
            )
        day_count = self.store.count_on_day(node.due().date())
        if day_count >= self.limits.max_nodes_per_day:
            raise TimelineError(
                f"{node.due().date()} 已排 {day_count} 个节点,达到上限 "
                f"{self.limits.max_nodes_per_day};排程失控通常是循环排期的征兆"
            )
        if not allow_conflict:
            clash = self.conflicts(node)
            if clash:
                raise TimelineError(
                    f"与已排节点冲突: {[c.node_id for c in clash]};"
                    f"下一个空档 {self._next_free_slot(clash, _now(), node.expected_minutes).isoformat()}"
                )
        self.store.put(node)
        LOGGER.info(
            f"timeline: {node.node_id} {node.kind.value} @ {node.scheduled_at} — {node.intent}"
        )
        return node

    def plan_task(
        self,
        *,
        intent: str,
        subject_ref: str,
        start_at: _dt.datetime,
        expected_minutes: int = 15,
        checkpoint_after_minutes: int | None = 15,
        on_miss: OnMiss | str = OnMiss.CATCHUP,
        context: Mapping[str, Any] | None = None,
    ) -> list[TimelineNode]:
        """The common shape: begin the work, then check on it.

        The follow-up defaults to RESCHEDULE on miss: a progress check four
        hours late tells you nothing, but the intent behind it — find out
        whether that finished — has not expired.
        """
        start = self.schedule(
            {
                "scheduled_at": start_at.isoformat(),
                "kind": NodeKind.START.value,
                "intent": intent,
                "subject_ref": subject_ref,
                "expected_minutes": expected_minutes,
                "on_miss": OnMiss(on_miss).value if not isinstance(on_miss, OnMiss) else on_miss.value,
                "context": dict(context or {}),
            }
        )
        nodes = [start]
        if checkpoint_after_minutes:
            check_at = start.ends_at() + _dt.timedelta(minutes=checkpoint_after_minutes)
            nodes.append(
                self.schedule(
                    {
                        "scheduled_at": check_at.isoformat(),
                        "kind": NodeKind.CHECKPOINT.value,
                        "intent": f"检查「{intent}」是否完成;完成了是否已汇报,未完成则排下一个检查",
                        "subject_ref": subject_ref,
                        "expected_minutes": 5,
                        "on_miss": OnMiss.RESCHEDULE.value,
                        "parent_node": start.node_id,
                        "chain_depth": start.chain_depth + 1,
                    },
                    allow_conflict=True,   # a 5-minute check may sit inside other work
                )
            )
        return nodes

    def follow_up(
        self, parent: TimelineNode, *, after_minutes: int, intent: str = ""
    ) -> TimelineNode:
        """Chain another check off an unfinished one, depth-capped."""
        return self.schedule(
            {
                "scheduled_at": (_now() + _dt.timedelta(minutes=after_minutes)).isoformat(),
                "kind": NodeKind.CHECKPOINT.value,
                "intent": intent or f"继续跟进「{parent.intent}」",
                "subject_ref": parent.subject_ref,
                "expected_minutes": 5,
                "on_miss": OnMiss.RESCHEDULE.value,
                "parent_node": parent.node_id,
                "chain_depth": parent.chain_depth + 1,
            },
            allow_conflict=True,
        )

    # -- delivery ----------------------------------------------------------
    def due(self, *, now: _dt.datetime | None = None) -> list[TimelineNode]:
        now = now or _now()
        return [n for n in self.store.by_states({NodeState.SCHEDULED}) if n.is_due(now)]

    def fire(self, node_id: str, *, now: _dt.datetime | None = None) -> TimelineNode:
        node = self._get(node_id)
        if node.state is not NodeState.SCHEDULED:
            raise TimelineError(f"节点 {node_id} 状态为 {node.state.value},不可投递")
        node.state = NodeState.FIRED
        node.fired_at = (now or _now()).isoformat()
        self.store.put(node)
        LOGGER.info(f"timeline: {node_id} FIRED — {node.intent}")
        return node

    def ack(self, node_id: str, *, outcome: str, now: _dt.datetime | None = None) -> TimelineNode:
        """The agent read it and acted. Without an outcome this is not an ack."""
        if not outcome.strip():
            raise TimelineError(
                "ack 必须写明 outcome —— "
                "「读到了」和「处理了」不是一回事,后者才是这个状态的含义"
            )
        node = self._get(node_id)
        if node.state not in (NodeState.FIRED, NodeState.CATCHUP):
            raise TimelineError(f"节点 {node_id} 状态为 {node.state.value},不可确认")
        node.state = NodeState.ACKED
        node.acked_at = (now or _now()).isoformat()
        node.outcome = outcome
        self.store.put(node)
        LOGGER.info(f"timeline: {node_id} ACKED — {outcome[:60]}")
        return node

    def cancel(self, node_id: str, *, reason: str) -> TimelineNode:
        node = self._get(node_id)
        if node.state is not NodeState.SCHEDULED:
            raise TimelineError(f"只能撤销未触发的节点,{node_id} 当前为 {node.state.value}")
        node.state = NodeState.CANCELLED
        node.triage_reason = reason
        self.store.put(node)
        return node

    # -- recovery ----------------------------------------------------------
    def sweep(self, *, grace_minutes: int = 10, now: _dt.datetime | None = None) -> dict[str, list]:
        """Detect what silently did not happen.

        Two distinct faults, kept separate because they point at different
        components: MISSED means the scheduler never ran, UNACKED means it ran
        but the agent never handled the result.
        """
        now = now or _now()
        missed, unacked = [], []

        for node in self.store.by_states({NodeState.SCHEDULED}):
            if node.lateness_minutes(now) > grace_minutes:
                node.state = NodeState.MISSED
                self.store.put(node)
                missed.append(node)
                LOGGER.warning(
                    f"timeline: {node.node_id} MISSED — 到点未触发(调度器未运行?)"
                )

        for node in self.store.by_states({NodeState.FIRED}):
            fired = _dt.datetime.fromisoformat(node.fired_at) if node.fired_at else node.due()
            if (now - fired).total_seconds() / 60 > grace_minutes:
                node.state = NodeState.UNACKED
                self.store.put(node)
                unacked.append(node)
                LOGGER.warning(
                    f"timeline: {node.node_id} UNACKED — 已投递但无人处理(模型不可达?)"
                )

        return {"missed": missed, "unacked": unacked}

    def unread(self) -> list[TimelineNode]:
        """Everything awaiting a triage decision, oldest first."""
        return sorted(self.store.by_states(UNREAD_STATES), key=lambda n: n.due())

    def triage(
        self, decisions: Iterable[Mapping[str, Any]], *, now: _dt.datetime | None = None
    ) -> dict[str, Any]:
        """One pass over the backlog after recovery.

        Each decision must carry a reason. Silently dropping a missed reminder
        is how a stalled task stays stalled, so "ignore" is not an option here —
        only an explicit discard, on the record.
        """
        now = now or _now()
        applied, rescheduled = [], []
        for decision in decisions:
            node = self._get(str(decision["node_id"]))
            if node.state not in UNREAD_STATES:
                raise TimelineError(
                    f"节点 {node.node_id} 不在未读队列(当前 {node.state.value})"
                )
            action = OnMiss(decision.get("action") or node.on_miss.value)
            reason = str(decision.get("reason", "")).strip()
            if not reason:
                raise TimelineError(
                    f"节点 {node.node_id} 的处置必须给出理由 —— "
                    f"未读提醒被无声丢弃,正是任务停滞无人发现的成因"
                )
            if action is OnMiss.ASK:
                raise TimelineError(
                    f"节点 {node.node_id} 的 on_miss 是「届时判断」,"
                    f"triage 时必须给出具体动作(catchup/discard/reschedule)"
                )

            node.triage_reason = reason
            if action is OnMiss.CATCHUP:
                node.state = NodeState.CATCHUP
            elif action is OnMiss.DISCARD:
                node.state = NodeState.DISCARDED
            else:  # RESCHEDULE — the moment passed, the intent did not
                node.state = NodeState.DISCARDED
                delay = int(decision.get("reschedule_in_minutes", 15))
                fresh = self.schedule(
                    {
                        "scheduled_at": (now + _dt.timedelta(minutes=delay)).isoformat(),
                        "kind": node.kind.value,
                        "intent": node.intent,
                        "subject_ref": node.subject_ref,
                        "expected_minutes": node.expected_minutes,
                        "on_miss": OnMiss.RESCHEDULE.value,
                        "parent_node": node.node_id,
                        "chain_depth": node.chain_depth + 1,
                        "context": {**dict(node.context), "rescheduled_from": node.node_id},
                    },
                    allow_conflict=True,
                )
                rescheduled.append(fresh)
            self.store.put(node)
            applied.append(node)

        remaining = self.unread()
        return {
            "applied": [n.to_dict() for n in applied],
            "rescheduled": [n.to_dict() for n in rescheduled],
            "remaining_unread": [n.to_dict() for n in remaining],
        }

    # -- helpers -----------------------------------------------------------
    def _get(self, node_id: str) -> TimelineNode:
        node = self.store.get(node_id)
        if node is None:
            raise TimelineError(f"时间线节点不存在: {node_id}")
        return node
