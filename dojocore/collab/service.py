"""Transition rules for cross-department requests.

All authority checks live here rather than in the HTTP layer, so the same rules
apply whether a transition arrives over REST, over MCP, or from the scheduler.
"""
from __future__ import annotations

import datetime as _dt
from typing import Any

from dojocore.collab.models import (
    REASON_REQUIRED,
    RECIPIENT_ONLY,
    REQUESTER_ONLY,
    TERMINAL,
    TRANSITIONS,
    CollabRequest,
    ProtocolError,
    RequestStatus,
)
from dojocore.collab.store import CollabStore
from dojocore.logging import LOGGER


class CollabService:
    def __init__(self, store: CollabStore, *, own_dept: str) -> None:
        self.store = store
        self.own_dept = own_dept

    # -- inbound -----------------------------------------------------------
    def receive(self, payload: dict[str, Any]) -> tuple[CollabRequest, bool]:
        """Another department posts work to us."""
        req = CollabRequest.from_dict(payload)
        if req.recipient.dept != self.own_dept:
            raise ProtocolError(
                f"该请求的收件部门是 '{req.recipient.dept}',不是本部门 '{self.own_dept}'"
            )
        req.status = RequestStatus.PENDING
        return self.store.put(req, box="inbox")

    def send(self, payload: dict[str, Any]) -> tuple[CollabRequest, bool]:
        """We ask another department for something. Mirrored into our outbox."""
        req = CollabRequest.from_dict(payload)
        if req.sender.dept != self.own_dept:
            raise ProtocolError(
                f"该请求的发起部门是 '{req.sender.dept}',不是本部门 '{self.own_dept}'"
            )
        return self.store.put(req, box="outbox")

    # -- transitions -------------------------------------------------------
    def transition(
        self,
        request_id: str,
        *,
        box: str,
        to: str | RequestStatus,
        actor_dept: str,
        reason: str = "",
        deliverable_asset_ids: list[str] | None = None,
    ) -> CollabRequest:
        req = self.store.get(request_id, box=box)
        if req is None:
            raise ProtocolError(f"请求不存在: {request_id} (box={box})")

        target = to if isinstance(to, RequestStatus) else RequestStatus(to)
        current = req.status

        if current in TERMINAL:
            raise ProtocolError(f"{request_id} 已处于终态 {current.value},不可再流转")

        allowed = TRANSITIONS.get(current, frozenset())
        if target not in allowed:
            raise ProtocolError(
                f"非法状态流转 {current.value} → {target.value};"
                f"当前只允许: {sorted(s.value for s in allowed) or '(终态)'}"
            )

        # Constraint 6 — acceptance belongs to whoever asked for the work.
        if target in REQUESTER_ONLY and actor_dept != req.sender.dept:
            raise ProtocolError(
                f"只有发起方({req.sender.dept})可以将请求置为 {target.value}。"
                f"接收方最多推进到 DELIVERED —— 自己声明自己做完了不算完成"
            )
        if target in RECIPIENT_ONLY and actor_dept != req.recipient.dept:
            raise ProtocolError(
                f"只有接收方({req.recipient.dept})可以将请求置为 {target.value}"
            )

        # Constraint 4 — "something went wrong" must say what.
        if target in REASON_REQUIRED and not reason.strip():
            raise ProtocolError(
                f"置为 {target.value} 必须给出 reason —— "
                f"说不清原因的拒绝/阻塞,对方无法处理,只会变成静默拖延"
            )

        if target is RequestStatus.DELIVERED:
            ids = deliverable_asset_ids or list(req.deliverable_asset_ids)
            if not ids:
                raise ProtocolError(
                    "DELIVERED 必须附 deliverable_asset_ids —— "
                    "交付物要先进资产中心,口头声明不算交付"
                )
            expected = req.expected.count
            if expected and len(ids) < expected:
                raise ProtocolError(
                    f"交付物数量不足:要求 {expected} 件,实际 {len(ids)} 件"
                )
            req.deliverable_asset_ids = tuple(ids)

        prev = current.value
        req.status = target
        req.reason = reason
        req.history = tuple(req.history) + (
            {"from": prev, "to": target.value, "actor": actor_dept,
             "reason": reason, "at": _dt.datetime.now(_dt.timezone.utc).isoformat()},
        )
        self.store.save(req, box=box)
        self.store.record_event(
            request_id, actor=actor_dept, from_state=prev,
            to_state=target.value, reason=reason,
        )
        LOGGER.info(f"collab {request_id}: {prev} → {target.value} by {actor_dept}")
        return req

    # -- scheduled -------------------------------------------------------
    def sweep_overdue(self, *, box: str = "inbox") -> list[CollabRequest]:
        """Expire overdue requests and escalate the ones already blocked.

        Runs on the recipient's scheduler. Expiry that depends on the requester
        chasing is not expiry, it is hope.
        """
        touched: list[CollabRequest] = []
        for req in self.store.due_for_escalation(box=box):
            if req.status in TERMINAL:
                continue
            target = (
                RequestStatus.ESCALATED
                if req.status in (RequestStatus.BLOCKED, RequestStatus.EXPIRED)
                else RequestStatus.EXPIRED
            )
            if target not in TRANSITIONS.get(req.status, frozenset()):
                continue
            reason = f"deadline {req.deadline} 已过,自动{'升级' if target is RequestStatus.ESCALATED else '过期'}"
            prev = req.status.value
            req.status = target
            req.reason = reason
            self.store.save(req, box=box)
            self.store.record_event(
                req.request_id, actor="scheduler", from_state=prev,
                to_state=target.value, reason=reason,
            )
            LOGGER.warning(f"collab {req.request_id}: {prev} → {target.value} ({reason})")
            touched.append(req)
        return touched


__all__ = ["CollabService"]
