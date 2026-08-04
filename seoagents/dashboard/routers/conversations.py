"""对话记录与归档 (L2)。

在此之前对话只活在浏览器内存里:刷新一次就没了,换台设备也看不到。
这一层把它落到 SQLite。

几个刻意的决定:

* **按用户隔离**。鉴权系统已经有用户名了,对话就该跟着人走 —— 否则多人共用
  时会互相看到对方问过什么。
* **归档不是删除**。归档只是从默认列表里挪走,数据还在、还能翻出来;删除才是
  真删。把两者做成同一个按钮,总有人会在想「收起来」的时候把东西弄丢。
* **trace 一起存**。回看旧对话时,「hm 当时调了哪些工具、拿到什么」比它最后
  那段话更有价值。只存结论等于把推理过程扔了。
* **标题自动取首条提问**,但可以改。让人给每次提问起标题,结果就是没人起。
"""
from __future__ import annotations

import datetime as _dt
import json
import os
import sqlite3
import threading
import uuid
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

_lock = threading.Lock()


def _db_path() -> str:
    # 惰性解析:模块级常量会在 import 那刻定死,之后改环境变量不生效
    return os.environ.get(
        "SEOAGENTS_CONVERSATIONS_DB",
        "/data/seo-stack/seoagents-data/conversations.db",
    )


_SCHEMA = """
CREATE TABLE IF NOT EXISTS conversations (
    id          TEXT PRIMARY KEY,
    owner       TEXT NOT NULL,
    title       TEXT NOT NULL,
    archived    INTEGER NOT NULL DEFAULT 0,
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_conv_owner ON conversations(owner, archived, updated_at DESC);

CREATE TABLE IF NOT EXISTS messages (
    id          TEXT PRIMARY KEY,
    conv_id     TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    sender      TEXT NOT NULL CHECK (sender IN ('user','agent')),
    text        TEXT NOT NULL,
    turns       INTEGER,
    elapsed     REAL,
    trace_json  TEXT NOT NULL DEFAULT '[]',
    ts          TEXT NOT NULL,
    seq         INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_msg_conv ON messages(conv_id, seq);
"""


def _conn() -> sqlite3.Connection:
    os.makedirs(os.path.dirname(_db_path()), exist_ok=True)
    c = sqlite3.connect(_db_path(), timeout=15)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA foreign_keys=ON")
    c.executescript(_SCHEMA)
    return c


def _now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).isoformat()


def _owner(request: Request) -> str:
    """当前登录用户。中间件已经放行的请求一定有它。"""
    return getattr(request.state, "user", None) or "unknown"


def _title_from(text: str, limit: int = 28) -> str:
    t = " ".join(text.strip().split())
    return (t[:limit] + "…") if len(t) > limit else (t or "新对话")


router = APIRouter(prefix="/api/conversations", tags=["conversations"])


@router.get("")
def list_conversations(request: Request, archived: bool = False,
                       limit: int = 100) -> dict[str, Any]:
    with _conn() as c:
        rows = [dict(r) for r in c.execute(
            "SELECT c.*, "
            " (SELECT COUNT(*) FROM messages m WHERE m.conv_id = c.id) AS message_count,"
            " (SELECT m.text FROM messages m WHERE m.conv_id = c.id"
            "  ORDER BY m.seq DESC LIMIT 1) AS last_text"
            " FROM conversations c WHERE c.owner = ? AND c.archived = ?"
            " ORDER BY c.updated_at DESC LIMIT ?",
            (_owner(request), 1 if archived else 0, limit),
        )]
        total_archived = c.execute(
            "SELECT COUNT(*) FROM conversations WHERE owner = ? AND archived = 1",
            (_owner(request),),
        ).fetchone()[0]
    for r in rows:
        r["archived"] = bool(r["archived"])
        r["last_text"] = (r.get("last_text") or "")[:80]
    return {"conversations": rows, "total": len(rows), "archived_count": total_archived}


class NewConv(BaseModel):
    title: str = ""


@router.post("")
def create_conversation(body: NewConv, request: Request) -> dict[str, Any]:
    cid = uuid.uuid4().hex[:16]
    now = _now()
    with _lock, _conn() as c:
        c.execute(
            "INSERT INTO conversations (id,owner,title,archived,created_at,updated_at)"
            " VALUES (?,?,?,0,?,?)",
            (cid, _owner(request), body.title.strip() or "新对话", now, now),
        )
    return {"ok": True, "id": cid, "title": body.title.strip() or "新对话",
            "created_at": now}


