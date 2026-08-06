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

from dojocore.logging import LOGGER
from dojocore.quality import DataStatus, extract_status
from seoagents.agent.models import ToolCall
from seoagents.agent.runtime import Runtime, get_runtime
from seoagents.cron import scheduler

EVOLUTION_JOB_ID = "seo_self_evolution_pipeline"
FIX_SKILL_ID = "FixDeadLinkWithAutoIndexSkill"


async def run_evolution_for_site(rt: Runtime, site_item: Any) -> dict[str, Any]:
    """对**一个**站点跑完整的一轮演化。

    每个受监控站点都是独立的评估对象:自己的 GSC 属性、自己的关键词、
    自己的品牌名、自己的 M_t 历史。没有「主站」这回事 —— 早先整条流水线
    只跑 config.sites.site_url,另外两个站配了也不会被看一眼。
    """
    config = rt.config
    site = site_item.site_url
    gsc_property = site_item.gsc_property
    keywords = list(site_item.tracked_keywords)
    brand = site_item.brand_name
    session_id = f"cron:evolution:{site}"
    trace: list[dict[str, Any]] = []

    LOGGER.info(f"===== 演化流水线开始 · {brand} ({site}) =====")

    # Every measurement records the trust level of its source so the scoring
    # gate can refuse to produce a number from a degraded input.
    sources: dict[str, str] = {}

    async def call(tool: str, args: dict[str, Any], *, label: str | None = None) -> str:
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
        if label:
            if not res.ok:
                sources[label] = DataStatus.UNAVAILABLE.value
            else:
                st = extract_status(res.as_text())
                sources[label] = (st or DataStatus.UNAVAILABLE).value
        return res.as_text()

    # 1) Technical audit + Lighthouse -------------------------------------
    audit_raw = await call("site_technical_auditor", {"start_url": site}, label="site_audit")
    audit = _safe_json(audit_raw)
    issues = audit.get("issues", [])
    dead_links = audit.get("dead_links", [])
    pages_crawled = int(audit.get("pages_crawled", 0)) or 1
    crawled_urls = list(audit.get("crawled_urls") or [])

    lh_raw = await call("lighthouse_audit", {"target_url": site}, label="cwv")
    lighthouse = _safe_json(lh_raw)
    # No zero-filling: 0/100 reads as "measured, and catastrophic", which is a
    # very different message from "not measured".
    _perf_raw = lighthouse.get("performance_score")
    performance = float(_perf_raw) if _perf_raw is not None else None

    # 2) Traffic / SERP / trends / AEO ------------------------------------
    gsc_out = await call(
        "google_seo_monitor",
        {"action": "query_gsc_performance", "target_site": gsc_property},
        label="traffic",
    )
    current_clicks = _parse_total_clicks(gsc_out)

    # C_t is defined as the organic click *delta*, not the running total. Using
    # the total made M_t track traffic scale, so `should_compile_skill(m_t)`
    # effectively asked "is this site big?" rather than "did this change help?".
    previous_clicks = rt.store.previous_clicks(site=site)
    if previous_clicks is None:
        clicks_delta = None
        sources["traffic_delta"] = DataStatus.UNAVAILABLE.value
        LOGGER.info("无上一窗口点击基线,C_t 无法计算 —— 本轮 M_t 将标记为 PARTIAL")
    else:
        clicks_delta = current_clicks - previous_clicks
        sources["traffic_delta"] = sources.get("traffic", DataStatus.UNAVAILABLE.value)

    serp_raw = await call(
        "serp_rank_tracker",
        {"keywords": keywords, "site_url": site},
        label="serp",
    )
    serp = _safe_json(serp_raw).get("positions", {})
    positions = {kw: entry.get("position") for kw, entry in serp.items()}

    await call("google_seo_monitor", {"action": "query_rising_keywords"}, label="trends")
    monitor_spec = rt.registry.get("google_seo_monitor")
    trend_weights = {
        kw: monitor_spec.trend_weight(kw) if monitor_spec else 1.0
        for kw in keywords
    }

    aeo_raw = await call(
        "aeo_visibility_monitor", {"brand": brand}, label="aeo"
    )
    aeo = _safe_json(aeo_raw)
    _v_raw = aeo.get("v_t")
    v_t = float(_v_raw) if _v_raw is not None else None

    # 3) Error accounting + M_t -------------------------------------------
    error_count = len(dead_links) + sum(1 for i in issues if i.get("severity") == "error")
    if performance is not None and performance < 90:
        error_count += 3

    # This is the crawl success ratio, NOT index coverage. Real index coverage
    # is `indexed URLs / submitted URLs` from GSC and has nothing to do with the
    # crawler. Renamed so the two are never conflated again; the β·I_t term now
    # consumes `index_coverage_ratio`, which stays None until GSC provides it.
    crawl_success_ratio = pages_crawled / (pages_crawled + len(dead_links))

    # 真实收录率:拿爬虫在站上发现的 URL 去问 GSC URL Inspection。
    # Search Analytics 接口不返回收录状态,早先在那里找 index_coverage_ratio
    # 永远是 None —— 这就是这一项一直 UNAVAILABLE 的原因。
    index_coverage_ratio = None
    try:
        from seoagents.tools.index_coverage import inspect_index_coverage
        from seoagents.tools.seo_trends import GoogleSEOMonitorSpec

        _svc = GoogleSEOMonitorSpec(config)._init_gsc_client()
        cov = inspect_index_coverage(
            _svc, site_url=site, gsc_property=gsc_property, urls=crawled_urls
        )
        sources["index_coverage"] = cov.get("data_status", DataStatus.UNAVAILABLE.value)
        index_coverage_ratio = cov.get("index_coverage_ratio")
        trace.append({
            "action": "gsc_url_inspection", "tool": "gsc_url_inspection",
            "arguments": {"sampled": len(crawled_urls)},
            "output": json.dumps(
                {k: v for k, v in cov.items() if k != "details"}, ensure_ascii=False
            )[:600],
            "ok": index_coverage_ratio is not None,
        })
    except Exception as exc:  # noqa: BLE001 - 收录查不到不该让整轮崩掉
        LOGGER.warning(f"URL Inspection 不可用: {type(exc).__name__}: {exc}")
        sources["index_coverage"] = DataStatus.UNAVAILABLE.value

    breakdown = rt.score_engine.compute_m_t(
        clicks=clicks_delta if clicks_delta is not None else 0.0,
        index_ratio=index_coverage_ratio if index_coverage_ratio is not None else 0.0,
        positions=positions,
        trend_weights=trend_weights,
        error_count=error_count,
        sources=sources,
    )
    m_t = round(breakdown.m_t, 4) if breakdown.m_t is not None else None
    if m_t is None:
        LOGGER.warning(
            f"M_t 拒绝计算(status={breakdown.status});非 REAL 输入: {breakdown.excluded}"
        )
    else:
        LOGGER.info(f"今日 SEO 综合演化评估得分 M_t: {m_t:.4f} (技术缺陷扣分项: {error_count})")

    # 4) Dead-link remediation (301 + sitemap + submission) ---------------
    links_proposed = 0
    if dead_links:
        redirects = [
            {"from_path": urlparse(link["url"]).path or "/", "to_path": "/"}
            for link in dead_links
        ]
        await call("gsc_indexing_ops", {"action": "create_301_mapping", "redirects": redirects})
        # NOTE: this only *proposes* redirects. Dead links stay unfixed until the
        # config is deployed and gsc_indexing_ops(action="verify_301_live")
        # observes a real 301 on the live host.
        healthy_urls = [site] + [
            f"{site}/{kw.replace(' ', '-')}" for kw in keywords
        ]
        await call("gsc_indexing_ops", {"action": "build_sitemap", "urls": healthy_urls})
        await call("gsc_indexing_ops", {"action": "submit_indexing"})
        links_proposed = len(redirects)

    # 5) Persist + skill distillation (L5) --------------------------------
    # Never persist an unscorable run: a NULL m_t row would still show up in
    # the history chart and in "did it improve?" comparisons.
    if m_t is not None:
        rt.store.record_audit_run(
            site=site,
            m_t=m_t,
            clicks=current_clicks,
            index_ratio=crawl_success_ratio,
            error_count=error_count,
            breakdown=breakdown.to_dict(),
        )
    else:
        # 分数不写(NULL 会污染历史曲线),但真实的点击观测必须留下 ——
        # 否则下一轮仍然没有基线,traffic_delta 永远算不出,形成死锁。
        # 历史图表按 m_t IS NOT NULL 过滤,这行观测不会出现在曲线里。
        rt.store.record_audit_run(
            site=site,
            m_t=None,
            clicks=current_clicks,
            index_ratio=crawl_success_ratio,
            error_count=error_count,
            # 把**为什么算不出来**一并留下 —— 只写一句固定文案的话,
            # 下次排查还是只能从头跑一遍。16 号文说排查起点是看
            # excluded_inputs 与 data_sources,但那两样此前根本没进库,
            # 于是「M_t 算不出」查了几天都停在「不知道是哪个源退化了」。
            breakdown={
                "observation_only": True,
                "reason": "M_t 不可计算,仅留存点击基线",
                **breakdown.to_dict(),
            },
        )
        LOGGER.warning(
            "本轮 M_t 不可计算,未写分数;已留存点击观测 "
            f"clicks={current_clicks} 作为下一轮的 C_t 基线 "
            f"| 挡住评分的输入: {list(breakdown.excluded) or '(未记录)'}"
        )

    compiled_skill: str | None = None
    # 拿上一轮的分数做对照:技能要固化的是「让指标变好的做法」
    prev_m_t = rt.store.previous_m_t(site=site)
    if rt.score_engine.should_compile_skill(m_t, previous_m_t=prev_m_t) and links_proposed:
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
        links_fixed=0,
        extra={
            "v_t": v_t,
            "issues": len(issues),
            "compiled_skill": compiled_skill,
        "previous_m_t": prev_m_t,
            "links_proposed": links_proposed,
            "excluded_inputs": list(breakdown.excluded),
        },
    )

    summary = {
        "site": site,
        "brand": brand,
        "gsc_property": gsc_property,
        "m_t": m_t,
        "score_status": breakdown.status,
        "excluded_inputs": list(breakdown.excluded),
        "data_sources": sources,
        "breakdown": breakdown.to_dict(),
        "clicks_total": current_clicks,
        "clicks_delta": clicks_delta,
        "crawl_success_ratio": round(crawl_success_ratio, 4),
        "index_coverage_ratio": index_coverage_ratio,
        "performance": performance,
        "issues": len(issues),
        "dead_links": len(dead_links),
        "links_proposed": links_proposed,
        "links_fixed": 0,  # nothing is "fixed" until verify_301_live passes
        "v_t": v_t,
        "compiled_skill": compiled_skill,
        "previous_m_t": prev_m_t,
        "trace_len": len(trace),
    }
    LOGGER.info(f"演化流水线完成 · {brand}: {json.dumps(summary, ensure_ascii=False)[:300]}")
    return summary


