"""Multi-agent orchestration (L3) — Auditor / Writer / Linker collaboration.

The manual's L3 mandate: "由 Auditor、Writer 和 Linker 智能体协同处理内容诊断
与 A/B 策略整改". Each role is a scoped agent loop sharing one ToolRegistry;
the orchestrator pipes findings forward:

    Auditor(诊断) --findings--> Writer(整改内容) --html--> Linker(内链植入)
"""
from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from typing import Any

from seoagents.agent.loop import UniversalAgentLoop
from seoagents.agent.models import AgentRunResult
from seoagents.config.models import SeoAgentsConfig
from seoagents.logging import LOGGER


@dataclass(frozen=True)
class AgentRole:
    name: str
    system_prompt: str
    allowed_tools: frozenset[str]


AUDITOR = AgentRole(
    name="auditor",
    system_prompt=(
        "role=auditor 你是 SEOAgents 的技术审计智能体。使用工具对目标站点执行"
        "技术审计与性能评估,汇总: 致命问题(error)、警告(warning)、死链清单、"
        "Core Web Vitals。输出结构化 JSON 摘要。"
    ),
    allowed_tools=frozenset({"site_technical_auditor", "lighthouse_audit", "google_seo_monitor"}),
)

WRITER = AgentRole(
    name="writer",
    system_prompt=(
        "role=writer 你是 SEOAgents 的内容整改智能体。依据审计发现与 E-E-A-T 规则"
        "(EEATSignalRules 技能)与 Schema 模版(SchemaTemplates 技能),产出整改后的"
        "HTML 内容与修复说明。返回 JSON: {summary, source_html}。"
    ),
    allowed_tools=frozenset(),
)

LINKER = AgentRole(
    name="linker",
    system_prompt=(
        "role=linker 你是 SEOAgents 的内链优化智能体。对 Writer 产出的 HTML 调用 "
        "nlp_internal_linker,依据整站页面库注入语义最相关的内链锚文本。"
    ),
    allowed_tools=frozenset({"nlp_internal_linker"}),
)


@dataclass
class PipelineResult:
    session_id: str
    auditor: AgentRunResult | None = None
    writer: AgentRunResult | None = None
    linker: AgentRunResult | None = None
    merged_trace: list[dict[str, Any]] = field(default_factory=list)

    @property
    def optimized_html(self) -> str:
        if self.linker is None:
            return ""
        for step in reversed(self.linker.trace):
            if step.tool == "nlp_internal_linker" and step.ok:
                try:
                    return json.loads(step.output).get("optimized_html", "")
                except json.JSONDecodeError:
                    return ""
        return ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "auditor_summary": self.auditor.final_text if self.auditor else "",
            "writer_summary": self.writer.final_text if self.writer else "",
            "linker_summary": self.linker.final_text if self.linker else "",
            "optimized_html": self.optimized_html,
            "trace_len": len(self.merged_trace),
        }


class MultiAgentOrchestrator:
    def __init__(self, loop: UniversalAgentLoop, config: SeoAgentsConfig) -> None:
        self.loop = loop
        self.config = config

    async def run_content_pipeline(self, target_url: str | None = None) -> PipelineResult:
        """Auditor -> Writer -> Linker, forwarding artifacts between stages."""
        site = target_url or self.config.sites.site_url
        session_id = f"pipe_{uuid.uuid4().hex[:10]}"
        result = PipelineResult(session_id=session_id)
        LOGGER.info(f"Content pipeline start site={site} session={session_id}")

        # 1) Auditor — diagnose
        result.auditor = await self.loop.run(
            f"对站点 {site} 执行完整技术审计并总结发现。",
            system=AUDITOR.system_prompt,
            allowed_tools=set(AUDITOR.allowed_tools),
            session_id=f"{session_id}:auditor",
        )
        result.merged_trace.extend(result.auditor.trace_dicts())

        # 2) Writer — remediate content
        writer_task = json.dumps(
            {
                "instruction": "依据以下审计发现产出整改内容",
                "audit_findings": result.auditor.final_text[:6000],
            },
            ensure_ascii=False,
        )
        result.writer = await self.loop.run(
            writer_task,
            system=WRITER.system_prompt,
            allowed_tools=set(WRITER.allowed_tools),
            session_id=f"{session_id}:writer",
        )
        result.merged_trace.extend(result.writer.trace_dicts())

        # 3) Linker — inject internal links into writer output
        source_html = self._extract_writer_html(result.writer.final_text)
        target_pages = [
            {"url": p.url, "anchor_candidates": list(p.anchor_candidates)}
            for p in self.config.sites.content_pages
        ] or self._default_target_pages()
        linker_task = json.dumps(
            {"source_html": source_html, "target_pages": target_pages}, ensure_ascii=False
        )
        result.linker = await self.loop.run(
            linker_task,
            system=LINKER.system_prompt,
            allowed_tools=set(LINKER.allowed_tools),
            session_id=f"{session_id}:linker",
        )
        result.merged_trace.extend(result.linker.trace_dicts())

        LOGGER.info(
            f"Content pipeline done session={session_id} trace_len={len(result.merged_trace)}"
        )
        return result

    @staticmethod
    def _extract_writer_html(final_text: str) -> str:
        try:
            payload = json.loads(final_text)
            if isinstance(payload, dict) and payload.get("source_html"):
                return str(payload["source_html"])
        except json.JSONDecodeError:
            pass
        return final_text or "<p>(writer produced no content)</p>"

    def _default_target_pages(self) -> list[dict[str, Any]]:
        site = self.config.sites.site_url
        return [
            {"url": f"{site}/features", "anchor_candidates": ["seo agent", "features"]},
            {"url": f"{site}/pricing", "anchor_candidates": ["pricing", "aeo monitoring"]},
        ]


__all__ = ["AUDITOR", "LINKER", "WRITER", "AgentRole", "MultiAgentOrchestrator", "PipelineResult"]
