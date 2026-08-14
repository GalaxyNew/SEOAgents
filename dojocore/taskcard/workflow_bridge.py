"""Bridge workflow execution to the task card ledger.

Before this, the two halves of the system did not know about each other. The
workflow engine ran the actual work; the ledger recorded what was supposed to
be happening. A pipeline could finish while its card still read IN_PROGRESS —
the "done in reality, in flight on the dashboard" drift the ledger rewrite was
meant to end. Conversely a card could reach review with an evidence chain that
never mentioned the pipeline that produced the work, leaving a reviewer nothing
to check.

The bridge is an **observer**, deliberately. It does not reach into
:class:`~dojocore.workflow.engine.WorkflowEngine`; callers invoke it after the
engine call they already make. Two reasons: the engine keeps working unchanged
for callers that have no ledger, and a defect in ledger bookkeeping cannot
corrupt workflow execution.

Two rules constrain what it may do.

**It may not promote a card to PASSED.** A finished pipeline moves its card to
REVIEW, never past it. The double-signoff gate — reviewer ≠ owner, and for L3+
a different provider — is the entire point of the ledger, and a workflow that
could self-promote would route around it. Automation reports; a person accepts.

**It may not break the pipeline.** Every public method swallows its own
exceptions and logs them. If the ledger is unreachable the workflow still runs
to completion; bookkeeping is subordinate to the work.
"""
from __future__ import annotations

from typing import Any

from dojocore.logging import LOGGER
from dojocore.taskcard.models import CardError, CardStatus, TaskCard
from dojocore.taskcard.service import TaskCardService
from dojocore.workflow.instance import InstanceStatus, NodeState, WorkflowInstance

__all__ = ["WorkflowCardBridge"]

# Node types whose completion is worth a ledger line. Control-flow plumbing
# (input/output) would only add noise to a reviewer's evidence chain.
_QUIET_NODE_TYPES = frozenset({"input", "output"})


