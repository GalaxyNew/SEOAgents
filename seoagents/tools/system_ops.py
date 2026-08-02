"""SystemOpsSpec (L4) — hm(Hermes)统筹智能体的系统管理工具。

这是 hm 管理整个 SEOAgents 系统的唯一入口:查看系统状态、读写配置、
排布时间线、把具体活派给 auditor / writer / linker、触发流水线与技能。

设计约束:
- 所有读操作返回真实运行时数据,不做任何编造;取不到就说取不到。
- 写操作(config_set / timeline_*)全部落盘并即时生效,且回显生效后的值。
- runtime 采用惰性获取,避免与 Runtime 装配过程形成循环依赖。
"""
from __future__ import annotations

import json
from typing import Any

from dojocore.logging import LOGGER
from dojocore.quality import real, unavailable
from seoagents.tools.base import BaseToolSpec

_READ_ACTIONS = ("status", "config_get", "tools_list", "skills_list", "timeline_agenda")
_WRITE_ACTIONS = ("config_set", "timeline_schedule", "timeline_ack", "timeline_cancel")
_EXEC_ACTIONS = ("dispatch", "run_pipeline")
_MEMORY_ACTIONS = ("memory_read", "memory_write", "tool_guide")
_ALL_ACTIONS = _READ_ACTIONS + _WRITE_ACTIONS + _EXEC_ACTIONS + _MEMORY_ACTIONS

# seohm(/data/hermes-seo)的记忆挂载点 —— hm 与 seohm 共用同一份记忆
HERMES_ROOT = "/hermes"
_MEMORY_FILES = {
    "soul": f"{HERMES_ROOT}/SOUL.md",
    "memory": f"{HERMES_ROOT}/memories/MEMORY.md",
    "user": f"{HERMES_ROOT}/memories/USER.md",
}

_DISPATCH_ROLES = ("auditor", "writer", "linker")


def _rt() -> Any:
    from seoagents.agent.runtime import get_runtime

    return get_runtime()


def _timeline() -> Any:
    from dojocore.timeline import get_timeline

    return get_timeline(owner="hm")


