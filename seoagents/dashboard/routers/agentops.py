"""Agent / skills / evolution operation routes (L2)."""
from __future__ import annotations

from fastapi import APIRouter, Depends

from seoagents.agent.runtime import Runtime
from seoagents.cron.seo_evo_jobs import run_seo_self_evolution_pipeline
from seoagents.dashboard.deps import runtime_dep
from seoagents.dashboard.schemas import (
    AgentTaskRequest,
    GenericResult,
    PipelineRequest,
    SkillReplayRequest,
)
from seoagents.multi_agent.orchestrator import AUDITOR, HM, LINKER, WRITER, hm_system_prompt

_ROLE_MAP = {"auditor": AUDITOR, "writer": WRITER, "linker": LINKER, "hm": HM}

router = APIRouter(prefix="/api", tags=["agent"])


@router.post("/agent/run", response_model=GenericResult)
async def run_agent(req: AgentTaskRequest, rt: Runtime = Depends(runtime_dep)) -> GenericResult:
    role = _ROLE_MAP.get(req.role)
    if role is HM:
        # hm 每次都现读 seohm 的记忆,保证两边始终是同一份
        system = hm_system_prompt()
    elif role:
        system = role.system_prompt
    else:
        system = "role=default 你是 SEOAgents 的通用 SEO 智能体。"
    result = await rt.loop.run(
        req.task,
        system=system,
        allowed_tools=set(role.allowed_tools) if role and role.allowed_tools else None,
    )
    return GenericResult(
        ok=result.ok,
        error=result.error,
        data={
            "final_text": result.final_text,
            "turns": result.turns,
            "trace": result.trace_dicts(),
        },
    )


@router.post("/pipeline/content", response_model=GenericResult)
async def run_content_pipeline(
    req: PipelineRequest, rt: Runtime = Depends(runtime_dep)
) -> GenericResult:
    result = await rt.orchestrator.run_content_pipeline(req.target_url)
    return GenericResult(ok=True, data=result.to_dict())


@router.post("/jobs/evolution/run", response_model=GenericResult)
async def trigger_evolution(rt: Runtime = Depends(runtime_dep)) -> GenericResult:
    summary = await run_seo_self_evolution_pipeline(rt)
    return GenericResult(ok=True, data=summary)


@router.get("/skills", response_model=GenericResult)
def list_skills(rt: Runtime = Depends(runtime_dep)) -> GenericResult:
    return GenericResult(ok=True, data=rt.skill_manager.list_skills())


@router.post("/skills/replay", response_model=GenericResult)
async def replay_skill(req: SkillReplayRequest, rt: Runtime = Depends(runtime_dep)) -> GenericResult:
    try:
        results = await rt.skill_compiler.execute_skill(req.skill_id, rt.executor)
    except KeyError as exc:
        return GenericResult(ok=False, error=str(exc))
    return GenericResult(ok=True, data=results)
