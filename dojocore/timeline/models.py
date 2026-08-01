"""Timeline nodes — an agent scheduling its own time.

A cron job is something done *to* an agent at a fixed hour. A timeline is
something an agent keeps *for itself*: on receiving work it reads what it has
already committed to, judges where the new task fits, and writes future nodes —
"start at 23:50, expect 15 minutes" and, crucially, "at 00:05 check whether that
finished and whether it was reported".

Two design points carry most of the value.

**Firing and reading are separate events.** A node that fired is not a node that
was handled: the scheduler can deliver into a dead gateway, or the model can be
unreachable. Recording ``fired_at`` and ``acked_at`` separately is what makes
"the reminder never actually happened" a detectable state rather than silence.
Seventeen notifications once failed here and the work was marked complete
anyway.

**Every node declares what to do if it is missed.** Deciding at planning time
forces the question "does this still matter three hours late?" while the intent
is fresh. A checkpoint that arrives four hours after the fact is worthless — but
the *intent* behind it (find out whether that finished) still is, which is a
different answer from "catch up" and from "drop it".
"""
from __future__ import annotations

import datetime as _dt
import re
import uuid
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

__all__ = [
    "UNREAD_STATES",
    "NodeKind",
    "NodeState",
    "OnMiss",
    "TimelineError",
    "TimelineNode",
    "new_node_id",
]

_ID_RE = re.compile(r"^TL-\d{8}-[0-9a-f]{8}$")


class TimelineError(ValueError):
    """A node or transition violates the timeline's rules."""


class NodeKind(str, Enum):
    START = "START"            # begin a piece of work
    CHECKPOINT = "CHECKPOINT"  # did that finish? was it reported?
    REPORT = "REPORT"          # time to report upward
    DEADLINE = "DEADLINE"      # hard due time
    RECURRING = "RECURRING"    # from a fixed rhythm (daily collection, etc.)
    REVIEW = "REVIEW"          # periodic reflection / retro

    @property
    def label(self) -> str:
        return _KIND_LABELS[self]

    @property
    def is_follow_up(self) -> bool:
        """Kinds whose value decays sharply with lateness."""
        return self in (NodeKind.CHECKPOINT, NodeKind.REPORT)


_KIND_LABELS = {
    NodeKind.START: "开始任务",
    NodeKind.CHECKPOINT: "进度检查",
    NodeKind.REPORT: "汇报",
    NodeKind.DEADLINE: "截止",
    NodeKind.RECURRING: "固定节律",
    NodeKind.REVIEW: "复盘",
}


class NodeState(str, Enum):
    SCHEDULED = "SCHEDULED"    # planned, not yet due
    FIRED = "FIRED"            # delivered by the scheduler, not yet handled
    ACKED = "ACKED"            # the agent read it and acted
    MISSED = "MISSED"          # due time passed and it never fired at all
    UNACKED = "UNACKED"        # it fired, but nobody ever handled it
    CATCHUP = "CATCHUP"        # triaged after recovery: do it late
    DISCARDED = "DISCARDED"    # triaged after recovery: let it go
    CANCELLED = "CANCELLED"    # withdrawn while still scheduled

    @property
    def settled(self) -> bool:
        return self in (
            NodeState.ACKED, NodeState.CATCHUP,
            NodeState.DISCARDED, NodeState.CANCELLED,
        )


# What the agent must look at after a restart. MISSED and UNACKED are kept
# distinct because they diagnose different faults: the scheduler died, versus
# the agent did.
UNREAD_STATES: frozenset[NodeState] = frozenset({NodeState.MISSED, NodeState.UNACKED})


class OnMiss(str, Enum):
    CATCHUP = "catchup"        # still worth doing late
    DISCARD = "discard"        # worthless once the moment passed
    RESCHEDULE = "reschedule"  # the moment passed, the intent has not
    ASK = "ask"                # let the agent judge with the situation in hand

    @property
    def label(self) -> str:
        return {
            OnMiss.CATCHUP: "补做",
            OnMiss.DISCARD: "丢弃",
            OnMiss.RESCHEDULE: "重排",
            OnMiss.ASK: "届时判断",
        }[self]


def _now() -> _dt.datetime:
    return _dt.datetime.now(_dt.timezone.utc)


def new_node_id(when: _dt.datetime | None = None) -> str:
    day = (when or _now()).strftime("%Y%m%d")
    return f"TL-{day}-{uuid.uuid4().hex[:8]}"


