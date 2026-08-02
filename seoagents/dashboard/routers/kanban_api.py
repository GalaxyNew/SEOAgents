"""Kanban bridge API (L2) — seoagents 与 seohm 共用同一份任务卡。

任务卡的唯一真源是 seohm 的 SQLite 看板(``/hermes/kanban.db``,即宿主上的
``/data/hermes-seo/kanban.db``)。seoagents 不另起一套存储,而是直接读写它,
这样两边看到的永远是同一批卡。

写操作用 SQLite 自身的事务与 busy_timeout 与 seohm 的写入并发,不额外造锁;
库不可达时如实返回 503,绝不用空列表冒充"没有任务"。
"""
from __future__ import annotations

import json
import os
import sqlite3
import time
import uuid
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from dojocore.logging import LOGGER

router = APIRouter(prefix="/api/kanban", tags=["kanban"])

KANBAN_DB = os.environ.get("SEOHM_KANBAN_DB", "/hermes/kanban.db")

# seohm 使用的状态集合(取自其代码中的字面量)
OPEN_STATUSES = ("pending", "todo", "in_progress", "running", "review", "blocked")
CLOSED_STATUSES = ("done", "completed", "failed", "cancelled")
ALL_STATUSES = OPEN_STATUSES + CLOSED_STATUSES

_TASK_COLUMNS = (
    "id", "title", "body", "assignee", "status", "priority", "created_by",
    "created_at", "started_at", "completed_at", "project_id", "tenant",
    "result", "current_step_key", "workflow_template_id", "skills",
    "consecutive_failures", "last_failure_error", "session_id",
)


def _connect(readonly: bool = True) -> sqlite3.Connection:
    if not os.path.exists(KANBAN_DB):
        raise HTTPException(
            status_code=503,
            detail=f"seohm 看板不可达: {KANBAN_DB} 不存在(容器未挂载 kanban.db?)",
        )
    try:
        uri = f"file:{KANBAN_DB}?mode={'ro' if readonly else 'rw'}"
        conn = sqlite3.connect(uri, uri=True, timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout=8000")
        return conn
    except sqlite3.Error as exc:
        raise HTTPException(status_code=503, detail=f"看板连接失败: {exc}") from exc


def _row_to_task(r: sqlite3.Row) -> dict[str, Any]:
    d = {k: r[k] for k in r.keys()}
    # 时间统一成秒级时间戳 -> ISO,方便前端直接渲染
    for k in ("created_at", "started_at", "completed_at"):
        v = d.get(k)
        if isinstance(v, int) and v > 0:
            d[f"{k}_iso"] = time.strftime("%Y-%m-%d %H:%M", time.localtime(v))
        else:
            d[f"{k}_iso"] = None
    if isinstance(d.get("skills"), str) and d["skills"]:
        try:
            d["skills"] = json.loads(d["skills"])
        except (json.JSONDecodeError, TypeError):
            pass
    d["is_open"] = (d.get("status") or "") in OPEN_STATUSES
    return d


class TaskCreate(BaseModel):
    title: str = Field(..., min_length=1, description="任务标题")
    body: str = ""
    assignee: str = ""
    status: str = "pending"
    priority: int = 3
    project_id: str = ""
    created_by: str = "seoagents"


class TaskPatch(BaseModel):
    title: str | None = None
    body: str | None = None
    assignee: str | None = None
    status: str | None = None
    priority: int | None = None
    result: str | None = None


@router.get("/board")
def get_board(
    status: str | None = Query(None, description="按状态过滤,逗号分隔"),
    assignee: str | None = Query(None),
    limit: int = Query(200, ge=1, le=1000),
) -> dict[str, Any]:
    """整块看板:任务按状态分组,附带统计。"""
    where, params = [], []
    if status:
        wanted = [s.strip() for s in status.split(",") if s.strip()]
        if wanted:
            where.append(f"status IN ({','.join('?' * len(wanted))})")
            params.extend(wanted)
    if assignee:
        where.append("assignee = ?")
        params.append(assignee)
    sql = f"SELECT {','.join(_TASK_COLUMNS)} FROM tasks"  # noqa: S608 - 列名为常量白名单
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY COALESCE(priority, 99) ASC, created_at DESC LIMIT ?"
    params.append(limit)

    conn = _connect(readonly=True)
    try:
        rows = [_row_to_task(r) for r in conn.execute(sql, params)]
    except sqlite3.Error as exc:
        LOGGER.warning(f"kanban 查询失败: {exc}")
        raise HTTPException(status_code=503, detail=f"看板查询失败: {exc}") from exc
    finally:
        conn.close()

    columns: dict[str, list] = {s: [] for s in ALL_STATUSES}
    for t in rows:
        columns.setdefault(t.get("status") or "pending", []).append(t)
    return {
        "ok": True,
        "source": KANBAN_DB,
        "total": len(rows),
        "open_count": sum(1 for t in rows if t["is_open"]),
        "columns": columns,
        "statuses": {"open": list(OPEN_STATUSES), "closed": list(CLOSED_STATUSES)},
        "items": rows,
    }


@router.get("/tasks/{task_id}")
def get_task(task_id: str) -> dict[str, Any]:
    """单卡详情,含评论、事件、执行记录。"""
    conn = _connect(readonly=True)
    try:
        row = conn.execute(
            f"SELECT {','.join(_TASK_COLUMNS)} FROM tasks WHERE id = ?",  # noqa: S608
            (task_id,),
        ).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail=f"任务卡 {task_id} 不存在")
        task = _row_to_task(row)
        task["comments"] = [dict(r) for r in conn.execute(
            "SELECT id,author,body,created_at FROM task_comments "
            "WHERE task_id=? ORDER BY created_at ASC", (task_id,))]
        task["events"] = [dict(r) for r in conn.execute(
            "SELECT id,kind,payload,created_at FROM task_events "
            "WHERE task_id=? ORDER BY created_at DESC LIMIT 50", (task_id,))]
        task["runs"] = [dict(r) for r in conn.execute(
            "SELECT id,step_key,status,outcome,summary,started_at,ended_at,error "
            "FROM task_runs WHERE task_id=? ORDER BY id DESC LIMIT 20", (task_id,))]
    except sqlite3.Error as exc:
        raise HTTPException(status_code=503, detail=f"看板查询失败: {exc}") from exc
    finally:
        conn.close()
    return {"ok": True, "task": task}


