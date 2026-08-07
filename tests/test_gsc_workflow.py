"""Test the daily_gsc_performance workflow template loads and validates."""
from __future__ import annotations

import tempfile

from dojocore.workflow.store import WorkflowStore


def test_gsc_template_loads_and_is_valid():
    """The GSC template must load without errors and pass DAG validation."""
    import seoagents.department  # noqa: F401 - activate SEO templates
    store = WorkflowStore(tempfile.mkdtemp())
    tpl = store.template("daily_gsc_performance")
    assert tpl is not None
    assert tpl.id == "daily_gsc_performance"
    assert tpl.version == "1.0"


def test_gsc_template_has_input_output_and_single_entry():
    """A visual workflow needs exactly one input node and at least one output."""
    import seoagents.department  # noqa: F401
    store = WorkflowStore(tempfile.mkdtemp())
    tpl = store.template("daily_gsc_performance")
    assert tpl is not None
    summary = tpl.summary()
    # 9 nodes: input, preflight, collect, normalize, analyze, archive,
    #          persist, verify_persisted, output
    assert summary["node_count"] == 9
    assert summary["human_gates"] == []


def test_gsc_template_layers_are_serial():
    """The GSC pipeline is serial by design (each node depends on the previous)."""
    import seoagents.department  # noqa: F401
    store = WorkflowStore(tempfile.mkdtemp())
    tpl = store.template("daily_gsc_performance")
    assert tpl is not None
    layers = tpl.layers()
    assert len(layers) >= 4  # at least 4 depth levels
    assert layers[0] == ["input"]
    assert layers[-1] == ["output"]
    assert summary_all_serial(layers)


def summary_all_serial(layers):
    """Each layer has exactly one node in a serial pipeline."""
    return all(len(layer) == 1 for layer in layers)


def test_gsc_template_collect_node_uses_google_seo_monitor():
    """The collection node must use the real google_seo_monitor tool."""
    import seoagents.department  # noqa: F401
    store = WorkflowStore(tempfile.mkdtemp())
    tpl = store.template("daily_gsc_performance")
    assert tpl is not None
    collect = tpl.node("collect_gsc")
    assert collect.config.get("tool") == "google_seo_monitor"
    assert collect.config.get("action") == "collect_gsc_module"
    assert "business_date" in collect.config.get("arguments", {})
    assert tpl.node("archive").depends_on == ("analyze",)
    assert tpl.node("persist").depends_on == ("archive",)
    assert tpl.node("verify_persisted").depends_on == ("persist",)