@router.get("/{cid}")
def get_conversation(cid: str, request: Request) -> dict[str, Any]:
    with _conn() as c:
        conv = c.execute(
            "SELECT * FROM conversations WHERE id = ? AND owner = ?",
            (cid, _owner(request)),
        ).fetchone()
        if not conv:
            raise HTTPException(404, "对话不存在")
        msgs = []
        for m in c.execute(
            "SELECT * FROM messages WHERE conv_id = ? ORDER BY seq", (cid,)
        ):
            d = dict(m)
            try:
                d["trace"] = json.loads(d.pop("trace_json") or "[]")
            except json.JSONDecodeError:
                d["trace"] = []
            msgs.append(d)
    out = dict(conv)
    out["archived"] = bool(out["archived"])
    out["messages"] = msgs
    return out


class MsgIn(BaseModel):
    sender: str
    text: str
    turns: int | None = None
    elapsed: float | None = None
    trace: list[dict[str, Any]] = []


@router.post("/{cid}/messages")
def append_message(cid: str, body: MsgIn, request: Request) -> dict[str, Any]:
    """追加一条消息。首条用户提问顺便把标题定下来。"""
    if body.sender not in ("user", "agent"):
        raise HTTPException(422, "sender 必须是 user 或 agent")
    owner = _owner(request)
    now = _now()
    with _lock, _conn() as c:
        conv = c.execute(
            "SELECT title FROM conversations WHERE id = ? AND owner = ?", (cid, owner)
        ).fetchone()
        if not conv:
            raise HTTPException(404, "对话不存在")
        seq = (c.execute(
            "SELECT COALESCE(MAX(seq),0) FROM messages WHERE conv_id = ?", (cid,)
        ).fetchone()[0]) + 1
        c.execute(
            "INSERT INTO messages (id,conv_id,sender,text,turns,elapsed,trace_json,ts,seq)"
            " VALUES (?,?,?,?,?,?,?,?,?)",
            (uuid.uuid4().hex[:16], cid, body.sender, body.text, body.turns,
             body.elapsed, json.dumps(body.trace, ensure_ascii=False), now, seq),
        )
        # 标题还是默认值时,用第一条提问顶上
        if body.sender == "user" and conv["title"] in ("新对话", ""):
            c.execute("UPDATE conversations SET title = ?, updated_at = ? WHERE id = ?",
                      (_title_from(body.text), now, cid))
        else:
            c.execute("UPDATE conversations SET updated_at = ? WHERE id = ?", (now, cid))
    return {"ok": True, "seq": seq}


class PatchConv(BaseModel):
    title: str | None = None
    archived: bool | None = None


@router.patch("/{cid}")
def patch_conversation(cid: str, body: PatchConv, request: Request) -> dict[str, Any]:
    sets, args = [], []
    if body.title is not None:
        sets.append("title = ?")
        args.append(body.title.strip() or "新对话")
    if body.archived is not None:
        sets.append("archived = ?")
        args.append(1 if body.archived else 0)
    if not sets:
        raise HTTPException(422, "没有要改的字段")
    sets.append("updated_at = ?")
    args += [_now(), cid, _owner(request)]
    with _lock, _conn() as c:
        cur = c.execute(
            f"UPDATE conversations SET {', '.join(sets)} WHERE id = ? AND owner = ?",  # noqa: S608
            args,
        )
        if not cur.rowcount:
            raise HTTPException(404, "对话不存在")
    return {"ok": True, "id": cid}


@router.delete("/{cid}")
def delete_conversation(cid: str, request: Request) -> dict[str, Any]:
    """真删。想留着就用归档(PATCH archived=true)。"""
    with _lock, _conn() as c:
        c.execute("DELETE FROM messages WHERE conv_id = ?", (cid,))
        cur = c.execute("DELETE FROM conversations WHERE id = ? AND owner = ?",
                        (cid, _owner(request)))
        if not cur.rowcount:
            raise HTTPException(404, "对话不存在")
    return {"ok": True, "id": cid}


__all__ = ["router"]
