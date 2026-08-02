"""中央存储中心 —— 多节点资产枢纽 (L4)。

各部门的 agent 不该关心「东西存在哪台机器上」。它们只说「我要存一份 SEO 报告」,
由这一层决定落到哪个存储节点、用什么 key、怎么记血缘。

设计要点:

* **多节点**。中科院 S3 只是第一个节点,后面会接更多(不同容量、不同用途、
  不同地域)。节点注册表是数据不是代码,加节点不用改程序。
* **凭证不进注册表**。每个节点声明 ``env_prefix``,凭证从
  ``{PREFIX}_ACCESS_KEY_ID`` / ``{PREFIX}_SECRET_ACCESS_KEY`` 读。
  注册表可以随便看、随便备份,不含任何密钥。
* **key 有规矩**。``{dept}/{kind}/{yyyy-mm}/{name}`` —— 部门隔离、类型分区、
  按月归档。没有约定的话,三个月后没人知道某个对象是谁写的、还能不能删。
* **写失败就是失败**。绝不静默落回本地磁盘 —— 那会造出「以为进了中央存储、
  实际散在各台机器上」的资产,比写失败难查十倍。
"""
from __future__ import annotations

import datetime as _dt
import json
import os
import re
from pathlib import Path
from typing import Any

from dojocore.logging import LOGGER
from seoagents.storage import quota

_REGISTRY_PATH = Path(
    os.environ.get("ASSET_HUB_REGISTRY", "/data/seo-stack/seoagents-data/storage_nodes.json")
)

# 资产类型 → 用途标签。节点声明自己支持哪些用途,路由时按此匹配。
KINDS = ("report", "content", "image", "dataset", "backup", "skill", "misc")

_SAFE = re.compile(r"[^A-Za-z0-9._一-鿿-]+")


class AssetHubError(RuntimeError):
    """资产操作失败。调用方必须上报,不得降级为本地写入。"""


# ── 节点注册表 ────────────────────────────────────────────────────────
def _default_registry() -> dict[str, Any]:
    """首次运行时的种子:把已验证可用的中科院节点登记进去。"""
    return {
        "cstcloud": {
            "id": "cstcloud",
            "label": "中科院数据空间",
            "kind": "s3",
            "endpoint": "https://s3.cstcloud.cn",
            "bucket": "9b73f22ebcea450e91d3687752a9fe29",
            "region": "us-east-1",
            # 该网关按 User-Agent 判断请求来自哪个客户端,必须与控制台里
            # 给 AccessKey 绑定的「应用」一致,否则一律 401
            "client_ua": "rclone/v1.65.2",
            "env_prefix": "S3",
            "capacity_gb": 20,
            "purposes": ["report", "dataset", "backup", "skill", "misc"],
            "enabled": True,
            "default": True,
            "notes": "列表最终一致;确认单个对象用 head 而非 list",
        }
    }