class WorkflowCardBridge:
    """Keeps a task card in step with the workflow instance that fulfils it.

    Typical use, alongside the engine calls a caller already makes::

        inst = WorkflowInstance.start(template, title="每日 GSC 抓取")
        bridge.on_start(inst, actor="hermes")        # opens or links the card

        engine.complete(inst, "fetch", acceptance_met=[True], actor="seo-tech")
        bridge.on_node_done(inst, "fetch", actor="seo-tech", evidence="200 OK")

        bridge.on_finish(inst)                        # card → REVIEW
    """

    def __init__(self, cards: TaskCardService, *, actor: str = "workflow") -> None:
        self.cards = cards
        self.actor = actor

    # -- helpers -----------------------------------------------------------
    @staticmethod
    def _node_type(inst: WorkflowInstance, node_id: str) -> str:
        """Read the node's type out of the pinned template snapshot.

        The snapshot rather than the live template: an instance may outlive an
        edit to the template file, and the ledger should describe what actually
        ran.
        """
        for node in (inst.template_snapshot or {}).get("nodes", []) or []:
            if str(node.get("id")) == node_id:
                return str(node.get("type", ""))
        return ""

    def _card_for(self, inst: WorkflowInstance) -> TaskCard | None:
        if not inst.parent_task:
            return None
        try:
            return self.cards.store.get(inst.parent_task)
        except Exception as exc:  # pragma: no cover - defensive
            LOGGER.warning("bridge.card_lookup_failed %s: %s", inst.parent_task, exc)
            return None

    def _safe(self, what: str, fn: Any) -> Any:
        """Run a ledger update; never let it take the pipeline down with it."""
        try:
            return fn()
        except CardError as exc:
            LOGGER.warning("bridge.%s_refused: %s", what, exc)
        except Exception as exc:  # pragma: no cover - defensive
            LOGGER.warning("bridge.%s_failed: %s", what, exc)
        return None

    # -- lifecycle ---------------------------------------------------------
    def on_start(
        self,
        inst: WorkflowInstance,
        *,
        actor: str = "",
        owner: str = "",
        card_id: str = "",
        level: str = "L2",
        priority: str = "P2",
        acceptance: list[str] | None = None,
        verify_cmd: str = "",
    ) -> str:
        """Attach the instance to a card, opening one if needed.

        Returns the card id, or "" when the ledger was unavailable — callers
        may ignore it; ``inst.parent_task`` is filled in either way.
        """
        actor = actor or self.actor

        if card_id:
            def link() -> str:
                card = self.cards.store.require(card_id)
                self.cards.add_evidence(
                    card.card_id, actor,
                    f"工作流启动: {inst.instance_id} ({inst.title})",
                    kind="note",
                )
                return card.card_id
            resolved = self._safe("link", link)
            if resolved:
                inst.parent_task = resolved
            return resolved or ""

        def create() -> str:
            criteria = list(acceptance or [])
            if not criteria:
                criteria = [
                    f"工作流 {inst.template_id} 全部节点 DONE",
                    "终点产出已落库且可核验",
                ]
            card = self.cards.open_card(
                title=inst.title or inst.template_id,
                goal=f"由工作流 {inst.template_id} 执行并交付: {inst.title}",
                acceptance=criteria,
                verify_cmd=verify_cmd,
                level=level,
                priority=priority,
                owner=owner,
                actor=actor,
                dept=inst.dept,
                meta={
                    "workflow_instance": inst.instance_id,
                    "workflow_template": inst.template_id,
                    "workflow_version": inst.template_version,
                },
            )
            if owner:
                self.cards.assign(card.card_id, owner, actor=actor,
                                  note=f"工作流 {inst.instance_id} 自动指派")
                self.cards.move(card.card_id, CardStatus.IN_PROGRESS, actor=actor,
                                note="工作流开始执行")
            return card.card_id

        new_id = self._safe("open", create)
        if new_id:
            inst.parent_task = new_id
            LOGGER.info("bridge.card_opened %s ← %s", new_id, inst.instance_id)
        return new_id or ""

    def on_node_done(
        self,
        inst: WorkflowInstance,
        node_id: str,
        *,
        actor: str = "",
        evidence: str = "",
        asset_ids: list[str] | None = None,
    ) -> None:
        """Record a finished node as a ledger evidence line."""
        card = self._card_for(inst)
        if card is None:
            return
        if self._node_type(inst, node_id) in _QUIET_NODE_TYPES:
            return
        actor = actor or self.actor
        detail = f"工序 {node_id} 完成"
        if evidence.strip():
            first = evidence.strip().splitlines()[0][:200]
            detail += f" | {first}"
        assets = list(asset_ids or [])

        def write() -> None:
            self.cards.add_evidence(
                card.card_id, actor, detail, kind="note",
                asset_id=assets[0] if assets else "",
            )
        self._safe("node_evidence", write)

    def on_node_failed(
        self, inst: WorkflowInstance, node_id: str, *, error: str,
        actor: str = "",
    ) -> None:
        """Move the card to BLOCKED and say which node broke."""
        card = self._card_for(inst)
        if card is None:
            return
        actor = actor or self.actor

        def write() -> None:
            self.cards.add_evidence(
                card.card_id, actor,
                f"工序 {node_id} 失败: {error[:300]}", kind="note",
            )
            fresh = self.cards.store.require(card.card_id)
            if fresh.status in (CardStatus.IN_PROGRESS, CardStatus.ASSIGNED):
                self.cards.move(card.card_id, CardStatus.BLOCKED, actor=actor,
                                note=f"工序 {node_id} 失败")
        self._safe("node_failed", write)

    def on_human_gate(
        self, inst: WorkflowInstance, node_id: str, *, prompt: str = "",
        actor: str = "",
    ) -> None:
        """Flag the card as waiting on a person, so it is visible as blocked."""
        card = self._card_for(inst)
        if card is None:
            return
        actor = actor or self.actor
        detail = f"工序 {node_id} 等待人工审批" + (f": {prompt[:200]}" if prompt else "")

        def write() -> None:
            self.cards.add_evidence(card.card_id, actor, detail, kind="note")
            fresh = self.cards.store.require(card.card_id)
            if fresh.status in (CardStatus.IN_PROGRESS, CardStatus.ASSIGNED):
                self.cards.move(card.card_id, CardStatus.BLOCKED, actor=actor,
                                note="等待人工审批")
        self._safe("human_gate", write)

    def on_finish(self, inst: WorkflowInstance, *, actor: str = "") -> None:
        """Reconcile the card with the instance's final state.

        A completed pipeline sends the card to REVIEW and stops there: PASSED
        requires a second person, and letting automation grant it would hollow
        out the gate.
        """
        card = self._card_for(inst)
        if card is None:
            return
        actor = actor or self.actor
        progress = inst.progress()

        def write() -> None:
            fresh = self.cards.store.require(card.card_id)
            if inst.status is InstanceStatus.DONE:
                self.cards.add_evidence(
                    card.card_id, actor,
                    f"工作流 {inst.instance_id} 完成: "
                    f"{progress['done']}/{progress['total']} 节点 DONE",
                    kind="note",
                )
                if fresh.status in (CardStatus.IN_PROGRESS, CardStatus.BLOCKED):
                    if fresh.status is CardStatus.BLOCKED:
                        self.cards.move(card.card_id, CardStatus.IN_PROGRESS,
                                        actor=actor, note="阻塞解除")
                    self.cards.move(
                        card.card_id, CardStatus.REVIEW, actor=actor,
                        note="工作流执行完毕,待验收 —— 验收仍需他人签发",
                    )
            elif inst.status in (InstanceStatus.FAILED, InstanceStatus.CANCELLED):
                failed = [r.node_id for r in inst.runs.values()
                          if r.state is NodeState.FAILED]
                self.cards.add_evidence(
                    card.card_id, actor,
                    f"工作流 {inst.instance_id} {inst.status.value}"
                    + (f",失败节点: {', '.join(failed)}" if failed else ""),
                    kind="note",
                )
                if fresh.status in (CardStatus.IN_PROGRESS, CardStatus.ASSIGNED):
                    self.cards.move(card.card_id, CardStatus.BLOCKED, actor=actor,
                                    note=f"工作流 {inst.status.value}")
        self._safe("finish", write)

    # -- reconciliation ----------------------------------------------------
    def reconcile(self, inst: WorkflowInstance) -> dict[str, Any]:
        """Report disagreement between an instance and its card.

        Used by the pulse sweep to catch the drift this module exists to
        prevent, in the cases where an event was missed entirely.
        """
        card = self._card_for(inst)
        if card is None:
            return {"linked": False, "drift": [], "instance": inst.instance_id}
        drift: list[str] = []
        if inst.status is InstanceStatus.DONE and card.status in (
            CardStatus.IN_PROGRESS, CardStatus.ASSIGNED, CardStatus.DRAFT,
        ):
            drift.append(
                f"工作流已完成但卡仍为 {card.status.label} —— 状态漂移"
            )
        if inst.status is InstanceStatus.FAILED and card.status not in (
            CardStatus.BLOCKED, CardStatus.REJECTED, CardStatus.CANCELLED,
        ):
            drift.append(f"工作流已失败但卡为 {card.status.label}")
        if card.status is CardStatus.PASSED and inst.status is not InstanceStatus.DONE:
            drift.append(
                f"卡已验收通过但工作流为 {inst.status.value} —— 假完成候选"
            )
        return {
            "linked": True,
            "card_id": card.card_id,
            "card_status": card.status.value,
            "instance": inst.instance_id,
            "instance_status": inst.status.value,
            "drift": drift,
        }
