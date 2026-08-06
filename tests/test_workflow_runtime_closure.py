"""No-side-effect regression tests for Workflow runtime closure."""
from __future__ import annotations

import asyncio
import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import httpx
import pytest

from dojocore.workflow import WorkflowTemplate, get_workflow_store, reset_workflow_state
from seoagents.dashboard.server import create_app


_TEMPLATE = {
    "id": "runtime_closure",
    "name": "Runtime closure",
    "version": "1.0",
    "nodes": [
        {
            "id": "execute",
            "type": "agent_task",
            "title": "Execute harmless fake work",
            "acceptance": ["fake result is explicitly accepted"],
            "config": {"instruction": "Return a deterministic fake result."},
        }
    ],
}


class FakeHermes:
    """Thread-safe local HTTP fake; every submit is observable and side-effect free."""

    def __init__(self) -> None:
        self.posts: list[dict] = []
        self.runs: dict[str, dict] = {}
        self._lock = threading.Lock()
        self._server: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None
        self.submit_entered = threading.Event()
        self.release_submit = threading.Event()
        self.release_submit.set()
        self.url = ""

    def start(self) -> "FakeHermes":
        fake = self

        class Handler(BaseHTTPRequestHandler):
            def _send(self, status: int, payload: dict) -> None:
                raw = json.dumps(payload).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            def do_POST(self) -> None:  # noqa: N802 - stdlib callback name
                if self.path != "/v1/runs":
                    self._send(404, {"error": "not found"})
                    return
                size = int(self.headers.get("Content-Length", "0"))
                body = json.loads(self.rfile.read(size) or b"{}")
                with fake._lock:
                    fake.posts.append(body)
                    run_id = f"fake-run-{len(fake.posts)}"
                    fake.runs[run_id] = {"status": "running", "output": ""}
                fake.submit_entered.set()
                if not fake.release_submit.wait(timeout=5):
                    self._send(500, {"error": "fake barrier timed out"})
                    return
                self._send(200, {"run_id": run_id, "status": "queued"})

            def do_GET(self) -> None:  # noqa: N802 - stdlib callback name
                prefix = "/v1/runs/"
                if not self.path.startswith(prefix):
                    self._send(404, {"error": "not found"})
                    return
                run_id = self.path[len(prefix):]
                with fake._lock:
                    run = dict(fake.runs.get(run_id) or {})
                if not run:
                    self._send(404, {"error": "unknown run"})
                    return
                self._send(200, {"run_id": run_id, **run})

            def log_message(self, format: str, *args) -> None:  # noqa: A002
                return

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        host, port = self._server.server_address[:2]
        self.url = f"http://{host}:{port}"
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()
        return self

    def set_run(self, run_id: str, *, status: str, output: str = "") -> None:
        with self._lock:
            self.runs[run_id] = {"status": status, "output": output}

    def close(self) -> None:
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
        if self._thread is not None:
            self._thread.join(timeout=2)


@pytest.fixture()
def fake_hermes(monkeypatch):
    fake = FakeHermes().start()
    monkeypatch.setenv("HERMES_API_URL", fake.url)
    monkeypatch.setenv("HERMES_API_KEY", "fake-test-key")
    try:
        yield fake
    finally:
        fake.close()


@pytest.fixture()
async def workflow_client(runtime, fake_hermes):
    assert runtime is not None
    reset_workflow_state()
    store = get_workflow_store()
    store.save_template(WorkflowTemplate.from_dict(_TEMPLATE))
    app = create_app()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield client
    reset_workflow_state()


async def _create(client: httpx.AsyncClient, *, auto_start: bool = False) -> dict:
    response = await client.post(
        "/api/workflows/instances",
        json={"template_id": _TEMPLATE["id"], "auto_start": auto_start},
    )
    assert response.status_code == 201, response.text
    return response.json()


