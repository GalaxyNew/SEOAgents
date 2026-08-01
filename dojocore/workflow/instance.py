"""A running pipeline.

Two properties matter more than the rest:

* **The template version is pinned at start.** Otherwise "did the revised
  process work better" is unanswerable, because the process changed underneath
  the comparison.
* **A node is DONE only with evidence.** Acceptance criteria are recorded
  per-node and checked off individually; "the step finished" is not the same
  claim as "the step produced what it was supposed to".
"""
from __future__ import annotations

import datetime as _dt
import uuid
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from dojocore.workflow.template import WorkflowTemplate

__all__ = ["InstanceStatus", "NodeRun", "NodeState", "WorkflowInstance"]


def _now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).isoformat()


class NodeState(str, Enum):
    PENDING = "PENDING"                   # dependencies unmet
    READY = "READY"                       # dependencies met, not started
    RUNNING = "RUNNING"
    WAITING_EXTERNAL = "WAITING_EXTERNAL"  # dept_request out, awaiting delivery
    WAITING_HUMAN = "WAITING_HUMAN"
    DONE = "DONE"
    FAILED = "FAILED"
    SKIPPED = "SKIPPED"

    @property
    def settled(self) -> bool:
        return self in (NodeState.DONE, NodeState.FAILED, NodeState.SKIPPED)


class InstanceStatus(str, Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    BLOCKED = "BLOCKED"
    DONE = "DONE"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


@dataclass
class NodeRun:
    node_id: str
    state: NodeState = NodeState.PENDING
    started_at: str = ""
    finished_at: str = ""
    output_asset_ids: tuple[str, ...] = ()
    evidence: str = ""
    acceptance_met: tuple[bool, ...] = ()
    error: str = ""
    external_request_id: str = ""     # links to the collab inbox/outbox record
    attempts: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "node_id": self.node_id, "state": self.state.value,
            "started_at": self.started_at, "finished_at": self.finished_at,
            "output_asset_ids": list(self.output_asset_ids),
            "evidence": self.evidence,
            "acceptance_met": list(self.acceptance_met),
            "error": self.error,
            "external_request_id": self.external_request_id,
            "attempts": self.attempts,
        }

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> NodeRun:
        return cls(
            node_id=str(d["node_id"]),
            state=NodeState(d.get("state", "PENDING")),
            started_at=str(d.get("started_at", "")),
            finished_at=str(d.get("finished_at", "")),
            output_asset_ids=tuple(d.get("output_asset_ids") or ()),
            evidence=str(d.get("evidence", "")),
            acceptance_met=tuple(d.get("acceptance_met") or ()),
            error=str(d.get("error", "")),
            external_request_id=str(d.get("external_request_id", "")),
            attempts=int(d.get("attempts", 0)),
        )


@dataclass
class WorkflowInstance:
    instance_id: str
    template_id: str
    template_version: str          # pinned — see module docstring
    title: str
    dept: str = "seo"
    status: InstanceStatus = InstanceStatus.PENDING
    runs: dict[str, NodeRun] = field(default_factory=dict)
    context: dict[str, Any] = field(default_factory=dict)
    parent_task: str = ""
    created_at: str = field(default_factory=_now)
    updated_at: str = field(default_factory=_now)

    @classmethod
    def start(
        cls, template: WorkflowTemplate, *, title: str = "",
        context: Mapping[str, Any] | None = None, parent_task: str = "",
    ) -> WorkflowInstance:
        inst = cls(
            instance_id=f"WF-{template.id.upper()}-{uuid.uuid4().hex[:8]}",
            template_id=template.id,
            template_version=template.version,
            title=title or template.name,
            dept=template.dept,
            context=dict(context or {}),
            parent_task=parent_task,
        )
        inst.runs = {n.id: NodeRun(node_id=n.id) for n in template.nodes}
        return inst

    # -- progress ----------------------------------------------------------
    def progress(self) -> dict[str, Any]:
        total = len(self.runs)
        done = sum(1 for r in self.runs.values() if r.state is NodeState.DONE)
        failed = sum(1 for r in self.runs.values() if r.state is NodeState.FAILED)
        waiting = [
            r.node_id for r in self.runs.values()
            if r.state in (NodeState.WAITING_EXTERNAL, NodeState.WAITING_HUMAN)
        ]
        return {
            "total": total, "done": done, "failed": failed,
            "percent": round(done / total * 100, 1) if total else 0.0,
            "waiting_on": waiting,
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "instance_id": self.instance_id,
            "template_id": self.template_id,
            "template_version": self.template_version,
            "title": self.title, "dept": self.dept,
            "status": self.status.value,
            "progress": self.progress(),
            "runs": {k: v.to_dict() for k, v in self.runs.items()},
            "context": self.context,
            "parent_task": self.parent_task,
            "created_at": self.created_at, "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> WorkflowInstance:
        inst = cls(
            instance_id=str(d["instance_id"]),
            template_id=str(d["template_id"]),
            template_version=str(d.get("template_version", "1.0")),
            title=str(d.get("title", "")),
            dept=str(d.get("dept", "seo")),
            status=InstanceStatus(d.get("status", "PENDING")),
            context=dict(d.get("context") or {}),
            parent_task=str(d.get("parent_task", "")),
            created_at=str(d.get("created_at", "")),
            updated_at=str(d.get("updated_at", "")),
        )
        inst.runs = {
            k: NodeRun.from_dict(v) for k, v in (d.get("runs") or {}).items()
        }
        return inst
