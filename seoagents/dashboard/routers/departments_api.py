"""部门目录 API (L2) —— 我认识哪些别的部门实例。

要区分两个概念:

* ``DepartmentProfile`` / ``config.collab.dept`` 说的是「我自己是哪个部门」,
  由代码在装配时注册,一个实例只有一个。
* 这里管的是 **peer**:别的部门跑在别的机器上,我只知道它的端点和它声称
  提供的能力。工作流里的 ``dept_request`` 节点、collab 的 outbox 都要靠它
  才知道该把工单发去哪。

能力清单不接受手填 —— 只从对方 ``/api/v1/capabilities`` 拉,拉不到就标记
不可达。让人在界面上敲一串能力名,等于允许「声称对方能做某事」,而工作流
会据此把活派过去,到时候失败得莫名其妙。
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from dojocore.logging import LOGGER
from seoagents.agent.runtime import get_runtime

router = APIRouter(prefix="/api/departments", tags=["departments"])

_STORE_PATH = Path(
    os.environ.get("SEOAGENTS_DEPT_STORE", "/data/seo-stack/seoagents-data/departments.json")
)


def _load() -> dict[str, dict[str, Any]]:
    if not _STORE_PATH.is_file():
        return {}
    try:
        return json.loads(_STORE_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        LOGGER.warning(f"部门目录读取失败,按空处理: {exc}")
        return {}


def _save(data: dict[str, dict[str, Any]]) -> None:
    _STORE_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = _STORE_PATH.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, _STORE_PATH)


class DeptIn(BaseModel):
    id: str = Field(..., min_length=1, description="部门标识,如 intel / content")
    display_name: str = ""
    endpoint: str = Field("", description="对方实例的 HTTP 根地址,如 http://10.0.0.5:8765")
    description: str = ""
    enabled: bool = True


class DeptPatch(BaseModel):
    display_name: str | None = None
    endpoint: str | None = None
    description: str | None = None
    enabled: bool | None = None


async def _probe(endpoint: str) -> dict[str, Any]:
    """探对方是否活着,并取回它自己声明的能力。"""
    base = (endpoint or "").rstrip("/")
    if not base:
        return {"reachable": False, "reason": "未配置端点", "capabilities": []}
    url = f"{base}/api/v1/capabilities"
    started = time.time()
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(url)
    except Exception as exc:  # noqa: BLE001 - 网络边界
        return {"reachable": False, "reason": f"{type(exc).__name__}: {exc}", "capabilities": []}
    if resp.status_code != 200:
        return {
            "reachable": False,
            "reason": f"HTTP {resp.status_code}",
            "capabilities": [],
        }
    try:
        payload = resp.json()
    except ValueError:
        return {"reachable": False, "reason": "返回不是 JSON", "capabilities": []}

    # 兼容两种形态:{"capabilities":[...]} 或直接 {cap_id: {...}}
    caps: list[str] = []
    if isinstance(payload, dict):
        raw = payload.get("capabilities", payload)
        if isinstance(raw, list):
            caps = [str(c.get("id") if isinstance(c, dict) else c) for c in raw]
        elif isinstance(raw, dict):
            caps = sorted(raw)
    return {
        "reachable": True,
        "reason": "",
        "capabilities": caps,
        "latency_ms": round((time.time() - started) * 1000),
    }


@router.get("")
async def list_departments() -> dict[str, Any]:
    """部门目录 + 本实例自己的身份。"""
    rt = get_runtime()
    peers = _load()
    return {
        "ok": True,
        "self": {
            "dept": rt.config.collab.dept,
            "display_name": rt.config.collab.display_name,
            "endpoint": rt.config.collab.endpoint or "(未配置对外端点)",
            "note": "这是本实例代表的部门,由 config.collab 决定,不在目录里管理",
        },
        "total": len(peers),
        "items": sorted(peers.values(), key=lambda d: d.get("id", "")),
        "store": str(_STORE_PATH),
    }


@router.post("", status_code=201)
async def add_department(body: DeptIn) -> dict[str, Any]:
    rt = get_runtime()
    if body.id == rt.config.collab.dept:
        raise HTTPException(
            status_code=400,
            detail=f"'{body.id}' 是本实例自己的部门标识,不能作为 peer 加入目录",
        )
    peers = _load()
    if body.id in peers:
        raise HTTPException(status_code=409, detail=f"部门 {body.id} 已存在")
    probe = await _probe(body.endpoint)
    peers[body.id] = {
        "id": body.id,
        "display_name": body.display_name or body.id,
        "endpoint": body.endpoint.rstrip("/"),
        "description": body.description,
        "enabled": body.enabled,
        "created_at": int(time.time()),
        "last_probe_at": int(time.time()),
        **probe,
    }
    _save(peers)
    LOGGER.info(f"部门目录:新增 {body.id} reachable={probe['reachable']}")
    return {"ok": True, "department": peers[body.id]}


@router.patch("/{dept_id}")
async def update_department(dept_id: str, body: DeptPatch) -> dict[str, Any]:
    peers = _load()
    if dept_id not in peers:
        raise HTTPException(status_code=404, detail=f"部门 {dept_id} 不存在")
    fields = {k: v for k, v in body.model_dump().items() if v is not None}
    if "endpoint" in fields:
        fields["endpoint"] = str(fields["endpoint"]).rstrip("/")
    peers[dept_id].update(fields)
    if "endpoint" in fields:
        probe = await _probe(fields["endpoint"])
        peers[dept_id].update(probe)
        peers[dept_id]["last_probe_at"] = int(time.time())
    _save(peers)
    return {"ok": True, "department": peers[dept_id]}


@router.delete("/{dept_id}")
async def delete_department(dept_id: str) -> dict[str, Any]:
    peers = _load()
    if dept_id not in peers:
        raise HTTPException(status_code=404, detail=f"部门 {dept_id} 不存在")
    peers.pop(dept_id)
    _save(peers)
    return {"ok": True, "deleted": dept_id}


@router.post("/{dept_id}/probe")
async def probe_department(dept_id: str) -> dict[str, Any]:
    """重新探一次:能力清单以对方当前声明为准,不吃缓存。"""
    peers = _load()
    if dept_id not in peers:
        raise HTTPException(status_code=404, detail=f"部门 {dept_id} 不存在")
    probe = await _probe(peers[dept_id].get("endpoint", ""))
    peers[dept_id].update(probe)
    peers[dept_id]["last_probe_at"] = int(time.time())
    _save(peers)
    return {"ok": True, "department": peers[dept_id]}


@router.post("/probe-all")
async def probe_all() -> dict[str, Any]:
    peers = _load()
    for dept_id, item in peers.items():
        probe = await _probe(item.get("endpoint", ""))
        item.update(probe)
        item["last_probe_at"] = int(time.time())
    _save(peers)
    reachable = sum(1 for i in peers.values() if i.get("reachable"))
    return {"ok": True, "total": len(peers), "reachable": reachable,
            "items": sorted(peers.values(), key=lambda d: d.get("id", ""))}


__all__ = ["router"]
