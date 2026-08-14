"""Task card persistence — local SQLite, one ledger per department node.

Cards live in the department that owns them; the control tower aggregates by
polling ``/api/v1/taskcards``. That keeps a node runnable when the tower is
down, which is the whole point of the federation.

The full card is stored as JSON in ``payload``; the columns beside it exist
only so the queries the dashboard actually runs (by status, by owner, by
parent) can use an index instead of scanning and re-parsing every row.
"""
from __future__ import annotations

import datetime as _dt
import json
import os
import sqlite3
import threading
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from dojocore.taskcard.models import (
    ACTIVE_STATUSES,
    CardError,
    CardStatus,
    TaskCard,
    new_card_id,
)

__all__ = ["TaskCardStore"]

_SCHEMA = """
CREATE TABLE IF NOT EXISTS task_cards (
    card_id      TEXT PRIMARY KEY,
    dept         TEXT NOT NULL,
    title        TEXT NOT NULL,
    status       TEXT NOT NULL,
    level        TEXT NOT NULL,
    priority     TEXT NOT NULL,
    owner        TEXT,
    parent_card  TEXT,
    collab_req   TEXT,
    github_issue INTEGER,
    deadline     TEXT,
    created_at   TEXT NOT NULL,
    updated_at   TEXT NOT NULL,
    payload      TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_tc_status  ON task_cards(status, updated_at);
CREATE INDEX IF NOT EXISTS idx_tc_owner   ON task_cards(owner, status);
CREATE INDEX IF NOT EXISTS idx_tc_dept    ON task_cards(dept, status);
CREATE INDEX IF NOT EXISTS idx_tc_parent  ON task_cards(parent_card);
CREATE INDEX IF NOT EXISTS idx_tc_collab  ON task_cards(collab_req);
"""


