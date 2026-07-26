"""L4 internal linker — safe TF-IDF anchor injection."""
from __future__ import annotations

import json

import pytest

from seoagents.tools.internal_linker import InternalLinkerSpec


@pytest.fixture()
def spec() -> InternalLinkerSpec:
    return InternalLinkerSpec()


async def test_injects_one_link_per_page(spec: InternalLinkerSpec):
    html = "<p>Our seo agent platform offers technical audit and pricing options.</p>"
    result = json.loads(
        await spec.execute(
            {
                "source_html": html,
                "target_pages": [
                    {"url": "/features", "anchor_candidates": ["seo agent"]},
                    {"url": "/pricing", "anchor_candidates": ["pricing"]},
                ],
            },
            "test",
        )
    )
    assert result["status"] == "Success"
    assert result["linked_links_injected"] == 2
    assert '<a href="/features"' in result["optimized_html"]
    assert '<a href="/pricing"' in result["optimized_html"]


async def test_does_not_double_link_existing_anchor(spec: InternalLinkerSpec):
    html = '<p>See our <a href="/features">seo agent</a> page for seo tips.</p>'
    result = json.loads(
        await spec.execute(
            {
                "source_html": html,
                "target_pages": [{"url": "/other", "anchor_candidates": ["seo agent"]}],
            },
            "test",
        )
    )
    # The only "seo agent" text is already inside an anchor -> nothing injected
    assert result["linked_links_injected"] == 0
    assert result["optimized_html"].count("<a ") == 1


async def test_never_injects_inside_tag_attributes(spec: InternalLinkerSpec):
    html = '<img alt="seo agent"><p>the seo agent wins</p>'
    result = json.loads(
        await spec.execute(
            {
                "source_html": html,
                "target_pages": [{"url": "/x", "anchor_candidates": ["seo agent"]}],
            },
            "test",
        )
    )
    assert result["linked_links_injected"] == 1
    assert '<img alt="seo agent">' in result["optimized_html"]  # attribute untouched
    assert '<a href="/x" title="seo agent relative link">seo agent</a>' in result["optimized_html"]


async def test_respects_max_links(spec: InternalLinkerSpec):
    html = "<p>alpha beta gamma delta</p>"
    pages = [{"url": f"/p{i}", "anchor_candidates": [w]} for i, w in
             enumerate(["alpha", "beta", "gamma", "delta"])]
    result = json.loads(
        await spec.execute({"source_html": html, "target_pages": pages, "max_links": 2}, "t")
    )
    assert result["linked_links_injected"] == 2


async def test_empty_source_skipped(spec: InternalLinkerSpec):
    result = json.loads(await spec.execute({"source_html": "", "target_pages": []}, "t"))
    assert result["status"] == "Skipped"
