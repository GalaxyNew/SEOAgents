"""Timeline ↔ Hermes Cron control-plane adapter.

Timeline owns intent, dependencies, and human/agent planning metadata. Hermes
Cron is the only clock and execution mechanism.  Creating a Timeline schedule
therefore creates the Hermes job first and persists its id in the Timeline node;
there is no second due-node runner.
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from dojocore.timeline import NodeState, TimelineError, get_timeline
from dojocore.workflow import get_workflow_store

router = APIRouter(prefix="/api/timeline", tags=["timeline-cron"])


class CreateScheduleBody(BaseModel):
    scheduled_at: str
    schedule: str = ""  # empty => scheduled_at one-shot; otherwise Hermes interval/cron/ISO
    kind: str = "START"
    intent: str
    subject_ref: str = ""
    expected_minutes: int = 15
    on_miss: str = "ask"
    parent_node: str = ""
    priority: str = "P1"
    task_type: str  # agent_prompt | workflow
    prompt: str = ""
    workflow_id: str = ""
    workflow_version: str = ""
    parameters: dict[str, Any] = Field(default_factory=dict)
    deliver: str = "local"
    skills: list[str] = Field(default_factory=list)
    enabled_toolsets: list[str] = Field(default_factory=list)
    approval_required: bool = False
    allow_conflict: bool = False
    created_by: str = "user"


class UpdateScheduleBody(BaseModel):
    intent: str | None = None
    schedule: str | None = None
    prompt: str | None = None
    deliver: str | None = None
    expected_minutes: int | None = None
    priority: str | None = None


class TriageBody(BaseModel):
    decisions: list[dict[str, Any]] = Field(default_factory=list)


def _svc():
    try:
        return get_timeline()
    except Exception as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


def _hermes_url() -> str:
    return os.environ.get("HERMES_API_URL", "http://172.19.0.1:8642").rstrip("/")


def _hermes_key() -> str:
    key = os.environ.get("HERMES_API_KEY", "").strip()
    if not key:
        raise HTTPException(status_code=503, detail="HERMES_API_KEY 未配置")
    return key


def _hermes(method: str, path: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
    data = json.dumps(body, ensure_ascii=False).encode() if body is not None else None
    req = urllib.request.Request(
        _hermes_url() + path,
        data=data,
        method=method,
        headers={
            "Authorization": f"Bearer {_hermes_key()}",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            detail = json.loads(raw).get("error") or json.loads(raw).get("detail") or raw
        except Exception:
            detail = raw or str(exc)
        raise HTTPException(status_code=exc.code, detail=f"Hermes Cron: {detail}") from exc
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Hermes Cron 不可达: {exc}") from exc


def _workflow_prompt(body: CreateScheduleBody, *, node_id_hint: str = "") -> str:
    store = get_workflow_store()
    tpl = store.template(body.workflow_id)
    if tpl is None:
        raise HTTPException(status_code=404, detail=f"工作流不存在: {body.workflow_id}")
    if body.workflow_version and tpl.version != body.workflow_version:
        raise HTTPException(
            status_code=409,
            detail=f"工作流版本不一致: 请求 {body.workflow_version}, 当前 {tpl.version}",
        )
    return (
        "执行 SEOAgents 已保存工作流。先调用 platform_ops.workflow_detail 读取并核对模板，"
        "再调用 platform_ops.workflow_start 显式创建并启动固定版本实例；该调用必须返回真实"
        "runtime.created run_id。随后仅观察/回写验收，不得另行手工 begin READY 节点。"
        "每个节点必须满足 acceptance 并写入证据/asset_id 后才能完成。遇到 human_gate、"
        "对外发送、付费、发布、品牌承诺、安装或凭证操作，停止并明确等待具名审批。"
        "不要启用 Auditor/Writer/Linker 独立 LLM 编排，所有判断由当前 Hermes 完成。\n\n"
        f"Timeline node: {node_id_hint or '(创建后绑定)'}\n"
        f"Workflow: {tpl.id}\nVersion: {tpl.version}\nTitle: {body.intent}\n"
        f"Parameters: {json.dumps(body.parameters, ensure_ascii=False)}\n\n"
        "最终响应的最后一段必须包含且只包含一个状态标记：\n"
        "WORKFLOW_STATUS: DONE（全部验收完成）\n"
        "WORKFLOW_STATUS: BLOCKED_APPROVAL（停在人工审批）\n"
        "WORKFLOW_STATUS: BLOCKED_DEPENDENCY（等待外部依赖）\n"
        "WORKFLOW_STATUS: FAILED（执行失败）"
    )


def _job_prompt(body: CreateScheduleBody) -> str:
    if body.task_type == "agent_prompt":
        if not body.prompt.strip():
            raise HTTPException(status_code=422, detail="Agent 任务必须填写 prompt")
        return body.prompt.strip()
    if body.task_type == "workflow":
        if not body.workflow_id.strip():
            raise HTTPException(status_code=422, detail="工作流任务必须选择 workflow_id")
        return _workflow_prompt(body)
    raise HTTPException(status_code=422, detail="task_type 只能是 agent_prompt 或 workflow")


def _job_id(node) -> str:
    return str(dict(node.context).get("hermes_job_id") or "")


def _cron_state(job: dict[str, Any]) -> str:
    latest = job.get("latest_execution") or {}
    estatus = str(latest.get("status") or "")
    if estatus in {"claimed", "running"}:
        return "RUNNING"
    if estatus == "failed":
        return "FAILED"
    if estatus == "unknown":
        return "UNKNOWN"
    if not job.get("enabled", True) or job.get("state") == "paused":
        return "PAUSED"
    if job.get("last_status") == "ok" and job.get("schedule", {}).get("kind") == "once":
        return "COMPLETED"
    return "SCHEDULED"


def _workflow_result_state(output: str) -> str:
    text = output.upper()
    if "WORKFLOW_STATUS: BLOCKED_APPROVAL" in text:
        return "BLOCKED_APPROVAL"
    if "WORKFLOW_STATUS: BLOCKED_DEPENDENCY" in text:
        return "BLOCKED_DEPENDENCY"
    if "WORKFLOW_STATUS: FAILED" in text:
        return "FAILED"
    if "WORKFLOW_STATUS: DONE" in text:
        return "COMPLETED"
    return ""


def _project(node, jobs: dict[str, dict[str, Any]]) -> dict[str, Any]:
    data = node.to_dict()
    jid = _job_id(node)
    job = jobs.get(jid)
    if jid and job:
        runtime_state = _cron_state(job)
        # Mirror durable execution facts into Timeline history. This is a
        # projection only; Cron remains the authority and no work is fired here.
        try:
            if runtime_state == "RUNNING" and node.state is NodeState.SCHEDULED:
                node = _svc().sync_from_cron(node.node_id, runtime_state="RUNNING")
            elif runtime_state == "FAILED" and node.state not in {NodeState.UNACKED, NodeState.ACKED}:
                node = _svc().sync_from_cron(
                    node.node_id, runtime_state="FAILED",
                    error=str(job.get("last_error") or (job.get("latest_execution") or {}).get("error") or ""),
                )
            elif runtime_state == "UNKNOWN" and node.state is not NodeState.UNACKED:
                node = _svc().sync_from_cron(node.node_id, runtime_state="UNKNOWN")
            if runtime_state == "COMPLETED" and node.state is not NodeState.ACKED:
                output = ""
                try:
                    output = str(_hermes("GET", f"/api/jobs/{jid}/output").get("output") or "")
                except Exception:
                    output = ""
                semantic_state = _workflow_result_state(output)
                if dict(node.context).get("task_type") == "workflow" and not semantic_state:
                    ctx = dict(node.context)
                    ctx["blocked_state"] = "AWAITING_ACCEPTANCE"
                    node.context = ctx
                    node.outcome = output or "Hermes process completed without workflow acceptance marker"
                    _svc().store.put(node)
                    runtime_state = "AWAITING_ACCEPTANCE"
                elif semantic_state in {"BLOCKED_APPROVAL", "BLOCKED_DEPENDENCY"}:
                    ctx = dict(node.context); ctx["blocked_state"] = semantic_state
                    node.context = ctx; node.outcome = output; _svc().store.put(node)
                    runtime_state = semantic_state
                elif semantic_state == "FAILED":
                    node = _svc().sync_from_cron(
                        node.node_id, runtime_state="FAILED", error=output,
                    )
                    runtime_state = "FAILED"
                else:
                    node = _svc().sync_from_cron(
                        node.node_id, runtime_state="COMPLETED",
                        outcome=output or f"Hermes Cron 完成 · {job.get('last_run_at') or ''}",
                    )
            data = node.to_dict()
        except Exception:
            pass
        data["cron"] = {
            "job_id": jid,
            "name": job.get("name"),
            "schedule": job.get("schedule"),
            "schedule_display": job.get("schedule_display"),
            "next_run_at": job.get("next_run_at"),
            "last_run_at": job.get("last_run_at"),
            "last_status": job.get("last_status"),
            "last_error": job.get("last_error"),
            "enabled": job.get("enabled"),
            "execution": job.get("latest_execution"),
        }
        data["runtime_state"] = runtime_state
    elif jid:
        # One-shot jobs are auto-removed after execution. Consult the durable
        # execution/output history before calling the Timeline binding orphaned.
        try:
            hist = _hermes("GET", f"/api/jobs/{jid}/output")
        except Exception:
            hist = {}
        execution = hist.get("execution") or {}
        status = str(execution.get("status") or "")
        if status == "completed":
            output_text = str(hist.get("output") or "")
            semantic_state = _workflow_result_state(output_text)
            if semantic_state in {"BLOCKED_APPROVAL", "BLOCKED_DEPENDENCY"}:
                # The Cron execution succeeded, but the business workflow is
                # intentionally waiting. Do not lie by marking it completed.
                try:
                    ctx = dict(node.context); ctx["blocked_state"] = semantic_state
                    node.context = ctx; node.outcome = output_text; _svc().store.put(node)
                    data = node.to_dict()
                except Exception:
                    pass
                data["runtime_state"] = semantic_state
            elif semantic_state == "FAILED":
                try:
                    node = _svc().sync_from_cron(
                        node.node_id, runtime_state="FAILED", error=output_text,
                    ); data = node.to_dict()
                except Exception:
                    pass
                data["runtime_state"] = "FAILED"
            elif dict(node.context).get("task_type") == "workflow" and not semantic_state:
                try:
                    ctx = dict(node.context); ctx["blocked_state"] = "AWAITING_ACCEPTANCE"
                    node.context = ctx
                    node.outcome = output_text or "Hermes process completed without workflow acceptance marker"
                    _svc().store.put(node); data = node.to_dict()
                except Exception:
                    pass
                data["runtime_state"] = "AWAITING_ACCEPTANCE"
            else:
                try:
                    node = _svc().sync_from_cron(
                        node.node_id, runtime_state="COMPLETED",
                        outcome=output_text or "Hermes Cron 执行完成",
                    )
                    data = node.to_dict()
                except Exception:
                    pass
                data["runtime_state"] = "COMPLETED"
        elif status in {"failed", "unknown"}:
            try:
                node = _svc().sync_from_cron(
                    node.node_id, runtime_state=status.upper(),
                    error=str(execution.get("error") or ""),
                )
                data = node.to_dict()
            except Exception:
                pass
            data["runtime_state"] = status.upper()
        else:
            data["runtime_state"] = "ORPHANED"
        data["cron"] = {
            "job_id": jid,
            "missing": True,
            "execution": execution or None,
            "output": hist.get("output") or "",
        }
    else:
        ctx = dict(node.context)
        data["runtime_state"] = str(ctx.get("runtime_state") or "LEGACY")
        if ctx.get("hermes_run_id"):
            data["run"] = {
                "run_id": ctx.get("hermes_run_id"),
                "scheduler": ctx.get("scheduler"),
            }
    return data


def _all_jobs() -> dict[str, dict[str, Any]]:
    payload = _hermes("GET", "/api/jobs?include_disabled=true")
    return {str(j["id"]): j for j in payload.get("jobs", [])}


@router.get("/cron-jobs")
async def cron_jobs() -> dict[str, Any]:
    jobs = list(_all_jobs().values())
    return {"total": len(jobs), "jobs": jobs}


@router.get("/agenda-v2")
async def agenda_v2(hours_ahead: int = Query(24, le=720)) -> dict[str, Any]:
    agenda = _svc().agenda(hours_ahead=hours_ahead)
    jobs = _all_jobs()
    # Keep only nodes inside the requested horizon and project live Cron state.
    import datetime as dt
    now = dt.datetime.now(dt.timezone.utc)
    end = now + dt.timedelta(hours=hours_ahead)
    agenda["upcoming"] = [_project(n, jobs) for n in _svc().store.between(now, end)
                          if n.state is NodeState.SCHEDULED]
    agenda["in_flight"] = [_project(n, jobs) for n in _svc().store.by_states({NodeState.FIRED})]
    agenda["cron_jobs"] = list(jobs.values())
    return agenda


@router.get("/range-v2")
async def range_v2(
    hours_back: int = Query(72, ge=0, le=8760),
    hours_ahead: int = Query(72, ge=0, le=8760),
) -> dict[str, Any]:
    import datetime as dt
    now = dt.datetime.now(dt.timezone.utc)
    jobs = _all_jobs()
    nodes = _svc().store.between(now - dt.timedelta(hours=hours_back), now + dt.timedelta(hours=hours_ahead))
    return {"now": now.isoformat(), "nodes": [_project(n, jobs) for n in nodes], "total": len(nodes)}


def create_schedule_sync(body: CreateScheduleBody) -> dict[str, Any]:
    """Create Hermes Cron first, then bind its id to Timeline atomically."""
    prompt = _job_prompt(body)
    if body.approval_required:
        prompt = (
            "本任务在执行契约中标记 approval_required=true。未取得用户具名批准前，"
            "只允许读取、分析和形成执行提案；不得执行任何写入、发布、发送、付费或品牌承诺。\n\n"
            + prompt
        )
    schedule = body.schedule.strip() or body.scheduled_at
    cron_body: dict[str, Any] = {
        "name": f"Timeline · {body.intent}"[:200],
        "schedule": schedule,
        "prompt": prompt,
        "deliver": body.deliver,
        "skills": body.skills,
    }
    # Cron is created first. A Timeline node must never exist without a real clock.
    created = _hermes("POST", "/api/jobs", cron_body).get("job") or {}
    jid = str(created.get("id") or "")
    if not jid:
        raise HTTPException(status_code=502, detail="Hermes Cron 未返回 job_id")

    workflow_version = body.workflow_version
    if body.task_type == "workflow" and not workflow_version:
        tpl = get_workflow_store().template(body.workflow_id)
        workflow_version = tpl.version if tpl else ""
    context = {
        "task_type": body.task_type,
        "agent_prompt": body.prompt if body.task_type == "agent_prompt" else "",
        "workflow_id": body.workflow_id,
        "workflow_version": workflow_version,
        "parameters": body.parameters,
        "priority": body.priority,
        "approval_required": body.approval_required,
        "hermes_job_id": jid,
        "scheduler": "hermes-cron",
        "created_by": body.created_by,
    }
    try:
        node = _svc().schedule(
            {
                "scheduled_at": created.get("next_run_at") or body.scheduled_at,
                "kind": body.kind,
                "intent": body.intent,
                "subject_ref": body.subject_ref,
                "expected_minutes": body.expected_minutes,
                "on_miss": body.on_miss,
                "parent_node": body.parent_node,
                "created_by": body.created_by,
                "context": context,
            },
            allow_conflict=body.allow_conflict,
        )
    except Exception:
        # Compensating delete: no orphan Cron if Timeline validation/storage fails.
        _hermes("DELETE", f"/api/jobs/{jid}")
        raise
    return _project(node, {jid: created})


def create_planned_node_sync(body: CreateScheduleBody) -> dict[str, Any]:
    """Agent-created plan: Timeline owns it; fixed Hermes Pulse is its clock."""
    if body.task_type == "agent_prompt" and not body.prompt.strip():
        raise HTTPException(status_code=422, detail="Agent 任务必须填写 prompt")
    if body.task_type == "workflow":
        _workflow_prompt(body)  # validate id/version; prompt is built by Pulse later
        if not body.workflow_version:
            tpl = get_workflow_store().template(body.workflow_id)
            body.workflow_version = tpl.version if tpl else ""
    context = {
        "task_type": body.task_type,
        "agent_prompt": body.prompt if body.task_type == "agent_prompt" else "",
        "workflow_id": body.workflow_id,
        "workflow_version": body.workflow_version,
        "parameters": body.parameters,
        "priority": body.priority,
        "approval_required": body.approval_required,
        "scheduler": "hermes-pulse",
        "runtime_state": "SCHEDULED",
        "created_by": body.created_by,
    }
    node = _svc().schedule(
        {
            "scheduled_at": body.scheduled_at, "kind": body.kind,
            "intent": body.intent, "subject_ref": body.subject_ref,
            "expected_minutes": body.expected_minutes, "on_miss": body.on_miss,
            "parent_node": body.parent_node, "created_by": body.created_by,
            "context": context,
        }, allow_conflict=body.allow_conflict,
    )
    data = node.to_dict(); data["runtime_state"] = "SCHEDULED"; return data


@router.post("/plans", status_code=201)
async def create_plan(body: CreateScheduleBody) -> dict[str, Any]:
    return create_planned_node_sync(body)


@router.post("/schedules", status_code=201)
async def create_schedule(body: CreateScheduleBody) -> dict[str, Any]:
    return create_schedule_sync(body)


@router.patch("/schedules/{node_id}")
async def update_schedule(node_id: str, body: UpdateScheduleBody) -> dict[str, Any]:
    node = _svc().store.get(node_id)
    if node is None:
        raise HTTPException(status_code=404, detail="Timeline 节点不存在")
    jid = _job_id(node)
    if not jid:
        raise HTTPException(status_code=409, detail="旧 Timeline 节点未绑定 Hermes Cron")
    patch: dict[str, Any] = {}
    if body.schedule is not None: patch["schedule"] = body.schedule
    if body.prompt is not None: patch["prompt"] = body.prompt
    if body.deliver is not None: patch["deliver"] = body.deliver
    if body.intent is not None: patch["name"] = f"Timeline · {body.intent}"[:200]
    result = _hermes("PATCH", f"/api/jobs/{jid}", patch).get("job") or {}
    if body.intent is not None: node.intent = body.intent
    if body.expected_minutes is not None: node.expected_minutes = body.expected_minutes
    if body.priority is not None:
        ctx = dict(node.context); ctx["priority"] = body.priority; node.context = ctx
    if result.get("next_run_at"): node.scheduled_at = result["next_run_at"]
    _svc().store.put(node)
    return _project(node, {jid: result})


@router.post("/schedules/{node_id}/{action}")
async def lifecycle(node_id: str, action: str) -> dict[str, Any]:
    if action not in {"pause", "resume", "run", "approve"}:
        raise HTTPException(status_code=404, detail="未知操作")
    node = _svc().store.get(node_id)
    if node is None:
        raise HTTPException(status_code=404, detail="Timeline 节点不存在")
    jid = _job_id(node)
    if jid:
        if action == "approve":
            raise HTTPException(status_code=409, detail="Cron 任务没有 Timeline 业务审批状态")
        job = _hermes("POST", f"/api/jobs/{jid}/{action}").get("job") or {}
        return _project(node, {jid: job})

    # Agent-planned nodes share one fixed Pulse Cron instead of one Cron per node.
    ctx = dict(node.context)
    if ctx.get("scheduler") != "hermes-pulse":
        raise HTTPException(status_code=409, detail="旧 Timeline 节点未绑定 Hermes Cron/Pulse")
    import datetime as dt
    import sqlite3
    if action in {"run", "resume", "approve"}:
        if action == "approve":
            ctx["approval_required"] = False
            ctx["approved_at"] = dt.datetime.now(dt.timezone.utc).isoformat()
            ctx["approved_by"] = "timeline-user"
        ctx["runtime_state"] = "SCHEDULED"
        node.context = ctx; node.state = NodeState.SCHEDULED
        if action == "run":
            node.scheduled_at = dt.datetime.now(dt.timezone.utc).isoformat()
        _svc().store.put(node)
        # Clear the previous claim so Pulse can make exactly one fresh attempt.
        run_db = __import__('pathlib').Path(_svc().store.dir) / "timeline_runs.db"
        if run_db.exists():
            c = sqlite3.connect(run_db)
            try:
                c.execute("DELETE FROM timeline_runs WHERE node_id=?", (node_id,)); c.commit()
            finally:
                c.close()
    elif action == "pause":
        ctx["runtime_state"] = "PAUSED"; node.context = ctx; _svc().store.put(node)
    data = node.to_dict(); data["runtime_state"] = ctx.get("runtime_state"); return data


@router.delete("/schedules/{node_id}")
async def delete_schedule(node_id: str) -> dict[str, Any]:
    node = _svc().store.get(node_id)
    if node is None:
        raise HTTPException(status_code=404, detail="Timeline 节点不存在")
    jid = _job_id(node)
    if jid:
        _hermes("DELETE", f"/api/jobs/{jid}")
    else:
        # Stop an in-flight Pulse-dispatched Hermes run when possible.
        run_id = str(dict(node.context).get("hermes_run_id") or "")
        if run_id:
            try: _hermes("POST", f"/v1/runs/{run_id}/stop")
            except Exception: pass
    if node.state in {NodeState.SCHEDULED, NodeState.FIRED}:
        if node.state is NodeState.SCHEDULED:
            _svc().cancel(node_id, reason="用户或 Agent 从 Timeline 取消;调度已撤销")
        else:
            ctx = dict(node.context); ctx["runtime_state"] = "CANCELLED"; node.context = ctx
            node.state = NodeState.CANCELLED; node.triage_reason = "用户或 Agent 取消运行"; _svc().store.put(node)
    return {"ok": True, "node": node.to_dict(), "deleted_job_id": jid}


@router.post("/triage-v2")
async def triage_v2(body: TriageBody) -> dict[str, Any]:
    try:
        return _svc().triage(body.decisions)
    except TimelineError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
