from __future__ import annotations

import json
from types import SimpleNamespace

from seoagents.dashboard.routers.workflow_api import (
    _execute_tool_node,
    _lookup_runtime_value,
    _node_instruction,
    _resolve_runtime_templates,
    _tool_call_arguments,
)


def _inst():
    return SimpleNamespace(
        instance_id="WF-1",
        template_id="daily_gsc_performance",
        template_version="1.1",
        context={
            "site_id": "context-must-not-win.example",
            "timeline_node_id": "TL-REAL-1",
            "input_params": {
                "site_id": "example.com",
                "gsc_property": "sc-domain:example.com",
                "business_date": "2026-08-07",
                "timeline_node_id": "TL-INPUT-MUST-NOT-WIN",
                "instance_id": "WF-INPUT-MUST-NOT-WIN",
            },
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


def test_runtime_input_and_context_namespaces_are_isolated_and_fail_closed():
    inst = _inst()
    deps = {
        "runtime": {"runtime_output": json.dumps({"instance_id": "WF-UPSTREAM-FAKE"})},
    }

    assert _lookup_runtime_value("runtime.instance_id", inst=inst, deps=deps) == "WF-1"
    assert _lookup_runtime_value("context.timeline_node_id", inst=inst, deps=deps) == "TL-REAL-1"
    assert _lookup_runtime_value("input.timeline_node_id", inst=inst, deps=deps) == "TL-INPUT-MUST-NOT-WIN"
    assert _lookup_runtime_value("input.site_id", inst=inst, deps=deps) == "example.com"
    assert _lookup_runtime_value("context.site_id", inst=inst, deps=deps) == "context-must-not-win.example"
    assert _lookup_runtime_value("context.input_params.site_id", inst=inst, deps=deps) is None
    assert _lookup_runtime_value("runtime.unknown", inst=inst, deps=deps) is None


def test_input_never_falls_back_to_top_level_context():
    inst = _inst()
    inst.context["input_params"] = {}
    assert _lookup_runtime_value("input.site_id", inst=inst, deps={}) is None


def test_legacy_instance_without_timeline_has_explicit_empty_contract():
    inst = _inst()
    inst.context.pop("timeline_node_id")
    resolved = _resolve_runtime_templates(
        {
            "workflow_instance_id": "{{ runtime.instance_id }}",
            "timeline_node_id": "{{ context.timeline_node_id }}",
        },
        inst=inst,
        deps={},
    )
    assert resolved == {"workflow_instance_id": "WF-1", "timeline_node_id": ""}


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
            "arguments": {
                "payload": "{{ collect_gsc }}",
                "workflow_instance_id": "{{ runtime.instance_id }}",
                "timeline_node_id": "{{ context.timeline_node_id }}",
            },
        },
    )
    assert _tool_call_arguments(inst, node) == {
        "action": "normalize_gsc_module",
        "payload": {"data_status": "REAL", "d0": "2026-08-05"},
        "workflow_instance_id": "WF-1",
        "timeline_node_id": "TL-REAL-1",
    }


async def test_deterministic_tool_rejects_non_real_result(monkeypatch):
    class Executor:
        async def execute_one(self, call, session_id="", runtime_metadata=None):
            assert runtime_metadata == {
                "instance_id": "WF-1",
                "node_id": "archive",
                "timeline_node_id": "TL-REAL-1",
                "lineage_instance_id": "",
                "lineage_timeline_node_id": "",
            }
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


async def test_normalize_execution_binds_resolved_lineage_to_runtime_metadata(monkeypatch):
    captured = {}

    class Executor:
        async def execute_one(self, call, session_id="", runtime_metadata=None):
            captured["arguments"] = dict(call.arguments)
            captured["runtime_metadata"] = dict(runtime_metadata or {})
            return SimpleNamespace(
                ok=True,
                content=json.dumps({"data_status": "REAL", "run": {}}),
                error="",
            )

    monkeypatch.setattr(
        "seoagents.agent.runtime.get_runtime",
        lambda: SimpleNamespace(executor=Executor()),
    )
    inst = _inst()
    node = SimpleNamespace(
        id="normalize",
        depends_on=("collect_gsc",),
        config={
            "tool": "google_seo_monitor",
            "action": "normalize_gsc_module",
            "arguments": {
                "payload": "{{ collect_gsc }}",
                "workflow_instance_id": "{{ runtime.instance_id }}",
                "timeline_node_id": "{{ context.timeline_node_id }}",
            },
        },
    )
    ok, _, error = await _execute_tool_node(inst, node, SimpleNamespace(attempts=1))
    assert ok is True and error == ""
    assert captured["arguments"]["workflow_instance_id"] == "WF-1"
    assert captured["arguments"]["timeline_node_id"] == "TL-REAL-1"
    assert captured["runtime_metadata"] == {
        "instance_id": "WF-1",
        "node_id": "normalize",
        "timeline_node_id": "TL-REAL-1",
        "lineage_instance_id": "WF-1",
        "lineage_timeline_node_id": "TL-REAL-1",
    }
