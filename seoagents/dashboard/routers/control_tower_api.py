"""总控大屏模块 API（登录鉴权）。

提供模块最新结果、历史趋势、问题诊断、巡检门禁的只读接口。
与 public_seo_control_tower 不同，这组接口需要管理员会话，返回完整数据
（含指标点、findings、attempt 历史），供卡片详情和放大视图使用。
"""
from __future__ import annotations

import os
from typing import Any

from fastapi import APIRouter, HTTPException, Query

from seoagents.agent.runtime import get_runtime
from seoagents.control_tower import ControlTowerStore

router = APIRouter(prefix="/api/control-tower", tags=["control-tower"])

_DEFAULT_DATA_DIR = "/data/seo-stack/seoagents-data"


def _store() -> ControlTowerStore:
    return ControlTowerStore(os.environ.get("SEO_CONTROL_TOWER_DATA_DIR", _DEFAULT_DATA_DIR))


def _allowed_site_ids() -> set[str]:
    """Return configured hostnames only; never infer a property from request input."""
    allowed: set[str] = set()
    for site in get_runtime().config.sites.monitored_sites:
        raw = site.site_url.removeprefix("https://").removeprefix("http://")
        host = raw.split("/", 1)[0].split(":", 1)[0].lower().removeprefix("www.")
        if host:
            allowed.add(host)
    return allowed


def _validate_scope(site_id: str, module_id: str) -> tuple[str, str]:
    normalized_site = site_id.lower().removeprefix("www.")
    if normalized_site not in _allowed_site_ids():
        raise HTTPException(404, "站点未配置或无权访问")
    if module_id not in _VALID_MODULES:
        raise HTTPException(422, f"未知模块 ID: {module_id}")
    return normalized_site, module_id


_VALID_MODULES = {
    "gsc", "ga4", "psi", "technical", "indexing",
    "content", "execution", "aeo", "inspection",
}


@router.head("/sites/{site_id}/modules/{module_id}/latest", include_in_schema=False)
@router.get("/sites/{site_id}/modules/{module_id}/latest")
def get_latest_module_result(site_id: str, module_id: str) -> dict[str, Any]:
    """获取指定站点的最新模块运行结果（含指标、维度、问题诊断）。"""
    site_id, module_id = _validate_scope(site_id, module_id)
    store = _store()
    result = store.latest(site_id, module_id)
    if result is None:
        raise HTTPException(404, f"模块 {module_id} 尚无运行记录（site={site_id}）")
    return result


@router.head("/sites/{site_id}/modules/{module_id}/history", include_in_schema=False)
@router.get("/sites/{site_id}/modules/{module_id}/history")
def get_module_history(
    site_id: str,
    module_id: str,
    start: str | None = Query(None, description="起始日期 YYYY-MM-DD"),
    end: str | None = Query(None, description="截止日期 YYYY-MM-DD"),
    limit: int = Query(30, ge=1, le=366),
) -> dict[str, Any]:
    """获取模块历史趋势序列，用于 D0/D-1/N 日对比和趋势图。"""
    site_id, module_id = _validate_scope(site_id, module_id)
    store = _store()
    items = store.history(site_id, module_id, start=start, end=end, limit=limit)
    return {
        "site_id": site_id,
        "module_id": module_id,
        "count": len(items),
        "items": items,
    }


@router.head(
    "/sites/{site_id}/modules/{module_id}/attempts/{module_run_id}",
    include_in_schema=False,
)
@router.get("/sites/{site_id}/modules/{module_id}/attempts/{module_run_id}")
def get_attempts(site_id: str, module_id: str, module_run_id: str) -> dict[str, Any]:
    """获取某次逻辑运行的全部重试记录（attempt）。"""
    site_id, module_id = _validate_scope(site_id, module_id)
    store = _store()
    items = store.attempts(module_run_id)
    if not items:
        raise HTTPException(404, f"逻辑运行 {module_run_id} 不存在")
    # 防止跨站点泄漏
    if (
        items[0].get("site_id") != site_id
        or items[0].get("module_id") != module_id
    ):
        raise HTTPException(403, "站点或模块不匹配")
    return {
        "site_id": site_id,
        "module_id": module_id,
        "module_run_id": module_run_id,
        "count": len(items),
        "items": items,
    }


@router.head(
    "/sites/{site_id}/modules/{module_id}/by-date/{business_date}",
    include_in_schema=False,
)
@router.get("/sites/{site_id}/modules/{module_id}/by-date/{business_date}")
def get_by_date(site_id: str, module_id: str, business_date: str) -> dict[str, Any]:
    """按业务日期查询模块结果。"""
    site_id, module_id = _validate_scope(site_id, module_id)
    store = _store()
    result = store.by_business_date(site_id, module_id, business_date)
    if result is None:
        raise HTTPException(
            404,
            f"模块 {module_id} 在 {business_date} 无运行记录（site={site_id}）",
        )
    return result


__all__ = ["router"]
