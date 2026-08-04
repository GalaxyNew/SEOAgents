"""技能提案审批 (L2)。

02 号文 §5.3:技能编译改为提案制,由 HM 参数化后签字固化。
编译器只产出提案(落在 `skills_dir/proposals/`),提案在签字前**不可重放** ——
那个隔离做在文件系统层,不是一个状态字段,所以绕不过去。

这里提供人(或 hm)审批用的接口。
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from seoagents.agent.runtime import get_runtime

router = APIRouter(prefix="/api/skills", tags=["skills"])


def _user(request: Request) -> str:
    return getattr(request.state, "user", None) or "unknown"


@router.get("/proposals")
def list_proposals() -> dict[str, Any]:
    """待签字的技能提案。"""
    rt = get_runtime()
    items = []
    for d in rt.skill_manager.list_proposals():
        items.append({
            "id": d.get("id"),
            "description": d.get("description"),
            "compiled_at": d.get("compiled_at"),
            "source": d.get("source") or {},
            "step_count": len(d.get("steps") or []),
            # 步骤原样给出来 —— 签字的人得看清它到底要重放什么,
            # 只给个步数等于让人闭着眼签
            "steps": d.get("steps") or [],
        })
    return {"proposals": items, "total": len(items)}


class ApproveIn(BaseModel):
    description: str = ""
    # 参数化:把轨迹里写死的实参换成要固定下来的值。
    # 形如 {"site_technical_auditor": {"max_pages": 25}}
    overrides: dict[str, dict[str, Any]] = {}


@router.post("/proposals/{skill_id}/approve")
def approve(skill_id: str, body: ApproveIn, request: Request) -> dict[str, Any]:
    rt = get_runtime()
    try:
        path = rt.skill_compiler.approve_proposal(
            skill_id, approved_by=_user(request),
            description=body.description, overrides=body.overrides or None,
        )
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc
    return {"ok": True, "skill_id": skill_id, "path": path,
            "approved_by": _user(request)}


class RejectIn(BaseModel):
    reason: str = ""


@router.post("/proposals/{skill_id}/reject")
def reject(skill_id: str, body: RejectIn, request: Request) -> dict[str, Any]:
    rt = get_runtime()
    try:
        rt.skill_compiler.reject_proposal(
            skill_id, rejected_by=_user(request), reason=body.reason
        )
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc
    return {"ok": True, "skill_id": skill_id, "rejected_by": _user(request)}


@router.get("/active")
def list_active() -> dict[str, Any]:
    """已签字、可重放的技能。内置技能也在其中。"""
    rt = get_runtime()
    return {"skills": rt.skill_manager.list_skills()}


__all__ = ["router"]