@router.post("/tasks", status_code=201)
def create_task(payload: TaskCreate) -> dict[str, Any]:
    """新建任务卡 —— 直接写进 seohm 的看板,seohm 那边立刻可见。"""
    if payload.status not in ALL_STATUSES:
        raise HTTPException(
            status_code=400,
            detail=f"status 必须是 {list(ALL_STATUSES)} 之一,收到 '{payload.status}'",
        )
    task_id = f"T-{uuid.uuid4().hex[:10]}"
    now = int(time.time())
    conn = _connect(readonly=False)
    try:
        conn.execute(
            "INSERT INTO tasks (id,title,body,assignee,status,priority,created_by,"
            "created_at,project_id) VALUES (?,?,?,?,?,?,?,?,?)",
            (task_id, payload.title, payload.body, payload.assignee, payload.status,
             payload.priority, payload.created_by, now, payload.project_id),
        )
        conn.execute(
            "INSERT INTO task_events (task_id,kind,payload,created_at) VALUES (?,?,?,?)",
            (task_id, "created", json.dumps({"by": payload.created_by}, ensure_ascii=False), now),
        )
        conn.commit()
    except sqlite3.Error as exc:
        conn.rollback()
        raise HTTPException(status_code=503, detail=f"写入看板失败: {exc}") from exc
    finally:
        conn.close()
    LOGGER.info(f"kanban: 新建任务卡 {task_id} — {payload.title}")
    return {"ok": True, "task_id": task_id}


@router.patch("/tasks/{task_id}")
def patch_task(task_id: str, payload: TaskPatch) -> dict[str, Any]:
    """改状态 / 指派 / 优先级,并留下事件轨迹。"""
    fields = {k: v for k, v in payload.model_dump().items() if v is not None}
    if not fields:
        raise HTTPException(status_code=400, detail="没有要修改的字段")
    if "status" in fields and fields["status"] not in ALL_STATUSES:
        raise HTTPException(
            status_code=400,
            detail=f"status 必须是 {list(ALL_STATUSES)} 之一,收到 '{fields['status']}'",
        )
    now = int(time.time())
    if fields.get("status") in ("in_progress", "running"):
        fields.setdefault("started_at", now)
    if fields.get("status") in CLOSED_STATUSES:
        fields.setdefault("completed_at", now)

    conn = _connect(readonly=False)
    try:
        if conn.execute("SELECT 1 FROM tasks WHERE id=?", (task_id,)).fetchone() is None:
            raise HTTPException(status_code=404, detail=f"任务卡 {task_id} 不存在")
        sets = ",".join(f"{k}=?" for k in fields)
        conn.execute(
            f"UPDATE tasks SET {sets} WHERE id=?",  # noqa: S608 - 键来自 pydantic 模型
            (*fields.values(), task_id),
        )
        conn.execute(
            "INSERT INTO task_events (task_id,kind,payload,created_at) VALUES (?,?,?,?)",
            (task_id, "updated", json.dumps(fields, ensure_ascii=False), now),
        )
        conn.commit()
    except sqlite3.Error as exc:
        conn.rollback()
        raise HTTPException(status_code=503, detail=f"更新看板失败: {exc}") from exc
    finally:
        conn.close()
    return {"ok": True, "task_id": task_id, "updated": fields}


@router.post("/tasks/{task_id}/comments", status_code=201)
def add_comment(task_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    body = str(payload.get("body") or "").strip()
    author = str(payload.get("author") or "seoagents").strip()
    if not body:
        raise HTTPException(status_code=400, detail="body 不能为空")
    now = int(time.time())
    conn = _connect(readonly=False)
    try:
        if conn.execute("SELECT 1 FROM tasks WHERE id=?", (task_id,)).fetchone() is None:
            raise HTTPException(status_code=404, detail=f"任务卡 {task_id} 不存在")
        conn.execute(
            "INSERT INTO task_comments (task_id,author,body,created_at) VALUES (?,?,?,?)",
            (task_id, author, body, now),
        )
        conn.commit()
    except sqlite3.Error as exc:
        conn.rollback()
        raise HTTPException(status_code=503, detail=f"写入评论失败: {exc}") from exc
    finally:
        conn.close()
    return {"ok": True, "task_id": task_id}


@router.get("/health")
def kanban_health() -> dict[str, Any]:
    """看板可达性 —— 前端用它决定是显示看板还是显示"未接通"。"""
    if not os.path.exists(KANBAN_DB):
        return {"ok": False, "reachable": False, "path": KANBAN_DB,
                "reason": "kanban.db 未挂载进容器"}
    try:
        conn = _connect(readonly=True)
        n = conn.execute("SELECT COUNT(*) FROM tasks").fetchone()[0]
        conn.close()
        return {"ok": True, "reachable": True, "path": KANBAN_DB, "task_count": n}
    except HTTPException as exc:
        return {"ok": False, "reachable": False, "path": KANBAN_DB, "reason": exc.detail}


__all__ = ["router"]
