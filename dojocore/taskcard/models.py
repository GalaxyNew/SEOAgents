"""Task cards — the single source of truth for what the federation is doing.

A task card is not a to-do item. It is the *ledger row* for a piece of work:
who owns it, what "done" means in terms a machine can check, what evidence
accumulated along the way, and who signed it off. Everything else in the
federation — dashboards, reconciliation, the evolution engine's scoring — reads
from here rather than from anybody's recollection.

The design answers three specific failures of the ledger this replaces (Mac
frontmatter markdown, retired 2026-08-12).

**Status drift.** Anyone could open a card in an editor and type ``PASSED``.
Cards were marked complete while the work sat untouched, and the dashboard
faithfully showed the lie. Here a status is reachable only through
:meth:`TaskCard.transition`, which refuses illegal edges and appends an audit
line naming the actor. There is no setter for ``status``.

**Acceptance by assertion.** "Done" meant somebody said done. A card now
carries ``verify_cmd`` — a command the engine actually runs at review time —
and ``acceptance``, the effectiveness criteria in curl/page/DDL terms. A card
that reaches PASSED with no verification evidence is a detectable defect
(:meth:`audit_flags`), not an invisible one.

**Self-review.** The author reviewed their own work and passed it. Promotion to
PASSED requires ``reviewed_by`` to differ from ``owner``; for L3+ cards the
reviewer's provider must differ from the owner's too, so a model cannot rubber
stamp its own output through a second identity.

The vocabulary is deliberately the one the operators already speak: L1–L4 for
difficulty, P0–P3 for priority, and the eight statuses that were in use before
this module existed.
"""
from __future__ import annotations

import datetime as _dt
import json
import re
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

__all__ = [
    "ACTIVE_STATUSES",
    "TERMINAL_STATUSES",
    "CardError",
    "CardLevel",
    "CardPriority",
    "CardStatus",
    "Evidence",
    "TaskCard",
    "new_card_id",
]

# TSEO20260812-01 — department slug is upper alnum, date, two-digit sequence.
_ID_RE = re.compile(r"^T[A-Z0-9]{2,8}\d{8}-\d{2,3}$")

# Providers are compared case-insensitively after stripping, because the same
# vendor arrives spelled "ZhiPu", "zhipu " and "zhipu" from three config files.
_PROVIDER_NORMALISE = re.compile(r"[\s_-]+")


class CardError(ValueError):
    """A card or a transition violates the ledger's rules."""


class CardStatus(str, Enum):
    DRAFT = "DRAFT"                # written, not yet given to anyone
    ASSIGNED = "ASSIGNED"          # has an owner, work not started
    IN_PROGRESS = "IN_PROGRESS"    # owner is working
    BLOCKED = "BLOCKED"            # waiting on a dependency or a decision
    REVIEW = "REVIEW"              # owner says done, awaiting verification
    PASSED = "PASSED"              # verified by someone other than the owner
    REJECTED = "REJECTED"          # verification failed, back to the owner
    CANCELLED = "CANCELLED"        # withdrawn; the work is not wanted

    @property
    def label(self) -> str:
        return _STATUS_LABELS[self]

    @property
    def is_terminal(self) -> bool:
        return self in (CardStatus.PASSED, CardStatus.CANCELLED)

    @property
    def is_active(self) -> bool:
        """Counts toward "what is the department actually doing right now"."""
        return self in (
            CardStatus.ASSIGNED, CardStatus.IN_PROGRESS,
            CardStatus.BLOCKED, CardStatus.REVIEW, CardStatus.REJECTED,
        )


_STATUS_LABELS = {
    CardStatus.DRAFT: "草稿",
    CardStatus.ASSIGNED: "已指派",
    CardStatus.IN_PROGRESS: "进行中",
    CardStatus.BLOCKED: "阻塞",
    CardStatus.REVIEW: "待验收",
    CardStatus.PASSED: "已通过",
    CardStatus.REJECTED: "已打回",
    CardStatus.CANCELLED: "已取消",
}

ACTIVE_STATUSES: frozenset[CardStatus] = frozenset(
    s for s in CardStatus if s.is_active
)
TERMINAL_STATUSES: frozenset[CardStatus] = frozenset(
    s for s in CardStatus if s.is_terminal
)

