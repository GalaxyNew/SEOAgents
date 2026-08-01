"""Cross-department inbox / outbox contract.

The tests that matter here are the refusals: a protocol whose guards can be
walked around is decoration.
"""
from __future__ import annotations

import datetime as _dt
import tempfile

import httpx
import pytest

from dojocore.collab import reset_collab_service
from dojocore.collab.models import CollabRequest, ProtocolError, RequestStatus, new_request_id
from dojocore.collab.service import CollabService
from dojocore.collab.store import CollabStore
from seoagents.dashboard.server import create_app


def _payload(**over):
    base = {
        "request_id": "REQ-SEO-20260801-0001",
        "from": {"dept": "seo", "hm": "hermes-seo@us"},
        "to": {"dept": "intel", "capability": "image_sourcing"},
        "title": "mejorsiptv D3 文章配图 6 张",
        "spec_asset_id": "AST-DOC-20260801-0012",
        "expected_deliverable": {
            "asset_class": "MEDIA", "count": 6,
            "acceptance": ["每张附版权来源", "尺寸 ≥ 1600x900"],
        },
        "priority": "P2",
    }
    base.update(over)
    return base


@pytest.fixture()
def svc() -> CollabService:
    return CollabService(CollabStore(tempfile.mkdtemp()), own_dept="intel")


# ── request shape ────────────────────────────────────────────────────────
def test_spec_must_be_an_asset_not_prose():
    """Requirements change; messages have no version, assets do."""
    with pytest.raises(ProtocolError, match="spec_asset_id"):
        CollabRequest.from_dict(_payload(spec_asset_id=""))


def test_acceptance_criteria_are_mandatory():
    """Being told what 'done' means only after delivering is the costly path."""
    with pytest.raises(ProtocolError, match="acceptance"):
        CollabRequest.from_dict(
            _payload(expected_deliverable={"asset_class": "MEDIA", "count": 6, "acceptance": []})
        )


def test_cannot_dispatch_to_own_department():
    with pytest.raises(ProtocolError, match="自己部门"):
        CollabRequest.from_dict(_payload(to={"dept": "seo", "capability": "x"}))


def test_request_id_is_requester_generated_and_shaped():
    assert new_request_id("seo", 7).startswith("REQ-SEO-")
    with pytest.raises(ProtocolError, match="request_id"):
        CollabRequest.from_dict(_payload(request_id="whatever-1"))


# ── idempotency ──────────────────────────────────────────────────────────
def test_resend_does_not_open_a_second_ticket(svc: CollabService):
    """Callbacks fail and senders retry — that has already happened here."""
    _, first = svc.receive(_payload())
    _, second = svc.receive(_payload())
    assert first is True and second is False
    assert len(svc.store.list(box="inbox")) == 1


# ── authority ────────────────────────────────────────────────────────────
def test_recipient_cannot_close_its_own_work(svc: CollabService):
    svc.receive(_payload())
    rid = "REQ-SEO-20260801-0001"
    svc.transition(rid, box="inbox", to="ACCEPTED", actor_dept="intel")
    svc.transition(rid, box="inbox", to="IN_PROGRESS", actor_dept="intel")
    svc.transition(rid, box="inbox", to="DELIVERED", actor_dept="intel",
                   deliverable_asset_ids=[f"AST-MEDIA-{i}" for i in range(6)])
    with pytest.raises(ProtocolError, match="只有发起方"):
        svc.transition(rid, box="inbox", to="CLOSED", actor_dept="intel")
    closed = svc.transition(rid, box="inbox", to="CLOSED", actor_dept="seo")
    assert closed.status is RequestStatus.CLOSED


def test_rejection_must_carry_a_reason(svc: CollabService):
    """Silence has no exit; an explicit refusal does."""
    svc.receive(_payload())
    with pytest.raises(ProtocolError, match="reason"):
        svc.transition("REQ-SEO-20260801-0001", box="inbox", to="REJECTED", actor_dept="intel")
    r = svc.transition("REQ-SEO-20260801-0001", box="inbox", to="REJECTED",
                       actor_dept="intel", reason="无版权图库权限,建议转视觉部")
    assert r.status is RequestStatus.REJECTED and r.reason