# ── 时间线留痕 ────────────────────────────────────────────────────────
def _record_on_timeline(rt: Any, summary: dict[str, Any]) -> None:
    """把这一轮演化写进时间线,并排下一轮。

    整个函数被 try 包住:时间线是记录,演化是主线。让记录的失败中断主线,
    是把优先级搞反了 —— 那样一个存储小故障就能停掉整个自进化。
    """
    import datetime as _dt

    from dojocore.timeline import NodeKind, get_timeline

    try:
        tl = get_timeline(rt.config, owner="seoagents")
        brand = summary.get("brand") or summary.get("site") or "站点"
        m_t = summary.get("m_t")
        status = summary.get("score_status")
        excluded = summary.get("excluded_inputs") or []

        # outcome 必须自带可信度。只写「M_t = -0.65」而不写数据状态,
        # 回看时无法判断那个数字能不能用。
        outcome = (
            f"M_t={m_t if m_t is not None else '不可计算'} · {status}"
            f" · 死链 {summary.get('dead_links', 0)} 提案 {summary.get('links_proposed', 0)}"
            f" · 技能提案 {summary.get('compiled_skill') or '无'}"
        )
        if excluded:
            outcome += f" · 非 REAL 输入: {excluded}"

        now = _dt.datetime.now(_dt.timezone.utc)
        node = tl.schedule({
            "kind": NodeKind.REVIEW,
            "intent": f"{brand} 自适应演化复盘",
            "subject_ref": summary.get("site", ""),
            # 这一轮刚跑完,时间就是此刻 —— scheduled_at 是必填,漏了会
            # KeyError,而整段被 try 包着,只会留下一行 warning 然后静默跳过
            "scheduled_at": now.isoformat(),
            "expected_minutes": 1,
            "created_by": "seo_evo_pipeline",
            "context": {
                "m_t": m_t, "score_status": status,
                "data_sources": summary.get("data_sources") or {},
                "excluded_inputs": excluded,
            },
        }, allow_conflict=True)
        tl.fire(node.node_id)
        tl.ack(node.node_id, outcome=outcome)

        # 下一轮的排期。定时任务是每日 02:00 UTC,照这个节奏排。
        nxt = (now + _dt.timedelta(days=1)).replace(
            hour=2, minute=0, second=0, microsecond=0
        )
        tl.schedule({
            "kind": NodeKind.RECURRING,
            "intent": f"{brand} 下一轮自适应演化",
            "subject_ref": summary.get("site", ""),
            "scheduled_at": nxt.isoformat(),
            "expected_minutes": 10,
            "created_by": "seo_evo_pipeline",
        }, allow_conflict=True)
    except Exception as exc:  # noqa: BLE001 - 记录失败不该拖垮演化
        LOGGER.warning(f"时间线留痕失败(不影响演化本身): {type(exc).__name__}: {exc}")


