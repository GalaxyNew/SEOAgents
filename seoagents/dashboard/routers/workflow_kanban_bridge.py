"""工作流 → Kanban 下发桥 (L2)。

三层的关系:

    工作流   编排层  —— 用户搭「这件事要经过哪些步骤」
      ↓ 下发
    Kanban  执行层  —— 唯一有 worker 的一层,真正把活干掉
      ↕ 回写
    collab  交接层  —— 跨部门节点在这里变成工单,对方收到后落进对方自己的 kanban

一个工作流实例下发后,每个节点变成一张 kanban 卡。卡跑完了状态回写到
工作流节点,工作流据此解锁下游节点。三层不再各存各的。

关联靠 kanban tasks 表原有的两个字段,不额外建表:
  * ``workflow_template_id`` 存工作流实例 ID
  * ``current_step_key``     存节点 ID

依赖关系不写进卡:kanban 的 worker 不认识 DAG。改由本模块按工作流的
``ready_nodes`` 分批下发 —— 只有依赖满足的节点才会出现在看板上,
避免 worker 抢到一张前置没完成的卡。
"""
from __future__ import annotations

import json
import sqlite3
import time
import uuid
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from dojocore.logging import LOGGER
from dojocore.workflow.engine import WorkflowEngine
from seoagents.dashboard.routers.kanban_api import KANBAN_DB, _connect

router = APIRouter(prefix="/api/workflows", tags=["workflow-kanban"])

# 节点类型 → 卡的优先级。人工闸门最高:它卡着整条链,且只有人能推。
_PRIORITY = {"human_gate": 1, "dept_request": 2, "agent_task": 3, "tool_call": 3}

# kanban 卡状态 → 工作流节点该走哪个动作
_CARD_TO_NODE = {
    "in_progress": "begin",
    "running": "begin",
    "done": "complete",
    "completed": "complete",
    "failed": "fail",
    "cancelled": "fail",
}


def _wf_store():
    # 复用 workflow_api 用的那个单例,别自己 new —— 两个 WorkflowStore
    # 会各开一份 SQLite 连接,写实例状态时互相看不见对方的未提交事务。
    from dojocore.workflow import get_workflow_store

    try:
        return get_workflow_store()
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=503, detail=f"工作流存储不可用: {exc}") from exc


def _load_instance(instance_id: str):
    store = _wf_store()
    inst = store.instance(instance_id)
    if inst is None:
        raise HTTPException(status_code=404, detail=f"工作流实例 {instance_id} 不存在")
    tpl = store.template_for_instance(inst)
    if tpl is None:
        raise HTTPException(status_code=409, detail=f"实例 {instance_id} 的模板快照不可用")
    return store, inst, tpl, WorkflowEngine(tpl)


class DispatchBody(BaseModel):
    assignee: str = "hm"
    only_ready: bool = True   # 只下发依赖已满足的节点
    dry_run: bool = False


@router.post("/instances/{instance_id}/dispatch")
def dispatch_to_kanban(instance_id: str, body: DispatchBody) -> dict[str, Any]:
    """把工作流实例的可执行节点下发成 kanban 卡。

    幂等:已经下发过的节点(同 instance + node 已有卡)不会重复建卡。
    """
    store, inst, tpl, engine = _load_instance(instance_id)
    engine.refresh(inst)

    nodes = engine.ready_nodes(inst) if body.only_ready else list(tpl.nodes)
    if not nodes:
        return {
            "ok": True, "instance_id": instance_id, "created": [], "skipped": [],
            "note": "当前没有依赖已满足的节点 —— 要么全在跑,要么被前置卡住",
        }

    conn = _connect(readonly=False)
    created, skipped = [], []
    try:
        for node in nodes:
            node_id = getattr(node, "id", None) or getattr(node, "node_id", "")
            exists = conn.execute(
                "SELECT id FROM tasks WHERE workflow_template_id=? AND current_step_key=?",
                (instance_id, node_id),
            ).fetchone()
            if exists:
                skipped.append({"node": node_id, "reason": "已下发", "task_id": exists[0]})
                continue

            ntype = getattr(getattr(node, "type", None), "value", str(getattr(node, "type", "")))
            label = getattr(node, "label", "") or node_id
            cfg = dict(getattr(node, "config", {}) or {})
            acceptance = list(getattr(node, "acceptance", []) or [])

            body_lines = [
                f"来自工作流:{tpl.name}({instance_id})",
                f"节点:{node_id} · 类型 {ntype}",
            ]
            if ntype == "agent_task" and cfg.get("instruction"):
                body_lines += ["", "指令:", str(cfg["instruction"])]
            elif ntype == "tool_call" and cfg.get("tool"):
                body_lines += ["", f"调用工具:{cfg['tool']}", f"参数:{json.dumps(cfg.get('arguments', {}), ensure_ascii=False)}"]
            elif ntype == "dept_request":
                body_lines += ["", f"⚠️ 跨部门:需向 {cfg.get('dept')} 请求 {cfg.get('capability')}",
                               "这张卡完成前应先发出 collab 工单并拿到交付"]
            elif ntype == "human_gate":
                body_lines += ["", f"🚦 人工审批:{cfg.get('prompt', '')}",
                               "agent 不得自行通过这张卡"]
            if acceptance:
                body_lines += ["", "验收标准(逐条勾):"] + [f"  [ ] {a}" for a in acceptance]

            task_id = f"T-{uuid.uuid4().hex[:10]}"
            now = int(time.time())
            if body.dry_run:
                created.append({"node": node_id, "task_id": "(dry-run)", "title": label})
                continue

            conn.execute(
                "INSERT INTO tasks (id,title,body,assignee,status,priority,created_by,"
                "created_at,project_id,workflow_template_id,current_step_key)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (task_id, f"[{tpl.name}] {label}", "\n".join(body_lines),
                 body.assignee, "pending", _PRIORITY.get(ntype, 3), "workflow",
                 now, instance_id, instance_id, node_id),
            )
            conn.execute(
                "INSERT INTO task_events (task_id,kind,payload,created_at) VALUES (?,?,?,?)",
                (task_id, "workflow_dispatch",
                 json.dumps({"instance": instance_id, "node": node_id, "type": ntype},
                            ensure_ascii=False), now),
            )
            created.append({"node": node_id, "task_id": task_id, "title": label, "type": ntype})
        if not body.dry_run:
            conn.commit()
    except sqlite3.Error as exc:
        conn.rollback()
        raise HTTPException(status_code=503, detail=f"下发失败: {exc}") from exc
    finally:
        conn.close()

    LOGGER.info(f"工作流 {instance_id} 下发 {len(created)} 张卡,跳过 {len(skipped)}")
    return {
        "ok": True, "instance_id": instance_id, "template": tpl.name,
        "created": created, "skipped": skipped, "kanban": KANBAN_DB,
    }


