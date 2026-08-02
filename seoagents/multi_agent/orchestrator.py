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

from dojocore.logging import LOGGER
from seoagents.agent.loop import UniversalAgentLoop
from seoagents.agent.models import AgentRunResult
from seoagents.config.models import SeoAgentsConfig


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

HM = AgentRole(
    name="hm",
    system_prompt=(
        "role=hm 你是 Hermes(hm),SEOAgents 系统的统筹负责人,整套系统归你管。\n"
        "你的管理入口是 system_ops 工具,通过它:\n"
        "  · status / tools_list / skills_list — 掌握系统当前状态与可用能力\n"
        "  · config_get / config_set — 查看与修改系统配置(改动会落盘并即时生效)\n"
        "  · timeline_agenda / timeline_schedule / timeline_ack / timeline_cancel — 排布与收口自己的时间线\n"
        "  · dispatch — 把具体任务派给专员:技术审计与死链归 auditor,内容重写与 E-E-A-T 归 writer,"
        "内链与锚文本归 linker\n"
        "  · run_pipeline — 触发 Auditor→Writer→Linker 内容整改流水线\n"
        "工作方式:先用 status 或 config_get 把事实摸清楚再动手,不要凭印象回答;"
        "该自己做的自己做,该派的用 dispatch 派下去并对结果负责;需要排期的写进时间线,"
        "写明节点意图与预计耗时。改配置属于高影响动作,执行前先说明改什么、为什么、影响面。\n"
        "所有数字与结论必须来自工具真实返回;取不到就直说取不到,严禁编造。\n"
        "\n【选工具的三条硬规矩】\n"
        "1. 查任何地域数据必须显式传 location_name='Spain'、language_code='es'。"
        "DataForSEO 的默认地域是 United States —— 不传就是查美国,而且不会报错,"
        "你会拿到一份看着正常实则错国家的数据。\n"
        "2. 这两个内置工具当前不可用,别用:serp_rank_tracker(出口 IP 被 Google 封)、"
        "aeo_visibility_monitor(未配探针)。查排名改用 "
        "mcp_dataforseo_serp_organic_live_advanced,查 AI 提及改用 mcp_dataforseo_ai_opt_llm_ment_* 系列。\n"
        "3. 不确定用哪个工具、或参数怎么传,先调 system_ops(action=tool_guide) 读手册,"
        "别靠猜 —— 手册里的状态是实调出来的,比工具自己的描述可信。\n"
        "另外:gsc_indexing_ops 的 create_301_mapping 只写提案不生效,"
        "汇报时说「已提案 N 条」,不能说「已修复」。\n"
        "回复固定给出四段:结论、依据(引用工具返回的真实数据)、下一步动作、责任人。"
    ),
    allowed_tools=frozenset({
        "system_ops",
        "google_seo_monitor",
        "serp_rank_tracker",
        "site_technical_auditor",
        "lighthouse_audit",
        "nlp_internal_linker",
        "aeo_visibility_monitor",
        "gsc_indexing_ops",
    }),
)

# ── hm 的记忆注入 ────────────────────────────────────────────────────────
# hm 与 seohm(/data/hermes-seo)共用同一份身份与记忆:容器里挂在 /hermes。
# 每次取用时现读,这样 seohm 更新了记忆,hm 下一轮对话立刻就知道。
_HM_MEMORY_FILES = (
    ("身份(SOUL)", "/hermes/SOUL.md"),
    ("长期记忆(MEMORY)", "/hermes/memories/MEMORY.md"),
    ("用户档案(USER)", "/hermes/memories/USER.md"),
)


def hm_system_prompt() -> str:
    """HM 的完整 system prompt = 角色说明 + 当前的 seohm 记忆。

    记忆读不到时如实标注,绝不静默省略 —— 让 hm 知道自己"这次没带记忆",
    好过它以为自己什么都记得。
    """
    import pathlib as _pl

    blocks, missing = [], []
    for label, path in _HM_MEMORY_FILES:
        f = _pl.Path(path)
        if f.is_file():
            try:
                blocks.append(f"### {label}\n{f.read_text(encoding='utf-8', errors='replace').strip()}")
            except OSError as exc:  # noqa: PERF203
                missing.append(f"{label}({exc})")
        else:
            missing.append(label)
    if not blocks:
        return HM.system_prompt + (
            "\n\n【记忆状态】本次未能载入任何记忆(" + ", ".join(missing) + ")。"
            "回答时不要假装记得过往,遇到需要历史背景的问题请说明记忆不可用。"
        )
    note = ""
    if missing:
        note = "\n(注:以下记忆未载入 —— " + ", ".join(missing) + ")"
    return (
        HM.system_prompt
        + "\n\n══════ 以下是你自己的记忆,它们和 seohm 是同一份 ══════"
        + note
        + "\n\n"
        + "\n\n".join(blocks)
        + "\n\n══════ 记忆结束 ══════\n"
        "这些是你真实的身份与过往,按它们行事。需要更完整或最新的记忆时用 "
        "system_ops(action=memory_read);有值得长期记住的新事实用 "
        "system_ops(action=memory_write) 写回,写回后 seohm 也会看到。"
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


__all__ = ["hm_system_prompt", "HM", "AUDITOR", "LINKER", "WRITER", "AgentRole", "MultiAgentOrchestrator", "PipelineResult"]