def test_delivery_requires_assets_and_the_agreed_count(svc: CollabService):
    svc.receive(_payload())
    rid = "REQ-SEO-20260801-0001"
    svc.transition(rid, box="inbox", to="ACCEPTED", actor_dept="intel")
    svc.transition(rid, box="inbox", to="IN_PROGRESS", actor_dept="intel")
    with pytest.raises(ProtocolError, match="deliverable_asset_ids"):
        svc.transition(rid, box="inbox", to="DELIVERED", actor_dept="intel")
    with pytest.raises(ProtocolError, match="数量不足"):
        svc.transition(rid, box="inbox", to="DELIVERED", actor_dept="intel",
                       deliverable_asset_ids=["AST-MEDIA-1"])


def test_illegal_transitions_are_refused(svc: CollabService):
    svc.receive(_payload())
    with pytest.raises(ProtocolError, match="非法状态流转"):
        svc.transition("REQ-SEO-20260801-0001", box="inbox", to="DELIVERED",
                       actor_dept="intel", deliverable_asset_ids=["A"])


def test_terminal_states_are_final(svc: CollabService):
    svc.receive(_payload())
    svc.transition("REQ-SEO-20260801-0001", box="inbox", to="REJECTED",
                   actor_dept="intel", reason="能力不匹配")
    with pytest.raises(ProtocolError, match="终态"):
        svc.transition("REQ-SEO-20260801-0001", box="inbox", to="ACCEPTED", actor_dept="intel")


# ── expiry ───────────────────────────────────────────────────────────────
def test_overdue_is_detected_by_the_recipient(svc: CollabService):
    """Expiry that waits for the requester to chase is not expiry."""
    past = (_dt.datetime.now(_dt.timezone.utc) - _dt.timedelta(days=1)).isoformat()
    svc.receive(_payload(deadline=past))
    touched = svc.sweep_overdue()
    assert [r.status for r in touched] == [RequestStatus.EXPIRED]
    assert svc.store.get("REQ-SEO-20260801-0001", box="inbox").reason


def test_blocked_and_overdue_escalates(svc: CollabService):
    past = (_dt.datetime.now(_dt.timezone.utc) - _dt.timedelta(days=1)).isoformat()
    svc.receive(_payload(deadline=past))
    rid = "REQ-SEO-20260801-0001"
    svc.transition(rid, box="inbox", to="ACCEPTED", actor_dept="intel")
    svc.transition(rid, box="inbox", to="BLOCKED", actor_dept="intel", reason="等版权授权")
    touched = svc.sweep_overdue()
    assert [r.status for r in touched] == [RequestStatus.ESCALATED]


# ── audit trail ──────────────────────────────────────────────────────────
def test_every_transition_is_recorded(svc: CollabService):
    svc.receive(_payload())
    svc.transition("REQ-SEO-20260801-0001", box="inbox", to="ACCEPTED", actor_dept="intel")
    events = svc.store.events("REQ-SEO-20260801-0001")
    assert [e["to_state"] for e in events] == ["PENDING", "ACCEPTED"]
    assert all(e["actor"] for e in events)


# ── HTTP surface ─────────────────────────────────────────────────────────
@pytest.fixture()
async def client(runtime):
    reset_collab_service()
    app = create_app()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    reset_collab_service()


async def test_capabilities_declare_what_cannot_be_done(client: httpx.AsyncClient):
    """Declaring an ability that instantly BLOCKs is worse than declining."""
    res = await client.get("/api/v1/capabilities")
    assert res.status_code == 200
    body = res.json()
    assert body["dept"]
    unavailable = [c for c in body["capabilities"] if not c["accepts_external"]]
    assert all(c.get("reason") for c in unavailable)


async def test_inbox_roundtrip_over_http(client: httpx.AsyncClient):
    payload = _payload(**{"to": {"dept": "seo", "capability": "site_audit"},
                          "from": {"dept": "intel"}})
    res = await client.post("/api/v1/inbox", json=payload)
    assert res.status_code == 201 and res.json()["created"] is True

    # idempotent
    res = await client.post("/api/v1/inbox", json=payload)
    assert res.json()["created"] is False

    res = await client.get("/api/v1/inbox")
    assert res.json()["total"] == 1

    # recipient may not close
    res = await client.patch(
        "/api/v1/inbox/REQ-SEO-20260801-0001",
        json={"status": "CLOSED", "actor_dept": "seo"},
    )
    assert res.status_code == 409


async def test_malformed_request_is_rejected_with_reason(client: httpx.AsyncClient):
    res = await client.post("/api/v1/inbox", json=_payload(spec_asset_id=""))
    assert res.status_code == 422
    assert "spec_asset_id" in res.json()["detail"]
