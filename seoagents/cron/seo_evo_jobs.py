"""seo_self_evolution_pipeline (L2→L6→L5) — 每日自适应演化与审计闭环流水线.

Fixed, fully-wired rewrite of manual §6.2. Every number that feeds the M_t
formula is *measured* by real L4 tool executions (mock-degradable), not the
hard-coded literals of the manual:

  1. L4 沙箱审计     -> issues / dead links / Lighthouse performance
  2. L4 指标工具     -> GSC clicks, SERP positions, trend weights, AEO rates
  3. L6 评分引擎     -> M_t = α·C_t + β·I_t + γ·Σ W_i/R_it − δ·E_t
  4. 死链整改        -> 301 mapping + sitemap + (dry-run) indexing submission
  5. L5 技能编译     -> M_t 超阈值时把整改 trace 固化为静态技能
  6. L2 网关推送     -> 飞书演化简报卡片
"""
from __future__ import annotations

import json
import re
from typing import Any
from urllib.parse import urlparse

from seoagents.agent.models import ToolCall
from seoagents.agent.runtime import Runtime, get_runtime
from seoagents.cron import scheduler
from seoagents.logging import LOGGER

EVOLUTION_JOB_ID = "seo_self_evolution_pipeline"
FIX_SKILL_ID = "FixDeadLinkWithAutoIndexSkill"


async def run_seo_self_evolution_pipeline(runtime: Runtime | None = None) -> dict[str, Any]:
    """One full evolution cycle. Returns a structured summary (also persisted)."""
    rt = runtime or get_runtime()
    config = rt.config
    site = config.sites.site_url
    session_id = "cron:evolution"
    trace: list[dict[str, Any]] = []

    LOGGER.info("========= 启动 SEOAgents 自适应演化与审计闭环流水线 =========")

    async def call(tool: str, args: dict[str, Any]) -> str:
        res = await rt.executor.execute_one(ToolCall(name=tool, arguments=args), session_id=session_id)
        trace.append(
            {
                "action": f"{tool}.{args.get('action')}" if args.get("action") else tool,
                "tool": tool,
                "arguments": args,
                "output": res.as_text(),
                "ok": res.ok,
            }
        )
        return res.as_text()

    # 1) Technical audit + Lighthouse -------------------------------------
    audit_raw = await call("site_technical_auditor", {"start_url": site})
    audit = _safe_json(audit_raw)
    issues = audit.get("issues", [])
    dead_links = audit.get("dead_links", [])
    pages_crawled = int(audit.get("pages_crawled", 0)) or 1

    lh_raw = await call("lighthouse_audit", {"target_url": site})
    lighthouse = _safe_json(lh_raw)
    performance = float(lighthouse.get("performance_score", 0.0))

    # 2) Traffic / SERP / trends / AEO ------------------------------------
    gsc_out = await call("google_seo_monitor", {"action": "query_gsc_performance"})
    clicks = _parse_total_clicks(gsc_out)

    serp_raw = await call(
        "serp_rank_tracker", {"keywords": list(config.sites.tracked_keywords)}
    )
    serp = _safe_json(serp_raw).get("positions", {})
    positions = {kw: entry.get("position") for kw, entry in serp.items()}

    await call("google_seo_monitor", {"action": "query_rising_keywords"})
    monitor_spec = rt.registry.get("google_seo_monitor")
    trend_weights = {
        kw: monitor_spec.trend_weight(kw) if monitor_spec else 1.0
        for kw in config.sites.tracked_keywords
    }

    aeo_raw = await call("aeo_visibility_monitor", {})
    aeo = _safe_json(aeo_raw)
    v_t = float(aeo.get("v_t", 0.0))

    # 3) Error accounting + M_t -------------------------------------------
    error_count = len(dead_links) + sum(1 for i in issues if i.get("severity") == "error")
    if performance and performance < 90:
        error_count += 3
    index_ratio = pages_crawled / (pages_crawled + len(dead_links))

    breakdown = rt.score_engine.compute_m_t(
        clicks=clicks,
        index_ratio=index_ratio,
        positions=positions,
        trend_weights=trend_weights,
        error_count=error_count,
    )
    m_t = round(breakdown.m_t, 4)  # single canonical value: stored == reported
    LOGGER.info(f"今日 SEO 综合演化评估得分 M_t: {m_t:.4f} (技术缺陷扣分项: {error_count})")

    # 4) Dead-link remediation (301 + sitemap + submission) ---------------
    links_fixed = 0
    if dead_links:
        redirects = [
            {"from_path": urlparse(link["url"]).path or "/", "to_path": "/"}
            for link in dead_links
        ]
        await call("gsc_indexing_ops", {"action": "create_301_mapping", "redirects": redirects})
        healthy_urls = [site] + [
            f"{site}/{kw.replace(' ', '-')}" for kw in config.sites.tracked_keywords
        ]
        await call("gsc_indexing_ops", {"action": "build_sitemap", "urls": healthy_urls})
        await call("gsc_indexing_ops", {"action": "submit_indexing"})
        links_fixed = len(redirects)

    # 5) Persist + skill distillation (L5) --------------------------------
    rt.store.record_audit_run(
        site=site,
        m_t=m_t,
        clicks=clicks,
        index_ratio=index_ratio,
        error_count=error_count,
        breakdown=breakdown.to_dict(),
    )

    compiled_skill: str | None = None
    if rt.score_engine.should_compile_skill(m_t) and links_fixed:
        LOGGER.info("当前整改策略表现优越,触发 L5 技能编译器,固化 301 重定向与收录提交技能")
        fix_trace = [t for t in trace if t["tool"] == "gsc_indexing_ops"]
        path = rt.skill_compiler.auto_distill_trace(
            skill_id=FIX_SKILL_ID,
            trace_history=fix_trace,
            description="死链自动 301 修复 + sitemap 重建 + 收录提交 (自进化固化)",
            m_t=m_t,
        )
        rt.store.record_skill_compilation(skill_id=FIX_SKILL_ID, m_t=m_t, trace_len=len(fix_trace))
        compiled_skill = FIX_SKILL_ID
        LOGGER.info(f"高表现自进化静态技能编译成功,已固化至: {path}")

    # 6) Gateway broadcast (L2) -------------------------------------------
    await rt.notifier.broadcast_evolution_alert(
        m_t_score=m_t,
        performance=performance,
        links_fixed=links_fixed,
        extra={"v_t": v_t, "issues": len(issues), "compiled_skill": compiled_skill},
    )

    summary = {
        "m_t": m_t,
        "breakdown": breakdown.to_dict(),
        "clicks": clicks,
        "index_ratio": round(index_ratio, 4),
        "performance": performance,
        "issues": len(issues),
        "dead_links": len(dead_links),
        "links_fixed": links_fixed,
        "v_t": v_t,
        "compiled_skill": compiled_skill,
        "trace_len": len(trace),
    }
    LOGGER.info(f"演化流水线完成: {json.dumps(summary, ensure_ascii=False)[:400]}")
    return summary


