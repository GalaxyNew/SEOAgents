"""No-side-effect tests for the Timeline -> Workflow runtime closure."""
from __future__ import annotations

import datetime as dt
import importlib.util
import sys
from pathlib import Path

import pytest

from dojocore.timeline import TimelineService, TimelineStore


_PULSE_PATH = Path("/opt/hermes-seo/scripts/timeline_pulse.py")


def _load_timeline_pulse():
    spec = importlib.util.spec_from_file_location("timeline_pulse_under_test", _PULSE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture()
def pulse_env(tmp_path: Path, monkeypatch):
    pulse = _load_timeline_pulse()
    monkeypatch.setattr(pulse, "DATA_DIR", tmp_path)
    monkeypatch.setattr(pulse, "TIMELINE_DB", tmp_path / "timeline.db")
    monkeypatch.setattr(pulse, "RUN_DB", tmp_path / "timeline_runs.db")
    store = TimelineStore(tmp_path)
    service = TimelineService(store, owner="test")
    return pulse, service


def _due_workflow(service: TimelineService):
    return service.schedule(
        {
            "scheduled_at": (dt.datetime.now(dt.timezone.utc) - dt.timedelta(seconds=1)).isoformat(),
            "kind": "START",
            "intent": "Run isolated workflow",
            "subject_ref": "test-only",
            "expected_minutes": 5,
            "context": {
                "task_type": "workflow",
                "workflow_id": "runtime_closure",
                "workflow_version": "1.0",
                "parameters": {"query": "fake"},
                "scheduler": "hermes-pulse",
                "runtime_state": "SCHEDULED",
            },
        }
    )


def _run_row(pulse, node_id: str) -> dict:
    with pulse.connect_runs() as conn:
        row = conn.execute("SELECT * FROM timeline_runs WHERE node_id=?", (node_id,)).fetchone()
    assert row is not None
    return dict(row)


def test_due_workflow_uses_auto_start_and_persists_instance_run_ids(
    pulse_env, monkeypatch,
):
    pulse, service = pulse_env
    node = _due_workflow(service)
    calls: list[tuple[str, str, dict | None]] = []

    def fake_dashboard(method: str, path: str, body: dict | None = None) -> dict:
        calls.append((method, path, body))
        return {
            "instance_id": "WF-FAKE-1",
            "runtime": {"created": [{"node": "execute", "run_id": "fake-run-1"}]},
        }

    monkeypatch.setattr(pulse, "seoagents_api", fake_dashboard)

    claimed = pulse.claim_due()
    assert [item["node_id"] for item in claimed] == [node.node_id]
    pulse.dispatch(claimed[0])

    assert len(calls) == 1
    method, path, body = calls[0]
    assert (method, path) == ("POST", "/api/workflows/instances")
    assert body is not None
    assert body["auto_start"] is True
    assert body["template_id"] == "runtime_closure"
    assert body["input_params"] == {"query": "fake"}
    assert body["parent_task"] == node.node_id

    persisted = pulse.load_node(node.node_id)
    assert persisted is not None
    assert persisted["state"] == "FIRED"
    assert persisted["context"]["workflow_instance_id"] == "WF-FAKE-1"
    assert persisted["context"]["workflow_run_ids"] == ["fake-run-1"]
    assert _run_row(pulse, node.node_id)["hermes_run_id"] == "workflow:WF-FAKE-1"


def test_timeline_acks_only_after_workflow_business_done(pulse_env, monkeypatch):
    pulse, service = pulse_env
    node = _due_workflow(service)
    statuses = iter(["RUNNING", "BLOCKED", "DONE"])
    post_bodies: list[dict] = []

    def fake_dashboard(method: str, path: str, body: dict | None = None) -> dict:
        if method == "POST":
            assert body is not None
            post_bodies.append(body)
            return {
                "instance_id": "WF-FAKE-2",
                "runtime": {"created": [{"node": "execute", "run_id": "fake-run-2"}]},
            }
        assert (method, path) == ("GET", "/api/workflows/instances/WF-FAKE-2")
        return {"instance_id": "WF-FAKE-2", "status": next(statuses)}

    monkeypatch.setattr(pulse, "seoagents_api", fake_dashboard)
    [claimed] = pulse.claim_due()
    pulse.dispatch(claimed)

    for expected in ("RUNNING", "BLOCKED"):
        assert pulse.reconcile() == []
        persisted = pulse.load_node(node.node_id)
        assert persisted is not None
        assert persisted["state"] == "FIRED"
        assert persisted["acked_at"] == ""
        assert persisted["context"]["runtime_state"] == "RUNNING"
        assert _run_row(pulse, node.node_id)["status"] == "RUNNING"

    assert pulse.reconcile() == []
    persisted = pulse.load_node(node.node_id)
    assert persisted is not None
    assert persisted["state"] == "ACKED"
    assert persisted["acked_at"]
    assert persisted["context"]["runtime_state"] == "COMPLETED"
    assert "business status DONE" in persisted["outcome"]
    assert _run_row(pulse, node.node_id)["status"] == "COMPLETED"
    assert len(post_bodies) == 1


def test_workflow_start_without_run_id_is_unknown_and_never_redispatched(
    pulse_env, monkeypatch,
):
    pulse, service = pulse_env
    node = _due_workflow(service)
    calls = 0

    def fake_dashboard(method: str, path: str, body: dict | None = None) -> dict:
        nonlocal calls
        calls += 1
        return {"instance_id": "WF-UNACKED", "runtime": {"created": []}}

    monkeypatch.setattr(pulse, "seoagents_api", fake_dashboard)
    assert pulse.main() == 0
    assert calls == 1
    persisted = pulse.load_node(node.node_id)
    assert persisted is not None
    assert persisted["state"] == "UNACKED"
    assert persisted["context"]["runtime_state"] == "UNKNOWN"
    assert _run_row(pulse, node.node_id)["status"] == "UNKNOWN"

    assert pulse.main() == 0
    assert calls == 1