@router.get("/instances/{instance_id}/cards")
def instance_cards(instance_id: str) -> dict[str, Any]:
    """这个实例已经下发出去的卡,以及它们现在什么状态。"""
    conn = _connect(readonly=True)
    try:
        rows = conn.execute(
            "SELECT id,title,status,assignee,current_step_key,created_at,completed_at"
            " FROM tasks WHERE workflow_template_id=? ORDER BY priority, created_at",
            (instance_id,),
        ).fetchall()
    finally:
        conn.close()
    cards = [dict(r) for r in rows]
    return {
        "ok": True, "instance_id": instance_id, "total": len(cards),
        "cards": cards,
        "done": sum(1 for c in cards if c["status"] in ("done", "completed")),
    }


@router.post("/instances/{instance_id}/sync")
def sync_from_kanban(instance_id: str) -> dict[str, Any]:
    """把卡的状态回写到工作流节点,让引擎解锁下游。

    只回写 kanban 侧已经settled 的卡。完成时按节点的验收标准全勾 ——
    真正的逐条勾在卡的 body 里由执行者确认,这里不替他判断,
    只把「卡被标记为完成」这个事实带回工作流。
    """
    store, inst, tpl, engine = _load_instance(instance_id)
    conn = _connect(readonly=True)
    try:
        rows = conn.execute(
            "SELECT id,status,current_step_key,result FROM tasks WHERE workflow_template_id=?",
            (instance_id,),
        ).fetchall()
    finally:
        conn.close()

    applied, ignored = [], []
    for r in rows:
        node_id = r["current_step_key"]
        action = _CARD_TO_NODE.get((r["status"] or "").lower())
        if not node_id or not action:
            ignored.append({"task": r["id"], "reason": f"状态 {r['status']} 无需回写"})
            continue
        run = inst.runs.get(node_id)
        if run is None:
            ignored.append({"task": r["id"], "reason": f"节点 {node_id} 不在实例里"})
            continue
        if run.state.settled:
            ignored.append({"task": r["id"], "reason": f"节点已终态 {run.state.value}"})
            continue
        try:
            node = tpl.node(node_id)
            if action == "begin":
                if run.state.value != "RUNNING":
                    engine.begin(inst, node_id)
                    applied.append({"node": node_id, "action": "begin"})
            elif action == "complete":
                if run.state.value != "RUNNING":
                    engine.begin(inst, node_id)
                engine.complete(
                    inst, node_id,
                    acceptance_met=[True] * len(getattr(node, "acceptance", []) or []),
                    evidence=f"kanban 卡 {r['id']} 标记完成" + (f":{r['result']}" if r["result"] else ""),
                    actor="kanban",
                )
                applied.append({"node": node_id, "action": "complete"})
            elif action == "fail":
                if run.state.value != "RUNNING":
                    engine.begin(inst, node_id)
                engine.fail(inst, node_id, error=f"kanban 卡 {r['id']} 状态 {r['status']}")
                applied.append({"node": node_id, "action": "fail"})
        except Exception as exc:  # noqa: BLE001 - 单个节点失败不该让整次同步崩掉
            ignored.append({"task": r["id"], "reason": f"{type(exc).__name__}: {exc}"})

    engine.refresh(inst)
    store.save_instance(inst)
    return {
        "ok": True, "instance_id": instance_id,
        "applied": applied, "ignored": ignored,
        "instance_status": inst.status.value,
        "next_ready": [getattr(n, "id", "") for n in engine.ready_nodes(inst)],
    }


__all__ = ["router"]
