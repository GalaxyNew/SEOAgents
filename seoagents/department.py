"""The SEO department, declared.

This file is the whole answer to "what makes SEOAgents an SEO system". Anything
not stated here is framework and is shared with every other department — which
is what lets the next one (search, content, ...) be a sibling declaration rather
than a fork.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from dojocore.department import DepartmentBuilder, DepartmentProfile, departments

_HERE = Path(__file__).parent


def _register_tools(registry: Any, config: Any, sandbox: Any, store: Any = None) -> None:
    from seoagents.tools import register_default_tools
    register_default_tools(registry, config, sandbox, store)


def _metric_engine(config: Any) -> Any:
    from seoagents.quant.scoring import SeoScoreEngine
    return SeoScoreEngine(config.scoring)


def build_profile() -> DepartmentProfile:
    return (
        DepartmentBuilder("seo", "SEO 部", "自然搜索流量的端到端负责部门")
        # ── 可被其他部门请求的能力 ───────────────────────────────
        .capability("serp_rank", "SERP 排名",
                    description="关键词在搜索结果中的实测位置",
                    result_schema="serp_rank", sla_hours=2)
        .capability("keyword_research", "关键词研究",
                    description="搜索量、竞争度、相关词与意图分层",
                    result_schema="keyword_research", sla_hours=4)
        .capability("site_audit", "全站技术审计",
                    description="抓取、索引、结构化数据、死链与重定向",
                    result_schema="site_audit", sla_hours=24)
        .capability("page_audit", "单页分析",
                    result_schema="page_audit", sla_hours=4)
        .capability("cwv", "Core Web Vitals",
                    result_schema="cwv", sla_hours=4)
        .capability("traffic", "真实流量",
                    description="GSC 点击、展现、CTR 与均位",
                    result_schema="traffic", sla_hours=4, comparable=False)
        .capability("indexing", "收录与提交",
                    result_schema="indexing", sla_hours=8, comparable=False)
        .capability("backlink", "外链",
                    result_schema="backlink", sla_hours=48)
        .capability("internal_link", "内链",
                    result_schema="internal_link", sla_hours=2, comparable=False)
        .capability("aeo_visibility", "AI 搜索可见度",
                    description="品牌在 AI 答案首屏的被引用率",
                    result_schema="aeo_visibility", sla_hours=72)
        .capability("content_publish", "内容发布",
                    description="排版、发布、线上回读校验",
                    result_schema="content_publish", sla_hours=24, comparable=False)
        # ── 实现 ─────────────────────────────────────────────────
        .tools(_register_tools)
        .templates(_HERE / "workflows")
        .metrics(_metric_engine)
        .catalog(_HERE / "plugins" / "catalog" / "builtin.yaml")
        .meta(headline_metric="M_t", secondary_metric="V_t")
        .build()
    )


PROFILE = departments.register(build_profile(), activate=True)

__all__ = ["PROFILE", "build_profile"]
