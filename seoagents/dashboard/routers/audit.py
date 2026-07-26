"""Audit API routes (L2)."""
from __future__ import annotations

import json

from fastapi import APIRouter, Depends

from seoagents.agent.models import ToolCall
from seoagents.agent.runtime import Runtime
from seoagents.dashboard.deps import runtime_dep
from seoagents.dashboard.schemas import AuditRunRequest, GenericResult

router = APIRouter(prefix="/api/audit", tags=["audit"])


@router.post("/run", response_model=GenericResult)
async def run_audit(req: AuditRunRequest, rt: Runtime = Depends(runtime_dep)) -> GenericResult:
    args: dict = {"max_pages": req.max_pages}
    if req.url:
        args["start_url"] = req.url
    res = await rt.executor.execute_one(
        ToolCall(name="site_technical_auditor", arguments=args), session_id="api:audit"
    )
    if not res.ok:
        return GenericResult(ok=False, error=res.error)
    try:
        return GenericResult(ok=True, data=json.loads(res.content))
    except json.JSONDecodeError:
        return GenericResult(ok=True, data={"raw": res.content})


@router.post("/lighthouse", response_model=GenericResult)
async def run_lighthouse(req: AuditRunRequest, rt: Runtime = Depends(runtime_dep)) -> GenericResult:
    args: dict = {}
    if req.url:
        args["target_url"] = req.url
    res = await rt.executor.execute_one(
        ToolCall(name="lighthouse_audit", arguments=args), session_id="api:lighthouse"
    )
    if not res.ok:
        return GenericResult(ok=False, error=res.error)
    return GenericResult(ok=True, data=json.loads(res.content))
