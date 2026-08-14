"""Task card business layer — opening, moving and verifying cards.

The store keeps rows; this keeps promises. Three of them.

**Verification is executed, not asserted.** :meth:`TaskCardService.verify` runs
the card's own ``verify_cmd`` in a subprocess and writes the exit code into the
evidence chain. Review can then require a *passing* run rather than a claim,
which is the difference between the effectiveness rule being policy and being
a gate.

**Every mutation lands in the audit chain.** There is no path here that changes
a card without appending evidence naming an actor.

**Timeline events follow state.** A status change emits a timeline event when a
timeline service is wired in, so "the card says PASSED but the timeline has no
verification event" becomes a query rather than an investigation.
"""
from __future__ import annotations

import datetime as _dt
import shlex
import subprocess
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from dojocore.logging import LOGGER
from dojocore.taskcard.models import (
    CardError,
    CardLevel,
    CardPriority,
    CardStatus,
    TaskCard,
)
from dojocore.taskcard.store import TaskCardStore

__all__ = ["TaskCardService", "VerifyResult"]

# A verification command is a check, not a deployment. Anything that needs
# longer than this is doing too much to be a gate.
_VERIFY_TIMEOUT_SEC = 180
_OUTPUT_KEEP = 2000


@dataclass(frozen=True)
class VerifyResult:
    card_id: str
    command: str
    exit_code: int
    stdout: str
    stderr: str
    duration_sec: float
    ran_at: str

    @property
    def passed(self) -> bool:
        return self.exit_code == 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "card_id": self.card_id,
            "command": self.command,
            "exit_code": self.exit_code,
            "passed": self.passed,
            "stdout": self.stdout,
            "stderr": self.stderr,
            "duration_sec": round(self.duration_sec, 3),
            "ran_at": self.ran_at,
        }


