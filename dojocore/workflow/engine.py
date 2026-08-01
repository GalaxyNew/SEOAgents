"""Pipeline engine — decides what may run, and refuses what may not.

The engine does not execute nodes; it says which are eligible and enforces the
rules around completion. Execution belongs to the department head (agent tasks),
the tool layer (tool calls), another department (dept requests) or a person
(human gates).

Two refusals carry most of the value:

* **A node cannot be completed without meeting its acceptance criteria.**
  "Finished" and "produced what it was supposed to" are different claims, and
  conflating them is how six written articles ended up marked PASSED with the
  review, render and publish steps never run.
* **A human gate cannot be self-approved.** An agent marking its own approval
  step complete defeats the only purpose that node has.
"""
from __future__ import annotations

import datetime as _dt

from dojocore.logging import LOGGER
from dojocore.workflow.instance import (
    InstanceStatus,
    NodeRun,
    NodeState,
    WorkflowInstance,
)
from dojocore.workflow.nodes import FailurePolicy, NodeType, WorkflowNode
from dojocore.workflow.template import WorkflowTemplate

__all__ = ["EngineError", "WorkflowEngine"]


class EngineError(RuntimeError):
    """An operation would violate the pipeline's rules."""


def _now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).isoformat()


class WorkflowEngine:
    def __init__(self, template: WorkflowTemplate) -> None:
        template.validate()
        self.template = template

    # -- scheduling --------------------------------------------------------
    def ready_nodes(self, inst: WorkflowInstance) -> list[WorkflowNode]:
        """Nodes whose dependencies are satisfied and which have not started.

        Everything returned here may run **at the same time** — the dependency
        graph has already ruled out anything that must be serialised, so the
        caller does not have to reason about it per task.
        """
        out: list[WorkflowNode] = []
        for node in self.template.nodes:
            run = inst.runs.get(node.id)
            # READY is a derived marker set by refresh(); a node that has been
            # marked ready is still eligible to start, so both count.
            if run is None or run.state not in (NodeState.PENDING, NodeState.READY):
                continue
            deps_ok = all(
                inst.runs[d].state in (NodeState.DONE, NodeState.SKIPPED)
                for d in node.depends_on
            )
            if deps_ok:
                out.append(node)
        return out

    def refresh(self, inst: WorkflowInstance) -> WorkflowInstance:
        """Recompute derived state: READY marks, and overall status."""
        for node in self.ready_nodes(inst):
            inst.runs[node.id].state = NodeState.READY

        states = [r.state for r in inst.runs.values()]
        if any(s is NodeState.FAILED for s in states):
            blocking = [
                r.node_id for r in inst.runs.values()
                if r.state is NodeState.FAILED
                and self.template.node(r.node_id).on_failure is FailurePolicy.STOP
            ]
            inst.status = InstanceStatus.FAILED if blocking else InstanceStatus.RUNNING
        elif all(s.settled for s in states):
            inst.status = InstanceStatus.DONE
        elif any(s in (NodeState.WAITING_EXTERNAL, NodeState.WAITING_HUMAN) for s in states) \
                and not any(s is NodeState.READY for s in states):
            # Nothing left we can act on ourselves.
            inst.status = InstanceStatus.BLOCKED
        elif any(s in (NodeState.RUNNING, NodeState.READY) for s in states):
            inst.status = InstanceStatus.RUNNING
        inst.updated_at = _now()
        return inst

    # -- transitions -------------------------------------------------------
    def begin(self, inst: WorkflowInstance, node_id: str) -> NodeRun:
        node = self.template.node(node_id)
        run = inst.runs[node_id]
        if run.state not in (NodeState.PENDING, NodeState.READY):
            raise EngineError(f"节点 {node_id} 当前为 {run.state.value},不可开始")
        unmet = [
            d for d in node.depends_on
            if inst.runs[d].state not in (NodeState.DONE, NodeState.SKIPPED)
        ]
        if unmet:
            raise EngineError(
                f"节点 {node_id} 的前置未完成: {unmet};"
                f"这是数据依赖,不能跳步"
            )
        run.state = (
            NodeState.WAITING_EXTERNAL if node.type is NodeType.DEPT_REQUEST
            else NodeState.WAITING_HUMAN if node.type is NodeType.HUMAN_GATE
            else NodeState.RUNNING
        )
        run.started_at = run.started_at or _now()
        run.attempts += 1
        self.refresh(inst)
        LOGGER.info(f"{inst.instance_id}: node {node_id} → {run.state.value}")
        return run

    def complete(
        self,
        inst: WorkflowInstance,
        node_id: str,
        *,
        acceptance_met: list[bool],
        evidence: str = "",
        output_asset_ids: list[str] | None = None,
        actor: str = "agent",
    ) -> NodeRun:
        node = self.template.node(node_id)
        run = inst.runs[node_id]
        if run.state.settled:
            raise EngineError(f"节点 {node_id} 已处于终态 {run.state.value}")

        if node.type is NodeType.HUMAN_GATE and actor == "agent":
            raise EngineError(
                f"节点 {node_id} 是人工审批,agent 不得自行通过 —— "
                f"自审会让这个节点失去唯一的作用"
            )

        if len(acceptance_met) != len(node.acceptance):
            raise EngineError(
                f"节点 {node_id} 有 {len(node.acceptance)} 条验收标准,"
                f"但只回报了 {len(acceptance_met)} 条结论;必须逐条勾"
            )
        unmet = [c for c, ok in zip(node.acceptance, acceptance_met) if not ok]
        if unmet:
            raise EngineError(
                f"节点 {node_id} 有未满足的验收标准,不得标记完成: {unmet}"
            )

        if node.type is NodeType.VERIFY and not evidence.strip():
            raise EngineError(
                f"节点 {node_id} 是验证节点,必须附命令输出作为证据 —— 断言不算证据"
            )

        run.state = NodeState.DONE
        run.finished_at = _now()
        run.evidence = evidence
        run.acceptance_met = tuple(acceptance_met)
        run.output_asset_ids = tuple(output_asset_ids or run.output_asset_ids)
        self.refresh(inst)
        LOGGER.info(f"{inst.instance_id}: node {node_id} DONE by {actor}")
        return run

    def fail(self, inst: WorkflowInstance, node_id: str, *, error: str) -> NodeRun:
        if not error.strip():
            raise EngineError("失败必须给出原因")
        run = inst.runs[node_id]
        run.state = NodeState.FAILED
        run.error = error
        run.finished_at = _now()
        policy = self.template.node(node_id).on_failure
        if policy is FailurePolicy.STOP:
            for other in inst.runs.values():
                if other.state in (NodeState.PENDING, NodeState.READY):
                    other.state = NodeState.SKIPPED
        self.refresh(inst)
        LOGGER.warning(f"{inst.instance_id}: node {node_id} FAILED ({policy.value}): {error}")
        return run

    def attach_external(self, inst: WorkflowInstance, node_id: str, request_id: str) -> NodeRun:
        """Link a dept_request node to its collab request record."""
        run = inst.runs[node_id]
        run.external_request_id = request_id
        run.state = NodeState.WAITING_EXTERNAL
        self.refresh(inst)
        return run

    # -- introspection -----------------------------------------------------
    def blocked_reason(self, inst: WorkflowInstance) -> list[dict[str, str]]:
        """Why the pipeline cannot move — for the dashboard and for escalation."""
        out = []
        for run in inst.runs.values():
            if run.state is NodeState.WAITING_EXTERNAL:
                node = self.template.node(run.node_id)
                out.append({
                    "node": run.node_id, "kind": "external",
                    "detail": f"等待 {node.config.get('dept')} 交付"
                              f"(请求 {run.external_request_id or '未发出'})",
                })
            elif run.state is NodeState.WAITING_HUMAN:
                out.append({
                    "node": run.node_id, "kind": "human",
                    "detail": str(self.template.node(run.node_id).config.get("prompt", "待人工审批")),
                })
            elif run.state is NodeState.FAILED:
                out.append({"node": run.node_id, "kind": "failed", "detail": run.error})
        return out
