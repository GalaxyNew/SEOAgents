"""分子化工序触发 API (G1-B).

28 号文 §八 G1-B 门禁要求「每个 task 单独 curl 触发返回 200；snapshot 有记录；
同日重跑 skip」——这个 router 就是那个触发面。

路由刻意放在 ``/api/v1/tasks`` 而不是塞进既有的 audit/metrics router：
工序是新的一等公民，编排方（AG、cron、人）需要一个稳定的地方问
「有哪些工序可用」和「跑一下这个」。
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, HTTPException, Query

from seoagents.cron.seo_tasks import (
    DAILY_SEQUENCE,
    SEO_TASKS,
    WEEKLY_SEQUENCE,
    list_tasks,
    run_daily_inspection,
    run_task,
)
from seoagents.storage.snapshot_store import SnapshotStore

router = APIRouter(prefix="/api/v1/tasks", tags=["seo-tasks"])


def _store() -> SnapshotStore:
    from seoagents.agent.runtime import get_runtime

    return SnapshotStore(get_runtime().config.storage.data_dir)


@router.get("")
def api_list_tasks(
    phase: str | None = Query(None, description="phase0..phase6"),
    cadence: str | None = Query(None, description="daily/weekly/on_demand"),
) -> dict[str, Any]:
    return {
        "total": len(SEO_TASKS),
        "tasks": list_tasks(phase=phase, cadence=cadence),
        "daily_sequence": DAILY_SEQUENCE,
        "weekly_sequence": WEEKLY_SEQUENCE,
    }


@router.post("/daily/run")
async def api_run_daily(
    site: str | None = Query(None),
    force: bool = Query(False),
) -> dict[str, Any]:
    """跑整轮每日巡检（等价 v1 流水线，但每步独立可重跑）。

    ⚠️ 这条路由**必须注册在 ``/{task_name}/run`` 之前**：FastAPI 按注册顺序
    匹配，写在后面会被那条通配路由吃掉，`daily` 当成工序名解析成 404。
    """
    return await run_daily_inspection(site=site, force=force)


@router.post("/{task_name}/run")
async def api_run_task(
    task_name: str,
    site: str | None = Query(None, description="站点 URL，缺省取 monitored_sites[0]"),
    force: bool = Query(False, description="true 则忽略当日缓存强制重跑"),
    payload: dict[str, Any] | None = Body(None),
) -> dict[str, Any]:
    """跑单个工序。

    未加 ``force`` 时，同日同站已有可信结果会直接返回 ``skipped=true``，
    **不会发出外部 API 请求**——这是 28 号文 §4.3 的去重纪律。
    """
    if task_name not in SEO_TASKS:
        raise HTTPException(404, f"未知工序 {task_name}；可用：{sorted(SEO_TASKS)}")
    result = await run_task(task_name, site=site, force=force, **(payload or {}))
    return result.to_dict()


@router.get("/snapshots")
def api_snapshots(
    date: str | None = Query(None, description="YYYY-MM-DD，缺省今天"),
    site: str | None = Query(None),
) -> dict[str, Any]:
    """当日快照总览——巡检跑了什么、数据可不可信，一眼看到。"""
    store = _store()
    rows = store.list_snapshots(date=date, site=site)
    return {"date": date or "today", "site": site, "count": len(rows), "snapshots": rows}


@router.get("/snapshots/{task_name}")
def api_snapshot_detail(
    task_name: str,
    site: str | None = Query(None),
    date: str | None = Query(None),
) -> dict[str, Any]:
    from seoagents.agent.runtime import get_runtime

    rt = get_runtime()
    target = site or (
        rt.config.sites.monitored_sites[0].site_url
        if rt.config.sites.monitored_sites else ""
    )
    rec = _store().read_snapshot(site=target, task_name=task_name, date=date)
    if rec is None:
        raise HTTPException(404, f"无快照：{target} / {task_name} / {date or 'today'}")
    rec.pop("data_json", None)
    return rec
