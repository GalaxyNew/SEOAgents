"""Agent 异步任务 API (L2) —— 长任务不能走同步 HTTP。

一次带工具调用的 agent 对话动辄两三分钟(爬站 + Lighthouse + 多轮推理),
而 Cloudflare 的源站超时是 100 秒:超时后返回的是一张 HTML 错误页,
前端 ``JSON.parse`` 直接抛 ``Unexpected token '<'``。用户看到的是
"网络请求异常",实际上后端跑得好好的。

这里把它拆成:提交立刻返回 job_id → 前端轮询进度 → 完成后取结果。
每个 HTTP 请求都在毫秒级,不触碰任何网关超时;副作用是前端能实时看到
agent 正在调哪个工具,比原来干等着强。
"""
from __future__ import annotations

import asyncio
import time
import uuid
from typing import Any

from fastapi import APIRouter, HTTPException

from dojocore.logging import LOGGER
from seoagents.agent.runtime import get_runtime
from seoagents.dashboard.schemas import AgentTaskRequest
from seoagents.multi_agent.orchestrator import AUDITOR, HM, LINKER, WRITER, hm_system_prompt

router = APIRouter(prefix="/api/agent", tags=["agent-jobs"])

_ROLE_MAP = {"auditor": AUDITOR, "writer": WRITER, "linker": LINKER, "hm": HM}

# 内存任务表。进程重启即丢 —— 对"看一眼结果"的场景够用,
# 真要持久化应该落库,但那会把一次对话变成一条业务数据,暂不需要。
_JOBS: dict[str, dict[str, Any]] = {}
_JOB_TTL_SECONDS = 3600
_MAX_JOBS = 200


def _sweep() -> None:
    """清掉过期任务,别让内存无限涨。"""
    now = time.time()
    stale = [k for k, v in _JOBS.items() if now - v.get("created_at", now) > _JOB_TTL_SECONDS]
    for k in stale:
        _JOBS.pop(k, None)
    if len(_JOBS) > _MAX_JOBS:
        for k in sorted(_JOBS, key=lambda x: _JOBS[x].get("created_at", 0))[: len(_JOBS) - _MAX_JOBS]:
            _JOBS.pop(k, None)


async def _run_job(job_id: str, task: str, role_name: str) -> None:
    job = _JOBS[job_id]
    job["status"] = "running"
    job["started_at"] = time.time()
    try:
        rt = get_runtime()
        role = _ROLE_MAP.get(role_name)
        if role is HM:
            system = hm_system_prompt()
        elif role:
            system = role.system_prompt
        else:
            system = "role=default 你是 SEOAgents 的通用 SEO 智能体。"

        result = await rt.loop.run(
            task,
            system=system,
            allowed_tools=set(role.allowed_tools) if role and role.allowed_tools else None,
        )
        job.update(
            status="done",
            ok=result.ok,
            error=result.error,
            final_text=result.final_text,
            turns=result.turns,
            trace=result.trace_dicts(),
            finished_at=time.time(),
        )
        LOGGER.info(f"agent job {job_id} 完成: ok={result.ok} turns={result.turns}")
    except Exception as exc:  # noqa: BLE001 - 任务失败要如实记录,不能让轮询方永远等
        LOGGER.warning(f"agent job {job_id} 异常: {type(exc).__name__}: {exc}")
        job.update(
            status="done",
            ok=False,
            error=f"{type(exc).__name__}: {exc}",
            final_text="",
            turns=0,
            trace=[],
            finished_at=time.time(),
        )


@router.post("/jobs", status_code=202)
async def submit_job(req: AgentTaskRequest) -> dict[str, Any]:
    """提交一次 agent 对话,立刻返回 job_id。"""
    _sweep()
    job_id = f"J-{uuid.uuid4().hex[:12]}"
    _JOBS[job_id] = {
        "job_id": job_id,
        "status": "queued",
        "task": req.task,
        "role": req.role,
        "created_at": time.time(),
    }
    asyncio.create_task(_run_job(job_id, req.task, req.role))
    return {"ok": True, "job_id": job_id, "status": "queued"}


@router.get("/jobs/{job_id}")
async def get_job(job_id: str) -> dict[str, Any]:
    """轮询任务状态。running 时也返回已经跑过的工具,前端好显示进度。"""
    job = _JOBS.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"任务 {job_id} 不存在或已过期")
    elapsed = time.time() - job.get("started_at", job.get("created_at", time.time()))
    out = {
        "ok": True,
        "job_id": job_id,
        "status": job["status"],
        "elapsed_seconds": round(elapsed, 1),
    }
    if job["status"] == "done":
        out.update(
            result_ok=job.get("ok"),
            error=job.get("error"),
            final_text=job.get("final_text"),
            turns=job.get("turns"),
            trace=job.get("trace") or [],
        )
    return out


__all__ = ["router"]
