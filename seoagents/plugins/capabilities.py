"""Capabilities — the unit that makes tools interchangeable and comparable.

A tool declares *what question it answers*, not just what it is called. Two
tools that declare the same capability must emit the same normalised shape, and
can therefore be run side by side and cross-checked against each other.

That cross-check is the point. A single data source can only be believed or
disbelieved; two independent sources produce a third outcome — disagreement —
which is itself the most valuable signal available, because synthetic data
almost never agrees with a real measurement.
"""
from __future__ import annotations

from enum import Enum


class Capability(str, Enum):
    SERP_RANK = "serp_rank"                  # keyword position in search results
    KEYWORD_RESEARCH = "keyword_research"    # volume / difficulty / related terms
    SITE_AUDIT = "site_audit"                # site-wide technical issues
    PAGE_AUDIT = "page_audit"                # single-page on-page analysis
    CWV = "cwv"                              # Core Web Vitals
    TRAFFIC = "traffic"                      # real traffic (GSC / GA)
    INDEXING = "indexing"                    # index status and submission
    BACKLINK = "backlink"
    INTERNAL_LINK = "internal_link"
    AEO_VISIBILITY = "aeo_visibility"        # brand visibility in AI answers
    CONTENT_PUBLISH = "content_publish"      # publish + read-back verification

    @property
    def label(self) -> str:
        return _LABELS.get(self, self.value)


_LABELS: dict[Capability, str] = {
    Capability.SERP_RANK: "SERP 排名",
    Capability.KEYWORD_RESEARCH: "关键词研究",
    Capability.SITE_AUDIT: "全站技术审计",
    Capability.PAGE_AUDIT: "单页分析",
    Capability.CWV: "Core Web Vitals",
    Capability.TRAFFIC: "真实流量",
    Capability.INDEXING: "收录与提交",
    Capability.BACKLINK: "外链",
    Capability.INTERNAL_LINK: "内链",
    Capability.AEO_VISIBILITY: "AI 搜索可见度",
    Capability.CONTENT_PUBLISH: "内容发布",
}

__all__ = ["Capability"]