async def run_seo_self_evolution_pipeline(runtime: Runtime | None = None) -> dict[str, Any]:
    """遍历**全部**受监控站点,各跑一轮演化。

    没有主站的概念:``monitored_sites`` 里的每一个都要被看。单站失败不影响
    其余站点 —— 一个站的 GSC 掉权限,不该让另外两个站当晚也没有数据。
    """
    rt = runtime or get_runtime()
    sites = list(rt.config.sites.monitored_sites)
    if not sites:
        LOGGER.warning("monitored_sites 为空,没有可评估的站点")
        return {"sites_total": 0, "results": [], "reason": "未配置任何受监控站点"}

    LOGGER.info(f"========= 自适应演化闭环 · 共 {len(sites)} 个站点 =========")
    results: list[dict[str, Any]] = []
    for item in sites:
        try:
            results.append(await run_evolution_for_site(rt, item))
        except Exception as exc:  # noqa: BLE001 - 单站失败不能连累其他站
            LOGGER.exception(f"站点 {item.site_url} 演化失败")
            results.append({
                "site": item.site_url,
                "brand": item.brand_name,
                "m_t": None,
                "score_status": "ERROR",
                "error": f"{type(exc).__name__}: {exc}",
            })

    for _r in results:
        _record_on_timeline(rt, _r)

    scored = [r for r in results if r.get("m_t") is not None]
    summary = {
        "sites_total": len(sites),
        "sites_scored": len(scored),
        "sites_partial": len(results) - len(scored),
        "results": results,
        # 刻意不提供顶层 m_t/score_status。多站点系统没有「全局 M_t」这种东西,
        # 拿 results[0] 冒充它,读的人会以为看到的是整体表现 —— 而它只是
        # 恰好排在第一位的那个站。要哪个站的分,就去 results 里按 site 取。
    }
    LOGGER.info(
        f"全部站点演化完成:{len(scored)}/{len(sites)} 个算出 M_t · "
        + ", ".join(f"{r.get('brand')}={r.get('m_t')}" for r in results)
    )
    return summary