@dataclass
class TimelineNode:
    node_id: str
    scheduled_at: str                     # ISO-8601, absolute
    kind: NodeKind
    intent: str                           # what this node is for, in plain words
    subject_ref: str = ""                 # where the task text lives
    expected_minutes: int = 15
    on_miss: OnMiss = OnMiss.ASK
    state: NodeState = NodeState.SCHEDULED
    parent_node: str = ""                 # the node that spawned this one
    chain_depth: int = 0                  # guards against endless "check again"
    created_by: str = "agent"
    created_at: str = ""
    fired_at: str = ""
    acked_at: str = ""
    outcome: str = ""                     # what the agent did when it handled it
    triage_reason: str = ""               # why it was caught up or dropped
    context: Mapping[str, Any] = field(default_factory=dict)

    # -- validation --------------------------------------------------------
    def validate(self) -> None:
        if not _ID_RE.match(self.node_id):
            raise TimelineError(f"node_id 格式错误: {self.node_id};应为 TL-YYYYMMDD-<8hex>")
        if not self.intent.strip():
            raise TimelineError(
                f"节点 {self.node_id} 缺 intent —— "
                f"未来的自己读到这条时,必须能看懂当时为什么排它"
            )
        try:
            self.due()
        except ValueError as exc:
            raise TimelineError(f"scheduled_at 非法: {self.scheduled_at}") from exc
        if self.expected_minutes <= 0:
            raise TimelineError("expected_minutes 必须为正 —— 排期要给出耗时估计")
        # A checkpoint with nothing to check is a reminder to nobody.
        if self.kind is NodeKind.CHECKPOINT and not (self.subject_ref or self.parent_node):
            raise TimelineError(
                f"节点 {self.node_id} 是进度检查,必须指明检查对象"
                f"(subject_ref 或 parent_node)"
            )

    # -- time --------------------------------------------------------------
    def due(self) -> _dt.datetime:
        dt = _dt.datetime.fromisoformat(self.scheduled_at)
        return dt if dt.tzinfo else dt.replace(tzinfo=_dt.timezone.utc)

    def is_due(self, now: _dt.datetime | None = None) -> bool:
        return (now or _now()) >= self.due()

    def lateness_minutes(self, now: _dt.datetime | None = None) -> float:
        delta = (now or _now()) - self.due()
        return max(0.0, delta.total_seconds() / 60)

    def ends_at(self) -> _dt.datetime:
        return self.due() + _dt.timedelta(minutes=self.expected_minutes)

    def overlaps(self, other: TimelineNode) -> bool:
        """Whether two planned blocks collide — used when fitting new work in."""
        return self.due() < other.ends_at() and other.due() < self.ends_at()

    # -- serialisation -----------------------------------------------------
    def to_dict(self) -> dict[str, Any]:
        return {
            "node_id": self.node_id,
            "scheduled_at": self.scheduled_at,
            "kind": self.kind.value,
            "kind_label": self.kind.label,
            "intent": self.intent,
            "subject_ref": self.subject_ref,
            "expected_minutes": self.expected_minutes,
            "on_miss": self.on_miss.value,
            "on_miss_label": self.on_miss.label,
            "state": self.state.value,
            "parent_node": self.parent_node,
            "chain_depth": self.chain_depth,
            "created_by": self.created_by,
            "created_at": self.created_at,
            "fired_at": self.fired_at,
            "acked_at": self.acked_at,
            "outcome": self.outcome,
            "triage_reason": self.triage_reason,
            "context": dict(self.context),
            "unread": self.state in UNREAD_STATES,
        }

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> TimelineNode:
        node = cls(
            node_id=str(d.get("node_id") or new_node_id()),
            scheduled_at=str(d["scheduled_at"]),
            kind=NodeKind(d.get("kind", "START")),
            intent=str(d.get("intent", "")),
            subject_ref=str(d.get("subject_ref", "")),
            expected_minutes=int(d.get("expected_minutes", 15)),
            on_miss=OnMiss(d.get("on_miss", "ask")),
            state=NodeState(d.get("state", "SCHEDULED")),
            parent_node=str(d.get("parent_node", "")),
            chain_depth=int(d.get("chain_depth", 0)),
            created_by=str(d.get("created_by", "agent")),
            created_at=str(d.get("created_at", "")),
            fired_at=str(d.get("fired_at", "")),
            acked_at=str(d.get("acked_at", "")),
            outcome=str(d.get("outcome", "")),
            triage_reason=str(d.get("triage_reason", "")),
            context=dict(d.get("context") or {}),
        )
        node.validate()
        return node
