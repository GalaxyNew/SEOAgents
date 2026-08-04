"""到点执行 —— 时间线节点的消费者 (L2)。

在此之前没有任何东西消费 due 节点:排了期,时间到了,节点静静躺在
SCHEDULED 状态里。界面上能新建定时任务,但那是个**不会响的闹钟**。

这个 runner 每分钟扫一次到期节点,按 `context` 里声明的执行方式分派:

* ``agent_task`` —— 一条自然语言指令,交给 hm 跑
* ``workflow_id`` —— 到点启动某个工作流
* 都没有 —— 只投递不执行,留给人处理(提醒类节点本该如此)

三个刻意的决定:

* **ack 必须写真实结果**。`ack()` 强制要求 outcome 是对的,但如果这里
  统一填「已执行」,那个门禁就被架空了。成功写摘要,失败写失败原因。
* **失败不重试**。到点没跑成的任务,再跑一次多半还是不成,反而会在下一
  分钟继续撞同一个错。ack 成失败结果、留痕,由人决定要不要重排。
* **单个节点失败不影响其他节点**。一个坏节点不该让整批到期任务卡住。
"""
from __future__ import annotations

import datetime as _dt
from typing import Any

from dojocore.logging import LOGGER
from dojocore.timeline import get_timeline

RUNNER_JOB_ID = "timeline_due_runner"


async def _run_agent_task(rt: Any, instruction: str, role_name: str) -> str:
    """把指令交给 agent 跑,返回给 outcome 用的摘要。

    走和 `/api/agent/jobs` 完全相同的装配方式(角色系统提示 + 工具白名单)——
    定时执行和手动执行如果走两条路,行为迟早会分叉。
    """
    from seoagents.dashboard.routers.agent_jobs import _ROLE_MAP
    from seoagents.multi_agent.orchestrator import HM, hm_system_prompt

    role = _ROLE_MAP.get(role_name or "hm")
    if role is HM:
        system = hm_system_prompt()
    elif role:
        system = role.system_prompt
    else:
        system = "role=default 你是 SEOAgents 的通用 SEO 智能体。"

    result = await rt.loop.run(
        instruction,
        system=system,
        allowed_tools=set(role.allowed_tools) if role and role.allowed_tools else None,
    )
    text = (result.final_text or "").strip()
    head = "完成" if result.ok else f"失败({result.error})"
    return f"[{role_name or 'hm'}] {head} · {result.turns} 轮 · {text[:160] or '(无文本输出)'}"


async def _run_workflow(rt: Any, template_id: str) -> str:
    import httpx

    async with httpx.AsyncClient(timeout=30.0, base_url="http://127.0.0.1:8765") as c:
        r = await c.post("/api/workflow/instances",
                         json={"template_id": template_id},
                         headers={"X-Service-Token": _service_token()})
        if r.status_code >= 400:
            return f"工作流 {template_id} 启动失败: HTTP {r.status_code} {r.text[:120]}"
        d = r.json()
    return f"工作流 {template_id} 已启动 · 实例 {d.get('instance_id') or d.get('id') or '?'}"


def _service_token() -> str:
    import os

    return os.environ.get("SEOAGENTS_SERVICE_TOKEN", "")


async def run_due_nodes(runtime: Any = None) -> dict[str, Any]:
    """扫一遍到期节点并执行。返回本轮处理情况,供巡检查看。"""
    from seoagents.agent.runtime import get_runtime

    rt = runtime or get_runtime()
    tl = get_timeline(rt.config, owner="seoagents")

    # 先扫一遍失约的。fire() 与 ack() 之间如果进程中断,节点会永远停在 FIRED,
    # 而 due() 只看 SCHEDULED —— 没人会再捡起它。sweep 正是为这个设计的:
    # MISSED = 调度器没跑,UNACKED = 跑了但没人处理,两者指向不同的故障部件。
    try:
        swept = tl.sweep(grace_minutes=10)
        if swept["missed"] or swept["unacked"]:
            LOGGER.warning(
                f"时间线失约:未触发 {len(swept['missed'])} 个,"
                f"已投递未处理 {len(swept['unacked'])} 个 —— 已转入待分诊"
            )
    except Exception as exc:  # noqa: BLE001
        LOGGER.warning(f"时间线 sweep 失败: {exc}")

    due = tl.due()
    if not due:
        return {"checked_at": _dt.datetime.now(_dt.timezone.utc).isoformat(),
                "due": 0, "executed": 0, "failed": 0, "results": []}

    results: list[dict[str, Any]] = []
    ok_count = fail_count = 0
    for node in due:
        ctx = dict(node.context or {})
        try:
            tl.fire(node.node_id)
        except Exception as exc:  # noqa: BLE001 - 状态不对就跳过,别拖累其他节点
            LOGGER.warning(f"节点 {node.node_id} 投递失败: {exc}")
            continue

        instruction = str(ctx.get("agent_task") or "").strip()
        workflow_id = str(ctx.get("workflow_id") or "").strip()
        try:
            if instruction:
                outcome = await _run_agent_task(rt, instruction, str(ctx.get("role") or "hm"))
            elif workflow_id:
                outcome = await _run_workflow(rt, workflow_id)
            else:
                # 提醒类节点:投递了就算到位,执行与否由人决定。
                # 这里如实写「未声明执行方式」,而不是含糊地写「已处理」。
                outcome = "已投递提醒 · 该节点未声明执行方式,等待人工处理"
            ok_count += 1
        except Exception as exc:  # noqa: BLE001 - API 边界
            # 失败也要 ack,并写清失败原因。不重试:到点没跑成的,
            # 下一分钟多半还是同样的错,只会刷屏。
            outcome = f"执行失败: {type(exc).__name__}: {exc}"
            fail_count += 1
            LOGGER.exception(f"时间线节点 {node.node_id} 执行失败")

        try:
            tl.ack(node.node_id, outcome=outcome)
        except Exception as exc:  # noqa: BLE001
            LOGGER.warning(f"节点 {node.node_id} 确认失败: {exc}")
        results.append({"node_id": node.node_id, "intent": node.intent,
                        "outcome": outcome[:200]})

    LOGGER.info(f"时间线到期执行:{len(due)} 个,成功 {ok_count},失败 {fail_count}")
    return {
        "checked_at": _dt.datetime.now(_dt.timezone.utc).isoformat(),
        "due": len(due), "executed": ok_count, "failed": fail_count,
        "results": results,
    }


def register_timeline_runner(runtime: Any) -> None:
    """每分钟扫一次。间隔要短 —— 定时任务迟到十分钟,人就不信它了。"""
    try:
        from apscheduler.triggers.interval import IntervalTrigger
    except ImportError:
        LOGGER.warning("APScheduler 未安装 —— 时间线到点执行不可用")
        return
    from seoagents.cron import scheduler

    scheduler.add_job(
        run_due_nodes,
        IntervalTrigger(minutes=1),
        id=RUNNER_JOB_ID,
        replace_existing=True,
        max_instances=1,          # 上一轮没跑完就跳过,避免同一节点被重复执行
        coalesce=True,
    )
    LOGGER.info("时间线到期执行器已注册(每分钟)")


__all__ = ["RUNNER_JOB_ID", "register_timeline_runner", "run_due_nodes"]
