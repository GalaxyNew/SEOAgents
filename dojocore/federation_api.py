"""联邦节点标准端点（dojocore 框架层）。

指挥中心靠这三个端点发现并监控每个部门节点。契约来自
console-migration/04-功能文档.md §F1-F3 与 05-开发文档.md §轮询端点：

    GET /api/v1/healthz           存活 + 健康灯
    GET /api/v1/inbox/summary     在办 / 今日交付 / 停滞 / 阻塞 计数
    GET /api/v1/timeline?limit=N  最新时间线事件

设计取舍：

1. 部门已有的 ``/api/v1/inbox``（明细）与 ``/api/timeline/*``（日程视图）保持
   不动，本模块只补「指挥中心视角」的聚合形态。既有 ``/inbox`` 的返回形状是
   明细列表，硬塞一个 summary 字典进去会让所有已接入调用方的类型校验失败，
   所以另开 ``/inbox/summary`` 而不是加 ``?summary=true`` 查询参数。

2. dojocore 不 import 任何部门包（ADR-02）。本模块只依赖 dojocore.collab /
   dojocore.timeline / dojocore.capability，部门通过 ``install_federation_meta()``
   注入自己的 dept_id 与版本号。

3. 三个端点都不抛异常。探活接口自己 500 会让指挥中心把「部分子系统降级」
   误判成「整机失联」，进而触发错误的熔断。降级信息走 ``data_status`` 字段
   （REAL / DEGRADED / UNAVAILABLE），遵循 quality.py 的四态约定。
"""
from __future__ import annotations

import datetime as _dt
import os
import time
from typing import Any

from fastapi import APIRouter, Query

from dojocore.logging import LOGGER

router = APIRouter(prefix="/api/v1", tags=["federation"])

_BOOT_TS = time.time()

_DEPT_META: dict[str, Any] = {
    "dept": os.environ.get("DOJO_DEPT_ID", "unknown"),
    "name": "",
    "version": "v2",
}


def install_federation_meta(dept: str, name: str = "", version: str = "v2") -> None:
    """部门启动时登记自己的身份（在 create_app 里调一次）。"""
    _DEPT_META["dept"] = dept
    _DEPT_META["name"] = name or dept
    _DEPT_META["version"] = version
    LOGGER.info(f"联邦节点身份已登记: dept={dept} name={_DEPT_META['name']}")


# ── 健康灯 ────────────────────────────────────────────────────────────────
def _probe_subsystems() -> tuple[str, dict[str, str]]:
    """绿=全就绪 / 黄=核心在但有降级 / 红=核心不可用。"""
    subs: dict[str, str] = {}

    try:
        from dojocore.collab import get_collab_service
        svc = get_collab_service()
        svc.store.list(box="inbox", limit=1)
        subs["collab"] = "ok"
    except Exception as exc:  # noqa: BLE001
        subs["collab"] = f"fail:{type(exc).__name__}"

    try:
        from dojocore.timeline import get_timeline
        get_timeline().store.recent(limit=1)
        subs["timeline"] = "ok"
    except Exception as exc:  # noqa: BLE001
        subs["timeline"] = f"degraded:{type(exc).__name__}"

    try:
        # capabilities 是模块级单例实例(capability.py:108)，不是工厂函数。
        # 写成 capabilities() 会 TypeError，健康灯永远停在 yellow。
        from dojocore.capability import capabilities
        subs["capabilities"] = f"ok:{len(capabilities.list())}"
    except Exception as exc:  # noqa: BLE001
        subs["capabilities"] = f"degraded:{type(exc).__name__}"

    try:
        # 只数在办卡，不拉证据链 —— 健康探针每 15 秒跑一次，必须轻。
        # 账本不可用记 degraded 而非 fail：部门丢了台账仍能干活，
        # 丢了 collab 才是联邦意义上的失联。
        from dojocore.taskcard import get_taskcards
        subs["taskcard"] = f"ok:{len(get_taskcards().store.active())}"
    except Exception as exc:  # noqa: BLE001
        subs["taskcard"] = f"degraded:{type(exc).__name__}"

    if subs.get("collab", "").startswith("fail"):
        light = "red"
    elif any(v.startswith(("fail", "degraded")) for v in subs.values()):
        light = "yellow"
    else:
        light = "green"
    return light, subs


