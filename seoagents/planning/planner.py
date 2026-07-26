"""Planning primitives (L3) — daily optimization plan model & builder."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

StepStatus = Literal["pending", "running", "done", "failed", "skipped"]


@dataclass
class PlanStep:
    id: str
    title: str
    tool: str = ""
    arguments: dict[str, Any] = field(default_factory=dict)
    status: StepStatus = "pending"
    output: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "tool": self.tool,
            "status": self.status,
            "output": self.output[:500],
        }


@dataclass
class Plan:
    goal: str
    steps: list[PlanStep] = field(default_factory=list)

    def next_pending(self) -> PlanStep | None:
        return next((s for s in self.steps if s.status == "pending"), None)

    def to_dict(self) -> dict[str, Any]:
        return {"goal": self.goal, "steps": [s.to_dict() for s in self.steps]}


class SeoPlanBuilder:
    """Builds the canonical daily optimization plan (mirrors the evolution cron)."""

    @staticmethod
    def build_daily_plan(site_url: str, keywords: list[str]) -> Plan:
        return Plan(
            goal=f"每日 SEO/AEO 闭环优化: {site_url}",
            steps=[
                PlanStep(id="audit", title="全站技术审计", tool="site_technical_auditor"),
                PlanStep(id="cwv", title="Core Web Vitals 评估", tool="lighthouse_audit"),
                PlanStep(
                    id="gsc", title="GSC 流量表现拉取", tool="google_seo_monitor",
                    arguments={"action": "query_gsc_performance"},
                ),
                PlanStep(
                    id="serp", title="SERP 排位追踪", tool="serp_rank_tracker",
                    arguments={"keywords": keywords},
                ),
                PlanStep(
                    id="trends", title="飙升词趋势探测", tool="google_seo_monitor",
                    arguments={"action": "query_rising_keywords", "keywords": keywords},
                ),
                PlanStep(id="aeo", title="AEO 品牌可见度探测", tool="aeo_visibility_monitor"),
                PlanStep(
                    id="fix", title="死链 301 修复与收录提交", tool="gsc_indexing_ops",
                    arguments={"action": "submit_indexing"},
                ),
            ],
        )


__all__ = ["Plan", "PlanStep", "SeoPlanBuilder"]