# The legal state graph. Anything not listed is refused by transition().
#
# Two edges deserve comment. DRAFT->CANCELLED exists so a card written in error
# can be withdrawn without ever having an owner. REJECTED->REVIEW exists so a
# rework loop does not have to travel back through IN_PROGRESS when the fix was
# a one-line change — but REJECTED->PASSED does not, because a rejected card
# must be resubmitted for verification, never promoted directly.
_TRANSITIONS: dict[CardStatus, frozenset[CardStatus]] = {
    CardStatus.DRAFT: frozenset({CardStatus.ASSIGNED, CardStatus.CANCELLED}),
    CardStatus.ASSIGNED: frozenset({
        CardStatus.IN_PROGRESS, CardStatus.BLOCKED, CardStatus.CANCELLED,
    }),
    CardStatus.IN_PROGRESS: frozenset({
        CardStatus.REVIEW, CardStatus.BLOCKED, CardStatus.CANCELLED,
    }),
    CardStatus.BLOCKED: frozenset({
        CardStatus.IN_PROGRESS, CardStatus.ASSIGNED, CardStatus.CANCELLED,
    }),
    CardStatus.REVIEW: frozenset({
        CardStatus.PASSED, CardStatus.REJECTED, CardStatus.BLOCKED,
    }),
    CardStatus.REJECTED: frozenset({
        CardStatus.IN_PROGRESS, CardStatus.REVIEW, CardStatus.CANCELLED,
    }),
    CardStatus.PASSED: frozenset(),
    CardStatus.CANCELLED: frozenset(),
}


class CardLevel(str, Enum):
    """Difficulty. Drives the review gate: L3+ demands a heterogeneous review."""

    L1 = "L1"
    L2 = "L2"
    L3 = "L3"
    L4 = "L4"

    @property
    def rank(self) -> int:
        return int(self.value[1])

    @property
    def needs_heterogeneous_review(self) -> bool:
        return self.rank >= 3


class CardPriority(str, Enum):
    P0 = "P0"
    P1 = "P1"
    P2 = "P2"
    P3 = "P3"

    @property
    def rank(self) -> int:
        return int(self.value[1])


def _now() -> _dt.datetime:
    return _dt.datetime.now(_dt.timezone.utc)


def _iso(when: _dt.datetime | None = None) -> str:
    return (when or _now()).isoformat()


def new_card_id(dept: str, seq: int, when: _dt.datetime | None = None) -> str:
    """Build a card id: ``T`` + dept slug + date + sequence.

    The sequence is per department per day and is allocated by the store, which
    is the only component that can see the other cards.
    """
    slug = re.sub(r"[^A-Za-z0-9]", "", dept).upper()[:8]
    if not slug:
        raise CardError(f"部门标识非法: {dept!r} —— 卡号无法生成")
    if seq < 1:
        raise CardError(f"序号必须为正: {seq}")
    day = (when or _now()).strftime("%Y%m%d")
    return f"T{slug}{day}-{seq:02d}"


@dataclass(frozen=True)
class Evidence:
    """One line of the audit trail.

    Every status change writes one, and so does every substantive act along the
    way (a verification run, a delivered asset). ``actor`` is who did it —
    unattributed evidence is what let the old ledger drift.
    """

    ts: str
    actor: str
    note: str
    kind: str = "note"            # note | transition | verify | asset | review
    asset_id: str = ""
    exit_code: int | None = None  # for kind="verify": what the command returned

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "ts": self.ts, "actor": self.actor,
            "note": self.note, "kind": self.kind,
        }
        if self.asset_id:
            d["asset_id"] = self.asset_id
        if self.exit_code is not None:
            d["exit_code"] = self.exit_code
        return d

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> Evidence:
        raw_code = d.get("exit_code")
        return cls(
            ts=str(d.get("ts") or _iso()),
            actor=str(d.get("actor", "")),
            note=str(d.get("note", "")),
            kind=str(d.get("kind", "note")),
            asset_id=str(d.get("asset_id", "")),
            exit_code=int(raw_code) if raw_code is not None else None,
        )

    @classmethod
    def make(cls, actor: str, note: str, **kw: Any) -> Evidence:
        return cls(ts=_iso(), actor=actor, note=note, **kw)


def _norm_provider(value: str) -> str:
    return _PROVIDER_NORMALISE.sub("", str(value).strip().lower())


