"""Task card REST API — the only writable path into the ledger.

Every mutating endpoint takes an ``actor``. That is not ceremony: the ledger
this replaces let anyone edit a status with no attribution, and the resulting
drift ("marked complete, never done") is the failure the whole module exists to
prevent. An unattributed write is refused at the schema.

Mounted under ``/api/v1/taskcards`` alongside the other federation endpoints,
so the control tower can aggregate every department through one contract.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from dojocore.logging import LOGGER
from dojocore.taskcard import get_taskcards
from dojocore.taskcard.models import CardError, CardStatus

router = APIRouter(prefix="/api/v1/taskcards", tags=["taskcard"])


# ── 请求体 ────────────────────────────────────────────────────────────────
class OpenCardBody(BaseModel):
    title: str
    goal: str
    acceptance: list[str] = Field(default_factory=list)
    verify_cmd: str = ""
    level: str = "L2"
    priority: str = "P2"
    owner: str = ""
    owner_provider: str = ""
    parent_card: str = ""
    collab_req: str = ""
    spec_asset: str = ""
    github_issue: int | None = None
    deadline: str = ""
    actor: str = "system"
    dept: str | None = None
    meta: dict[str, Any] = Field(default_factory=dict)


class AssignBody(BaseModel):
    owner: str
    actor: str
    owner_provider: str = ""
    note: str = ""


class MoveBody(BaseModel):
    status: str
    actor: str
    note: str = ""
    reviewer_provider: str = ""
    force: bool = False


class EvidenceBody(BaseModel):
    actor: str
    note: str
    kind: str = "note"
    asset_id: str = ""


class ApproveBody(BaseModel):
    reviewer: str
    reviewer_provider: str = ""
    note: str = ""
    require_verification: bool = True


class RejectBody(BaseModel):
    reviewer: str
    reason: str


class VerifyBody(BaseModel):
    actor: str = "engine"


def _guard(fn: Any) -> Any:
    """Turn ledger rule violations into 400s that quote the rule."""
    try:
        return fn()
    except CardError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


# ── 读 ────────────────────────────────────────────────────────────────────
@router.get("")
async def list_cards(
    status: str = Query("active", description="active | all | 逗号分隔的状态"),
    owner: str = Query("", description="按负责人过滤"),
    limit: int = Query(100, ge=1, le=500),
) -> dict[str, Any]:
    svc = get_taskcards()
    if owner:
        cards = svc.store.by_owner(owner, active_only=(status == "active"))
    elif status == "active":
        cards = svc.store.active()
    elif status == "all":
        cards = svc.store.recent(limit=limit)
    else:
        try:
            wanted = [CardStatus(s.strip().upper()) for s in status.split(",") if s.strip()]
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=f"未知状态: {status}") from exc
        cards = svc.store.by_statuses(wanted)
    cards = cards[:limit]
    return {
        "dept": svc.dept,
        "data_status": "REAL",
        "count": len(cards),
        "cards": [c.to_dict() for c in cards],
    }


@router.get("/summary")
async def cards_summary() -> dict[str, Any]:
    return get_taskcards().summary()


@router.get("/audit")
async def cards_audit() -> dict[str, Any]:
    """Cards whose state contradicts their evidence — the假完成 sweep."""
    svc = get_taskcards()
    flagged = svc.audit()
    return {
        "dept": svc.dept, "data_status": "REAL",
        "count": len(flagged), "flagged": flagged,
    }


@router.get("/stalled")
async def cards_stalled(hours: float = Query(2.0, gt=0, le=720)) -> dict[str, Any]:
    svc = get_taskcards()
    cards = svc.store.stalled(hours=hours)
    return {
        "dept": svc.dept, "data_status": "REAL", "hours": hours,
        "count": len(cards),
        "cards": [
            {"card_id": c.card_id, "title": c.title, "status": c.status.value,
             "owner": c.owner, "updated_at": c.updated_at}
            for c in cards
        ],
    }


@router.get("/{card_id}")
async def get_card(card_id: str) -> dict[str, Any]:
    card = get_taskcards().store.get(card_id)
    if card is None:
        raise HTTPException(status_code=404, detail=f"任务卡不存在: {card_id}")
    return card.to_dict()


# ── 写 ────────────────────────────────────────────────────────────────────
@router.post("")
async def open_card(body: OpenCardBody) -> dict[str, Any]:
    svc = get_taskcards()
    payload = body.model_dump()
    actor = payload.pop("actor")
    dept = payload.pop("dept")
    card = _guard(lambda: svc.open_card(actor=actor, dept=dept, **payload))
    LOGGER.info("api.taskcard.open %s by %s", card.card_id, actor)
    return card.to_dict()


@router.post("/{card_id}/assign")
async def assign_card(card_id: str, body: AssignBody) -> dict[str, Any]:
    svc = get_taskcards()
    card = _guard(lambda: svc.assign(
        card_id, body.owner, actor=body.actor,
        owner_provider=body.owner_provider, note=body.note,
    ))
    return card.to_dict()


@router.post("/{card_id}/move")
async def move_card(card_id: str, body: MoveBody) -> dict[str, Any]:
    svc = get_taskcards()
    try:
        target = CardStatus(body.status.strip().upper())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"未知状态: {body.status}") from exc
    card = _guard(lambda: svc.move(
        card_id, target, actor=body.actor, note=body.note,
        reviewer_provider=body.reviewer_provider, force=body.force,
    ))
    return card.to_dict()


@router.post("/{card_id}/evidence")
async def add_evidence(card_id: str, body: EvidenceBody) -> dict[str, Any]:
    svc = get_taskcards()
    card = _guard(lambda: svc.add_evidence(
        card_id, body.actor, body.note, kind=body.kind, asset_id=body.asset_id,
    ))
    return card.to_dict()


@router.post("/{card_id}/verify")
async def verify_card(card_id: str, body: VerifyBody | None = None) -> dict[str, Any]:
    svc = get_taskcards()
    actor = body.actor if body else "engine"
    result = _guard(lambda: svc.verify(card_id, actor=actor))
    return result.to_dict()


@router.post("/{card_id}/approve")
async def approve_card(card_id: str, body: ApproveBody) -> dict[str, Any]:
    svc = get_taskcards()
    card = _guard(lambda: svc.approve(
        card_id, reviewer=body.reviewer, reviewer_provider=body.reviewer_provider,
        note=body.note, require_verification=body.require_verification,
    ))
    return card.to_dict()


@router.post("/{card_id}/reject")
async def reject_card(card_id: str, body: RejectBody) -> dict[str, Any]:
    svc = get_taskcards()
    card = _guard(lambda: svc.reject(card_id, reviewer=body.reviewer, reason=body.reason))
    return card.to_dict()