def load_nodes() -> dict[str, dict[str, Any]]:
    if not _REGISTRY_PATH.is_file():
        save_nodes(_default_registry())
        LOGGER.info(f"资产枢纽:已初始化节点注册表 {_REGISTRY_PATH}")
    try:
        return json.loads(_REGISTRY_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        raise AssetHubError(f"节点注册表读取失败: {exc}") from exc


def save_nodes(nodes: dict[str, Any]) -> None:
    _REGISTRY_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = _REGISTRY_PATH.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(nodes, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, _REGISTRY_PATH)


def pick_node(kind: str = "misc", node_id: str = "", *, for_write: bool = False) -> dict[str, Any]:
    """选一个能承接这类资产的节点。

    显式指定优先;否则挑「启用 + 支持该用途」的,default 优先。
    一个都没有时报错说清楚原因,不要随便找个节点硬塞。
    """
    nodes = load_nodes()
    if node_id:
        n = nodes.get(node_id)
        if not n:
            raise AssetHubError(f"未知存储节点 '{node_id}';已注册: {sorted(nodes)}")
        if not n.get("enabled", True):
            raise AssetHubError(f"节点 '{node_id}' 已停用")
        return n
    usable = [n for n in nodes.values()
              if n.get("enabled", True) and kind in (n.get("purposes") or [])]
    if not usable:
        raise AssetHubError(
            f"没有可承接 kind='{kind}' 的存储节点。"
            f"已注册节点及其用途: "
            f"{ {k: v.get('purposes') for k, v in nodes.items()} }"
        )
    usable.sort(key=lambda n: (not n.get("default"), n.get("id", "")))

    if not for_write:
        return usable[0]

    # 写入前过配额闸门:达到阈值的节点自动跳过,换下一个还能写的。
    # 全部满了就明确报出来 —— 不静默写超,那会变成月底的账单惊喜。
    blocked = []
    for n in usable:
        st = quota.check(n)
        if st["writable"]:
            if blocked:
                LOGGER.warning(f"节点 {[b[0] for b in blocked]} 已达配额,改用 {n['id']}")
            return n
        blocked.append((n["id"], st["reason"]))
    raise AssetHubError(
        "所有可承接节点都已达到配额上限,已停止写入(读取不受影响):\n"
        + "\n".join(f"  · {nid}: {why}" for nid, why in blocked)
        + "\n处理方式:等下月额度重置、提高该节点 quota.stop_write_at_pct、"
          "或再加一个存储节点账号。"
    )


# ── 客户端 ────────────────────────────────────────────────────────────
_clients: dict[str, Any] = {}


def _client(node: dict[str, Any]) -> Any:
    nid = node["id"]
    if nid in _clients:
        return _clients[nid]
    try:
        import boto3
        from botocore.config import Config
    except ImportError as exc:
        raise AssetHubError("boto3 未安装:pip install boto3") from exc

    pfx = node.get("env_prefix") or nid.upper()
    ak = os.environ.get(f"{pfx}_ACCESS_KEY_ID", "").strip()
    sk = os.environ.get(f"{pfx}_SECRET_ACCESS_KEY", "").strip()
    if not ak or not sk:
        raise AssetHubError(
            f"节点 '{nid}' 缺少凭证环境变量 {pfx}_ACCESS_KEY_ID / {pfx}_SECRET_ACCESS_KEY"
        )
    c = boto3.client(
        "s3",
        endpoint_url=node["endpoint"],
        aws_access_key_id=ak,
        aws_secret_access_key=sk,
        region_name=node.get("region", "us-east-1"),
        config=Config(
            signature_version="s3v4",
            # 各家不一样:中科院必须 path,七牛必须 virtual。写死任一个都会有一家连不上。
            s3={"addressing_style": node.get("addressing_style", "path")},
            user_agent=node.get("client_ua") or "rclone/v1.65.2",  # 网关按 UA 认应用
            request_checksum_calculation="when_required",  # 服务端不支持 aws-chunked
            response_checksum_validation="when_required",
            retries={"max_attempts": 3, "mode": "standard"},
        ),
    )
    _clients[nid] = c
    return c


# ── 资产读写 ──────────────────────────────────────────────────────────
def build_key(dept: str, kind: str, name: str) -> str:
    """统一 key 规则:``{dept}/{kind}/{yyyy-mm}/{name}``。"""
    safe = _SAFE.sub("-", (name or "unnamed").strip()) or "unnamed"
    month = _dt.datetime.now().strftime("%Y-%m")
    return f"{(dept or 'unknown').strip()}/{kind}/{month}/{safe}"


def _is_gdrive(node: dict[str, Any]) -> bool:
    return (node.get("kind") or "s3") == "gdrive"


def put(
    data: bytes | str,
    *,
    dept: str,
    kind: str = "misc",
    name: str,
    content_type: str = "application/octet-stream",
    node_id: str = "",
    metadata: dict[str, str] | None = None,
) -> dict[str, Any]:
    """存一份资产。返回可用于回取的定位信息。"""
    if kind not in KINDS:
        raise AssetHubError(f"kind 必须是 {list(KINDS)} 之一,收到 '{kind}'")
    node = pick_node(kind, node_id, for_write=True)
    body = data.encode("utf-8") if isinstance(data, str) else data
    key = build_key(dept, kind, name)
    extra: dict[str, Any] = {"ContentType": content_type}
    if metadata:
        extra["Metadata"] = {str(k): str(v) for k, v in metadata.items()}
    try:
        if _is_gdrive(node):
            from seoagents.storage import gdrive_driver as gd

            gd.put(node, key, body, content_type)
        else:
            _client(node).put_object(Bucket=node["bucket"], Key=key, Body=body, **extra)
    except Exception as exc:  # noqa: BLE001 - 写不进去必须让人知道
        raise AssetHubError(f"写入节点 {node['id']} 失败: {type(exc).__name__}: {exc}") from exc
    quota.record(node["id"], op="put", size=len(body))
    LOGGER.info(f"资产已存入 {node['id']}:{key} ({len(body)}B)")
    return {
        "ok": True, "node": node["id"],
        # 非 S3 节点没有 bucket 概念,用 .get 而不是下标
        "bucket": node.get("bucket", "(n/a)"),
        "kind": node.get("kind", "s3"),
        "key": key, "size": len(body), "content_type": content_type,
    }


def put_json(obj: Any, *, dept: str, kind: str = "report", name: str, **kw: Any) -> dict[str, Any]:
    return put(json.dumps(obj, ensure_ascii=False, indent=2),
               dept=dept, kind=kind, name=name,
               content_type="application/json", **kw)


def get(key: str, *, node_id: str = "") -> bytes:
    node = pick_node(node_id=node_id) if node_id else _node_of_default()
    try:
        if _is_gdrive(node):
            from seoagents.storage import gdrive_driver as gd

            raw = gd.get(node, key)
        else:
            raw = _client(node).get_object(Bucket=node["bucket"], Key=key)["Body"].read()
    except Exception as exc:  # noqa: BLE001
        raise AssetHubError(f"读取 {node['id']}:{key} 失败: {type(exc).__name__}: {exc}") from exc
    quota.record(node["id"], op="get")
    return raw


def _node_of_default() -> dict[str, Any]:
    nodes = [n for n in load_nodes().values() if n.get("enabled", True)]
    if not nodes:
        raise AssetHubError("没有任何启用的存储节点")
    nodes.sort(key=lambda n: (not n.get("default"), n.get("id", "")))
    return nodes[0]


def exists(key: str, *, node_id: str = "") -> bool:
    """用 head 判断 —— 列表是最终一致的,刚写的对象可能列不出来。"""
    node = pick_node(node_id=node_id) if node_id else _node_of_default()
    if _is_gdrive(node):
        from seoagents.storage import gdrive_driver as gd

        return gd.exists(node, key)
    try:
        _client(node).head_object(Bucket=node["bucket"], Key=key)
        return True
    except Exception:  # noqa: BLE001
        return False


def listing(prefix: str = "", *, node_id: str = "", limit: int = 200) -> list[dict[str, Any]]:
    node = pick_node(node_id=node_id) if node_id else _node_of_default()
    if _is_gdrive(node):
        from seoagents.storage import gdrive_driver as gd

        return [{**i, "node": node["id"]} for i in gd.listing(node, prefix, limit)]
    resp = _client(node).list_objects_v2(
        Bucket=node["bucket"], Prefix=prefix, MaxKeys=limit)
    return [
        {"key": o["Key"], "size": o["Size"],
         "modified": o["LastModified"].isoformat(), "node": node["id"]}
        for o in resp.get("Contents", [])
    ]


def delete(key: str, *, node_id: str = "") -> dict[str, Any]:
    node = pick_node(node_id=node_id) if node_id else _node_of_default()
    size = 0
    if _is_gdrive(node):
        from seoagents.storage import gdrive_driver as gd

        size = gd.head_size(node, key)
        gd.delete(node, key)
    else:
        try:
            size = int(_client(node).head_object(Bucket=node["bucket"], Key=key).get("ContentLength", 0))
        except Exception:  # noqa: BLE001 - 拿不到大小不影响删除本身
            pass
        _client(node).delete_object(Bucket=node["bucket"], Key=key)
    quota.record(node["id"], op="delete", size=size)
    LOGGER.info(f"资产已删除 {node['id']}:{key}")
    return {"ok": True, "node": node["id"], "key": key}


def health() -> dict[str, Any]:
    """逐个节点探活。某个节点挂了不影响其余节点的判定。"""
    out = []
    for nid, node in load_nodes().items():
        if not node.get("enabled", True):
            out.append({"node": nid, "reachable": False, "reason": "已停用"})
            continue
        try:
            info: dict[str, Any] = {}
            if _is_gdrive(node):
                from seoagents.storage import gdrive_driver as gd

                # Drive 自己就报真实占用,比我们本地记账准,直接用它的
                info = gd.quota_info(node)
            else:
                _client(node).list_objects_v2(Bucket=node["bucket"], MaxKeys=1)
            out.append({
                "node": nid, "label": node.get("label"), "reachable": True,
                "endpoint": node.get("endpoint", "(Google Drive API)"),
                "capacity_gb": node.get("capacity_gb"),
                "purposes": node.get("purposes"),
                **({"live_quota": info} if info else {}),
            })
        except Exception as exc:  # noqa: BLE001
            out.append({"node": nid, "label": node.get("label"), "reachable": False,
                        "reason": f"{type(exc).__name__}: {str(exc)[:160]}"})
    ok = sum(1 for n in out if n.get("reachable"))
    return {
        "ok": ok > 0, "nodes_total": len(out), "nodes_reachable": ok, "nodes": out,
        "quota": quota.report(load_nodes()),
    }


__all__ = [
    "KINDS", "AssetHubError", "build_key", "delete", "exists", "get", "health",
    "listing", "load_nodes", "pick_node", "put", "put_json", "save_nodes",
]


# ── 存储 + 登记一体化 ─────────────────────────────────────────────────
def put_asset(
    data: bytes | str,
    *,
    dept: str,
    name: str,
    kind: str = "misc",
    level: str = "L1",
    task_id: str,
    owner_agent: str,
    summary: str,
    usage: str,
    source_evidence: str,
    asset_class: str = "DOC",
    content_type: str = "application/octet-stream",
    node_id: str = "",
    rollback: str = "",
    review_cycle: str = "90d",
    **kw: Any,
) -> dict[str, Any]:
    """存一份资产并登记进台账。L3 会**真的**镜像到第二个节点。

    L3 要求 ``backup_location``。如果只让人手填一行字,写什么都能过 —— 纸面合规。
    所以这里对 L3 做真实镜像:写完主节点再写一份到另一个节点,拿镜像的实际
    落点作为 backup_location。没有第二个可写节点就直接失败,不允许「先登记、
    备份以后再补」—— 那个「以后」在事故里从来没到过。
    """
    from seoagents.storage import asset_registry as _reg

    body = data.encode("utf-8") if isinstance(data, str) else data

    # L3 的可备份性必须在写任何东西之前确认。先写主节点再发现没法备份,
    # 会在存储里留下一个没有台账的孤儿对象 —— 那正是资产登记要消灭的东西。
    mirror_node = ""
    if level == "L3":
        intended = pick_node(kind, node_id, for_write=True)["id"]
        others = [
            nid for nid, n in load_nodes().items()
            if nid != intended and n.get("enabled", True) and quota.check(n)["writable"]
        ]
        if not others:
            raise AssetHubError(
                f"L3 资产 '{name}' 需要异地备份,但除 {intended} 外"
                f"没有其它可写节点 —— 拒绝以「无备份」状态登记 L3。"
                f"请先加节点,或确认它其实是 L2。(未写入任何数据)"
            )
        mirror_node = others[0]

    primary = put(body, dept=dept, kind=kind, name=name,
                  content_type=content_type, node_id=node_id, **kw)

    backup_loc = ""
    if level == "L3":
        try:
            mirror = put(body, dept=dept, kind=kind, name=name,
                         content_type=content_type, node_id=mirror_node, **kw)
        except AssetHubError as exc:
            raise AssetHubError(
                f"L3 主节点已写入 {primary['node']}:{primary['key']},"
                f"但镜像到 {mirror_node} 失败: {exc} —— 未登记,请重试或换节点"
            ) from exc
        backup_loc = f"{mirror['node']}:{mirror['key']}"
        rollback = rollback or f"从 {mirror['node']} get '{mirror['key']}' 覆盖回 {primary['node']}"

    entry = _reg.register(
        name=name, cls=asset_class, level=level, task_id=task_id,
        owner_department=dept, owner_agent=owner_agent,
        location=primary["key"], location_type="gdrive" if primary["kind"] == "gdrive" else "s3",
        storage_node=primary["node"], summary=summary, usage=usage,
        source_evidence=source_evidence, content=body, content_type=content_type,
        backup_location=backup_loc, rollback=rollback if level == "L3" else "",
        review_cycle=review_cycle if level == "L3" else "",
    )
    return {**primary, "asset_id": entry["asset_id"], "level": level,
            "checksum": entry["checksum"], "backup": backup_loc}
