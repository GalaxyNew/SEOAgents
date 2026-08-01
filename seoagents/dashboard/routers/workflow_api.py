"""Workflow API (L2) — templates, instances, and the node editor's data source.

The department picker in a ``dept_request`` node calls
``/api/workflows/departments/{id}/capabilities``, which proxies that
department's own ``/api/v1/capabilities``. Nothing is hardcoded: what you can
ask another department to do is whatever it currently says it can do.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from dojocore.logging import LOGGER
from dojocore.workflow import (
    NODE_SPECS,
    EngineError,
    NodeType,
    TemplateError,
    WorkflowEngine,
    WorkflowInstance,
    WorkflowTemplate,
    get_department_registry,
    get_workflow_store,
)

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
    except TemplateError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    path = _store().save_template(tpl)
    return {"saved": str(path), "template": tpl.to_dict()}


@router.post("/templates/validate")
async def validate_template(payload: dict[str, Any]) -> dict[str, Any]:
    """Dry-run validation, so the composer can show errors before saving."""
    try:
        tpl = WorkflowTemplate.from_dict(payload)
    except TemplateError as exc:
        return {"valid": False, "error": str(exc)}
    return {"valid": True, "summary": tpl.summary(), "layers": tpl.layers()}


# ── instances ────────────────────────────────────────────────────────────
class StartBody(BaseModel):
    template_id: str
    title: str = ""
    context: dict[str, Any] = Field(default_factory=dict)
    parent_task: str = ""


@router.post("/instances", status_code=201)
async def start_instance(body: StartBody) -> dict[str, Any]:
    store = _store()
    tpl = store.template(body.template_id)
    if tpl is None:
        raise HTTPException(status_code=404, detail=f"unknown template '{body.template_id}'")
    inst = WorkflowInstance.start(
        tpl, title=body.title, context=body.context, parent_task=body.parent_task
    )
    WorkflowEngine(tpl).refresh(inst)
    store.save_instance(inst)
    LOGGER.info(f"workflow started: {inst.instance_id} from {tpl.id} v{tpl.version}")
    return inst.to_dict()


@router.get("/instances")
async def list_instances(
    status: str | None = None,
    template_id: str | None = None,
    limit: int = Query(50, le=200),
) -> dict[str, Any]:
    items = _store().instances(status=status, template_id=template_id, limit=limit)
    return {"total": len(items), "items": [i.to_dict() for i in items]}


def _load(instance_id: str):
    store = _store()
    inst = store.instance(instance_id)
    if inst is None:
        raise HTTPException(status_code=404, detail=f"unknown instance '{instance_id}'")
    tpl = store.template(inst.template_id)
    if tpl is None:
        raise HTTPException(
            status_code=409,
            detail=f"实例引用的模板 '{inst.template_id}' 已不存在",
        )
    return store, inst, WorkflowEngine(tpl)


@router.get("/instances/{instance_id}")
async def get_instance(instance_id: str) -> dict[str, Any]:
    _, inst, engine = _load(instance_id)
    return {
        **inst.to_dict(),
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


__all__ = ["router"]
