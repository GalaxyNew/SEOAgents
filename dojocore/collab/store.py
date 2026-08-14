"""SQLite-backed inbox/outbox storage.

Local to each department — there is no shared table. A request exists in the
recipient's inbox and (as a mirror) in the sender's outbox, and neither side
can write the other's copy directly.
"""
from __future__ import annotations

import datetime as _dt
import json
import os
import sqlite3
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from dojocore.collab.models import (
    CollabRequest,
)
from dojocore.logging import LOGGER

_SCHEMA = """
CREATE TABLE IF NOT EXISTS collab_requests (
    request_id     TEXT PRIMARY KEY,
    box            TEXT NOT NULL CHECK (box IN ('inbox','outbox')),
    sender_dept    TEXT NOT NULL,
    recipient_dept TEXT NOT NULL,
    capability     TEXT NOT NULL,
    status         TEXT NOT NULL,
    priority       TEXT NOT NULL,
    deadline       TEXT,
    parent_task    TEXT,
    payload        TEXT NOT NULL,
    created_at     TEXT NOT NULL,
    updated_at     TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_collab_box    ON collab_requests(box, status);
CREATE INDEX IF NOT EXISTS idx_collab_due    ON collab_requests(deadline);
CREATE INDEX IF NOT EXISTS idx_collab_parent ON collab_requests(parent_task);

CREATE TABLE IF NOT EXISTS collab_events (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    request_id TEXT NOT NULL,
    actor      TEXT NOT NULL,
    from_state TEXT,
    to_state   TEXT NOT NULL,
    reason     TEXT,
    at         TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_events_req ON collab_events(request_id, id);
"""


def _now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).isoformat()


class CollabStore:
    def __init__(self, data_dir: str | os.PathLike[str]) -> None:
        self.path = Path(os.path.expanduser(str(data_dir)))
        self.path.mkdir(parents=True, exist_ok=True)
        self.db = self.path / "collab.db"
        self._lock = threading.Lock()
        with self._conn() as conn:
            conn.executescript(_SCHEMA)

    @contextmanager
    def _conn(self) -> Iterator[sqlite3.Connection]:
        """Open, commit, and — crucially — close.

        ``sqlite3.Connection.__exit__`` commits but does not close. Relying on
        it leaks a file descriptor per query; a few hundred operations later
        SQLite refuses with "unable to open database file", which reads like
        corruption and is not.
        """
        conn = sqlite3.connect(self.db, timeout=15)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    # -- writes ------------------------------------------------------------
    def put(self, req: CollabRequest, *, box: str) -> tuple[CollabRequest, bool]:
        """Insert, or return the existing row untouched.

        Returns ``(request, created)``. Idempotency lives here: a resend of the
        same ``request_id`` must not open a second ticket, because callbacks
        fail and senders retry — that has already happened in production.
        """
        req.validate()
        with self._lock, self._conn() as conn:
            row = conn.execute(
                "SELECT payload FROM collab_requests WHERE request_id=? AND box=?",
                (req.request_id, box),
            ).fetchone()
            if row is not None:
                LOGGER.info(f"collab: duplicate {req.request_id} ignored (idempotent)")
                return CollabRequest.from_dict(json.loads(row["payload"])), False

            now = _now()
            req.created_at = req.created_at or now
            req.updated_at = now
            conn.execute(
                "INSERT INTO collab_requests (request_id,box,sender_dept,recipient_dept,"
                "capability,status,priority,deadline,parent_task,payload,created_at,updated_at)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (req.request_id, box, req.sender.dept, req.recipient.dept, req.capability,
                 req.status.value, req.priority.value, req.deadline, req.parent_task,
                 json.dumps(req.to_dict(), ensure_ascii=False), req.created_at, req.updated_at),
            )
            conn.execute(
                "INSERT INTO collab_events (request_id,actor,from_state,to_state,reason,at)"
                " VALUES (?,?,?,?,?,?)",
                (req.request_id, req.sender.dept, None, req.status.value, "created", now),
            )
        return req, True

    def save(self, req: CollabRequest, *, box: str) -> None:
        with self._lock, self._conn() as conn:
            req.updated_at = _now()
            conn.execute(
                "UPDATE collab_requests SET status=?,deadline=?,payload=?,updated_at=?"
                " WHERE request_id=? AND box=?",
                (req.status.value, req.deadline,
                 json.dumps(req.to_dict(), ensure_ascii=False), req.updated_at,
                 req.request_id, box),
            )

    def record_event(
        self, request_id: str, *, actor: str, from_state: str | None,
        to_state: str, reason: str = "",
    ) -> None:
        with self._lock, self._conn() as conn:
            conn.execute(
                "INSERT INTO collab_events (request_id,actor,from_state,to_state,reason,at)"
                " VALUES (?,?,?,?,?,?)",
                (request_id, actor, from_state, to_state, reason, _now()),
            )

    # -- reads -------------------------------------------------------------
    def get(self, request_id: str, *, box: str) -> CollabRequest | None:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT payload FROM collab_requests WHERE request_id=? AND box=?",
                (request_id, box),
            ).fetchone()
        return CollabRequest.from_dict(json.loads(row["payload"])) if row else None

    def list(
        self, *, box: str, status: str | None = None, dept: str | None = None,
        overdue: bool | None = None, limit: int = 100,
    ) -> list[CollabRequest]:
        sql = "SELECT payload FROM collab_requests WHERE box=?"
        args: list[Any] = [box]
        if status:
            sql += " AND status=?"; args.append(status)
        if dept:
            sql += " AND (sender_dept=? OR recipient_dept=?)"; args += [dept, dept]
        sql += " ORDER BY priority ASC, created_at ASC LIMIT ?"; args.append(limit)
        with self._conn() as conn:
            rows = conn.execute(sql, args).fetchall()
        out = [CollabRequest.from_dict(json.loads(r["payload"])) for r in rows]
        if overdue is not None:
            out = [r for r in out if r.is_overdue() == overdue]
        return out

    def events(self, request_id: str) -> list[dict[str, Any]]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT actor,from_state,to_state,reason,at FROM collab_events"
                " WHERE request_id=? ORDER BY id",
                (request_id,),
            ).fetchall()
        return [dict(r) for r in rows]

    def due_for_escalation(self, *, box: str = "inbox") -> list[CollabRequest]:
        """Overdue requests that are not finished.

        Detected on the *recipient* side deliberately: expiry must not depend on
        the requester remembering to chase.
        """
        return [r for r in self.list(box=box, limit=1000) if r.is_overdue()]


__all__ = ["CollabStore"]
