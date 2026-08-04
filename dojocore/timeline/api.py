"""Timeline API — the agent's own schedule, and what it failed to handle."""
from __future__ import annotations

import datetime as _dt
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from dojocore.timeline import TimelineError, get_timeline

router = APIRouter(prefix="/api/timeline", tags=["timeline"])


def _svc():
    try:
        return get_timeline()
    except Exception as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


class ScheduleBody(BaseModel):
    scheduled_at: str
    kind: str = "START"
    intent: str
    subject_ref: str = ""
    expected_minutes: int = 15
    on_miss: str = "ask"
    parent_node: str = ""
    context: dict[str, Any] = Field(default_factory=dict)
    allow_conflict: bool = False


class PlanBody(BaseModel):
    intent: str
    subject_ref: str
    start_in_minutes: int = 30
    expected_minutes: int = 15
    checkpoint_after_minutes: int | None = 15
    on_miss: str = "catchup"


class AckBody(BaseModel):
    outcome: str


class TriageBody(BaseModel):
    decisions: list[dict[str, Any]] = Field(default_factory=list)


@router.get("/agenda")
async def agenda(hours_ahead: int = Query(24, le=720)) -> dict[str, Any]:
    """What the agent has already committed to — read this before planning."""
    return _svc().agenda(hours_ahead=hours_ahead)


@router.get("/range")
async def node_range(
    hours_back: int = Query(72, ge=0, le=8760),
    hours_ahead: int = Query(72, ge=0, le=8760),
) -> dict[str, Any]:
    """一段时间窗内的**全部**节点,不分状态。

    `agenda` 只给待办,`unread` 只给没处理的 —— 横向时间轴要的是
    「左边已发生(带结论)、右边将发生」的完整视图,所以需要这一条。
    """
    import datetime as _dt

    now = _dt.datetime.now(_dt.timezone.utc)
    svc = _svc()
    nodes = svc.store.between(
        now - _dt.timedelta(hours=hours_back),
        now + _dt.timedelta(hours=hours_ahead),
    )
    return {
        "now": now.isoformat(),
        "window": {"hours_back": hours_back, "hours_ahead": hours_ahead},
        "nodes": [n.to_dict() for n in nodes],
        "total": len(nodes),
    }


@router.post("/nodes", status_code=201)
async def schedule(body: ScheduleBody) -> dict[str, Any]:
    try:
        node = _svc().schedule(
            body.model_dump(exclude={"allow_conflict"}), allow_conflict=body.allow_conflict
        )
    except TimelineError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return node.to_dict()


@router.post("/plan", status_code=201)
async def plan(body: PlanBody) -> dict[str, Any]:
    """Plan work plus its follow-up check — the common shape."""
    svc = _svc()
    try:
        nodes = svc.plan_task(
            intent=body.intent,
            subject_ref=body.subject_ref,
            start_at=_dt.datetime.now(_dt.timezone.utc)
            + _dt.timedelta(minutes=body.start_in_minutes),
            expected_minutes=body.expected_minutes,
            checkpoint_after_minutes=body.checkpoint_after_minutes,
            on_miss=body.on_miss,
        )
    except TimelineError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"nodes": [n.to_dict() for n in nodes]}


@router.get("/due")
async def due() -> dict[str, Any]:
    return {"items": [n.to_dict() for n in _svc().due()]}


@router.post("/nodes/{node_id}/fire")
async def fire(node_id: str) -> dict[str, Any]:
    try:
        return _svc().fire(node_id).to_dict()
    except TimelineError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/nodes/{node_id}/ack")
async def ack(node_id: str, body: AckBody) -> dict[str, Any]:
    try:
        return _svc().ack(node_id, outcome=body.outcome).to_dict()
    except TimelineError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/sweep")
async def sweep(grace_minutes: int = 10) -> dict[str, Any]:
    """Find what silently did not happen."""
    result = _svc().sweep(grace_minutes=grace_minutes)
    return {k: [n.to_dict() for n in v] for k, v in result.items()}


@router.get("/unread")
async def unread() -> dict[str, Any]:
    """Awaiting a triage decision. Nothing here may be ignored, only decided."""
    items = _svc().unread()
    return {"total": len(items), "items": [n.to_dict() for n in items]}


@router.post("/triage")
async def triage(body: TriageBody) -> dict[str, Any]:
    try:
        return _svc().triage(body.decisions)
    except TimelineError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


__all__ = ["router"]
