from __future__ import annotations

import json
from types import SimpleNamespace

from seoagents.dashboard.routers.workflow_api import (
    _execute_tool_node,
    _node_instruction,
    _resolve_runtime_templates,
    _tool_call_arguments,
)


def _inst():
    return SimpleNamespace(
        instance_id="WF-1",
        template_version="1.1",
        context={
            "site_id": "example.com",
            "gsc_property": "sc-domain:example.com",
            "business_date": "2026-08-07",
        },
        runs={
            "collect_gsc": SimpleNamespace(
                evidence="ok", output_asset_ids=(),
                runtime_output=json.dumps({"data_status": "REAL", "d0": "2026-08-05"}),
            ),
        },
    )


def test_resolve_runtime_templates_keeps_structured_values():
    inst = _inst()
    deps = {"collect_gsc": {"runtime_output": inst.runs["collect_gsc"].runtime_output}}
    value = _resolve_runtime_templates(
        {
            "site": "{{ input.gsc_property }}",
            "asset_name": "gsc-{{ input.site_id }}-{{ input.business_date }}",
            "payload": "{{ collect_gsc }}",
            "status": "{{ collect_gsc.data_status }}",
        },
        inst=inst,
        deps=deps,
    )
    assert value["site"] == "sc-domain:example.com"
    assert value["asset_name"] == "gsc-example.com-2026-08-07"
    assert value["payload"]["d0"] == "2026-08-05"
    assert value["status"] == "REAL"


def test_tool_instruction_contains_resolved_arguments():
    inst = _inst()
    tpl = SimpleNamespace(id="daily_gsc_performance")
    node = SimpleNamespace(
        id="normalize", title="标准化", type=__import__(
            "dojocore.workflow.nodes", fromlist=["NodeType"]
        ).NodeType.TOOL_CALL,
        depends_on=("collect_gsc",), acceptance=(),
        config={
            "tool": "google_seo_monitor",
            "action": "normalize_gsc_module",
            "arguments": {"payload": "{{ collect_gsc }}"},
        },
    )
    instruction = _node_instruction(inst, tpl, node)
    assert '"d0": "2026-08-05"' in instruction
    assert "{{ collect_gsc }}" not in instruction
    assert "normalize_gsc_module" in instruction


def test_tool_call_arguments_injects_action_and_resolves_payload():
    inst = _inst()
    node = SimpleNamespace(
        id="normalize",
        depends_on=("collect_gsc",),
        config={
            "action": "normalize_gsc_module",
            "arguments": {"payload": "{{ collect_gsc }}"},
        },
    )
    assert _tool_call_arguments(inst, node) == {
        "action": "normalize_gsc_module",
        "payload": {"data_status": "REAL", "d0": "2026-08-05"},
    }


async def test_deterministic_tool_rejects_non_real_result(monkeypatch):
    class Executor:
        async def execute_one(self, call, session_id=""):
            return SimpleNamespace(
                ok=True,
                content=json.dumps(
                    {"data_status": "UNAVAILABLE", "degraded_reason": "asset storage unavailable"}
                ),
                error="",
            )

    runtime = SimpleNamespace(executor=Executor())
    monkeypatch.setattr("seoagents.agent.runtime.get_runtime", lambda: runtime)
    inst = _inst()
    node = SimpleNamespace(
        id="archive",
        depends_on=("collect_gsc",),
        config={"tool": "asset_hub", "action": "put", "arguments": {"name": "x", "content": "x"}},
    )
    run = SimpleNamespace(attempts=1)
    ok, output, error = await _execute_tool_node(inst, node, run)
    assert ok is False
    assert "UNAVAILABLE" in error
    assert "asset storage unavailable" in output
