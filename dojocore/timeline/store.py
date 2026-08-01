"""Timeline persistence — local SQLite, one timeline per agent."""
from __future__ import annotations

import datetime as _dt
import json
import os
import sqlite3
import threading
from collections.abc import Iterable
from pathlib import Path

from dojocore.timeline.models import NodeState, TimelineNode

__all__ = ["TimelineStore"]

_SCHEMA = """
CREATE TABLE IF NOT EXISTS timeline_nodes (
    node_id      TEXT PRIMARY KEY,
    owner        TEXT NOT NULL,
    scheduled_at TEXT NOT NULL,
    kind         TEXT NOT NULL,
    state        TEXT NOT NULL,
    subject_ref  TEXT,
    parent_node  TEXT,
    payload      TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_tl_due   ON timeline_nodes(state, scheduled_at);
CREATE INDEX IF NOT EXISTS idx_tl_subj  ON timeline_nodes(subject_ref);
CREATE INDEX IF NOT EXISTS idx_tl_owner ON timeline_nodes(owner, scheduled_at);
"""


class TimelineStore:
    def __init__(self, data_dir: str | os.PathLike[str], *, owner: str = "hm") -> None:
        self.dir = Path(os.path.expanduser(str(data_dir)))
        self.dir.mkdir(parents=True, exist_ok=True)
        self.db = self.dir / "timeline.db"
        self.owner = owner
        self._lock = threading.Lock()
        with self._conn() as conn:
            conn.executescript(_SCHEMA)

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db, timeout=15)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def put(self, node: TimelineNode) -> TimelineNode:
        node.validate()
        with self._lock, self._conn() as conn:
            conn.execute(
                "INSERT INTO timeline_nodes (node_id,owner,scheduled_at,kind,state,"
                "subject_ref,parent_node,payload) VALUES (?,?,?,?,?,?,?,?)"
                " ON CONFLICT(node_id) DO UPDATE SET state=excluded.state,"
                " scheduled_at=excluded.scheduled_at, payload=excluded.payload",
                (node.node_id, self.owner, node.scheduled_at, node.kind.value,
                 node.state.value, node.subject_ref, node.parent_node,
                 json.dumps(node.to_dict(), ensure_ascii=False)),
            )
        return node

    def get(self, node_id: str) -> TimelineNode | None:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT payload FROM timeline_nodes WHERE node_id=?", (node_id,)
            ).fetchone()
        return TimelineNode.from_dict(json.loads(row["payload"])) if row else None

    def by_states(self, states: Iterable[NodeState | str]) -> list[TimelineNode]:
        values = [s.value if isinstance(s, NodeState) else str(s) for s in states]
        if not values:
            return []
        marks = ",".join("?" * len(values))
        with self._conn() as conn:
            rows = conn.execute(
                f"SELECT payload FROM timeline_nodes WHERE state IN ({marks})"
                " ORDER BY scheduled_at",
                values,
            ).fetchall()
        return [TimelineNode.from_dict(json.loads(r["payload"])) for r in rows]

    def between(self, start: _dt.datetime, end: _dt.datetime) -> list[TimelineNode]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT payload FROM timeline_nodes WHERE scheduled_at >= ? AND scheduled_at <= ?"
                " ORDER BY scheduled_at",
                (start.isoformat(), end.isoformat()),
            ).fetchall()
        return [TimelineNode.from_dict(json.loads(r["payload"])) for r in rows]

    def for_subject(self, subject_ref: str) -> list[TimelineNode]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT payload FROM timeline_nodes WHERE subject_ref=? ORDER BY scheduled_at",
                (subject_ref,),
            ).fetchall()
        return [TimelineNode.from_dict(json.loads(r["payload"])) for r in rows]

    def count_on_day(self, day: _dt.date) -> int:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT COUNT(*) c FROM timeline_nodes WHERE substr(scheduled_at,1,10)=?"
                " AND state NOT IN ('CANCELLED','DISCARDED')",
                (day.isoformat(),),
            ).fetchone()
        return int(row["c"])

    def recent(self, limit: int = 100) -> list[TimelineNode]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT payload FROM timeline_nodes ORDER BY scheduled_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [TimelineNode.from_dict(json.loads(r["payload"])) for r in rows]
