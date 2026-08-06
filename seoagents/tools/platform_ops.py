"""PlatformOpsSpec (L4) — the department head operates its own platform.

Until now the head had data tools (audit a site, query GSC, look up rankings)
but no way to *run* the system it is supposed to be responsible for. It could
tell you a page was slow; it could not look at which tools were installed,
start a content pipeline, plan its own week, or see what another department had
asked it for.

This exposes the platform's management surface as one tool, so all of it
arrives through the same MCP connection as everything else.

**Read freely, propose to change.** Reading state is unrestricted. Anything that
spends money, executes third-party code, or alters what the system will do
without a human present returns a *proposal* instead of doing it — installing a
tool runs someone else's code on the host, and editing credentials or scoring
weights silently changes every number produced afterwards. That matches the
department head's own standing rule: approval cannot be delegated to it.
"""
from __future__ import annotations

import datetime as _dt
from typing import Any

from dojocore.logging import LOGGER
from dojocore.quality import real, unavailable
from seoagents.config.models import SeoAgentsConfig
from seoagents.tools.base import BaseToolSpec

__all__ = ["PROPOSE_ONLY_ACTIONS", "READ_ACTIONS", "PlatformOpsSpec"]

READ_ACTIONS = (
    "catalog_list", "catalog_detail", "capability_map", "resource_estimate",
    "workflow_templates", "workflow_detail", "workflow_instances", "workflow_status",
    "timeline_agenda", "timeline_unread", "timeline_cron_jobs",
    "timeline_node_detail", "timeline_run_status",
    "collab_inbox", "collab_outbox", "collab_capabilities",
    "config_get", "system_status",
)

ACT_ACTIONS = (
    "workflow_start", "workflow_begin_node", "workflow_complete_node",
    "timeline_plan", "timeline_schedule", "timeline_pause", "timeline_resume",
    "timeline_run", "timeline_cancel", "timeline_triage", "collab_send", "collab_deliver",
)

# Doing these without a person present would spend money, run third-party code,
# or silently change what every later number means.
PROPOSE_ONLY_ACTIONS = ("catalog_install", "config_set", "credential_set")