def register_jobs(runtime: Runtime) -> None:
    """Attach the nightly evolution job per scheduler config (default 02:00)."""
    try:
        from apscheduler.triggers.cron import CronTrigger
    except ImportError:
        LOGGER.warning("APScheduler not installed — nightly evolution job disabled")
        return
    sched_cfg = runtime.config.scheduler
    from seoagents.cron.timeline_runner import register_timeline_runner
    register_timeline_runner(runtime)

    # ── Collab Deliverer: poll outbox every 15s and deliver to recipient inbox ──
    try:
        from apscheduler.triggers.interval import IntervalTrigger as _IT
        from dojocore.collab.deliverer import run_delivery_once

        def _deliverer_tick():
            try:
                run_delivery_once()
            except Exception as exc:
                LOGGER.warning(f"deliverer tick error: {exc}")

        scheduler.add_job(
            _deliverer_tick,
            _IT(seconds=15),
            id="collab-deliverer",
            replace_existing=True,
            misfire_grace_time=30,
        )
        LOGGER.info("Collab deliverer registered: 15s interval")
    except ImportError:
        LOGGER.warning("Collab deliverer not registered (deliverer.py or APScheduler missing)")

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
    data = _safe_json(gsc_output)
    if "total_clicks" in data:
        try:
            return float(data["total_clicks"])
        except (TypeError, ValueError):
            return 0.0
    match = re.search(r"total_clicks=([\d.]+)", gsc_output)
    return float(match.group(1)) if match else 0.0


def _parse_index_coverage(gsc_output: str) -> float | None:
    """Real index coverage from GSC, or None.

    Returning None (rather than a crawl-derived stand-in) is what lets the
    scoring gate mark the run PARTIAL instead of silently scoring on a
    mislabelled metric.
    """
    data = _safe_json(gsc_output)
    value = data.get("index_coverage_ratio")
    if value is None:
        return None
    try:
        return max(0.0, min(1.0, float(value)))
    except (TypeError, ValueError):
        return None


__all__ = [
    "EVOLUTION_JOB_ID",
    "FIX_SKILL_ID",
    "register_jobs",
    "run_evolution_for_site",
    "run_seo_self_evolution_pipeline",
]