@router.get("/healthz")
async def federation_healthz() -> dict[str, Any]:
    """存活 + 健康灯。指挥中心 15s 轮询一次。"""
    try:
        light, subs = _probe_subsystems()
    except Exception as exc:  # noqa: BLE001
        LOGGER.warning(f"healthz probe failed: {exc}")
        light, subs = "red", {"probe": f"fail:{type(exc).__name__}"}

    return {
        "status": "ok" if light != "red" else "degraded",
        "light": light,
        "dept": _DEPT_META["dept"],
        "name": _DEPT_META["name"],
        "version": _DEPT_META["version"],
        "uptime_sec": int(time.time() - _BOOT_TS),
        "subsystems": subs,
        "ts": int(time.time()),
    }


# ── inbox 摘要 ────────────────────────────────────────────────────────────
# 状态取自 dojocore.collab.models.RequestStatus，10 态封闭集。
_ACTIVE = {"PENDING", "ACCEPTED", "IN_PROGRESS"}
_BLOCKED = {"BLOCKED", "REJECTED", "RETURNED", "ESCALATED", "EXPIRED"}
_DONE = {"DELIVERED", "CLOSED"}


def _iso_day(value: Any) -> str:
    """从各种时间字段里取出 YYYY-MM-DD，取不到返回空串。"""
    if not value:
        return ""
    s = str(value)
    if len(s) >= 10 and s[4] == "-" and s[7] == "-":
        return s[:10]
    try:  # epoch 秒
        return _dt.datetime.fromtimestamp(float(s)).strftime("%Y-%m-%d")
    except (TypeError, ValueError, OSError):
        return ""


def _summarize(reqs: list[Any]) -> dict[str, int]:
    today = _dt.date.today().isoformat()
    active = delivered_today = stalled = blocked = 0

    for r in reqs:
        st = str(getattr(r, "status", "") or "").upper()
        st = st.rsplit(".", 1)[-1]  # 兼容 "RequestStatus.PENDING"

        if st in _ACTIVE:
            active += 1
            try:
                if r.is_overdue():
                    stalled += 1
            except Exception:  # noqa: BLE001
                pass
        if st in _BLOCKED:
            blocked += 1
        if st in _DONE:
            d = getattr(r, "updated_at", "") or getattr(r, "delivered_at", "")
            if _iso_day(d) == today:
                delivered_today += 1

    return {"active": active, "delivered_today": delivered_today,
            "stalled": stalled, "blocked": blocked}


def _taskcard_summary() -> dict[str, Any]:
    """本部门任务卡计数。账本不可用时如实说，绝不补零。

    补零会让指挥中心把「账本挂了」显示成「今天没活」——那是数据铁律
    要防的第一种谎。
    """
    try:
        from dojocore.taskcard import get_taskcards
        svc = get_taskcards()
        counts = svc.store.counts_by_status()
        return {
            "data_status": "REAL",
            "total": sum(counts.values()),
            "active": len(svc.store.active()),
            "stalled": len(svc.store.stalled()),
            "blocked": counts.get("BLOCKED", 0),
            "review": counts.get("REVIEW", 0),
            "audit_flagged": len(svc.audit()),
        }
    except Exception as exc:  # noqa: BLE001
        LOGGER.warning(f"taskcard summary unavailable: {exc}")
        return {
            "data_status": "UNAVAILABLE",
            "reason": f"{type(exc).__name__}: {exc}"[:200],
        }


@router.get("/inbox/summary")
async def inbox_summary() -> dict[str, Any]:
    """指挥中心宫格卡用的聚合计数（6 项实时信息中的 4 项）。"""
    # 两个数据源各自独立降级。曾经 collab 一抛异常就整体早退，
    # 结果任务卡数据明明健在也一起消失 —— 邻居坏了不该让自己也隐形。
    try:
        from dojocore.collab import get_collab_service
        store = get_collab_service().store
        inbox = store.list(box="inbox", limit=500)
        outbox = store.list(box="outbox", limit=500)
    except Exception as exc:  # noqa: BLE001
        LOGGER.warning(f"inbox summary unavailable: {exc}")
        return {
            "dept": _DEPT_META["dept"],
            "data_status": "UNAVAILABLE",
            "reason": f"{type(exc).__name__}: {exc}"[:200],
            # collab 不可用不代表台账也不可用：这一半仍照常给。
            "taskcards": _taskcard_summary(),
            "ts": int(time.time()),
        }

    s_in = _summarize(inbox)
    s_out = _summarize(outbox)
    return {
        "dept": _DEPT_META["dept"],
        "data_status": "REAL",
        "inbox": s_in,
        "outbox": s_out,
        # 本部门自己的台账。与 inbox/outbox 是不同的东西：收发件箱记跨部门
        # 委托，任务卡记本部门在干什么。指挥中心此前只看得到前者，
        # 于是「部门在干什么」的全貌一直缺一半。
        "taskcards": _taskcard_summary(),
        # 顶层扁平字段：指挥中心宫格卡直接取用，免去客户端再拆一层。
        # 口径必须统一为 inbox 视角（本部门要干的活）——曾经把 stalled/blocked
        # 写成 inbox+outbox 相加而 in_progress 只取 inbox，宫格上出现过
        # 「停滞 2 > 在办 1」的自相矛盾读数（停滞本是在办的子集）。
        # outbox 是本部门委托别人干的活，不计入「本部门在办」，
        # 其明细仍保留在嵌套的 outbox 字段里供单独取用。
        "in_progress": s_in["active"],
        "delivered_today": s_in["delivered_today"],
        "stalled": s_in["stalled"],
        "blocked": s_in["blocked"],
        "ts": int(time.time()),
    }


