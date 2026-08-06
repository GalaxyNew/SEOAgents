"""Workflow API (L2) — templates, instances, and the node editor's data source.

The department picker in a ``dept_request`` node calls
``/api/workflows/departments/{id}/capabilities``, which proxies that
department's own ``/api/v1/capabilities``. Nothing is hardcoded: what you can
ask another department to do is whatever it currently says it can do.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import time
import urllib.error
import urllib.request
import uuid
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from dojocore.logging import LOGGER
from dojocore.workflow import (
    NODE_SPECS,
    EngineError,
    NodeType,
    TemplateError,
    WorkflowConflict,
    WorkflowEngine,
    WorkflowInstance,
    WorkflowTemplate,
    get_department_registry,
    get_workflow_store,
)
from dojocore.workflow.instance import InstanceStatus, NodeState

router = APIRouter(prefix="/api/workflows", tags=["workflow"])


def _store():
    try:
        return get_workflow_store()
    except Exception as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


# ── node palette ─────────────────────────────────────────────────────────
@router.get("/node-types")
async def node_types() -> dict[str, Any]:
    """The closed set of node types, for the composer's palette."""
    return {
        "types": [
            {
                "id": t.value,
                "label": t.label,
                "required_config": list(NODE_SPECS[t]["required"]),
                "hint": NODE_SPECS[t]["why"],
                "runs_externally": t.runs_externally,
                "acceptance_required": t is not NodeType.HUMAN_GATE,
            }
            for t in NodeType
        ]
    }


# ── departments (for the dept_request node editor) ───────────────────────
@router.get("/departments")
async def list_departments() -> dict[str, Any]:
    reg = get_department_registry()
    return {"departments": [d.to_dict() for d in reg.list(enabled_only=False)]}


@router.get("/departments/{dept_id}/capabilities")
async def department_capabilities(dept_id: str, force: bool = False) -> dict[str, Any]:
    """What that department can be asked to do, fetched live.

    Returns an explicit error rather than a guess when the department is
    unreachable: a node configured against a capability that does not exist
    only fails once the pipeline is already running.
    """
    return await get_department_registry().capabilities(dept_id, force=force)


# ── templates ────────────────────────────────────────────────────────────
@router.get("/templates")
async def list_templates() -> dict[str, Any]:
    return {"templates": [t.summary() for t in _store().templates()]}


@router.post("/templates/id", status_code=201)
async def allocate_template_id() -> dict[str, str]:
    """Allocate a collision-resistant ID; names remain presentation only."""
    store = _store()
    for _ in range(10):
        candidate = f"wf_{uuid.uuid4().hex[:12]}"
        if store.template(candidate) is None:
            return {"template_id": candidate}
    raise HTTPException(status_code=503, detail="无法分配唯一模板 ID")


@router.get("/templates/{template_id}")
async def get_template(template_id: str) -> dict[str, Any]:
    tpl = _store().template(template_id)
    if tpl is None:
        raise HTTPException(status_code=404, detail=f"unknown template '{template_id}'")
    return tpl.to_dict()