class TaskCardService:
    def __init__(
        self,
        store: TaskCardStore,
        *,
        dept: str = "hm",
        timeline: Any = None,
    ) -> None:
        self.store = store
        self.dept = dept
        self._timeline = timeline

    # -- opening -----------------------------------------------------------
    def open_card(
        self,
        *,
        title: str,
        goal: str,
        acceptance: Sequence[str] | None = None,
        actor: str = "system",
        dept: str | None = None,
        level: CardLevel | str = CardLevel.L2,
        priority: CardPriority | str = CardPriority.P2,
        **kw: Any,
    ) -> TaskCard:
        """Write a new card in DRAFT.

        ``acceptance`` is not optional in spirit — a card without effectiveness
        criteria cannot be verified, and :meth:`TaskCard.audit_flags` will say
        so — but it is accepted empty here so a card can be drafted before its
        criteria are agreed.
        """
        card = TaskCard.create(
            card_id=self.store.next_card_id(dept or self.dept),
            dept=dept or self.dept,
            title=title,
            goal=goal,
            acceptance=list(acceptance or []),
            level=CardLevel(level),
            priority=CardPriority(priority),
            actor=actor,
            **kw,
        )
        self.store.put(card)
        self._emit(card, "START", f"立卡: {title}")
        LOGGER.info("taskcard.open %s %s", card.card_id, title)
        return card

    # -- movement ----------------------------------------------------------
    def assign(self, card_id: str, owner: str, *, actor: str = "system",
               owner_provider: str = "", note: str = "") -> TaskCard:
        card = self.store.require(card_id)
        if not owner.strip():
            raise CardError("指派必须有 owner")
        card.owner = owner
        if owner_provider:
            card.owner_provider = owner_provider
        if card.status is CardStatus.DRAFT:
            card.transition(CardStatus.ASSIGNED, actor,
                            note=note or f"指派给 {owner}")
        else:
            card.add_evidence(actor, f"改派给 {owner}" + (f"; {note}" if note else ""))
        self.store.put(card)
        self._emit(card, "START", f"指派 {card.card_id} → {owner}")
        return card

    def move(self, card_id: str, target: CardStatus | str, *, actor: str,
             note: str = "", reviewer_provider: str = "",
             force: bool = False) -> TaskCard:
        card = self.store.require(card_id)
        card.transition(CardStatus(target), actor, note=note,
                        reviewer_provider=reviewer_provider, force=force)
        self.store.put(card)
        self._emit(card, self._kind_for(card.status),
                   f"{card.card_id} → {card.status.label}")
        return card

    def add_evidence(self, card_id: str, actor: str, note: str, *,
                     kind: str = "note", **kw: Any) -> TaskCard:
        card = self.store.require(card_id)
        card.add_evidence(actor, note, kind=kind, **kw)
        self.store.put(card)
        return card

    # -- verification ------------------------------------------------------
    def verify(self, card_id: str, *, actor: str = "engine",
               cwd: str | None = None) -> VerifyResult:
        """Actually run the card's verify_cmd and record what happened.

        Refuses when the card names no command: a silent "nothing to run, so it
        passes" is precisely the hole this closes.
        """
        card = self.store.require(card_id)
        cmd = (card.verify_cmd or "").strip()
        if not cmd:
            raise CardError(
                f"卡 {card_id} 未定义 verify_cmd —— 无法执行验证。"
                f"生效性铁律要求验收命令写到端点/页面探活层"
            )
        started = _dt.datetime.now(_dt.timezone.utc)
        try:
            proc = subprocess.run(  # noqa: S602 - operator-authored command by design
                cmd, shell=True, capture_output=True, text=True,
                timeout=_VERIFY_TIMEOUT_SEC, cwd=cwd,
            )
            code, out, err = proc.returncode, proc.stdout, proc.stderr
        except subprocess.TimeoutExpired:
            code, out, err = 124, "", f"验证命令超时 (>{_VERIFY_TIMEOUT_SEC}s)"
        except Exception as exc:  # pragma: no cover - environment dependent
            code, out, err = 127, "", f"验证命令无法执行: {exc}"

        duration = (_dt.datetime.now(_dt.timezone.utc) - started).total_seconds()
        result = VerifyResult(
            card_id=card_id, command=cmd, exit_code=code,
            stdout=out[-_OUTPUT_KEEP:], stderr=err[-_OUTPUT_KEEP:],
            duration_sec=duration, ran_at=started.isoformat(),
        )
        verdict = "通过" if result.passed else f"失败 (exit={code})"
        tail = (out or err or "").strip().splitlines()
        excerpt = tail[-1][:200] if tail else ""
        card.add_evidence(
            actor,
            f"验证命令{verdict}: {shlex.quote(cmd)[:160]}"
            + (f" | {excerpt}" if excerpt else ""),
            kind="verify", exit_code=code,
        )
        self.store.put(card)
        self._emit(card, "CHECKPOINT", f"{card_id} 验证{verdict}")
        LOGGER.info("taskcard.verify %s exit=%s", card_id, code)
        return result

    def submit_for_review(self, card_id: str, *, actor: str,
                          note: str = "") -> TaskCard:
        return self.move(card_id, CardStatus.REVIEW, actor=actor, note=note)

    def approve(self, card_id: str, *, reviewer: str, reviewer_provider: str = "",
                note: str = "", require_verification: bool = True) -> TaskCard:
        """Promote to PASSED, enforcing the effectiveness rule.

        The heterogeneous-review and self-review gates live in the model; the
        one added here is that a card naming a ``verify_cmd`` must have a
        passing run on record. Callers that genuinely have no runnable check
        pass ``require_verification=False`` — and the audit sweep will still
        flag the card, by design.
        """
        card = self.store.require(card_id)
        if require_verification and card.verify_cmd and not card.has_passing_verification:
            raise CardError(
                f"卡 {card_id} 定义了 verify_cmd 但无成功验证记录,不得验收。"
                f"请先跑 verify() —— 「不重跑验证命令就验收」是红线"
            )
        return self.move(card_id, CardStatus.PASSED, actor=reviewer, note=note,
                         reviewer_provider=reviewer_provider)

    def reject(self, card_id: str, *, reviewer: str, reason: str) -> TaskCard:
        if not reason.strip():
            raise CardError("打回必须写原因 —— 否则返修方无从下手")
        return self.move(card_id, CardStatus.REJECTED, actor=reviewer, note=reason)

    # -- reporting ---------------------------------------------------------
    def summary(self) -> dict[str, Any]:
        counts = self.store.counts_by_status()
        active = self.store.active()
        stalled = self.store.stalled()
        return {
            "dept": self.dept,
            "data_status": "REAL",
            "total": sum(counts.values()),
            "counts": counts,
            "active": len(active),
            "stalled": len(stalled),
            "blocked": counts.get(CardStatus.BLOCKED.value, 0),
            "review": counts.get(CardStatus.REVIEW.value, 0),
            "ts": int(_dt.datetime.now(_dt.timezone.utc).timestamp()),
        }

    def audit(self) -> list[dict[str, Any]]:
        """Every card carrying at least one defect flag."""
        out: list[dict[str, Any]] = []
        for card in self.store.recent(limit=500):
            flags = card.audit_flags()
            if flags:
                out.append({
                    "card_id": card.card_id, "title": card.title,
                    "status": card.status.value, "owner": card.owner,
                    "flags": flags,
                })
        return out

    # -- timeline bridge ---------------------------------------------------
    @staticmethod
    def _kind_for(status: CardStatus) -> str:
        if status is CardStatus.REVIEW:
            return "REPORT"
        if status in (CardStatus.PASSED, CardStatus.CANCELLED):
            return "CHECKPOINT"
        return "START"

    def _emit(self, card: TaskCard, kind: str, summary: str) -> None:
        """Record a card movement on the timeline as an event that already happened.

        Deliberately not ``schedule()``: that plans *future* work and enforces
        conflict and per-day quotas, which a stream of facts would blow through
        while polluting the agenda. A card movement is history, so the node is
        written straight to the store already ACKED.
        """
        if self._timeline is None:
            return
        try:
            store = getattr(self._timeline, "store", None)
            if store is None:
                return
            from dojocore.timeline.models import (
                NodeKind,
                NodeState,
                TimelineNode,
                new_node_id,
            )

            now = _dt.datetime.now(_dt.timezone.utc).isoformat()
            store.put(TimelineNode(
                node_id=new_node_id(),
                scheduled_at=now,
                kind=NodeKind(kind),
                intent=summary,
                subject_ref=f"taskcard:{card.card_id}",
                state=NodeState.ACKED,
                created_by="taskcard",
                created_at=now,
                fired_at=now,
                acked_at=now,
                outcome=card.status.value,
            ))
        except Exception as exc:  # pragma: no cover - defensive
            LOGGER.warning("taskcard.timeline_emit_failed %s: %s", card.card_id, exc)