# ── timeline ─────────────────────────────────────────────────────────────
@router.get("/timeline")
async def federation_timeline(limit: int = Query(5, ge=1, le=50)) -> dict[str, Any]:
    """最新 N 条时间线事件（指挥中心作战大屏用）。

    与部门内部 ``/api/timeline/agenda`` 的区别：那个是日程视图（含未来待办），
    这个是事件流（只回溯已发生）。指挥中心不关心别的部门明天要干嘛。
    """
    try:
        from dojocore.timeline import get_timeline
        nodes = get_timeline().store.recent(limit=limit)
    except Exception as exc:  # noqa: BLE001
        return {
            "dept": _DEPT_META["dept"],
            "data_status": "UNAVAILABLE",
            "reason": f"{type(exc).__name__}: {exc}"[:200],
            "count": 0,
            "events": [],
            "ts": int(time.time()),
        }

    events = []
    for n in nodes[:limit]:
        state = str(getattr(n, "state", "") or "").rsplit(".", 1)[-1]
        kind = str(getattr(n, "kind", "") or "").rsplit(".", 1)[-1]
        events.append({
            "ts": getattr(n, "acked_at", "") or getattr(n, "fired_at", "")
                  or getattr(n, "created_at", "") or getattr(n, "scheduled_at", ""),
            "node_id": getattr(n, "node_id", ""),
            "kind": kind,
            "state": state,
            "summary": (getattr(n, "intent", "") or "")[:200],
            "outcome": (getattr(n, "outcome", "") or "")[:200],
            "ref": getattr(n, "subject_ref", ""),
        })

    return {
        "dept": _DEPT_META["dept"],
        "data_status": "REAL" if events else "DEGRADED",
        "reason": "" if events else "timeline 无事件（v1 遗留：0 行数据）",
        "count": len(events),
        "events": events,
        "ts": int(time.time()),
    }


# ── 任务卡联邦投影 ────────────────────────────────────────────────────────
@router.get("/taskcards/federation")
async def federation_taskcards(
    limit: int = Query(50, ge=1, le=200),
    status: str = Query("active", description="active | all"),
) -> dict[str, Any]:
    """指挥中心聚合专用的精简投影。

    刻意不返回 evidence 与 meta：指挥中心每 15 秒轮询 12 个节点，把完整
    证据链拉过来只为在宫格上显示一行标题，是拿带宽换不需要的细节。
    需要全文时客户端再单点取 ``/api/v1/taskcards/{card_id}``。
    """
    try:
        from dojocore.taskcard import get_taskcards
        svc = get_taskcards()
        cards = svc.store.active() if status == "active" else svc.store.recent(limit=limit)
    except Exception as exc:  # noqa: BLE001
        LOGGER.warning(f"federation taskcards unavailable: {exc}")
        return {
            "dept": _DEPT_META["dept"],
            "data_status": "UNAVAILABLE",
            "reason": f"{type(exc).__name__}: {exc}"[:200],
            "count": 0,
            "cards": [],
            "ts": int(time.time()),
        }

    projection = [
        {
            "card_id": c.card_id,
            "title": c.title[:120],
            "status": c.status.value,
            "status_label": c.status.label,
            "level": c.level.value,
            "priority": c.priority.value,
            "owner": c.owner,
            "parent_card": c.parent_card,
            "collab_req": c.collab_req,
            "github_issue": c.github_issue,
            "deadline": c.deadline,
            "updated_at": c.updated_at,
            # 布尔而非完整清单：宫格只需要知道该不该标红。
            "has_audit_flags": bool(c.audit_flags()),
        }
        for c in cards[:limit]
    ]
    return {
        "dept": _DEPT_META["dept"],
        "data_status": "REAL",
        "count": len(projection),
        "cards": projection,
        "ts": int(time.time()),
    }


# ── capabilities 已由 collab_api 提供，此处不重复注册 ──────────────────────