class TaskCardStore:
    def __init__(self, data_dir: str | os.PathLike[str], *, dept: str = "hm") -> None:
        self.dir = Path(os.path.expanduser(str(data_dir)))
        self.dir.mkdir(parents=True, exist_ok=True)
        self.db = self.dir / "taskcards.db"
        self.dept = dept
        self._lock = threading.Lock()
        with self._conn() as conn:
            conn.executescript(_SCHEMA)

    @contextmanager
    def _conn(self) -> Iterator[sqlite3.Connection]:
        """Open, commit, and — crucially — close.

        ``sqlite3.Connection.__exit__`` commits the transaction but leaves the
        connection open. Relying on it leaks one file descriptor per query;
        under a few hundred operations SQLite starts refusing with "unable to
        open database file", which reads like corruption and is not.
        """
        conn = sqlite3.connect(self.db, timeout=15)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    # -- id allocation -----------------------------------------------------
    def next_card_id(self, dept: str | None = None,
                     when: _dt.datetime | None = None) -> str:
        """Allocate the next per-department, per-day sequence.

        Held under the same lock as the insert in :meth:`create`, so two
        concurrent openings cannot be handed the same number.
        """
        dept = dept or self.dept
        day = (when or _dt.datetime.now(_dt.timezone.utc)).strftime("%Y%m%d")
        prefix = new_card_id(dept, 1, when)[:-2]  # T<DEPT><DAY>-
        with self._conn() as conn:
            row = conn.execute(
                "SELECT card_id FROM task_cards WHERE card_id LIKE ?"
                " ORDER BY card_id DESC LIMIT 1",
                (f"{prefix}%",),
            ).fetchone()
        seq = 1
        if row:
            try:
                seq = int(str(row["card_id"]).rsplit("-", 1)[1]) + 1
            except (IndexError, ValueError):  # pragma: no cover - malformed row
                seq = 1
        del day
        return new_card_id(dept, seq, when)

    # -- writes ------------------------------------------------------------
    def put(self, card: TaskCard) -> TaskCard:
        card.validate()
        with self._lock, self._conn() as conn:
            conn.execute(
                "INSERT INTO task_cards (card_id,dept,title,status,level,priority,"
                "owner,parent_card,collab_req,github_issue,deadline,created_at,"
                "updated_at,payload) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)"
                " ON CONFLICT(card_id) DO UPDATE SET"
                " title=excluded.title, status=excluded.status, level=excluded.level,"
                " priority=excluded.priority, owner=excluded.owner,"
                " parent_card=excluded.parent_card, collab_req=excluded.collab_req,"
                " github_issue=excluded.github_issue, deadline=excluded.deadline,"
                " updated_at=excluded.updated_at, payload=excluded.payload",
                (
                    card.card_id, card.dept, card.title, card.status.value,
                    card.level.value, card.priority.value, card.owner,
                    card.parent_card, card.collab_req, card.github_issue,
                    card.deadline, card.created_at, card.updated_at,
                    json.dumps(card.to_dict(), ensure_ascii=False),
                ),
            )
        return card

    def create(self, **kw: Any) -> TaskCard:
        """Open a card with an auto-allocated id."""
        dept = str(kw.pop("dept", self.dept))
        card = TaskCard.create(card_id=self.next_card_id(dept), dept=dept, **kw)
        return self.put(card)

    def delete(self, card_id: str) -> bool:
        with self._lock, self._conn() as conn:
            cur = conn.execute("DELETE FROM task_cards WHERE card_id=?", (card_id,))
            return cur.rowcount > 0

    # -- reads -------------------------------------------------------------
    def get(self, card_id: str) -> TaskCard | None:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT payload FROM task_cards WHERE card_id=?", (card_id,)
            ).fetchone()
        return TaskCard.from_dict(json.loads(row["payload"])) if row else None

    def require(self, card_id: str) -> TaskCard:
        card = self.get(card_id)
        if card is None:
            raise CardError(f"任务卡不存在: {card_id}")
        return card

    def _rows_to_cards(self, rows: Iterable[sqlite3.Row]) -> list[TaskCard]:
        return [TaskCard.from_dict(json.loads(r["payload"])) for r in rows]

    def by_statuses(self, statuses: Iterable[CardStatus | str]) -> list[TaskCard]:
        values = [s.value if isinstance(s, CardStatus) else str(s) for s in statuses]
        if not values:
            return []
        marks = ",".join("?" * len(values))
        with self._conn() as conn:
            rows = conn.execute(
                f"SELECT payload FROM task_cards WHERE status IN ({marks})"
                " ORDER BY updated_at DESC",
                values,
            ).fetchall()
        return self._rows_to_cards(rows)

    def active(self) -> list[TaskCard]:
        return self.by_statuses(ACTIVE_STATUSES)

    def by_owner(self, owner: str, *, active_only: bool = True) -> list[TaskCard]:
        sql = "SELECT payload FROM task_cards WHERE owner=?"
        params: list[Any] = [owner]
        if active_only:
            marks = ",".join("?" * len(ACTIVE_STATUSES))
            sql += f" AND status IN ({marks})"
            params += [s.value for s in ACTIVE_STATUSES]
        sql += " ORDER BY updated_at DESC"
        with self._conn() as conn:
            return self._rows_to_cards(conn.execute(sql, params).fetchall())

    def children(self, parent_card: str) -> list[TaskCard]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT payload FROM task_cards WHERE parent_card=? ORDER BY card_id",
                (parent_card,),
            ).fetchall()
        return self._rows_to_cards(rows)

    def by_collab_req(self, collab_req: str) -> list[TaskCard]:
        """Cards on both sides of a cross-department request."""
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT payload FROM task_cards WHERE collab_req=? ORDER BY card_id",
                (collab_req,),
            ).fetchall()
        return self._rows_to_cards(rows)

    def recent(self, limit: int = 50) -> list[TaskCard]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT payload FROM task_cards ORDER BY updated_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return self._rows_to_cards(rows)

    def stalled(self, hours: float = 2.0,
                now: _dt.datetime | None = None) -> list[TaskCard]:
        """Active cards with no evidence line for ``hours``.

        The staleness signal the pulse inspection runs on: not "is it late"
        but "has anything happened".
        """
        cutoff = (now or _dt.datetime.now(_dt.timezone.utc)) - _dt.timedelta(hours=hours)
        marks = ",".join("?" * len(ACTIVE_STATUSES))
        with self._conn() as conn:
            rows = conn.execute(
                f"SELECT payload FROM task_cards WHERE status IN ({marks})"
                " AND updated_at < ? ORDER BY updated_at",
                [s.value for s in ACTIVE_STATUSES] + [cutoff.isoformat()],
            ).fetchall()
        return self._rows_to_cards(rows)

    def counts_by_status(self) -> dict[str, int]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT status, COUNT(*) c FROM task_cards GROUP BY status"
            ).fetchall()
        return {str(r["status"]): int(r["c"]) for r in rows}
