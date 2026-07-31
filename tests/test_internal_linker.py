"""InternalLinkerSpec — TF-IDF ranking, HTML-aware injection, over-link guard."""
from __future__ import annotations

import pytest

from seoagents.tools.internal_linker import InternalLinkerSpec

pytestmark = pytest.mark.asyncio


@pytest.fixture()
def spec() -> InternalLinkerSpec:
    return InternalLinkerSpec()


async def test_injects_one_link_per_page(spec: InternalLinkerSpec):
    html = "<p>Our seo agent platform offers technical audit and pricing options.</p>"
    result = await spec.execute(
        {
            "source_html": html,
            "target_pages": [
                {"url": "/features", "anchor_candidates": ["seo agent"]},
                {"url": "/pricing", "anchor_candidates": ["pricing"]},
            ],
        },
        "test",
    )
    assert result["data_status"] == "REAL"
    assert result["linked_links_injected"] == 2
    assert '<a href="/features"' in result["optimized_html"]
    assert '<a href="/pricing"' in result["optimized_html"]


async def test_does_not_double_link_existing_anchor(spec: InternalLinkerSpec):
    html = '<p>Read about <a href="/features">seo agent</a> and pricing.</p>'
    result = await spec.execute(
        {
            "source_html": html,
            "target_pages": [
                {"url": "/features", "anchor_candidates": ["seo agent"]},
                {"url": "/pricing", "anchor_candidates": ["pricing"]},
            ],
        },
        "test",
    )
    assert result["optimized_html"].count('href="/features"') == 1


async def test_never_injects_inside_tag_attributes(spec: InternalLinkerSpec):
    html = '<img alt="pricing" src="/p.png"><p>Our pricing is simple.</p>'
    result = await spec.execute(
        {
            "source_html": html,
            "target_pages": [{"url": "/pricing", "anchor_candidates": ["pricing"]}],
        },
        "test",
    )
    assert '<img alt="pricing"' in result["optimized_html"]


async def test_respects_max_links(spec: InternalLinkerSpec):
    html = "<p>alpha beta gamma delta epsilon</p>"
    pages = [
        {"url": f"/p{i}", "anchor_candidates": [w]}
        for i, w in enumerate(["alpha", "beta", "gamma", "delta", "epsilon"])
    ]
    result = await spec.execute(
        {"source_html": html, "target_pages": pages, "max_links": 2}, "test"
    )
    assert result["linked_links_injected"] == 2


async def test_empty_source_reports_unavailable(spec: InternalLinkerSpec):
    """No text is not a zero result — it is an absent one, and must say so."""
    result = await spec.execute({"source_html": "", "target_pages": []}, "test")
    assert result["data_status"] == "UNAVAILABLE"
    assert result["degraded_reason"]