class SystemOpsSpec(BaseToolSpec):
    """hm 的系统管理面板。"""

    def get_name(self) -> str:
        return "system_ops"

    def get_schema(self) -> dict[str, Any]:
        return {
            "name": "system_ops",
            "description": (
                "SEOAgents 系统管理面板(hm 专用)。用它查看系统状态、读写配置、"
                "排布时间线、把具体任务派给专员智能体、触发流水线。\n"
                "action 取值:\n"
                "  status          — 系统总览:模型provider、监控站点、已注册工具、技能数、待办节点\n"
                "  config_get      — 读取当前配置(密钥自动脱敏)\n"
                "  config_set      — 修改配置,patch 为要合并的 JSON 对象,写入 agents.yaml 并即时生效\n"
                "  tools_list      — 列出全部可调用工具及其用途\n"
                "  skills_list     — 列出已沉淀的技能\n"
                "  timeline_agenda — 查看时间线日程\n"
                "  timeline_schedule — 排一个节点,payload 需含 scheduled_at/kind/intent\n"
                "  timeline_ack    — 确认某节点完成,需 node_id 与 outcome\n"
                "  timeline_cancel — 取消某节点,需 node_id 与 reason\n"
                "  dispatch        — 把任务派给专员:role 取 auditor/writer/linker,task 为任务描述\n"
                "  run_pipeline    — 触发 Auditor→Writer→Linker 内容整改流水线,可带 target_url"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": list(_ALL_ACTIONS),
                        "description": "要执行的操作",
                    },
                    "patch": {
                        "type": "object",
                        "description": "config_set 用:要深合并进配置的 JSON 对象",
                    },
                    "payload": {
                        "type": "object",
                        "description": "timeline_schedule 用:节点内容",
                    },
                    "node_id": {"type": "string", "description": "timeline_ack/cancel 用"},
                    "outcome": {"type": "string", "description": "timeline_ack 用:完成结果"},
                    "reason": {"type": "string", "description": "timeline_cancel 用:取消原因"},
                    "role": {
                        "type": "string",
                        "enum": list(_DISPATCH_ROLES),
                        "description": "dispatch 用:承接任务的专员",
                    },
                    "task": {"type": "string", "description": "dispatch 用:派下去的任务描述"},
                    "target_url": {"type": "string", "description": "run_pipeline 用:目标页面"},
                    "which": {
                        "type": "string",
                        "enum": ["soul", "memory", "user", "all"],
                        "description": "memory_read 用:读哪份记忆,默认 all",
                    },
                    "text": {"type": "string", "description": "memory_write 用:要追加记住的内容"},
                    "hours_ahead": {
                        "type": "integer",
                        "description": "timeline_agenda 用:向后看几小时,默认 24",
                    },
                    "days": {"type": "integer", "description": "timeline_agenda 用:向后看几天(会换算成小时)"},
                },
                "required": ["action"],
            },
        }

    async def execute(self, arguments: dict[str, Any], session_id: str) -> dict[str, Any]:
        action = str(arguments.get("action") or "").strip()
        if action not in _ALL_ACTIONS:
            return unavailable(
                source="system_ops",
                reason=f"未知 action '{action}'",
                available=list(_ALL_ACTIONS),
            )
        handler = getattr(self, f"_do_{action}")
        try:
            out = await handler(arguments, session_id)
        except Exception as exc:  # noqa: BLE001 - 工具失败必须如实回报,不能静默
            LOGGER.warning(f"system_ops.{action} 失败: {exc}")
            return unavailable(
                source=f"system_ops.{action}",
                reason=f"{type(exc).__name__}: {exc}",
                action=action,
            )
        # 数据诚信契约:取不到就是 unavailable,绝不用空值冒充成功
        if not out.get("ok"):
            return unavailable(
                source=f"system_ops.{action}",
                reason=str(out.get("error") or "未知失败"),
                action=action,
            )
        return real(out, source=f"system_ops.{action}")

    # ── 读 ────────────────────────────────────────────────────────────────
    async def _do_status(self, args: dict[str, Any], sid: str) -> dict[str, Any]:
        rt = _rt()
        cfg = rt.config
        try:
            skills = rt.skill_manager.list_skills()
            skill_n = len(skills)
        except Exception:  # noqa: BLE001
            skill_n = None
        pending = None
        try:
            pending = len(_timeline().due())
        except Exception:  # noqa: BLE001
            pending = None
        return {
            "ok": True,
            "action": "status",
            "provider": rt.provider.name,
            "model": getattr(rt.provider, "model", None),
            "site": cfg.sites.site_url,
            "gsc_property": cfg.sites.gsc_property,
            "monitored_sites": [s.site_url for s in cfg.sites.monitored_sites],
            "tools": rt.registry.names(),
            "skills_count": skill_n,
            "timeline_due": pending,
            "openserp_endpoint": cfg.seo_credentials.openserp_endpoint,
            "seonaut_endpoint": cfg.seo_credentials.seonaut_endpoint,
        }

    async def _do_config_get(self, args: dict[str, Any], sid: str) -> dict[str, Any]:
        rt = _rt()
        return {"ok": True, "action": "config_get", "config": rt.config_store.redacted()}

    async def _do_tools_list(self, args: dict[str, Any], sid: str) -> dict[str, Any]:
        rt = _rt()
        out = []
        for name in rt.registry.names():
            spec = rt.registry.get(name)
            desc = ""
            try:
                desc = str(spec.get_schema().get("description", ""))[:200]
            except Exception:  # noqa: BLE001
                pass
            out.append({"name": name, "description": desc})
        return {"ok": True, "action": "tools_list", "tools": out}

    async def _do_skills_list(self, args: dict[str, Any], sid: str) -> dict[str, Any]:
        rt = _rt()
        return {"ok": True, "action": "skills_list", "skills": rt.skill_manager.list_skills()}

    async def _do_timeline_agenda(self, args: dict[str, Any], sid: str) -> dict[str, Any]:
        # agenda 的视野单位是小时;沿用 days 参数时换算,默认向后看 24 小时
        hours = args.get("hours_ahead")
        if hours is None:
            days = args.get("days")
            hours = int(days) * 24 if days else 24
        agenda = _timeline().agenda(hours_ahead=int(hours))
        return {"ok": True, "action": "timeline_agenda", "agenda": agenda}

    # ── 写 ────────────────────────────────────────────────────────────────
    async def _do_config_set(self, args: dict[str, Any], sid: str) -> dict[str, Any]:
        patch = args.get("patch")
        if isinstance(patch, str):
            patch = json.loads(patch)
        if not isinstance(patch, dict) or not patch:
            return {"ok": False, "action": "config_set", "error": "patch 必须是非空 JSON 对象"}
        rt = _rt()
        rt.config_store.update(patch)
        rt.reload_config()
        return {
            "ok": True,
            "action": "config_set",
            "applied": patch,
            "config_now": _rt().config_store.redacted(),
            "note": "已写入 agents.yaml 并重载运行时",
        }

    async def _do_timeline_schedule(self, args: dict[str, Any], sid: str) -> dict[str, Any]:
        payload = args.get("payload")
        if isinstance(payload, str):
            payload = json.loads(payload)
        if not isinstance(payload, dict) or not payload:
            return {
                "ok": False,
                "action": "timeline_schedule",
                "error": "payload 必须含 scheduled_at / kind / intent",
            }
        node = _timeline().schedule(payload)
        return {
            "ok": True,
            "action": "timeline_schedule",
            "node": node.to_dict() if hasattr(node, "to_dict") else str(node),
        }

    async def _do_timeline_ack(self, args: dict[str, Any], sid: str) -> dict[str, Any]:
        node_id = str(args.get("node_id") or "").strip()
        outcome = str(args.get("outcome") or "").strip()
        if not node_id or not outcome:
            return {"ok": False, "action": "timeline_ack", "error": "需要 node_id 与 outcome"}
        node = _timeline().ack(node_id, outcome=outcome)
        return {
            "ok": True,
            "action": "timeline_ack",
            "node": node.to_dict() if hasattr(node, "to_dict") else str(node),
        }

    async def _do_timeline_cancel(self, args: dict[str, Any], sid: str) -> dict[str, Any]:
        node_id = str(args.get("node_id") or "").strip()
        reason = str(args.get("reason") or "").strip()
        if not node_id or not reason:
            return {"ok": False, "action": "timeline_cancel", "error": "需要 node_id 与 reason"}
        node = _timeline().cancel(node_id, reason=reason)
        return {
            "ok": True,
            "action": "timeline_cancel",
            "node": node.to_dict() if hasattr(node, "to_dict") else str(node),
        }

    # ── 执行 ──────────────────────────────────────────────────────────────
    async def _do_dispatch(self, args: dict[str, Any], sid: str) -> dict[str, Any]:
        from seoagents.multi_agent.orchestrator import AUDITOR, LINKER, WRITER

        role_map = {"auditor": AUDITOR, "writer": WRITER, "linker": LINKER}
        role_name = str(args.get("role") or "").strip()
        task = str(args.get("task") or "").strip()
        role = role_map.get(role_name)
        if role is None:
            return {
                "ok": False,
                "action": "dispatch",
                "error": f"role 必须是 {list(_DISPATCH_ROLES)} 之一,收到 '{role_name}'",
            }
        if not task:
            return {"ok": False, "action": "dispatch", "error": "task 不能为空"}
        rt = _rt()
        result = await rt.loop.run(
            task,
            system=role.system_prompt,
            allowed_tools=set(role.allowed_tools) if role.allowed_tools else None,
        )
        return {
            "ok": result.ok,
            "action": "dispatch",
            "role": role_name,
            "task": task,
            "error": result.error,
            "final_text": result.final_text,
            "turns": result.turns,
        }

    async def _do_run_pipeline(self, args: dict[str, Any], sid: str) -> dict[str, Any]:
        rt = _rt()
        target = args.get("target_url") or None
        result = await rt.orchestrator.run_content_pipeline(target)
        return {
            "ok": True,
            "action": "run_pipeline",
            "target_url": target,
            "result": result.to_dict(),
        }


    # ── 记忆 ──────────────────────────────────────────────────────────────
    async def _do_memory_read(self, args: dict[str, Any], sid: str) -> dict[str, Any]:
        import pathlib as _pl

        which = str(args.get("which") or "all").strip()
        targets = _MEMORY_FILES if which == "all" else {which: _MEMORY_FILES.get(which)}
        if which != "all" and not targets.get(which):
            return {
                "ok": False,
                "action": "memory_read",
                "error": f"which 必须是 soul/memory/user/all,收到 '{which}'",
            }
        out, missing = {}, []
        for name, path in targets.items():
            f = _pl.Path(path)
            if f.is_file():
                out[name] = f.read_text(encoding="utf-8", errors="replace")
            else:
                missing.append(path)
        if not out:
            return {
                "ok": False,
                "action": "memory_read",
                "error": f"记忆文件不存在: {missing}",
            }
        return {"ok": True, "action": "memory_read", "memory": out, "missing": missing}

    async def _do_memory_write(self, args: dict[str, Any], sid: str) -> dict[str, Any]:
        import datetime as _dt
        import pathlib as _pl

        from seoagents.storage.locks import file_lock

        text = str(args.get("text") or "").strip()
        if not text:
            return {"ok": False, "action": "memory_write", "error": "text 不能为空"}
        f = _pl.Path(_MEMORY_FILES["memory"])
        if not f.parent.is_dir():
            return {
                "ok": False,
                "action": "memory_write",
                "error": f"记忆目录不存在: {f.parent}(seohm 未挂载?)",
            }
        stamp = _dt.datetime.now().strftime("%Y-%m-%d")
        entry = f"{text}（seoagents/hm 记于 {stamp}）\n§\n"
        # 与 seohm 共用同名锁文件,避免两边同时写坏记忆
        with file_lock(str(f) + ".lock", timeout=10):
            with f.open("a", encoding="utf-8") as fh:
                fh.write(entry)
        return {
            "ok": True,
            "action": "memory_write",
            "appended": entry.strip(),
            "file": str(f),
        }


    async def _do_tool_guide(self, args: dict[str, Any], sid: str) -> dict[str, Any]:
        """工具手册全文 —— 手册里的状态来自实调,比工具自己的 description 可信。"""
        import pathlib as _pl

        f = _pl.Path("/app/docs/TOOLS.md")
        if not f.is_file():
            return {"ok": False, "action": "tool_guide", "error": f"手册不存在: {f}"}
        return {
            "ok": True,
            "action": "tool_guide",
            "guide": f.read_text(encoding="utf-8", errors="replace"),
            "path": str(f),
        }


__all__ = ["SystemOpsSpec"]
