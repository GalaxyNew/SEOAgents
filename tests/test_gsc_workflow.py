"""生产 GSC 工作流模板必须由确定性工具闭环。"""
from __future__ import annotations

import tempfile

from dojocore.workflow.store import WorkflowStore


def _template():
    import seoagents.department  # noqa: F401 - activate SEO templates

    tpl = WorkflowStore(tempfile.mkdtemp()).template("daily_gsc_performance")
    assert tpl is not None
    return tpl


def test_gsc_template_loads_and_is_production_version():
    tpl = _template()
    assert tpl.id == "daily_gsc_performance"
    assert tpl.version == "1.1"
    assert tpl.summary()["node_count"] == 6
    assert tpl.summary()["human_gates"] == []


def test_gsc_template_is_deterministic_archive_before_persist():
    tpl = _template()
    assert tpl.layers() == [
        ["input"], ["collect_gsc"], ["normalize"], ["archive"], ["persist"], ["output"]
    ]
    for node_id in ("collect_gsc", "normalize", "archive", "persist"):
        assert tpl.node(node_id).type.value == "tool_call"
    assert tpl.node("collect_gsc").config["action"] == "collect_gsc_module"
    assert tpl.node("normalize").config["action"] == "normalize_gsc_module"
    normalize_args = tpl.node("normalize").config["arguments"]
    assert normalize_args["workflow_instance_id"] == "{{ runtime.instance_id }}"
    assert normalize_args["timeline_node_id"] == "{{ context.timeline_node_id }}"
    assert tpl.node("archive").config["tool"] == "asset_hub"
    assert tpl.node("archive").config["action"] == "put"
    assert set(tpl.node("persist").depends_on) == {"normalize", "archive"}
    assert tpl.node("persist").config["action"] == "persist_gsc_module"


def test_gsc_template_has_no_second_clock_or_mock_path():
    tpl = _template()
    raw = str(tpl.to_dict()).lower()
    assert "cron" not in raw
    assert "schedule" not in raw
    assert "mock" not in raw
    assert "query_gsc_performance" not in raw
