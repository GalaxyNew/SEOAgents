"""中央存储与资产台账 API (L2)。

界面上要能回答三个问题:东西存在哪(节点)、还剩多少额度(配额)、
谁产出的能不能回滚(台账)。三者共用一套底层,所以放在同一个路由里。

写入接口刻意只暴露 ``put_asset`` 一条路 —— 裸 ``put`` 不开放给界面。
存了东西却不登记,就是在造下一个「不知道这是谁的、能不能删」的对象。
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from seoagents.storage import asset_hub, asset_registry, quota

router = APIRouter(prefix="/api/storage", tags=["storage"])


# ── 节点与配额 ────────────────────────────────────────────────────────
@router.get("/nodes")
def list_nodes() -> dict[str, Any]:
    """节点清单。凭证不在注册表里,所以整份返回都可以安全展示。"""
    nodes = asset_hub.load_nodes()
    out = []
    for nid, n in nodes.items():
        c = quota.check(n)
        out.append({
            "id": nid,
            "label": n.get("label", nid),
            "kind": n.get("kind", "s3"),
            "endpoint": n.get("endpoint", ""),
            "bucket": n.get("bucket", ""),
            "kinds": n.get("kinds", []),
            "enabled": n.get("enabled", True),
            "default": n.get("default", False),
            "writable": c["writable"],
            "block_reason": c["reason"] if not c["writable"] else "",
            "quota": n.get("quota", {}),
            "ratios": c["ratios"],
        })
    out.sort(key=lambda x: (not x["default"], x["id"]))
    return {"nodes": out, "total": len(out)}


@router.get("/quota")
def quota_report() -> dict[str, Any]:
    """用量、占比、月底预估、是否已转只读。"""
    return quota.report(asset_hub.load_nodes())


@router.get("/quota/{node_id}/history")
def quota_history(node_id: str, limit: int = 6) -> dict[str, Any]:
    return {"node": node_id, "history": quota.history(node_id, limit=limit),
            "forecast": quota.forecast(node_id)}


@router.get("/health")
def health() -> dict[str, Any]:
    """逐节点连通性实测 —— 不是读配置,是真发一次请求。"""
    return asset_hub.health()


@router.get("/objects")
def list_objects(prefix: str = "", node_id: str = "", limit: int = 200) -> dict[str, Any]:
    try:
        items = asset_hub.listing(prefix, node_id=node_id, limit=limit)
    except asset_hub.AssetHubError as exc:
        raise HTTPException(502, str(exc)) from exc
    return {"prefix": prefix, "node": node_id or "(默认)", "objects": items,
            "total": len(items)}


# ── 资产台账 ──────────────────────────────────────────────────────────
class AssetIn(BaseModel):
    name: str
    content: str
    dept: str
    task_id: str
    owner_agent: str
    summary: str
    usage: str
    source_evidence: str
    kind: str = "misc"
    level: str = Field("L1", pattern="^L[0-3]$")
    asset_class: str = "DOC"
    content_type: str = "text/plain"
    node_id: str = ""
    rollback: str = ""
    review_cycle: str = "90d"


@router.post("/assets")
def create_asset(body: AssetIn) -> dict[str, Any]:
    """存储 + 登记一步完成。L3 会真实镜像到第二个节点后才登记。

    L3 缺备份返回 422 与错误码 ``L3_REQUIRES_BACKUP`` —— 界面据此提示,
    不要把它当成一般的 500 吞掉。
    """
    try:
        return asset_hub.put_asset(
            body.content, dept=body.dept, name=body.name, kind=body.kind,
            level=body.level, task_id=body.task_id, owner_agent=body.owner_agent,
            summary=body.summary, usage=body.usage,
            source_evidence=body.source_evidence, asset_class=body.asset_class,
            content_type=body.content_type, node_id=body.node_id,
            rollback=body.rollback, review_cycle=body.review_cycle,
        )
    except asset_registry.AssetError as exc:
        raise HTTPException(422, detail={"code": "L3_REQUIRES_BACKUP", "message": str(exc)}) from exc
    except asset_hub.AssetHubError as exc:
        msg = str(exc)
        code = "L3_REQUIRES_BACKUP" if "异地备份" in msg else "STORAGE_WRITE_FAILED"
        raise HTTPException(422 if code.startswith("L3") else 502,
                            detail={"code": code, "message": msg}) from exc


class DeclareIn(BaseModel):
    """声明一份已经存在于别处的资产(git 仓库、服务器配置、飞书文档……)。

    与 ``/assets`` 的区别:那条会真的把内容存进中央存储并自动做 L3 镜像;
    这条只登记,本体不归我们管。正因为本体在外面,L3 的备份与回滚必须由
    声明者写清楚 —— 系统没法替它造一个备份出来。
    """
    name: str
    location: str
    dept: str
    task_id: str
    owner_agent: str
    summary: str
    usage: str
    source_evidence: str
    level: str = Field("L1", pattern="^L[0-3]$")
    asset_class: str = "DOC"
    location_type: str = "git"
    backup_location: str = ""
    rollback: str = ""
    review_cycle: str = ""


@router.post("/assets/declare")
def declare_asset(body: DeclareIn) -> dict[str, Any]:
    """只登记不搬运。L3 缺备份三项 → 422 / ``L3_REQUIRES_BACKUP``。"""
    try:
        return asset_registry.register(
            name=body.name, cls=body.asset_class, level=body.level,
            task_id=body.task_id, owner_department=body.dept,
            owner_agent=body.owner_agent, location=body.location,
            location_type=body.location_type, summary=body.summary,
            usage=body.usage, source_evidence=body.source_evidence,
            backup_location=body.backup_location, rollback=body.rollback,
            review_cycle=body.review_cycle,
        )
    except asset_registry.AssetError as exc:
        raise HTTPException(422, detail={"code": "L3_REQUIRES_BACKUP", "message": str(exc)}) from exc


@router.get("/assets")
def list_assets(level: str = "", cls: str = "", status: str = "",
                department: str = "", limit: int = 100) -> dict[str, Any]:
    rows = asset_registry.listing(level=level, cls=cls, status=status,
                                  department=department, limit=limit)
    return {"assets": rows, "total": len(rows), "stats": asset_registry.stats()}


@router.get("/assets/stats")
def asset_stats() -> dict[str, Any]:
    return asset_registry.stats()


@router.get("/assets/events")
def asset_events(asset_id: str = "", limit: int = 100) -> dict[str, Any]:
    """审计轨迹。不给 asset_id 就是全量时间线。

    ⚠️ 这个函数必须定义在 ``/assets/{asset_id}`` **之前**。FastAPI 按定义
    顺序匹配,反过来的话 "events" 会被当成一个 asset_id 吃掉,永远 404。

    只读 —— 审计没有修改与删除接口,能改的审计等于没有审计。
    """
    rows = asset_registry.events(asset_id, limit=limit)
    return {"events": rows, "total": len(rows), "asset_id": asset_id or "(全部)"}


@router.get("/assets/{asset_id}")
def get_asset(asset_id: str) -> dict[str, Any]:
    row = asset_registry.get(asset_id)
    if not row:
        raise HTTPException(404, f"资产不存在: {asset_id}")
    return row


@router.get("/assets/{asset_id}/content")
def get_asset_content(asset_id: str) -> dict[str, Any]:
    """按台账记的位置把本体取回来,顺带核对 checksum。

    校验不通过不报错、只标 ``checksum_match: false`` —— 内容可能被合法更新过
    而台账没跟上。是哪种情况得看人,系统不该替它下判断。
    """
    row = asset_registry.get(asset_id)
    if not row:
        raise HTTPException(404, f"资产不存在: {asset_id}")
    try:
        raw = asset_hub.get(row["location"], node_id=row.get("storage_node") or "")
    except asset_hub.AssetHubError as exc:
        raise HTTPException(502, f"取回失败: {exc}") from exc
    import hashlib

    actual = f"sha256:{hashlib.sha256(raw).hexdigest()}"
    return {
        "asset_id": asset_id,
        "content": raw.decode("utf-8", errors="replace"),
        "size": len(raw),
        "checksum_recorded": row.get("checksum"),
        "checksum_actual": actual,
        "checksum_match": row.get("checksum") == actual,
    }


class VerifyIn(BaseModel):
    verified_by: str


@router.post("/assets/{asset_id}/verify")
def verify_asset(asset_id: str, body: VerifyIn) -> dict[str, Any]:
    """终验。刻意不提供改 level 的入口:声明是 L3 就得按 L3 验。"""
    try:
        return asset_registry.verify(asset_id, verified_by=body.verified_by)
    except asset_registry.AssetError as exc:
        raise HTTPException(422, detail={"code": "VERIFY_REJECTED", "message": str(exc)}) from exc


@router.post("/assets/{asset_id}/restore")
def restore_asset(asset_id: str) -> dict[str, Any]:
    """从备份节点把本体恢复回主节点 —— 台账里 rollback 那一栏的实际执行。

    写下来的回滚步骤如果没人跑过,出事那天就是第一次跑。这条接口让它
    随时可以演练。
    """
    row = asset_registry.get(asset_id)
    if not row:
        raise HTTPException(404, f"资产不存在: {asset_id}")
    backup = (row.get("backup_location") or "").strip()
    if not backup or ":" not in backup:
        raise HTTPException(422, detail={
            "code": "NO_BACKUP",
            "message": f"{asset_id} 没有登记备份位置(level={row['level']}),无法恢复"})
    bnode, bkey = backup.split(":", 1)
    try:
        raw = asset_hub.get(bkey, node_id=bnode)
        asset_hub.put(raw, dept=row["owner_department"], kind="backup",
                      name=row["name"], node_id=row.get("storage_node") or "",
                      content_type=row.get("content_type") or "application/octet-stream")
    except asset_hub.AssetHubError as exc:
        raise HTTPException(502, f"恢复失败: {exc}") from exc
    return {"ok": True, "asset_id": asset_id, "restored_from": backup,
            "size": len(raw), "to_node": row.get("storage_node")}


class LinkIn(BaseModel):
    parent_id: str
    child_id: str
    relation: str = "derived_from"


@router.post("/assets/link")
def link_assets(body: LinkIn) -> dict[str, Any]:
    try:
        return asset_registry.link(body.parent_id, body.child_id, body.relation)
    except asset_registry.AssetError as exc:
        raise HTTPException(422, detail={"code": "LINEAGE_REJECTED", "message": str(exc)}) from exc
