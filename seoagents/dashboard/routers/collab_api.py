"""Cross-department inbox / outbox API (L2).

Eight endpoints every federated department system implements. The contract is
identical across departments; the implementation behind it is not.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from dojocore.capability import capabilities as _caps
from dojocore.collab import get_collab_service
from dojocore.collab.models import ProtocolError
from dojocore.logging import LOGGER
from seoagents.agent.runtime import get_runtime
from seoagents.plugins.catalog_loader import capability_map

router = APIRouter(prefix="/api/v1", tags=["collab"])


def _svc():
    try:
        return get_collab_service()
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"collab service unavailable: {exc}") from exc


class TransitionBody(BaseModel):
    status: str
    actor_dept: str = Field(..., description="发起该流转的部门,用于权限校验")
    reason: str = ""
    deliverable_asset_ids: list[str] | None = None


# ── inbox ────────────────────────────────────────────────────────────────
@router.post("/inbox", status_code=201)
async def receive_request(payload: dict[str, Any]) -> dict[str, Any]:
    """Another department posts work to us. Idempotent on ``request_id``."""
    try:
        req, created = _svc().receive(payload)
    except ProtocolError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"created": created, "request": req.to_dict()}


@router.get("/inbox")
async def list_inbox(
    status: str | None = None,
    dept: str | None = None,
    overdue: bool | None = None,
    limit: int = Query(100, le=500),
) -> dict[str, Any]:
    items = _svc().store.list(box="inbox", status=status, dept=dept, overdue=overdue, limit=limit)
    return {
        "total": len(items),
        "overdue_count": sum(1 for r in items if r.is_overdue()),
        "items": [r.to_dict() for r in items],
    }


@router.get("/inbox/{request_id}")
async def get_inbox_item(request_id: str) -> dict[str, Any]:
    svc = _svc()
    req = svc.store.get(request_id, box="inbox")
    if req is None:
        raise HTTPException(status_code=404, detail=f"unknown request '{request_id}'")
    return {**req.to_dict(), "events": svc.store.events(request_id)}


@router.patch("/inbox/{request_id}")
async def transition_inbox(request_id: str, body: TransitionBody) -> dict[str, Any]:
    try:
        req = _svc().transition(
            request_id, box="inbox", to=body.status, actor_dept=body.actor_dept,
            reason=body.reason, deliverable_asset_ids=body.deliverable_asset_ids,
        )
    except ProtocolError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return req.to_dict()


# ── outbox ───────────────────────────────────────────────────────────────
@router.post("/outbox", status_code=201)
async def create_request(payload: dict[str, Any]) -> dict[str, Any]:
    """We ask another department for something.

    Mirrored locally so the request stays visible even if the recipient's
    endpoint is temporarily unreachable — delivery is retried, not lost.
    """
    try:
        req, created = _svc().send(payload)
    except ProtocolError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"created": created, "request": req.to_dict(),
            "note": "已记入 outbox;投递到对方 inbox 由发送器负责,失败会重试"}


@router.get("/outbox")
async def list_outbox(
    status: str | None = None,
    overdue: bool | None = None,
    limit: int = Query(100, le=500),
) -> dict[str, Any]:
    items = _svc().store.list(box="outbox", status=status, overdue=overdue, limit=limit)
    return {
        "total": len(items),
        "overdue_count": sum(1 for r in items if r.is_overdue()),
        "items": [r.to_dict() for r in items],
    }


@router.patch("/outbox/{request_id}")
async def transition_outbox(request_id: str, body: TransitionBody) -> dict[str, Any]:
    try:
        req = _svc().transition(
            request_id, box="outbox", to=body.status, actor_dept=body.actor_dept,
            reason=body.reason, deliverable_asset_ids=body.deliverable_asset_ids,
        )
    except ProtocolError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return req.to_dict()


# ── capability discovery ─────────────────────────────────────────────────


@router.get("/capabilities")
async def list_own_capabilities() -> dict[str, Any]:
    """What this department can be asked to do.

    A capability with no installed provider says so, with the reason. Declaring
    an ability that immediately BLOCKs is worse than declining up front.
    """
    svc = _svc()
    try:
        installed = set(get_runtime().registry.names())
    except Exception:  # noqa: BLE001 - discovery must work without a runtime
        installed = set()
    grouped = capability_map()
    out = []
    for cap in _caps.list():
        tools = [t for t in grouped.get(cap.id, []) if t.installable]
        ready = bool(tools) and bool(installed)
        entry: dict[str, Any] = {
            "id": cap.id,
            "label": cap.label,
            "sla_hours": cap.default_sla_hours,
            "accepts_external": ready,
            "providers": [t.id for t in tools],
        }
        if not ready:
            entry["reason"] = (
                "无已安装的工具提供该能力,当前会返回 DATA_UNAVAILABLE"
                if not tools else "运行时未就绪"
            )
        out.append(entry)
    return {"dept": svc.own_dept, "capabilities": out}


@router.post("/collab/sweep")
async def sweep_overdue() -> dict[str, Any]:
    """Expire / escalate overdue requests. Also wired to the scheduler."""
    touched = _svc().sweep_overdue()
    LOGGER.info(f"collab sweep touched {len(touched)} overdue request(s)")
    return {"touched": [r.to_dict() for r in touched]}


__all__ = ["router"]