@dataclass
class TaskCard:
    """A unit of work in the federation ledger.

    Construct through :meth:`create` or the service layer rather than by hand:
    both fill the timestamps and the opening evidence line that make the card
    auditable from birth.
    """

    card_id: str
    dept: str
    title: str
    goal: str                                   # the north star, one sentence
    acceptance: Sequence[str] = field(default_factory=list)
    verify_cmd: str = ""
    level: CardLevel = CardLevel.L2
    priority: CardPriority = CardPriority.P2
    status: CardStatus = CardStatus.DRAFT
    owner: str = ""
    owner_provider: str = ""
    reviewed_by: str = ""
    reviewer_provider: str = ""
    parent_card: str = ""
    collab_req: str = ""
    spec_asset: str = ""
    deliverables: Sequence[str] = field(default_factory=list)
    evidence: list[Evidence] = field(default_factory=list)
    github_issue: int | None = None
    deadline: str = ""
    created_at: str = ""
    updated_at: str = ""
    meta: Mapping[str, Any] = field(default_factory=dict)

    # -- construction ------------------------------------------------------
    @classmethod
    def create(
        cls,
        *,
        card_id: str,
        dept: str,
        title: str,
        goal: str,
        actor: str = "system",
        **kw: Any,
    ) -> TaskCard:
        now = _iso()
        card = cls(
            card_id=card_id, dept=dept, title=title, goal=goal,
            created_at=now, updated_at=now, **kw,
        )
        card.evidence.append(
            Evidence(ts=now, actor=actor, note=f"立卡: {title}", kind="transition")
        )
        card.validate()
        return card

    # -- validation --------------------------------------------------------
    def validate(self) -> None:
        if not _ID_RE.match(self.card_id):
            raise CardError(
                f"card_id 格式错误: {self.card_id};应为 T<部门><YYYYMMDD>-<序号>,"
                f"例 TSEO20260812-01"
            )
        if not self.title.strip():
            raise CardError(f"卡 {self.card_id} 缺标题")
        if not self.goal.strip():
            raise CardError(
                f"卡 {self.card_id} 缺 goal —— 北极星一句话是拆解与验收的共同依据,不可省"
            )
        if not self.dept.strip():
            raise CardError(f"卡 {self.card_id} 缺 dept")
        if self.deadline:
            try:
                _dt.datetime.fromisoformat(self.deadline)
            except ValueError as exc:
                raise CardError(f"deadline 非法: {self.deadline}") from exc
        if self.github_issue is not None and self.github_issue <= 0:
            raise CardError(f"github_issue 必须为正整数: {self.github_issue}")

    # -- evidence ----------------------------------------------------------
    def add_evidence(
        self, actor: str, note: str, *, kind: str = "note", **kw: Any
    ) -> Evidence:
        if not actor.strip():
            raise CardError("证据行必须记名 —— 无行为人的证据是旧账本漂移的病根")
        if not note.strip():
            raise CardError("证据行不能为空")
        ev = Evidence.make(actor, note, kind=kind, **kw)
        self.evidence.append(ev)
        self.updated_at = ev.ts
        return ev

    def evidence_of(self, kind: str) -> list[Evidence]:
        return [e for e in self.evidence if e.kind == kind]

    @property
    def has_passing_verification(self) -> bool:
        """Whether a verification run recorded a zero exit code.

        This is what separates "somebody clicked done" from "the command the
        card itself named actually succeeded".
        """
        return any(e.exit_code == 0 for e in self.evidence_of("verify"))

    # -- state machine -----------------------------------------------------
    def can_transition_to(self, target: CardStatus) -> bool:
        return target in _TRANSITIONS[self.status]

    def transition(
        self,
        target: CardStatus,
        actor: str,
        *,
        note: str = "",
        reviewer_provider: str = "",
        force: bool = False,
    ) -> TaskCard:
        """Move the card, or refuse and say why.

        ``force`` skips the *edge* check only — for administrative correction of
        a card wedged by a bug. It never skips the review gates below, which are
        the point of the module.
        """
        if not actor.strip():
            raise CardError("状态变更必须记名 —— 谁改的进不了审计就等于没改")
        if target is self.status:
            raise CardError(f"卡 {self.card_id} 已处于 {target.label},无需变更")
        if not force and not self.can_transition_to(target):
            allowed = "、".join(s.label for s in sorted(
                _TRANSITIONS[self.status], key=lambda s: s.value
            )) or "无(终态)"
            raise CardError(
                f"非法状态迁移: {self.status.label} → {target.label}。"
                f"当前允许: {allowed}"
            )

        if target is CardStatus.PASSED:
            self._check_review_gate(actor, reviewer_provider)
        if target is CardStatus.ASSIGNED and not (self.owner or "").strip():
            raise CardError(f"卡 {self.card_id} 无 owner,不能置为已指派")

        previous = self.status
        self.status = target
        if target is CardStatus.PASSED:
            self.reviewed_by = actor
            if reviewer_provider:
                self.reviewer_provider = reviewer_provider
        detail = f"{previous.label} → {target.label}"
        self.add_evidence(
            actor, f"{detail}{('; ' + note) if note else ''}", kind="transition"
        )
        return self

    def _check_review_gate(self, actor: str, reviewer_provider: str) -> None:
        """The two rules that make PASSED mean something.

        Raised as CardError rather than returning False so a caller cannot
        ignore the result — the old ledger's failure was exactly that the check
        was advisory.
        """
        owner = (self.owner or "").strip()
        if owner and actor.strip() == owner:
            raise CardError(
                f"卡 {self.card_id} 自审被拒: 验收人 {actor} 即负责人。"
                f"REVIEW→PASSED 必须由他人签发"
            )
        if self.level.needs_heterogeneous_review:
            reviewer_p = _norm_provider(reviewer_provider or self.reviewer_provider)
            owner_p = _norm_provider(self.owner_provider)
            if not reviewer_p:
                raise CardError(
                    f"卡 {self.card_id} 为 {self.level.value},终验须声明 reviewer_provider "
                    f"以校验异构评审"
                )
            if owner_p and reviewer_p == owner_p:
                raise CardError(
                    f"卡 {self.card_id} 异构评审门禁未过: 评审方与作者方同为 "
                    f"{reviewer_provider or self.reviewer_provider};"
                    f"{self.level.value} 卡要求 provider 不同,请换模型再审"
                )

    # -- audit -------------------------------------------------------------
    def audit_flags(self) -> list[str]:
        """Defects a reconciliation sweep should surface. Empty list = clean."""
        flags: list[str] = []
        if self.status is CardStatus.PASSED:
            if self.verify_cmd and not self.has_passing_verification:
                flags.append("PASSED 但无成功的验证记录 —— 假完成候选")
            if not self.reviewed_by:
                flags.append("PASSED 但无验收人")
            elif self.owner and self.reviewed_by == self.owner:
                flags.append("PASSED 但验收人=负责人 —— 自审")
            if self.level.needs_heterogeneous_review:
                r, o = (_norm_provider(self.reviewer_provider),
                        _norm_provider(self.owner_provider))
                if r and o and r == o:
                    flags.append(f"{self.level.value} 卡评审方与作者方同源 —— 异构评审未生效")
        if self.status.is_active and not self.owner:
            flags.append(f"{self.status.label} 但无 owner —— 无人负责")
        if not self.acceptance:
            flags.append("缺验收标准 —— 无法判定生效性")
        return flags

    # -- serialisation -----------------------------------------------------
    def to_dict(self) -> dict[str, Any]:
        return {
            "card_id": self.card_id,
            "dept": self.dept,
            "title": self.title,
            "goal": self.goal,
            "acceptance": list(self.acceptance),
            "verify_cmd": self.verify_cmd,
            "level": self.level.value,
            "priority": self.priority.value,
            "status": self.status.value,
            "status_label": self.status.label,
            "owner": self.owner,
            "owner_provider": self.owner_provider,
            "reviewed_by": self.reviewed_by,
            "reviewer_provider": self.reviewer_provider,
            "parent_card": self.parent_card,
            "collab_req": self.collab_req,
            "spec_asset": self.spec_asset,
            "deliverables": list(self.deliverables),
            "evidence": [e.to_dict() for e in self.evidence],
            "github_issue": self.github_issue,
            "deadline": self.deadline,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "meta": dict(self.meta),
            "active": self.status.is_active,
            "audit_flags": self.audit_flags(),
        }

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> TaskCard:
        issue = d.get("github_issue")
        return cls(
            card_id=str(d["card_id"]),
            dept=str(d.get("dept", "")),
            title=str(d.get("title", "")),
            goal=str(d.get("goal", "")),
            acceptance=list(d.get("acceptance") or []),
            verify_cmd=str(d.get("verify_cmd", "")),
            level=CardLevel(d.get("level", "L2")),
            priority=CardPriority(d.get("priority", "P2")),
            status=CardStatus(d.get("status", "DRAFT")),
            owner=str(d.get("owner", "")),
            owner_provider=str(d.get("owner_provider", "")),
            reviewed_by=str(d.get("reviewed_by", "")),
            reviewer_provider=str(d.get("reviewer_provider", "")),
            parent_card=str(d.get("parent_card", "")),
            collab_req=str(d.get("collab_req", "")),
            spec_asset=str(d.get("spec_asset", "")),
            deliverables=list(d.get("deliverables") or []),
            evidence=[Evidence.from_dict(e) for e in (d.get("evidence") or [])],
            github_issue=int(issue) if issue not in (None, "") else None,
            deadline=str(d.get("deadline", "")),
            created_at=str(d.get("created_at", "")),
            updated_at=str(d.get("updated_at", "")),
            meta=dict(d.get("meta") or {}),
        )

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False)