def register_jobs(runtime: Runtime) -> None:
    """Attach the nightly evolution job per scheduler config (default 02:00)."""
    try:
        from apscheduler.triggers.cron import CronTrigger
    except ImportError:
        LOGGER.warning("APScheduler not installed — nightly evolution job disabled")
        return
    sched_cfg = runtime.config.scheduler
    scheduler.add_job(
        run_seo_self_evolution_pipeline,
        CronTrigger(hour=sched_cfg.evolution_hour, minute=sched_cfg.evolution_minute),
        id=EVOLUTION_JOB_ID,
        kwargs={"runtime": runtime},
        replace_existing=True,
        misfire_grace_time=3600,
    )
    LOGGER.info(
        f"Evolution job registered at "
        f"{sched_cfg.evolution_hour:02d}:{sched_cfg.evolution_minute:02d} UTC daily"
    )


# -- helpers ---------------------------------------------------------------
def _safe_json(text: str) -> dict[str, Any]:
    try:
        data = json.loads(text)
        return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, TypeError):
        return {}


def _parse_total_clicks(gsc_output: str) -> float:
    match = re.search(r"total_clicks=([\d.]+)", gsc_output)
    return float(match.group(1)) if match else 0.0


__all__ = ["run_seo_self_evolution_pipeline", "register_jobs", "EVOLUTION_JOB_ID", "FIX_SKILL_ID"]