class PlatformOpsSpec(BaseToolSpec):
    """SEOAgents 平台管理:工具目录、工作流、时间线、收发件箱、配置。"""

    def __init__(self, config: SeoAgentsConfig) -> None:
        self.config = config

    def get_name(self) -> str:
        return "platform_ops"

    def get_schema(self) -> dict[str, Any]:
        return {
            "name": "platform_ops",
            "description": (
                "管理 SEOAgents 平台本身。读类动作直接执行;"
                "安装工具/改配置/改凭证只返回提案,需人工批准后由人执行 —— "
                "装工具等于在主机上跑第三方代码,改配置会静默改变之后所有数字的含义。\n"
                f"读: {', '.join(READ_ACTIONS)}\n"
                f"执行: {', '.join(ACT_ACTIONS)}\n"
                f"仅提案: {', '.join(PROPOSE_ONLY_ACTIONS)}"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": list(READ_ACTIONS + ACT_ACTIONS + PROPOSE_ONLY_ACTIONS),
                    },
                    "params": {"type": "object", "description": "该动作的参数"},
                },
                "required": ["action"],
            },
        }

    async def execute(self, arguments: dict[str, Any], session_id: str) -> dict[str, Any]:
        action = str(arguments.get("action", ""))
        p = dict(arguments.get("params") or {})

        if action in PROPOSE_ONLY_ACTIONS:
            return self._propose(action, p)
        handler = getattr(self, f"_do_{action}", None)
        if handler is None:
            return unavailable(
                source="platform_ops",
                reason=f"未知动作 '{action}';可用: {sorted(READ_ACTIONS + ACT_ACTIONS + PROPOSE_ONLY_ACTIONS)}",
            )
        try:
            return handler(p)
        except Exception as exc:  # noqa: BLE001 - boundary
            LOGGER.exception(f"platform_ops.{action} failed")
            return unavailable(source=f"platform_ops.{action}", reason=str(exc))

    # ── proposals ────────────────────────────────────────────────────────
    def _propose(self, action: str, p: dict[str, Any]) -> dict[str, Any]:
        why = {
            "catalog_install": "安装工具会在主机上执行第三方代码,并可能产生持续费用",
            "config_set": "改配置会静默改变之后所有指标的含义与口径",
            "credential_set": "凭证变更等于变更花钱与访问权限",
        }[action]
        return real(
            {
                "proposal": {
                    "action": action,
                    "params": p,
                    "requires": "human_approval",
                    "reason": why,
                    "proposed_at": _dt.datetime.now(_dt.timezone.utc).isoformat(),
                },
                "next_step": "把这份提案发给用户,取得具名批准后由人执行;不要自行重试",
            },
            source="platform_ops.propose",
        )

    # ── catalog ──────────────────────────────────────────────────────────
    def _do_catalog_list(self, p: dict[str, Any]) -> dict[str, Any]:
        from seoagents.plugins.catalog_loader import load_catalog

        entries = load_catalog()
        return real(
            {
                "total": len(entries),
                "items": [
                    {k: v for k, v in e.to_dict().items()
                     if k in ("id", "display_name", "status", "capabilities",
                              "summary", "memory_mb", "recommended_mode", "installable")}
                    for e in entries
                ],
            },
            source="platform_ops.catalog",
        )

    def _do_catalog_detail(self, p: dict[str, Any]) -> dict[str, Any]:
        from seoagents.plugins.catalog_loader import load_catalog

        entry = next((e for e in load_catalog() if e.id == p.get("id")), None)
        if entry is None:
            return unavailable(source="platform_ops.catalog", reason=f"未知条目 '{p.get('id')}'")
        return real(entry.to_dict(), source="platform_ops.catalog")

    def _do_capability_map(self, p: dict[str, Any]) -> dict[str, Any]:
        from dojocore.capability import capabilities
        from seoagents.plugins.catalog_loader import capability_map

        grouped = capability_map()
        out = {}
        for cap in capabilities.list():
            tools = [t.id for t in grouped.get(cap.id, []) if t.installable]
            out[cap.id] = {
                "label": cap.label, "providers": tools,
                "comparable": len(tools) > 1,
                "single_source_risk": len(tools) == 1,
                "uncovered": not tools,
            }
        return real({"capabilities": out}, source="platform_ops.capabilities")

    def _do_resource_estimate(self, p: dict[str, Any]) -> dict[str, Any]:
        from seoagents.plugins.catalog_loader import estimate_footprint

        return real(estimate_footprint(p.get("plan") or []), source="platform_ops.resources")

    # ── workflow ─────────────────────────────────────────────────────────
    def _do_workflow_templates(self, p: dict[str, Any]) -> dict[str, Any]:
        from dojocore.workflow import get_workflow_store

        return real(
            {"templates": [t.summary() for t in get_workflow_store().templates()]},
            source="platform_ops.workflow",
        )

    def _do_workflow_detail(self, p: dict[str, Any]) -> dict[str, Any]:
        from dojocore.workflow import get_workflow_store

        tpl = get_workflow_store().template(str(p.get("template_id", "")))
        if tpl is None:
            return unavailable(source="platform_ops.workflow", reason="未知模板")
        return real(tpl.to_dict(), source="platform_ops.workflow")

    def _do_workflow_instances(self, p: dict[str, Any]) -> dict[str, Any]:
        from dojocore.workflow import get_workflow_store

        items = get_workflow_store().instances(status=p.get("status"), limit=int(p.get("limit", 50)))
        return real({"items": [i.to_dict() for i in items]}, source="platform_ops.workflow")

    def _do_workflow_start(self, p: dict[str, Any]) -> dict[str, Any]:
        """Use Dashboard as the single writer/dispatcher for real workflow start."""
        import json as _json
        import os as _os
        import urllib.request as _urlrequest

        template_id = str(p.get("template_id", ""))
        if not template_id:
            return unavailable(source="platform_ops.workflow", reason="template_id 必填")
        base = _os.environ.get(
            "SEOAGENTS_DASHBOARD_URL", "http://seoagents-dashboard:8765"
        ).rstrip("/")
        token = _os.environ.get("SEOAGENTS_SERVICE_TOKEN", "").strip()
        payload = _json.dumps({
            "template_id": template_id,
            "title": str(p.get("title", "")),
            "context": dict(p.get("context") or {}),
            "input_params": dict(p.get("input_params") or p.get("parameters") or {}),
            "parent_task": str(p.get("parent_task", "")),
            "auto_start": True,
        }, ensure_ascii=False).encode()
        headers = {"Content-Type": "application/json"}
        if token:
            headers["X-Service-Token"] = token
        req = _urlrequest.Request(
            f"{base}/api/workflows/instances",
            data=payload, method="POST", headers=headers,
        )
        try:
            with _urlrequest.urlopen(req, timeout=60) as resp:
                result = _json.loads(resp.read() or b"{}")
        except Exception as exc:
            return unavailable(
                source="platform_ops.workflow",
                reason=f"Dashboard workflow start failed: {exc}",
            )
        return real(result, source="platform_ops.workflow")

    def _do_workflow_status(self, p: dict[str, Any]) -> dict[str, Any]:
        from dojocore.workflow import WorkflowEngine, get_workflow_store

        store = get_workflow_store()
        inst = store.instance(str(p.get("instance_id", "")))
        if inst is None:
            return unavailable(source="platform_ops.workflow", reason="未知实例")
        tpl = store.template_for_instance(inst)
        if tpl is None:
            return unavailable(source="platform_ops.workflow", reason="实例模板快照不可用")
        engine = WorkflowEngine(tpl)
        return real(
            {**inst.to_dict(),
             "ready": [n.id for n in engine.ready_nodes(inst)],
             "blocked_reason": engine.blocked_reason(inst)},
            source="platform_ops.workflow",
        )

    def _do_workflow_begin_node(self, p: dict[str, Any]) -> dict[str, Any]:
        return self._node_action(p, "begin")

    def _do_workflow_complete_node(self, p: dict[str, Any]) -> dict[str, Any]:
        result = self._node_action(p, "complete")
        # If this node belongs to a dashboard-dispatched Hermes run, immediately
        # project the accepted completion and fan out newly-ready DAG nodes.
        try:
            if result.get("data_status") == "REAL":
                import json as _json
                import os as _os
                import urllib.request as _urlrequest
                iid, nid = str(p.get("instance_id", "")), str(p.get("node_id", ""))
                base = _os.environ.get("SEOAGENTS_DASHBOARD_URL", "http://127.0.0.1:8765").rstrip("/")
                token = _os.environ.get("SEOAGENTS_SERVICE_TOKEN", "").strip()
                payload = _json.dumps({"status": "ACCEPTED", "evidence": str(p.get("evidence", "")),
                                       "output_asset_ids": list(p.get("output_asset_ids") or [])}, ensure_ascii=False).encode()
                headers = {"Content-Type": "application/json"}
                if token: headers["X-Service-Token"] = token
                req = _urlrequest.Request(f"{base}/api/workflows/internal/instances/{iid}/nodes/{nid}/runtime",
                                          data=payload, method="POST", headers=headers)
                with _urlrequest.urlopen(req, timeout=30) as resp:
                    result["runtime_projection"] = _json.loads(resp.read() or b"{}")
        except Exception as exc:
            result["runtime_projection_error"] = str(exc)
        return result

    def _node_action(self, p: dict[str, Any], op: str) -> dict[str, Any]:
        from dojocore.workflow import EngineError, WorkflowEngine, get_workflow_store

        store = get_workflow_store()
        inst = store.instance(str(p.get("instance_id", "")))
        if inst is None:
            return unavailable(source="platform_ops.workflow", reason="未知实例")
        tpl = store.template_for_instance(inst)
        if tpl is None:
            return unavailable(source="platform_ops.workflow", reason="实例模板快照不可用")
        engine = WorkflowEngine(tpl)
        try:
            if op == "begin":
                engine.begin(inst, str(p["node_id"]))
            else:
                engine.complete(
                    inst, str(p["node_id"]),
                    acceptance_met=list(p.get("acceptance_met") or []),
                    evidence=str(p.get("evidence", "")),
                    output_asset_ids=list(p.get("output_asset_ids") or []),
                    actor=str(p.get("actor", "agent")),
                )
        except (EngineError, KeyError) as exc:
            return unavailable(source="platform_ops.workflow", reason=str(exc))
        store.save_instance(inst)
        return real(inst.to_dict(), source="platform_ops.workflow")

    # ── timeline ─────────────────────────────────────────────────────────
    def _do_timeline_agenda(self, p: dict[str, Any]) -> dict[str, Any]:
        from dojocore.timeline import get_timeline

        return real(
            get_timeline().agenda(hours_ahead=int(p.get("hours_ahead", 24))),
            source="platform_ops.timeline",
        )

    def _do_timeline_plan(self, p: dict[str, Any]) -> dict[str, Any]:
        """Commit Agent-planned work; a fixed Hermes Cron pulse executes it.

        This path deliberately does NOT create another Cron job. It is safe to
        call from the Daily Planner Cron: the already-existing Timeline Pulse
        is the sole wake-up clock and dispatches due nodes to current Hermes.
        """
        from dojocore.timeline import TimelineError, get_timeline

        task_type = str(p.get("task_type") or "agent_prompt")
        if task_type not in {"agent_prompt", "workflow"}:
            return unavailable(source="platform_ops.timeline", reason="task_type 仅支持 agent_prompt/workflow")
        if task_type == "agent_prompt" and not str(p.get("prompt") or "").strip():
            return unavailable(source="platform_ops.timeline", reason="Agent 任务必须提供 prompt")
        if task_type == "workflow" and not str(p.get("workflow_id") or "").strip():
            return unavailable(source="platform_ops.timeline", reason="工作流任务必须提供 workflow_id")
        context = {
            "task_type": task_type,
            "agent_prompt": str(p.get("prompt") or ""),
            "workflow_id": str(p.get("workflow_id") or ""),
            "workflow_version": str(p.get("workflow_version") or ""),
            "parameters": dict(p.get("parameters") or {}),
            "priority": str(p.get("priority") or "P1"),
            "approval_required": bool(p.get("approval_required", False)),
            "scheduler": "hermes-pulse",
            "runtime_state": "SCHEDULED",
            "planning_reason": str(p.get("reason") or ""),
        }
        try:
            nodes = get_timeline().plan_task(
                intent=str(p["intent"]),
                subject_ref=str(p.get("subject_ref", "")),
                start_at=_dt.datetime.now(_dt.timezone.utc)
                + _dt.timedelta(minutes=int(p.get("start_in_minutes", 30))),
                expected_minutes=int(p.get("expected_minutes", 15)),
                checkpoint_after_minutes=p.get("checkpoint_after_minutes"),
                on_miss=str(p.get("on_miss", "catchup")),
                context=context,
            )
        except (TimelineError, KeyError) as exc:
            return unavailable(source="platform_ops.timeline", reason=str(exc))
        return real({"nodes": [n.to_dict() for n in nodes]}, source="platform_ops.timeline")

    def _do_timeline_node_detail(self, p: dict[str, Any]) -> dict[str, Any]:
        from dojocore.timeline import get_timeline
        node = get_timeline().store.get(str(p.get("node_id") or ""))
        if node is None:
            return unavailable(source="platform_ops.timeline", reason="节点不存在")
        return real(node.to_dict(), source="platform_ops.timeline")

    def _do_timeline_run_status(self, p: dict[str, Any]) -> dict[str, Any]:
        import sqlite3
        from dojocore.context import get_config
        db = __import__('pathlib').Path(get_config().storage.data_dir) / "timeline_runs.db"
        if not db.exists():
            return real({"items": []}, source="platform_ops.timeline")
        c = sqlite3.connect(db); c.row_factory = sqlite3.Row
        try:
            if p.get("node_id"):
                rows = c.execute("SELECT * FROM timeline_runs WHERE node_id=?", (str(p["node_id"]),)).fetchall()
            else:
                rows = c.execute("SELECT * FROM timeline_runs ORDER BY claimed_at DESC LIMIT ?", (int(p.get("limit", 50)),)).fetchall()
        finally:
            c.close()
        return real({"items": [dict(r) for r in rows]}, source="platform_ops.timeline")

    def _do_timeline_cron_jobs(self, p: dict[str, Any]) -> dict[str, Any]:
        from seoagents.dashboard.routers.timeline_cron_api import _all_jobs
        return real({"jobs": list(_all_jobs().values())}, source="platform_ops.timeline")

    def _do_timeline_schedule(self, p: dict[str, Any]) -> dict[str, Any]:
        from seoagents.dashboard.routers.timeline_cron_api import CreateScheduleBody, create_schedule_sync
        try:
            return real(create_schedule_sync(CreateScheduleBody.model_validate(p)),
                        source="platform_ops.timeline")
        except Exception as exc:
            return unavailable(source="platform_ops.timeline", reason=str(exc))

    def _timeline_lifecycle(self, p: dict[str, Any], action: str) -> dict[str, Any]:
        from seoagents.dashboard.routers.timeline_cron_api import _hermes, _job_id
        from dojocore.timeline import get_timeline
        node = get_timeline().store.get(str(p.get("node_id") or ""))
        if node is None:
            return unavailable(source="platform_ops.timeline", reason="节点不存在")
        jid = _job_id(node)
        if not jid:
            return unavailable(source="platform_ops.timeline", reason="旧节点未绑定 Hermes Cron")
        try:
            if action == "cancel":
                result = _hermes("DELETE", f"/api/jobs/{jid}")
                if node.state.value == "SCHEDULED":
                    get_timeline().cancel(node.node_id, reason="Agent 取消;Hermes Cron 已删除")
            else:
                result = _hermes("POST", f"/api/jobs/{jid}/{action}")
            return real({"node_id": node.node_id, "job_id": jid, "result": result},
                        source="platform_ops.timeline")
        except Exception as exc:
            return unavailable(source="platform_ops.timeline", reason=str(exc))

    def _do_timeline_pause(self, p: dict[str, Any]) -> dict[str, Any]:
        return self._timeline_lifecycle(p, "pause")

    def _do_timeline_resume(self, p: dict[str, Any]) -> dict[str, Any]:
        return self._timeline_lifecycle(p, "resume")

    def _do_timeline_run(self, p: dict[str, Any]) -> dict[str, Any]:
        return self._timeline_lifecycle(p, "run")

    def _do_timeline_cancel(self, p: dict[str, Any]) -> dict[str, Any]:
        return self._timeline_lifecycle(p, "cancel")

    def _do_timeline_unread(self, p: dict[str, Any]) -> dict[str, Any]:
        from dojocore.timeline import get_timeline

        items = get_timeline().unread()
        return real(
            {"total": len(items), "items": [n.to_dict() for n in items],
             "note": "每条都必须给出处置与理由,不存在「忽略」这个选项"},
            source="platform_ops.timeline",
        )

    def _do_timeline_triage(self, p: dict[str, Any]) -> dict[str, Any]:
        from dojocore.timeline import TimelineError, get_timeline

        try:
            return real(
                get_timeline().triage(p.get("decisions") or []),
                source="platform_ops.timeline",
            )
        except TimelineError as exc:
            return unavailable(source="platform_ops.timeline", reason=str(exc))

    # ── collab ───────────────────────────────────────────────────────────
    def _do_collab_inbox(self, p: dict[str, Any]) -> dict[str, Any]:
        from dojocore.collab import get_collab_service

        items = get_collab_service().store.list(box="inbox", status=p.get("status"), limit=100)
        return real(
            {"total": len(items), "overdue": sum(1 for r in items if r.is_overdue()),
             "items": [r.to_dict() for r in items]},
            source="platform_ops.collab",
        )

    def _do_collab_outbox(self, p: dict[str, Any]) -> dict[str, Any]:
        from dojocore.collab import get_collab_service

        items = get_collab_service().store.list(box="outbox", status=p.get("status"), limit=100)
        return real({"total": len(items), "items": [r.to_dict() for r in items]},
                    source="platform_ops.collab")

    def _do_collab_capabilities(self, p: dict[str, Any]) -> dict[str, Any]:
        from dojocore.workflow import get_department_registry

        reg = get_department_registry()
        return real({"departments": [d.to_dict() for d in reg.list(enabled_only=False)]},
                    source="platform_ops.collab")

    def _do_collab_send(self, p: dict[str, Any]) -> dict[str, Any]:
        from dojocore.collab import ProtocolError, get_collab_service

        try:
            req, created = get_collab_service().send(p)
        except ProtocolError as exc:
            return unavailable(source="platform_ops.collab", reason=str(exc))
        return real({"created": created, "request": req.to_dict()}, source="platform_ops.collab")

    def _do_collab_deliver(self, p: dict[str, Any]) -> dict[str, Any]:
        from dojocore.collab import ProtocolError, get_collab_service

        try:
            req = get_collab_service().transition(
                str(p["request_id"]), box="inbox", to="DELIVERED",
                actor_dept=str(p.get("actor_dept", "seo")),
                deliverable_asset_ids=list(p.get("deliverable_asset_ids") or []),
            )
        except (ProtocolError, KeyError) as exc:
            return unavailable(source="platform_ops.collab", reason=str(exc))
        return real(req.to_dict(), source="platform_ops.collab")

    # ── config / status ──────────────────────────────────────────────────
    def _do_config_get(self, p: dict[str, Any]) -> dict[str, Any]:
        from seoagents.config import ConfigStore

        return real({"config": ConfigStore.get_instance().redacted()},
                    source="platform_ops.config")

    def _do_system_status(self, p: dict[str, Any]) -> dict[str, Any]:
        """One call answering "what is this platform able to do right now"."""
        from dojocore.capability import capabilities
        from dojocore.department import departments
        from seoagents.agent.runtime import get_runtime

        rt = get_runtime()
        caps = self._do_capability_map({})
        cap_map = caps.get("capabilities", {})
        return real(
            {
                "department": departments.active.id if departments.active else None,
                "tools_registered": rt.registry.names(),
                "capabilities_declared": capabilities.ids(),
                "single_source_risks": [k for k, v in cap_map.items() if v["single_source_risk"]],
                "uncovered_capabilities": [k for k, v in cap_map.items() if v["uncovered"]],
                "site": rt.config.sites.site_url,
                "gsc_property": rt.config.sites.gsc_property,
                "llm_provider": rt.provider.name,
            },
            source="platform_ops.status",
        )