@router.post("/templates", status_code=201)
async def save_template(payload: dict[str, Any]) -> dict[str, Any]:
    """Create or revise a pipeline. Validated before it can be saved."""
    try:
        tpl = WorkflowTemplate.from_dict(payload)
    except (TemplateError, ValueError, TypeError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    path = _store().save_template(tpl)
    return {"saved": str(path), "template": tpl.to_dict()}


@router.put("/templates/{template_id}")
async def update_template(template_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Edit built-in/user templates by writing a validated user override."""
    payload = dict(payload); payload["id"] = template_id
    try:
        tpl = WorkflowTemplate.from_dict(payload)
    except (TemplateError, ValueError, TypeError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    path = _store().save_template(tpl)
    return {"saved": str(path), "template": tpl.to_dict(), "override": True}


@router.delete("/templates/{template_id}")
async def delete_template(template_id: str) -> dict[str, Any]:
    store = _store()
    if store.template(template_id) is None:
        raise HTTPException(status_code=404, detail=f"unknown template '{template_id}'")
    if store.instances(template_id=template_id, limit=1):
        raise HTTPException(status_code=409, detail="模板已有实例记录;请保留模板以便审计")
    if not store.delete_template(template_id):
        raise HTTPException(status_code=409, detail="内置模板不可删除;可编辑并保存为用户覆盖版")
    return {"ok": True, "template_id": template_id}


@router.post("/templates/validate")
async def validate_template(payload: dict[str, Any]) -> dict[str, Any]:
    """Dry-run validation, so the composer can show errors before saving."""
    try:
        tpl = WorkflowTemplate.from_dict(payload)
    except (TemplateError, ValueError, TypeError) as exc:
        return {"valid": False, "error": str(exc)}
    return {"valid": True, "summary": tpl.summary(), "layers": tpl.layers()}


# ── instances ────────────────────────────────────────────────────────────
class StartBody(BaseModel):
    template_id: str
    title: str = ""
    context: dict[str, Any] = Field(default_factory=dict)
    input_params: dict[str, Any] = Field(default_factory=dict)
    parent_task: str = ""
    auto_start: bool = False


@router.post("/instances", status_code=201)
async def start_instance(body: StartBody) -> dict[str, Any]:
    store = _store()
    tpl = store.template(body.template_id)
    if tpl is None:
        raise HTTPException(status_code=404, detail=f"unknown template '{body.template_id}'")
    inst = WorkflowInstance.start(
        tpl, title=body.title,
        context={**body.context, "input_params": dict(body.input_params)},
        parent_task=body.parent_task,
    )
    store.save_instance(inst)
    LOGGER.info(f"workflow instance created: {inst.instance_id} from {tpl.id} v{tpl.version}")
    if body.auto_start:
        try:
            inst = store.authorize_start(inst.instance_id)
        except WorkflowConflict as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        runtime = _dispatch_ready_runs(store, inst, WorkflowEngine(tpl))
        return {**(store.instance(inst.instance_id) or inst).to_dict(), "runtime": runtime}
    return inst.to_dict()


@router.get("/instances")
async def list_instances(
    status: str | None = None,
    template_id: str | None = None,
    limit: int = Query(50, le=200),
) -> dict[str, Any]:
    items = _store().instances(status=status, template_id=template_id, limit=limit)
    return {"total": len(items), "items": [i.to_dict() for i in items]}


def _make_template_snapshot(inst: WorkflowInstance, tpl: WorkflowTemplate) -> WorkflowTemplate:
    """Backfill immutable snapshots for legacy instances once, before edits."""
    if not inst.template_snapshot:
        inst.template_snapshot = tpl.to_dict()
    return tpl


def _load(instance_id: str):
    store = _store()
    inst = store.instance(instance_id)
    if inst is None:
        raise HTTPException(status_code=404, detail=f"unknown instance '{instance_id}'")
    tpl = store.template_for_instance(inst)
    if tpl is None:
        raise HTTPException(
            status_code=409,
            detail=f"实例引用的模板 '{inst.template_id}' 快照不可用",
        )
    if not inst.template_snapshot:
        _make_template_snapshot(inst, tpl)
        store.save_instance(inst)
    return store, inst, WorkflowEngine(tpl)


def _hermes_settings() -> tuple[str, str]:
    return (
        os.environ.get("HERMES_API_URL", "http://172.19.0.1:8642").rstrip("/"),
        os.environ.get("HERMES_API_KEY", "").strip(),
    )


def _hermes(method: str, path: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
    base, key = _hermes_settings()
    if not key:
        raise HTTPException(status_code=503, detail="HERMES_API_KEY 未配置")
    raw = json.dumps(body, ensure_ascii=False).encode() if body is not None else None
    req = urllib.request.Request(
        base + path, data=raw, method=method,
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read() or b"{}")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode(errors="replace")
        raise HTTPException(status_code=502, detail=f"Hermes API {exc.code}: {detail[:300]}") from exc


def _node_model_config(node) -> dict[str, Any]:
    """Resolve model/provider/reasoning_effort for an executable node.

    Priority: node config > (department default, not yet modeled) >
    Hermes system default (omitted fields → gateway picks its current model).
    Only non-empty values are emitted so the gateway keeps its defaults
    whenever the node did not pin a specific runtime.
    """
    config = dict(node.config or {})
    provider = str(config.get("provider") or "").strip()
    model = str(config.get("model") or "").strip()
    effort = str(config.get("reasoning_effort") or "").strip().lower()
    fields: dict[str, Any] = {}
    if provider:
        fields["provider"] = provider
    if model:
        fields["model"] = model
    if effort and effort != "auto":
        fields["model_options"] = {
            "reasoning": {"enabled": effort != "none", "effort": effort},
            "reasoning_effort": effort,
        }
    return fields


def _node_instruction(inst, tpl, node) -> str:
    deps = {
        dep: {
            "evidence": inst.runs[dep].evidence,
            "output_asset_ids": list(inst.runs[dep].output_asset_ids),
            "runtime_output": inst.runs[dep].runtime_output,
        }
        for dep in node.depends_on
    }
    config = dict(node.config)
    if node.type is NodeType.INPUT:
        task = (
            f"运行已有工作流 {config.get('workflow_id')} 并等待其完成"
            if config.get("input_mode") == "workflow" else "接受实例输入参数"
        )
    elif node.type is NodeType.AGENT_TASK:
        task = str(config.get("instruction") or "")
    elif node.type is NodeType.TOOL_CALL:
        task = (
            f"调用工具 {config.get('tool')} 执行 action={config.get('action', '')};"
            f"参数={json.dumps(config.get('arguments') or {}, ensure_ascii=False)}"
        )
    elif node.type is NodeType.VERIFY:
        task = f"运行并核验以下验证命令，返回真实输出：\n{config.get('command', '')}"
    elif node.type is NodeType.OUTPUT:
        mode = str(config.get("output_mode") or "end")
        approval = (inst.context.get("approvals") or {}).get(node.id) or {}
        if mode == "agent":
            # Agent output: Hermes generates the workflow deliverable under the
            # composer-provided instruction. Validation (nodes.py) guarantees
            # agent_instruction is non-empty, but coerce defensively.
            agent_instruction = str(config.get("agent_instruction") or "").strip()
            task = (
                f"生成本工作流的最终交付物。要求：\n{agent_instruction}\n"
                "只使用本节点上游的真实结果，不得臆造。"
            )
        elif mode == "webhook":
            signature_clause = ""
            sig = config.get("webhook_signature")
            if sig is not None and str(sig).strip():
                # Forward the configured signature hint so the agent computes
                # the matching HMAC over the exact body it sends.
                signature_clause = f"\n请求需带 X-Signature 头（HMAC-SHA256，密钥由 webhook_signature 派生）：已配置签名。"
            at_agents = config.get("at_agents") or []
            target_chat_id = config.get("target_chat_id") or ""
            notify_mode = config.get("notify_mode") or "group"
            raw_url = config.get('webhook_url', '')
            if at_agents:
                # 用户选了通知 Agent：后台透明切换到中转地址
                mode_desc = "私聊" if notify_mode == "private" else "群@"
                task = (
                    f"将上游结果发送到 Webhook 中转地址 http://127.0.0.1:9100/relay（{mode_desc}模式）。具名审批已取得："
                    f"approver={approval.get('approver')}, approved_at={approval.get('approved_at')}, note={approval.get('note')}. "
                    "只允许发送本节点上游结果，不得扩展发送范围。\n"
                    f"POST body 必须是 JSON 格式，包含以下字段：\n"
                    f'  - "text": 上游结果的摘要文本\n'
                    f'  - "title": "SEOAgents 工作流通知"\n'
                    f'  - "at_agents": {json.dumps(at_agents)}\n'
                    f'  - "mode": "{notify_mode}"\n'
                    + (f'  - "chat_id": "{target_chat_id}"\n' if target_chat_id and notify_mode == "group" else '')
                    + f"注意：选了通知 Agent 时不能直接 POST 到原始飞书 webhook，"
                    f"必须 POST 到中转地址让后台用应用 API 发送。"
                )
            else:
                task = (
                    f"将上游结果发送到 Webhook {raw_url}。具名审批已取得："
                    f"approver={approval.get('approver')}, approved_at={approval.get('approved_at')}, note={approval.get('note')}. "
                    "只允许发送本节点上游结果，不得扩展发送范围。"
                    f"{signature_clause}"
                )
        else:
            task = f"生成工作流输出，模式={mode}"
    else:
        task = str(config.get("prompt") or config.get("instruction") or "")
    return (
        "你正在执行 SEOAgents 工作流的一个节点。只完成本节点，不跳到下游。"
        "必须使用真实工具输出；交付物先入 Asset Hub；不得自行通过人工审批。\n\n"
        f"Instance: {inst.instance_id}\nTemplate: {tpl.id}@{inst.template_version}\n"
        f"Node: {node.id} · {node.title}\nType: {node.type.value}\n"
        f"Task: {task}\nAcceptance: {json.dumps(list(node.acceptance), ensure_ascii=False)}\n"
        f"Workflow context: {json.dumps(inst.context, ensure_ascii=False)}\n"
        f"Upstream: {json.dumps(deps, ensure_ascii=False)}\n\n"
        "完成后必须调用 platform_ops.workflow_complete_node 回写本节点："
        f"instance_id={inst.instance_id}, node_id={node.id}，"
        "acceptance_met 必须与验收项逐条对应，evidence 必须是真实工具输出，"
        "output_asset_ids 填入所有资产 ID。任一项不满足就不要完成节点。"
    )


def _dispatch_ready_runs(store, inst, engine) -> dict[str, Any]:
    """Dispatch dependency-ready nodes behind a persisted CAS claim.

    Direct start, auto-start, and Pulse converge here. A node is claimed in
    SQLite before any external submit. If Hermes acknowledgement is lost, the
    claim remains UNKNOWN and cannot be blindly retried.
    """
    terminal = {
        InstanceStatus.PAUSED, InstanceStatus.CANCELLED,
        InstanceStatus.DONE, InstanceStatus.FAILED,
    }
    if inst.status in terminal:
        return {"created": [], "skipped": [], "errors": [], "status": inst.status.value}
    if not inst.context.get("start_authorized"):
        return {
            "created": [], "skipped": [{"reason": "start not authorized"}],
            "errors": [], "status": inst.status.value,
        }

    tpl = engine.template
    created: list[dict[str, str]] = []
    skipped: list[dict[str, str]] = []
    errors: list[dict[str, str]] = []
    # Deterministic control nodes may unlock another layer immediately.
    for _ in range(max(1, len(tpl.nodes) + 1)):
        current = store.instance(inst.instance_id)
        if current is None or current.status in terminal:
            break
        inst = current
        engine = WorkflowEngine(tpl)
        engine.refresh(inst)
        ready = list(engine.ready_nodes(inst))
        if not ready:
            break
        progressed = False
        for node in ready:
            claimed = store.claim_ready_node(inst.instance_id, node.id)
            if claimed is None:
                skipped.append({"node": node.id, "reason": "already claimed or not ready"})
                continue
            inst = claimed
            engine = WorkflowEngine(tpl)
            run = inst.runs[node.id]
            token = run.dispatch_token

            if node.type is NodeType.INPUT:
                mode = str(node.config.get("input_mode") or "direct")
                if mode == "workflow":
                    child_id = str(node.config.get("workflow_id") or "")
                    child_tpl = store.template(child_id)
                    if child_tpl is None:
                        engine.fail(inst, node.id, error=f"输入工作流 {child_id} 不存在")
                        store.save_instance(inst)
                        skipped.append({"node": node.id, "reason": "input workflow missing"})
                        progressed = True
                        continue
                    child = WorkflowInstance.start(
                        child_tpl,
                        title=f"{inst.title} · 输入 {node.title}",
                        context={
                            **inst.context,
                            "parent_instance_id": inst.instance_id,
                            "parent_node_id": node.id,
                        },
                        parent_task=inst.instance_id,
                    )
                    store.save_instance(child)
                    engine.begin(inst, node.id)
                    run.external_request_id = child.instance_id
                    run.runtime_status = "WAITING_CHILD_WORKFLOW"
                    run.dispatch_token = ""
                    store.save_instance(inst)
                    child = store.authorize_start(child.instance_id)
                    child_runtime = _dispatch_ready_runs(store, child, WorkflowEngine(child_tpl))
                    skipped.append({
                        "node": node.id, "reason": "child workflow",
                        "instance_id": child.instance_id,
                        "child_runs": str(len(child_runtime.get("created") or [])),
                    })
                    progressed = True
                    continue
                engine.complete_control_node(
                    inst, node.id,
                    evidence=f"instance input accepted: {json.dumps(inst.context.get('input_params') or {}, ensure_ascii=False)}",
                )
                run.dispatch_token = ""
                store.save_instance(inst)
                skipped.append({"node": node.id, "reason": "direct input accepted"})
                progressed = True
                continue

            if node.type is NodeType.OUTPUT and node.config.get("output_mode") in {
                "end", "result", "boolean",
            }:
                upstream = {
                    dep: {
                        "evidence": inst.runs[dep].evidence,
                        "output_asset_ids": list(inst.runs[dep].output_asset_ids),
                        "runtime_output": inst.runs[dep].runtime_output,
                    }
                    for dep in node.depends_on
                }
                mode = str(node.config.get("output_mode") or "end")
                if mode == "boolean":
                    inst.context["workflow_output"] = str(node.config.get("boolean_value")).lower() == "true"
                elif mode == "result":
                    inst.context["workflow_output"] = upstream
                engine.complete_control_node(
                    inst, node.id, evidence=json.dumps(upstream, ensure_ascii=False)
                )
                run.dispatch_token = ""
                store.save_instance(inst)
                skipped.append({"node": node.id, "reason": f"output {mode}"})
                progressed = True
                continue

            if node.type is NodeType.OUTPUT and node.config.get("output_mode") == "webhook":
                approval = (inst.context.get("approvals") or {}).get(node.id)
                if not approval:
                    run.state = NodeState.WAITING_HUMAN
                    run.runtime_status = "BLOCKED_APPROVAL"
                    run.dispatch_token = ""
                    engine.refresh(inst)
                    store.save_instance(inst)
                    skipped.append({"node": node.id, "reason": "webhook approval required"})
                    progressed = True
                    continue

            if node.type is NodeType.HUMAN_GATE:
                engine.begin(inst, node.id)
                run.runtime_status = "BLOCKED_APPROVAL"
                run.dispatch_token = ""
                store.save_instance(inst)
                skipped.append({"node": node.id, "reason": "human approval"})
                progressed = True
                continue

            if node.type is NodeType.DEPT_REQUEST:
                engine.begin(inst, node.id)
                run.runtime_status = "BLOCKED_DEPENDENCY"
                run.dispatch_token = ""
                # ── B1: Create collab outbox record ──────────────────────
                try:
                    from dojocore.collab import get_collab_service, new_request_id
                    import datetime as _dt
                    import time as _time
                    _svc = get_collab_service()
                    _seq = int(_time.time()) % 10000
                    _rid = new_request_id(dept=_svc.own_dept, seq=_seq)
                    _target_dept = str(node.config.get("dept", ""))
                    _capability = str(node.config.get("capability", ""))
                    _spec = str(node.config.get("spec_asset_id") or node.config.get("spec_template") or f"WF-{inst.instance_id}:{node.id}")
                    _acceptance = list(node.acceptance) if node.acceptance else ["交付物符合规格"]
                    _timeout_h = float(node.config.get("timeout_hours", 48))
                    _deadline = (_dt.datetime.now(_dt.timezone.utc) + _dt.timedelta(hours=_timeout_h)).isoformat()
                    _payload = {
                        "request_id": _rid,
                        "from": {"dept": _svc.own_dept, "endpoint": "https://seoag.775767.xyz"},
                        "to": {"dept": _target_dept, "capability": _capability},
                        "recipient": {"dept": _target_dept},
                        "title": node.title or f"{_capability} for {inst.instance_id}",
                        "spec_asset_id": _spec,
                        "expected_deliverable": {
                            "asset_class": str(node.config.get("asset_class", "MEDIA")),
                            "count": int(node.config.get("expected_count", 1)),
                            "acceptance": _acceptance,
                        },
                        "priority": str(node.config.get("priority", "P2")),
                        "deadline": _deadline,
                        "parent_task": inst.instance_id,
                    }
                    _req_obj, _created = _svc.send(_payload)
                    run.external_request_id = _rid
                    LOGGER.info(f"B1: collab outbox created {_rid} -> {_target_dept}/{_capability}")
                except Exception as _exc:
                    LOGGER.warning(f"B1: collab outbox creation failed: {_exc}")
                # ── end B1 ────────────────────────────────────────────────
                store.save_instance(inst)
                skipped.append({"node": node.id, "reason": "external department"})
                progressed = True
                continue

            # ── B6: Dispatch to Kanban (control plane record) ────────────
            try:
                from seoagents.dashboard.routers.workflow_kanban_bridge import dispatch_to_kanban, DispatchBody
                dispatch_to_kanban(inst.instance_id, DispatchBody(assignee="hm", only_ready=False))
            except Exception:
                pass  # Kanban write failure must not block workflow execution
            # ── end B6 ────────────────────────────────────────────────────
            payload: dict[str, Any] = {
                "input": _node_instruction(inst, tpl, node),
                "session_id": f"workflow:{inst.instance_id}:{node.id}:{run.attempts}",
            }
            payload.update(_node_model_config(node))
            try:
                response = _hermes("POST", "/v1/runs", payload)
            except Exception as exc:
                inst = store.bind_dispatch(
                    inst.instance_id, node.id, token,
                    error=f"Hermes submit unacknowledged: {type(exc).__name__}: {exc}",
                )
                errors.append({"node": node.id, "error": inst.runs[node.id].error})
                progressed = True
                continue
            rid = str(response.get("run_id") or "")
            if not rid:
                inst = store.bind_dispatch(
                    inst.instance_id, node.id, token,
                    error="Hermes accepted request but did not return run_id",
                )
                errors.append({"node": node.id, "error": inst.runs[node.id].error})
                progressed = True
                continue
            inst = store.bind_dispatch(inst.instance_id, node.id, token, run_id=rid)
            created.append({"node": node.id, "run_id": rid})
            progressed = True
        if not progressed:
            break

    final = store.instance(inst.instance_id) or inst
    return {
        "created": created, "skipped": skipped, "errors": errors,
        "status": final.status.value,
    }


def _stop_active_runs(inst) -> list[str]:
    stopped = []
    for run in inst.runs.values():
        if run.runtime_run_id and run.runtime_status in {"QUEUED", "RUNNING", "WAITING_FOR_APPROVAL"}:
            stopped_ok = False
            try:
                _hermes("POST", f"/v1/runs/{run.runtime_run_id}/stop")
                stopped.append(run.runtime_run_id)
                stopped_ok = True
            except Exception:
                # We lost control of a possibly side-effecting run.  Do not
                # pretend it can safely resume or retry.
                run.runtime_status = "UNKNOWN"
            if stopped_ok:
                run.runtime_status = "STOPPED"
                run.runtime_run_id = ""
                if run.state is NodeState.RUNNING:
                    run.state = NodeState.READY
    return stopped


@router.get("/instances/{instance_id}")
async def get_instance(instance_id: str) -> dict[str, Any]:
    _, inst, engine = _load(instance_id)
    nodes = []
    for node in engine.template.nodes:
        run = inst.runs[node.id]
        nodes.append({**node.to_dict(), **run.to_dict()})
    return {
        **inst.to_dict(),
        "state": inst.status.value,
        "nodes": nodes,
        "ready": [n.id for n in engine.ready_nodes(inst)],
        "blocked_reason": engine.blocked_reason(inst),
        "layers": engine.template.layers(),
    }


class NodeActionBody(BaseModel):
    acceptance_met: list[bool] = Field(default_factory=list)
    evidence: str = ""
    output_asset_ids: list[str] = Field(default_factory=list)
    actor: str = "agent"
    error: str = ""
    external_request_id: str = ""


@router.post("/instances/{instance_id}/start")
async def start_runtime(instance_id: str) -> dict[str, Any]:
    store, inst, engine = _load(instance_id)
    if inst.status in (InstanceStatus.CANCELLED, InstanceStatus.DONE, InstanceStatus.FAILED):
        raise HTTPException(status_code=409, detail=f"实例已处于 {inst.status.value}")
    try:
        inst = store.authorize_start(instance_id)
    except WorkflowConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"ok": True, "instance_id": instance_id, **_dispatch_ready_runs(store, inst, engine)}


@router.post("/instances/{instance_id}/pause")
async def pause_instance(instance_id: str) -> dict[str, Any]:
    store, inst, _ = _load(instance_id)
    if inst.status in (InstanceStatus.DONE, InstanceStatus.CANCELLED):
        raise HTTPException(status_code=409, detail=f"实例已处于 {inst.status.value}")
    stopped = _stop_active_runs(inst)
    uncertain = [
        r.node_id for r in inst.runs.values()
        if r.runtime_status == "UNKNOWN"
        and r.state not in (NodeState.DONE, NodeState.FAILED, NodeState.SKIPPED)
    ]
    if uncertain:
        store.save_instance(inst)
        raise HTTPException(status_code=409, detail=f"以下节点运行状态不可确认，拒绝暂停后自动重试: {uncertain}")
    inst.status = InstanceStatus.PAUSED
    inst.updated_at = dt.datetime.now(dt.timezone.utc).isoformat()
    store.save_instance(inst)
    return {"ok": True, "instance": inst.to_dict(), "stopped_runs": stopped}


@router.post("/instances/{instance_id}/resume")
async def resume_instance(instance_id: str) -> dict[str, Any]:
    store, inst, engine = _load(instance_id)
    if inst.status is not InstanceStatus.PAUSED:
        raise HTTPException(status_code=409, detail="只有暂停中的实例可以恢复")
    inst.status = InstanceStatus.RUNNING
    inst.context["start_authorized"] = True
    store.save_instance(inst)
    return {"ok": True, "instance_id": instance_id, **_dispatch_ready_runs(store, inst, engine)}


@router.delete("/instances/{instance_id}")
async def delete_instance(instance_id: str) -> dict[str, Any]:
    store, inst, _ = _load(instance_id)
    stopped = _stop_active_runs(inst)
    # Only block deletion if an ACTIVE run has unknown status.
    # Settled nodes (DONE/FAILED/CANCELLED) are safe to delete regardless of runtime_status.
    uncertain = [
        r.node_id for r in inst.runs.values()
        if r.runtime_status == "UNKNOWN"
        and r.state not in (NodeState.DONE, NodeState.FAILED, NodeState.SKIPPED)
    ]
    if uncertain:
        store.save_instance(inst)
        raise HTTPException(status_code=409, detail=f"以下节点运行状态不可确认，拒绝删除审计记录: {uncertain}")
    # Delete associated legacy Kanban cards, if any.  Runtime v2 executes via
    # Hermes runs directly, but old instances remain cleanly removable.
    try:
        from seoagents.dashboard.routers.kanban_api import _connect
        conn = _connect(readonly=False)
        try:
            conn.execute("DELETE FROM task_events WHERE task_id IN (SELECT id FROM tasks WHERE workflow_template_id=?)", (instance_id,))
            conn.execute("DELETE FROM tasks WHERE workflow_template_id=?", (instance_id,))
            conn.commit()
        finally:
            conn.close()
    except Exception:
        pass
    if not store.delete_instance(instance_id):
        raise HTTPException(status_code=404, detail="实例不存在")
    return {"ok": True, "instance_id": instance_id, "stopped_runs": stopped}


class ApprovalBody(BaseModel):
    approver: str
    approved: bool = True
    note: str = ""


@router.post("/instances/{instance_id}/nodes/{node_id}/approve")
async def approve_node(instance_id: str, node_id: str, body: ApprovalBody) -> dict[str, Any]:
    """Named approval for human gates and side-effecting webhook output."""
    store, inst, engine = _load(instance_id)
    approver = body.approver.strip()
    if not approver or approver.lower() in {"agent", "hermes", "system", "unknown"}:
        raise HTTPException(status_code=422, detail="必须填写具名人类审批人")
    node = engine.template.node(node_id)
    run = inst.runs[node_id]
    if node.type is NodeType.HUMAN_GATE:
        try:
            engine.complete(
                inst, node_id, acceptance_met=[],
                evidence=f"approved by {approver}: {body.note}" if body.approved else f"rejected by {approver}: {body.note}",
                actor=approver,
            ) if body.approved else engine.fail(inst, node_id, error=f"rejected by {approver}: {body.note}")
        except EngineError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
    elif node.type is NodeType.OUTPUT and node.config.get("output_mode") == "webhook":
        if not body.approved:
            engine.fail(inst, node_id, error=f"Webhook rejected by {approver}: {body.note}")
        else:
            # Release exactly one Hermes attempt; the approved actor/scope are
            # embedded in its self-contained instruction and durable evidence.
            if run.state is not NodeState.WAITING_HUMAN or run.runtime_status != "BLOCKED_APPROVAL":
                raise HTTPException(status_code=409, detail="Webhook 节点当前不在等待审批状态")
            run.state = NodeState.READY
            run.runtime_status = "APPROVED"
            inst.context.setdefault("approvals", {})[node_id] = {
                "approver": approver, "note": body.note, "approved_at": dt.datetime.now(dt.timezone.utc).isoformat(),
            }
    else:
        raise HTTPException(status_code=409, detail="该节点不是审批节点")
    store.save_instance(inst)
    runtime = _dispatch_ready_runs(store, inst, engine)
    return {"ok": True, "instance": inst.to_dict(), "runtime": runtime}


@router.post("/instances/{instance_id}/nodes/{node_id}/begin")
async def begin_node(instance_id: str, node_id: str) -> dict[str, Any]:
    store, inst, engine = _load(instance_id)
    try:
        engine.begin(inst, node_id)
    except (EngineError, KeyError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    store.save_instance(inst)
    return inst.to_dict()


@router.post("/instances/{instance_id}/nodes/{node_id}/complete")
async def complete_node(instance_id: str, node_id: str, body: NodeActionBody) -> dict[str, Any]:
    store, inst, engine = _load(instance_id)
    try:
        engine.complete(
            inst, node_id,
            acceptance_met=body.acceptance_met,
            evidence=body.evidence,
            output_asset_ids=body.output_asset_ids,
            actor=body.actor,
        )
    except (EngineError, KeyError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    store.save_instance(inst)
    return inst.to_dict()


@router.post("/instances/{instance_id}/nodes/{node_id}/fail")
async def fail_node(instance_id: str, node_id: str, body: NodeActionBody) -> dict[str, Any]:
    store, inst, engine = _load(instance_id)
    try:
        engine.fail(inst, node_id, error=body.error)
    except (EngineError, KeyError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    store.save_instance(inst)
    return inst.to_dict()


@router.post("/instances/{instance_id}/nodes/{node_id}/attach-request")
async def attach_request(instance_id: str, node_id: str, body: NodeActionBody) -> dict[str, Any]:
    """Link a dept_request node to the collab request it produced."""
    store, inst, engine = _load(instance_id)
    if not body.external_request_id:
        raise HTTPException(status_code=422, detail="external_request_id 必填")
    engine.attach_external(inst, node_id, body.external_request_id)
    store.save_instance(inst)
    return inst.to_dict()


@router.get("/internal/instances")
async def internal_instances(active: bool = True) -> dict[str, Any]:
    statuses = {InstanceStatus.RUNNING, InstanceStatus.BLOCKED}
    items = _store().instances(limit=200)
    if active:
        items = [
            i for i in items
            if i.status in statuses and i.context.get("start_authorized")
        ]
    return {"items": [i.to_dict() for i in items]}


@router.post("/internal/instances/{instance_id}/tick")
async def internal_tick(instance_id: str) -> dict[str, Any]:
    store, inst, engine = _load(instance_id)
    if (not inst.context.get("start_authorized")
            or inst.status in (
                InstanceStatus.PENDING, InstanceStatus.PAUSED,
                InstanceStatus.CANCELLED, InstanceStatus.DONE,
            )):
        return {"ok": True, "instance": inst.to_dict(), "runtime": {"created": [], "skipped": []}}
    reconciled, errors = [], []
    # Resolve child-workflow input nodes before polling Hermes runs.
    for node_id, run in inst.runs.items():
        if run.runtime_status != "WAITING_CHILD_WORKFLOW" or not run.external_request_id:
            continue
        child = store.instance(run.external_request_id)
        if child is None:
            engine.fail(inst, node_id, error=f"子工作流实例 {run.external_request_id} 不存在")
            errors.append({"node": node_id, "error": "child workflow missing"})
        elif child.status is InstanceStatus.DONE:
            engine.complete_control_node(
                inst, node_id,
                evidence=f"child workflow {child.instance_id} DONE",
            )
            run.runtime_status = "COMPLETED"
            reconciled.append({"node": node_id, "status": "CHILD_DONE"})
        elif child.status in (InstanceStatus.FAILED, InstanceStatus.CANCELLED):
            engine.fail(inst, node_id, error=f"子工作流 {child.instance_id} 为 {child.status.value}")
            errors.append({"node": node_id, "error": child.status.value})
    # ── B4: Collab outbox reconciliation ──────────────────────────────
    for node_id, run in inst.runs.items():
        if run.runtime_status != "BLOCKED_DEPENDENCY" or not getattr(run, "external_request_id", ""):
            continue
        try:
            from dojocore.collab import get_collab_service
            _svc2 = get_collab_service()
            _req2 = _svc2.store.get(run.external_request_id, box="outbox")
            if _req2 is None:
                continue
            if _req2.status.value == "DELIVERED":
                run.runtime_output = f"collab {_req2.request_id} DELIVERED, assets: {list(_req2.deliverable_asset_ids)}"
                node2 = engine.template.node(node_id)
                if node2.acceptance:
                    run.runtime_status = "AWAITING_ACCEPTANCE"
                    reconciled.append({"node": node_id, "status": "COLLAB_DELIVERED_AWAITING"})
                else:
                    try:
                        engine.complete(inst, node_id, acceptance_met=[], evidence=run.runtime_output, actor="collab-sync")
                    except Exception:
                        pass
                    reconciled.append({"node": node_id, "status": "COLLAB_DELIVERED"})
            elif _req2.status.value == "CLOSED":
                node2 = engine.template.node(node_id)
                try:
                    engine.complete(inst, node_id,
                        acceptance_met=[True]*len(node2.acceptance) if node2.acceptance else [],
                        evidence=f"collab {_req2.request_id} CLOSED", actor="collab-sync")
                except Exception:
                    pass
                reconciled.append({"node": node_id, "status": "COLLAB_CLOSED"})
            elif _req2.status.value in ("ESCALATED", "EXPIRED", "REJECTED"):
                run.runtime_status = "FAILED"
                run.error = f"collab {_req2.request_id} {_req2.status.value}: {_req2.reason}"
                reconciled.append({"node": node_id, "status": f"COLLAB_{_req2.status.value}"})
        except Exception as _exc2:
            errors.append({"node": node_id, "error": f"collab sync: {_exc2}"})
    # ── end B4 ────────────────────────────────────────────────────────
    for node_id, run in inst.runs.items():
        if not run.runtime_run_id or run.state is not NodeState.RUNNING:
            continue
        try:
            live = _hermes("GET", f"/v1/runs/{run.runtime_run_id}")
        except HTTPException as exc:
            if exc.status_code == 502 and "404" in str(exc.detail):
                run.runtime_status = "UNKNOWN"
                errors.append({"node": node_id, "error": "Hermes 重启后 run 状态已丢失，禁止自动重试"})
            else:
                errors.append({"node": node_id, "error": str(exc.detail)})
            continue
        status = str(live.get("status") or "").upper()
        run.runtime_status = status
        if status == "COMPLETED":
            run.runtime_output = str(live.get("output") or "")
            node = engine.template.node(node_id)
            if node.acceptance:
                # Acceptance is a business claim, not implied by process exit 0.
                # Keep the node in RUNNING until a human/current-Hermes supplies
                # explicit checks and evidence through the runtime callback.
                run.runtime_status = "AWAITING_ACCEPTANCE"
                errors.append({"node": node_id, "error": "等待逐条验收确认"})
                continue
            try:
                engine.complete(
                    inst, node_id, acceptance_met=[],
                    evidence=run.runtime_output or "Hermes run completed",
                    actor="hermes-runtime",
                )
            except EngineError as exc:
                engine.fail(inst, node_id, error=str(exc))
            reconciled.append({"node": node_id, "status": status})
        elif status in {"FAILED", "UNKNOWN", "CANCELLED"}:
            engine.fail(inst, node_id, error=str(live.get("error") or status))
            reconciled.append({"node": node_id, "status": status})
        elif status not in {"QUEUED", "RUNNING", "WAITING_FOR_APPROVAL"}:
            # A newly introduced/intermediate Hermes state is non-terminal. If
            # the API loses this run after restart it returns 404, handled above;
            # do not convert an unfamiliar live state into a retryable failure.
            run.runtime_status = status or "UNKNOWN"
            errors.append({"node": node_id, "error": f"未识别的 Hermes 状态 {status or '(empty)'}，等待复核"})
    store.save_instance(inst)
    runtime = _dispatch_ready_runs(store, inst, engine)
    return {"ok": True, "reconciled": reconciled, "errors": errors,
            "runtime": runtime, "instance": inst.to_dict()}


class RuntimeUpdateBody(BaseModel):
    run_id: str = ""
    status: str
    output: str = ""
    error: str = ""
    evidence: str = ""
    output_asset_ids: list[str] = Field(default_factory=list)
    acceptance_met: list[bool] = Field(default_factory=list)


@router.post("/internal/instances/{instance_id}/nodes/{node_id}/runtime")
async def runtime_update(instance_id: str, node_id: str, body: RuntimeUpdateBody) -> dict[str, Any]:
    """Pulse callback: project a real Hermes run into workflow business state."""
    store, inst, engine = _load(instance_id)
    run = inst.runs.get(node_id)
    if run is None:
        raise HTTPException(status_code=404, detail="节点不存在")
    if body.run_id and run.runtime_run_id and body.run_id != run.runtime_run_id:
        raise HTTPException(status_code=409, detail="run_id 与当前节点运行不一致")
    status = body.status.upper()
    run.runtime_status = status
    run.runtime_output = body.output
    if status == "ACCEPTED":
        # Agent completed the workflow node through platform_ops.  That call
        # already enforced acceptance; this callback only unlocks/dispatches.
        status = "COMPLETED"
        run.runtime_status = "COMPLETED"
    if (status == "COMPLETED" and run.state.settled):
        # The current Hermes may have already completed the node via platform_ops;
        # only reconcile the runtime handle and fan out the next layer.
        run.runtime_status = "COMPLETED"
        store.save_instance(inst)
        runtime = _dispatch_ready_runs(store, inst, engine)
        return {"ok": True, "instance": inst.to_dict(), "runtime": runtime,
                "next_ready": [n.id for n in engine.ready_nodes(inst)]}
    if status == "COMPLETED" and not run.state.settled:
        node = engine.template.node(node_id)
        checks = body.acceptance_met
        evidence = body.evidence or body.output
        if node.acceptance and (
            len(checks) != len(node.acceptance) or not all(checks) or not evidence.strip()
        ):
            # Process completion is only a settlement fact. Missing per-item
            # acceptance/evidence keeps the business node open.
            run.runtime_status = "AWAITING_ACCEPTANCE"
            store.save_instance(inst)
            return {
                "ok": True, "instance": inst.to_dict(),
                "runtime": {"created": [], "skipped": [], "errors": []},
                "next_ready": [n.id for n in engine.ready_nodes(inst)],
            }
        try:
            engine.complete(
                inst, node_id, acceptance_met=checks, evidence=evidence,
                output_asset_ids=body.output_asset_ids, actor="hermes-runtime",
            )
        except EngineError as exc:
            engine.fail(inst, node_id, error=str(exc))
    elif status in {"FAILED", "UNKNOWN", "CANCELLED"} and not run.state.settled:
        engine.fail(inst, node_id, error=body.error or body.output or status)
    store.save_instance(inst)
    runtime = _dispatch_ready_runs(store, inst, engine)
    return {"ok": True, "instance": inst.to_dict(), "runtime": runtime,
            "next_ready": [n.id for n in engine.ready_nodes(inst)]}


@router.post("/instances/{instance_id}/sync-runtime")
async def sync_runtime(instance_id: str) -> dict[str, Any]:
    """Reconcile live Hermes run statuses and immediately unlock next DAG layer."""
    store, inst, engine = _load(instance_id)
    if inst.status is InstanceStatus.PAUSED:
        return {"ok": True, "instance": inst.to_dict(), "runtime": {"created": [], "skipped": []}}
    reconciled, errors = [], []
    # Resolve child-workflow input nodes before polling Hermes runs.
    for node_id, run in inst.runs.items():
        if run.runtime_status != "WAITING_CHILD_WORKFLOW" or not run.external_request_id:
            continue
        child = store.instance(run.external_request_id)
        if child is None:
            engine.fail(inst, node_id, error=f"子工作流实例 {run.external_request_id} 不存在")
            errors.append({"node": node_id, "error": "child workflow missing"})
        elif child.status is InstanceStatus.DONE:
            engine.complete_control_node(
                inst, node_id,
                evidence=f"child workflow {child.instance_id} DONE",
            )
            run.runtime_status = "COMPLETED"
            reconciled.append({"node": node_id, "status": "CHILD_DONE"})
        elif child.status in (InstanceStatus.FAILED, InstanceStatus.CANCELLED):
            engine.fail(inst, node_id, error=f"子工作流 {child.instance_id} 为 {child.status.value}")
            errors.append({"node": node_id, "error": child.status.value})
    # ── B4-sync: Collab outbox reconciliation ──────────────────────────
    for node_id, run in inst.runs.items():
        if run.runtime_status != "BLOCKED_DEPENDENCY" or not getattr(run, "external_request_id", ""):
            continue
        try:
            from dojocore.collab import get_collab_service
            _svc2 = get_collab_service()
            _req2 = _svc2.store.get(run.external_request_id, box="outbox")
            if _req2 is None:
                continue
            if _req2.status.value == "DELIVERED":
                run.runtime_output = f"collab {_req2.request_id} DELIVERED, assets: {list(_req2.deliverable_asset_ids)}"
                node2 = engine.template.node(node_id)
                if node2.acceptance:
                    run.runtime_status = "AWAITING_ACCEPTANCE"
                    reconciled.append({"node": node_id, "status": "COLLAB_DELIVERED_AWAITING"})
                else:
                    try:
                        engine.complete(inst, node_id, acceptance_met=[], evidence=run.runtime_output, actor="collab-sync")
                    except Exception:
                        pass
                    reconciled.append({"node": node_id, "status": "COLLAB_DELIVERED"})
            elif _req2.status.value == "CLOSED":
                node2 = engine.template.node(node_id)
                try:
                    engine.complete(inst, node_id,
                        acceptance_met=[True]*len(node2.acceptance) if node2.acceptance else [],
                        evidence=f"collab {_req2.request_id} CLOSED", actor="collab-sync")
                except Exception:
                    pass
                reconciled.append({"node": node_id, "status": "COLLAB_CLOSED"})
            elif _req2.status.value in ("ESCALATED", "EXPIRED", "REJECTED"):
                run.runtime_status = "FAILED"
                run.error = f"collab {_req2.request_id} {_req2.status.value}: {_req2.reason}"
                reconciled.append({"node": node_id, "status": f"COLLAB_{_req2.status.value}"})
        except Exception as _exc2:
            errors.append({"node": node_id, "error": f"collab sync: {_exc2}"})
    # ── end B4-sync ────────────────────────────────────────────────────
    for node_id, run in inst.runs.items():
        if not run.runtime_run_id or run.state is not NodeState.RUNNING:
            continue
        try:
            live = _hermes("GET", f"/v1/runs/{run.runtime_run_id}")
        except HTTPException as exc:
            if exc.status_code == 502 and "404" in str(exc.detail):
                run.runtime_status = "UNKNOWN"
                errors.append({"node": node_id, "error": "Hermes 重启后 run 状态已丢失，禁止自动重试"})
            continue
        status = str(live.get("status") or "").upper()
        run.runtime_status = status
        if status == "COMPLETED":
            run.runtime_output = str(live.get("output") or "")
            node = engine.template.node(node_id)
            if node.acceptance:
                # Acceptance is a business claim, not implied by process exit 0.
                # Keep the node in RUNNING until a human/current-Hermes supplies
                # explicit checks and evidence through the runtime callback.
                run.runtime_status = "AWAITING_ACCEPTANCE"
                errors.append({"node": node_id, "error": "等待逐条验收确认"})
                continue
            try:
                engine.complete(
                    inst, node_id, acceptance_met=[],
                    evidence=run.runtime_output or "Hermes run completed",
                    actor="hermes-runtime",
                )
            except EngineError as exc:
                engine.fail(inst, node_id, error=str(exc))
            reconciled.append({"node": node_id, "status": status})
        elif status in {"FAILED", "UNKNOWN", "CANCELLED"}:
            engine.fail(inst, node_id, error=str(live.get("error") or status))
            reconciled.append({"node": node_id, "status": status})
        elif status not in {"QUEUED", "RUNNING", "WAITING_FOR_APPROVAL"}:
            # A newly introduced/intermediate Hermes state is non-terminal. If
            # the API loses this run after restart it returns 404, handled above;
            # do not convert an unfamiliar live state into a retryable failure.
            run.runtime_status = status or "UNKNOWN"
            errors.append({"node": node_id, "error": f"未识别的 Hermes 状态 {status or '(empty)'}，等待复核"})
    store.save_instance(inst)
    runtime = _dispatch_ready_runs(store, inst, engine)
    return {"ok": True, "reconciled": reconciled, "errors": errors,
            "runtime": runtime, "instance": inst.to_dict()}


__all__ = ["router"]