async def test_create_only_stays_pending_and_is_excluded_from_active_ticks(
    workflow_client: httpx.AsyncClient, fake_hermes: FakeHermes,
):
    created = await _create(workflow_client)
    instance_id = created["instance_id"]

    for _ in range(2):
        active = (await workflow_client.get("/api/workflows/internal/instances?active=true")).json()
        assert instance_id not in {item["instance_id"] for item in active["items"]}
        tick = await workflow_client.post(f"/api/workflows/internal/instances/{instance_id}/tick")
        assert tick.status_code == 200
        assert tick.json()["runtime"]["created"] == []

    detail = (await workflow_client.get(f"/api/workflows/instances/{instance_id}")).json()
    assert detail["status"] == "PENDING"
    assert detail["runs"]["execute"]["state"] == "PENDING"
    assert fake_hermes.posts == []


async def test_explicit_start_persists_real_run_id_once(
    workflow_client: httpx.AsyncClient, fake_hermes: FakeHermes,
):
    created = await _create(workflow_client)
    instance_id = created["instance_id"]

    started = await workflow_client.post(f"/api/workflows/instances/{instance_id}/start")
    assert started.status_code == 200, started.text
    runtime = started.json()
    assert runtime["created"] == [{"node": "execute", "run_id": "fake-run-1"}]

    detail = (await workflow_client.get(f"/api/workflows/instances/{instance_id}")).json()
    assert detail["context"]["start_authorized"] is True
    assert detail["runs"]["execute"]["runtime_run_id"] == "fake-run-1"
    assert detail["runs"]["execute"]["state"] == "RUNNING"
    assert detail["runs"]["execute"]["attempts"] == 1

    await workflow_client.post(f"/api/workflows/internal/instances/{instance_id}/tick")
    assert len(fake_hermes.posts) == 1


async def test_direct_start_and_tick_race_dispatches_only_once(
    workflow_client: httpx.AsyncClient, fake_hermes: FakeHermes,
):
    created = await _create(workflow_client)
    instance_id = created["instance_id"]
    store = get_workflow_store()
    store.authorize_start(instance_id)

    fake_hermes.release_submit.clear()

    # Direct /start and Pulse tick converge on this production dispatcher. Race
    # their respective endpoint callables through the shared persisted CAS boundary.
    from seoagents.dashboard.routers import workflow_api

    def direct_start() -> dict:
        return asyncio.run(workflow_api.start_runtime(instance_id))

    def pulse_tick() -> dict:
        return asyncio.run(workflow_api.internal_tick(instance_id))

    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(direct_start)
        assert fake_hermes.submit_entered.wait(timeout=3)
        second = pool.submit(pulse_tick)
        time.sleep(0.1)
        fake_hermes.release_submit.set()
        outputs = [first.result(timeout=5), second.result(timeout=5)]

    created_count = sum(
        len(output.get("created") or (output.get("runtime") or {}).get("created") or [])
        for output in outputs
    )
    assert created_count == 1
    assert len(fake_hermes.posts) == 1
    persisted = store.instance(instance_id)
    assert persisted is not None
    assert persisted.runs["execute"].runtime_run_id == "fake-run-1"
    assert persisted.runs["execute"].attempts == 1


async def test_completed_process_without_acceptance_or_evidence_is_not_done(
    workflow_client: httpx.AsyncClient, fake_hermes: FakeHermes,
):
    created = await _create(workflow_client, auto_start=True)
    instance_id = created["instance_id"]
    run_id = created["runtime"]["created"][0]["run_id"]
    fake_hermes.set_run(run_id, status="completed", output="process exited cleanly")

    tick = await workflow_client.post(f"/api/workflows/internal/instances/{instance_id}/tick")
    assert tick.status_code == 200, tick.text
    body = tick.json()
    run = body["instance"]["runs"]["execute"]
    assert run["runtime_status"] == "AWAITING_ACCEPTANCE"
    assert run["state"] != "DONE"
    assert body["instance"]["status"] != "DONE"

    callback = await workflow_client.post(
        f"/api/workflows/internal/instances/{instance_id}/nodes/execute/runtime",
        json={"run_id": run_id, "status": "completed", "output": "still no evidence"},
    )
    assert callback.status_code == 200, callback.text
    callback_run = callback.json()["instance"]["runs"]["execute"]
    assert callback_run["runtime_status"] == "AWAITING_ACCEPTANCE"
    assert callback_run["state"] != "DONE"
    assert len(fake_hermes.posts) == 1
