"""AssetHubSpec (L4) —— 各部门 agent 存取中央资产的统一入口。

一个 agent 产出了报告、文章、数据集,不该自己决定「存哪台机器的哪个目录」。
它只说存什么、属于哪个部门、是什么类型,由资产枢纽决定落到哪个存储节点。

这样做的直接好处:换存储、加节点、迁移数据,agent 侧一行都不用改。
"""
from __future__ import annotations

import json
from typing import Any

from dojocore.logging import LOGGER
from dojocore.quality import real, unavailable
from seoagents.config.models import SeoAgentsConfig
from seoagents.storage import asset_hub as hub
from seoagents.tools.base import BaseToolSpec

_ACTIONS = ("put", "get", "list", "exists", "delete", "health", "nodes")


class AssetHubSpec(BaseToolSpec):
    """中央资产存储。"""

    def __init__(self, config: SeoAgentsConfig, store: Any = None) -> None:
        # 本实例代表哪个部门 —— 资产 key 按部门隔离,防止互相覆盖
        self.dept = getattr(config.collab, "dept", "") or "seo"

    def get_name(self) -> str:
        return "asset_hub"

    def get_schema(self) -> dict[str, Any]:
        return {
            "name": "asset_hub",
            "description": (
                "中央资产存储(多节点)。产出物一律存这里,不要写本地磁盘 —— "
                "本地文件换台机器就找不到了。\n"
                "action:\n"
                "  put    存一份资产,需 name 与 content;kind 取 "
                f"{list(hub.KINDS)};返回 key,凭它回取\n"
                "  get    按 key 取回内容\n"
                "  list   按前缀列出资产(注意列表最终一致,刚写的可能列不出)\n"
                "  exists 判断某个 key 是否存在(用 head,比 list 可靠)\n"
                "  delete 删除某个 key\n"
                "  health 各存储节点连通性\n"
                "  nodes  已注册的存储节点及其用途与容量"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {"type": "string", "enum": list(_ACTIONS)},
                    "name": {"type": "string", "description": "put 用:资产名,会做安全化处理"},
                    "content": {"type": "string", "description": "put 用:内容(文本或 JSON 字符串)"},
                    "kind": {
                        "type": "string",
                        "enum": list(hub.KINDS),
                        "description": "资产类型,决定路由到哪个节点,默认 misc",
                    },
                    "content_type": {"type": "string", "description": "MIME 类型,默认按内容猜"},
                    "key": {"type": "string", "description": "get/exists/delete 用:完整 key"},
                    "prefix": {"type": "string", "description": "list 用:key 前缀,如 seo/report/"},
                    "node_id": {"type": "string", "description": "指定存储节点;不传则自动路由"},
                    "dept": {"type": "string", "description": "归属部门;不传用本实例所属部门"},
                },
                "required": ["action"],
            },
        }

    async def execute(self, arguments: dict[str, Any], session_id: str) -> dict[str, Any]:
        action = str(arguments.get("action") or "").strip()
        if action not in _ACTIONS:
            return unavailable(
                source="asset_hub",
                reason=f"未知 action '{action}'",
                available=list(_ACTIONS),
            )
        try:
            return real(self._run(action, arguments), source=f"asset_hub.{action}")
        except hub.AssetHubError as exc:
            # 资产存不进去是必须让人知道的事,绝不静默降级到本地磁盘
            LOGGER.warning(f"asset_hub.{action} 失败: {exc}")
            return unavailable(source=f"asset_hub.{action}", reason=str(exc), action=action)
        except Exception as exc:  # noqa: BLE001
            LOGGER.warning(f"asset_hub.{action} 异常: {type(exc).__name__}: {exc}")
            return unavailable(
                source=f"asset_hub.{action}",
                reason=f"{type(exc).__name__}: {exc}",
                action=action,
            )

    def _run(self, action: str, a: dict[str, Any]) -> dict[str, Any]:
        dept = str(a.get("dept") or self.dept)
        node_id = str(a.get("node_id") or "")

        if action == "put":
            name = str(a.get("name") or "").strip()
            content = a.get("content")
            if not name:
                raise hub.AssetHubError("put 需要 name")
            if content is None:
                raise hub.AssetHubError("put 需要 content")
            kind = str(a.get("kind") or "misc")
            ct = str(a.get("content_type") or "")
            if not ct:
                ct = "application/json" if _looks_json(content) else "text/plain; charset=utf-8"
            return hub.put(
                content if isinstance(content, (str, bytes)) else json.dumps(content, ensure_ascii=False),
                dept=dept, kind=kind, name=name, content_type=ct, node_id=node_id,
            )

        if action == "get":
            key = str(a.get("key") or "")
            if not key:
                raise hub.AssetHubError("get 需要 key")
            raw = hub.get(key, node_id=node_id)
            try:
                text = raw.decode("utf-8")
            except UnicodeDecodeError:
                return {"key": key, "size": len(raw), "binary": True,
                        "note": "二进制内容,未解码"}
            return {"key": key, "size": len(raw), "content": text}

        if action == "list":
            items = hub.listing(str(a.get("prefix") or ""), node_id=node_id)
            return {"prefix": a.get("prefix", ""), "count": len(items), "items": items,
                    "note": "列表最终一致;刚写入的对象可能尚未出现,确认单个对象请用 exists"}

        if action == "exists":
            key = str(a.get("key") or "")
            if not key:
                raise hub.AssetHubError("exists 需要 key")
            return {"key": key, "exists": hub.exists(key, node_id=node_id)}

        if action == "delete":
            key = str(a.get("key") or "")
            if not key:
                raise hub.AssetHubError("delete 需要 key")
            return hub.delete(key, node_id=node_id)

        if action == "health":
            return hub.health()

        # nodes
        nodes = hub.load_nodes()
        return {
            "total": len(nodes),
            "nodes": [
                {k: v for k, v in n.items() if k != "env_prefix"}
                for n in nodes.values()
            ],
        }


def _looks_json(v: Any) -> bool:
    if not isinstance(v, str):
        return True
    s = v.strip()
    return s.startswith(("{", "[")) and s.endswith(("}", "]"))


__all__ = ["AssetHubSpec"]
