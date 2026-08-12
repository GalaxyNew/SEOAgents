"""SEO 分子化工序注册表 (G1-B) —— 把 495 行写死的巡检流水线拆成可独立调用的原子.

28 号文 §4.1 的设计原则在这里落地：

* **每个工序 = 一个独立函数 + 一条注册记录**，不依赖其他工序的执行顺序。
* **数据是粘合剂，不是代码**：工序之间通过 ``seo_daily_snapshot`` 传结果，
  而不是通过函数调用链。所以 ``seo.m_t_score`` 不再要求前面几步"刚刚在同一个
  函数里跑过"——它去查表，今天谁写过就用谁的。
* **省配额靠 skip 在前**：每个工序执行前查 ``should_skip()``，同日同站同工序
  已有可信结果就直接返回 ``skipped``，**不发出外部请求**。

与 v1 的关键差别不是"代码更漂亮"，而是：v1 里想单独重跑一次 CWV 测量，只能把
整条 495 行的流水线连着 GSC、SERP、AEO 一起再跑一遍；现在可以只跑那一个。

注册表本身不含 HTTP 层，可被 cron、dashboard router、CLI 任意一方调用。
"""
from __future__ import annotations

import inspect
import json
import time
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

from dojocore.logging import LOGGER
from dojocore.quality import DataStatus, extract_status
from seoagents.agent.models import ToolCall
from seoagents.storage.snapshot_store import SnapshotStore

__all__ = [
    "TaskSpec",
    "TaskResult",
    "SEO_TASKS",
    "register_task",
    "get_task",
    "list_tasks",
    "run_task",
    "run_daily_inspection",
]


@dataclass(frozen=True)
class TaskSpec:
    """一个分子工序的元数据。"""

    name: str
    phase: str                      # 28 号文的 Phase 0-6
    description: str
    handler: Callable[..., Awaitable[dict[str, Any]]]
    cadence: str = "daily"          # daily / weekly / on_demand
    cacheable: bool = True          # False = 每次都真跑（如汇总类）
    requires_site: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "phase": self.phase,
            "description": self.description,
            "cadence": self.cadence,
            "cacheable": self.cacheable,
            "requires_site": self.requires_site,
        }


@dataclass
class TaskResult:
    task: str
    site: str
    ok: bool
    skipped: bool = False
    data_status: str = DataStatus.UNAVAILABLE.value
    data: Any = None
    error: str | None = None
    elapsed_ms: int = 0
    meta: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "task": self.task,
            "site": self.site,
            "ok": self.ok,
            "skipped": self.skipped,
            "data_status": self.data_status,
            "data": self.data,
            "error": self.error,
            "elapsed_ms": self.elapsed_ms,
            **({"meta": self.meta} if self.meta else {}),
        }


SEO_TASKS: dict[str, TaskSpec] = {}


def register_task(spec: TaskSpec) -> TaskSpec:
    if spec.name in SEO_TASKS:
        LOGGER.warning(f"工序 {spec.name} 被重复注册，后者覆盖前者")
    SEO_TASKS[spec.name] = spec
    return spec


def get_task(name: str) -> TaskSpec | None:
    return SEO_TASKS.get(name)


def list_tasks(*, phase: str | None = None, cadence: str | None = None) -> list[dict[str, Any]]:
    out = [s.to_dict() for s in SEO_TASKS.values()]
    if phase:
        out = [t for t in out if t["phase"] == phase]
    if cadence:
        out = [t for t in out if t["cadence"] == cadence]
    return sorted(out, key=lambda t: (t["phase"], t["name"]))


# ── 工序内部共用的小工具 ──────────────────────────────────────────────
def _safe_json(text: str) -> dict[str, Any]:
    try:
        data = json.loads(text)
        return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, TypeError):
        return {}


def _store(rt: Any) -> SnapshotStore:
    return SnapshotStore(rt.config.storage.data_dir)


async def _call_tool(rt: Any, tool: str, args: dict[str, Any], *, site: str) -> tuple[str, str]:
    """调一个 L4 工具，返回 (原始输出, data_status)。

    工具自己声明可信度（DataStatus）；调用失败一律 UNAVAILABLE——
    绝不把失败当成 "0" 往下传，那正是 v1 的病根。
    """
    res = await rt.executor.execute_one(
        ToolCall(name=tool, arguments=args), session_id=f"task:{site}"
    )
    text = res.as_text()
    if not res.ok:
        return text, DataStatus.UNAVAILABLE.value
    st = extract_status(text)
    return text, (st or DataStatus.REAL).value


def _site_item(rt: Any, site: str) -> Any:
    """按 site_url 找到配置里的站点项；找不到抛错而不是猜。"""
    for item in rt.config.sites.monitored_sites:
        if item.site_url == site:
            return item
    raise ValueError(
        f"站点 {site} 不在 monitored_sites 中；"
        f"可选：{[i.site_url for i in rt.config.sites.monitored_sites]}"
    )


# ── Phase 3：技术面工序 ───────────────────────────────────────────────
async def _task_tech_crawl(rt: Any, site: str, **kw: Any) -> dict[str, Any]:
    raw, status = await _call_tool(rt, "site_technical_auditor", {"start_url": site}, site=site)
    audit = _safe_json(raw)
    return {
        "data": {
            "issues": audit.get("issues", []),
            "dead_links": audit.get("dead_links", []),
            "pages_crawled": int(audit.get("pages_crawled", 0)),
            "crawled_urls": list(audit.get("crawled_urls") or []),
        },
        "data_status": status,
    }


async def _task_cwv_measure(rt: Any, site: str, **kw: Any) -> dict[str, Any]:
    raw, status = await _call_tool(rt, "lighthouse_audit", {"target_url": site}, site=site)
    lh = _safe_json(raw)
    perf = lh.get("performance_score")
    data = {
        "performance_score": float(perf) if perf is not None else None,
        "lcp": lh.get("lcp"), "inp": lh.get("inp"), "cls": lh.get("cls"),
        "fcp": lh.get("fcp"), "ttfb": lh.get("ttfb"),
    }
    # CWV 明细单独进 cwv_history —— 趋势图要的是按 URL 的时间序列，
    # 从 snapshot 的 JSON 里捞是能捞，但那等于把一张表当日志文件用。
    if any(v is not None for v in data.values()):
        try:
            _store(rt).write_cwv(
                url=site, lcp=data["lcp"], inp=data["inp"], cls=data["cls"],
                fcp=data["fcp"], ttfb=data["ttfb"],
                performance=int(data["performance_score"]) if data["performance_score"] is not None else None,
                source="lighthouse", data_status=status,
            )
        except Exception as exc:  # noqa: BLE001 - 明细写失败不该让本工序判失败
            LOGGER.warning(f"cwv_history 写入失败（不影响 snapshot）: {exc}")
    return {"data": data, "data_status": status}


async def _task_dead_link_scan(rt: Any, site: str, **kw: Any) -> dict[str, Any]:
    """死链扫描。优先复用今天的 tech_crawl 结果，不重爬一遍站。"""
    store = _store(rt)
    snap = store.read_snapshot(site=site, task_name="seo.tech_crawl")
    if snap and snap.get("data"):
        dead = snap["data"].get("dead_links", [])
        return {
            "data": {"dead_links": dead, "count": len(dead), "reused_from": "seo.tech_crawl"},
            "data_status": snap.get("data_status", DataStatus.REAL.value),
        }
    raw, status = await _call_tool(rt, "site_technical_auditor", {"start_url": site}, site=site)
    dead = _safe_json(raw).get("dead_links", [])
    return {"data": {"dead_links": dead, "count": len(dead)}, "data_status": status}


async def _task_index_status(rt: Any, site: str, **kw: Any) -> dict[str, Any]:
    """GSC URL Inspection 真实收录率。

    爬虫的抓取成功率不是收录率——v1 把两者混为一谈过一次，这里用的 URL 列表
    来自今天的 tech_crawl 快照，拿不到就如实 UNAVAILABLE，不用爬虫比例顶替。
    """
    item = _site_item(rt, site)
    store = _store(rt)
    snap = store.read_snapshot(site=site, task_name="seo.tech_crawl")
    urls = (snap or {}).get("data", {}).get("crawled_urls") or []
    if not urls:
        return {
            "data": {"index_coverage_ratio": None, "reason": "今日无 tech_crawl 快照，无 URL 可查"},
            "data_status": DataStatus.UNAVAILABLE.value,
        }
    try:
        from seoagents.tools.index_coverage import inspect_index_coverage
        from seoagents.tools.seo_trends import GoogleSEOMonitorSpec

        svc = GoogleSEOMonitorSpec(rt.config)._init_gsc_client()
        cov = inspect_index_coverage(
            svc, site_url=site, gsc_property=item.gsc_property, urls=urls
        )
        return {
            "data": {k: v for k, v in cov.items() if k != "details"},
            "data_status": cov.get("data_status", DataStatus.UNAVAILABLE.value),
        }
    except Exception as exc:  # noqa: BLE001
        LOGGER.warning(f"URL Inspection 不可用: {type(exc).__name__}: {exc}")
        return {
            "data": {"index_coverage_ratio": None, "error": f"{type(exc).__name__}: {exc}"},
            "data_status": DataStatus.UNAVAILABLE.value,
        }


# ── Phase 6：数据面工序 ───────────────────────────────────────────────
async def _task_gsc_performance(rt: Any, site: str, **kw: Any) -> dict[str, Any]:
    item = _site_item(rt, site)
    raw, status = await _call_tool(
        rt, "google_seo_monitor",
        {"action": "query_gsc_performance", "target_site": item.gsc_property},
        site=site,
    )
    data = _safe_json(raw)
    total = data.get("total_clicks")
    try:
        clicks = float(total) if total is not None else None
    except (TypeError, ValueError):
        clicks = None
    return {
        "data": {
            "total_clicks": clicks,
            "impressions": data.get("total_impressions"),
            "ctr": data.get("ctr"),
            "position": data.get("average_position"),
            "rows": data.get("rows"),
        },
        "data_status": status,
    }


async def _task_serp_track(rt: Any, site: str, **kw: Any) -> dict[str, Any]:
    item = _site_item(rt, site)
    keywords = list(kw.get("keywords") or item.tracked_keywords)
    if not keywords:
        return {"data": {"positions": {}, "reason": "无追踪词"},
                "data_status": DataStatus.UNAVAILABLE.value}
    raw, status = await _call_tool(
        rt, "serp_rank_tracker", {"keywords": keywords, "site_url": site}, site=site
    )
    serp = _safe_json(raw).get("positions", {})
    positions = {k: v.get("position") for k, v in serp.items()}
    # 明细同时进 serp_positions（既有表），趋势图沿用原路径
    try:
        for k, pos in positions.items():
            rt.store.record_serp_position(
                keyword=k, position=pos, url=serp.get(k, {}).get("url", "")
            )
    except Exception as exc:  # noqa: BLE001
        LOGGER.warning(f"serp_positions 写入失败: {exc}")
    return {"data": {"positions": positions, "keywords": keywords}, "data_status": status}


async def _task_trend_rising(rt: Any, site: str, **kw: Any) -> dict[str, Any]:
    raw, status = await _call_tool(
        rt, "google_seo_monitor", {"action": "query_rising_keywords"}, site=site
    )
    return {"data": _safe_json(raw), "data_status": status}


async def _task_aeo_probe(rt: Any, site: str, **kw: Any) -> dict[str, Any]:
    item = _site_item(rt, site)
    raw, status = await _call_tool(
        rt, "aeo_visibility_monitor", {"brand": item.brand_name}, site=site
    )
    data = _safe_json(raw)
    v_t = data.get("v_t")
    return {
        "data": {"v_t": float(v_t) if v_t is not None else None, "raw": data},
        "data_status": status,
    }


async def _task_m_t_score(rt: Any, site: str, **kw: Any) -> dict[str, Any]:
    """汇总评分——**只读今天的快照表**，不再重复调用任何外部 API。

    这是分子化最直接的好处：v1 里 M_t 必须跟六次工具调用绑在同一个函数里，
    想重算一次分就得重新拉一遍 GSC。现在评分是纯函数：查表 → 算分。
    """
    item = _site_item(rt, site)
    store = _store(rt)
    snaps = {
        s["task_name"]: store.read_snapshot(site=site, task_name=s["task_name"])
        for s in store.list_snapshots(site=site)
    }

    def _d(name: str) -> dict[str, Any]:
        rec = snaps.get(name) or {}
        return rec.get("data") or {}

    def _st(name: str) -> str:
        rec = snaps.get(name)
        return rec.get("data_status", DataStatus.UNAVAILABLE.value) if rec else DataStatus.UNAVAILABLE.value

    tech = _d("seo.tech_crawl")
    gsc = _d("seo.gsc_performance")
    serp = _d("seo.serp_track")
    cwv = _d("seo.cwv_measure")
    idx = _d("seo.index_status")

    missing = [
        n for n in ("seo.tech_crawl", "seo.gsc_performance", "seo.serp_track")
        if n not in snaps
    ]
    if missing:
        return {
            "data": {"m_t": None, "reason": f"缺少前置工序快照: {missing}"},
            "data_status": DataStatus.UNAVAILABLE.value,
        }

    dead_links = tech.get("dead_links", [])
    issues = tech.get("issues", [])
    error_count = len(dead_links) + sum(1 for i in issues if i.get("severity") == "error")
    perf = cwv.get("performance_score")
    if perf is not None and perf < 90:
        error_count += 3

    current_clicks = gsc.get("total_clicks")
    previous_clicks = rt.store.previous_clicks(site=site)
    sources = {
        "site_audit": _st("seo.tech_crawl"),
        "traffic": _st("seo.gsc_performance"),
        "serp": _st("seo.serp_track"),
        "cwv": _st("seo.cwv_measure"),
        "index_coverage": _st("seo.index_status"),
        "aeo": _st("seo.aeo_probe"),
    }
    if previous_clicks is None or current_clicks is None:
        clicks_delta = None
        sources["traffic_delta"] = DataStatus.UNAVAILABLE.value
    else:
        clicks_delta = current_clicks - previous_clicks
        sources["traffic_delta"] = sources["traffic"]

    positions = serp.get("positions", {})
    monitor_spec = rt.registry.get("google_seo_monitor")
    trend_weights = {
        k: (monitor_spec.trend_weight(k) if monitor_spec else 1.0) for k in positions
    }

    breakdown = rt.score_engine.compute_m_t(
        clicks=clicks_delta if clicks_delta is not None else 0.0,
        index_ratio=idx.get("index_coverage_ratio") or 0.0,
        positions=positions,
        trend_weights=trend_weights,
        error_count=error_count,
        sources=sources,
    )
    m_t = round(breakdown.m_t, 4) if breakdown.m_t is not None else None

    pages = int(tech.get("pages_crawled", 0)) or 1
    crawl_success_ratio = pages / (pages + len(dead_links))
    if current_clicks is not None:
        rt.store.record_audit_run(
            site=site, m_t=m_t, clicks=current_clicks,
            index_ratio=crawl_success_ratio, error_count=error_count,
            breakdown=(
                breakdown.to_dict() if m_t is not None
                else {"observation_only": True,
                      "reason": "M_t 不可计算，仅留存点击基线",
                      **breakdown.to_dict()}
            ),
        )

    return {
        "data": {
            "m_t": m_t,
            "score_status": breakdown.status,
            "excluded_inputs": list(breakdown.excluded),
            "breakdown": breakdown.to_dict(),
            "error_count": error_count,
            "clicks_total": current_clicks,
            "clicks_delta": clicks_delta,
            "crawl_success_ratio": round(crawl_success_ratio, 4),
            "data_sources": sources,
        },
        "data_status": (
            DataStatus.REAL.value if m_t is not None else DataStatus.UNAVAILABLE.value
        ),
    }


async def _task_dead_link_fix(rt: Any, site: str, **kw: Any) -> dict[str, Any]:
    """死链整改：301 提案 + sitemap 重建 + 收录提交。

    刻意标 ``cacheable=False``：整改是动作不是观测，"今天已经提过一次" 不构成
    今天不该再提的理由（死链列表可能刚变）。
    """
    from urllib.parse import urlparse

    item = _site_item(rt, site)
    store = _store(rt)
    snap = store.read_snapshot(site=site, task_name="seo.dead_link_scan") or \
        store.read_snapshot(site=site, task_name="seo.tech_crawl")
    dead = ((snap or {}).get("data") or {}).get("dead_links") or []
    if not dead:
        return {"data": {"links_proposed": 0, "reason": "无死链或今日未扫描"},
                "data_status": DataStatus.REAL.value}

    redirects = [{"from_path": urlparse(l["url"]).path or "/", "to_path": "/"} for l in dead]
    await _call_tool(rt, "gsc_indexing_ops",
                     {"action": "create_301_mapping", "redirects": redirects}, site=site)
    healthy = [site] + [f"{site}/{k.replace(' ', '-')}" for k in item.tracked_keywords]
    await _call_tool(rt, "gsc_indexing_ops",
                     {"action": "build_sitemap", "urls": healthy}, site=site)
    await _call_tool(rt, "gsc_indexing_ops", {"action": "submit_indexing"}, site=site)
    return {
        "data": {
            "links_proposed": len(redirects),
            # 提案 ≠ 修复。只有 verify_301_live 在真实主机上观测到 301
            # 才算修好，这里绝不提前把 links_fixed 记成非零。
            "links_fixed": 0,
        },
        "data_status": DataStatus.REAL.value,
    }


# ── 注册 ──────────────────────────────────────────────────────────────
register_task(TaskSpec("seo.tech_crawl", "phase3", "全站技术审计（on-page 问题 + 死链）", _task_tech_crawl))
register_task(TaskSpec("seo.cwv_measure", "phase3", "Core Web Vitals / Lighthouse 性能测量", _task_cwv_measure))
register_task(TaskSpec("seo.dead_link_scan", "phase3", "死链扫描（复用当日 tech_crawl）", _task_dead_link_scan))
register_task(TaskSpec("seo.index_status", "phase3", "GSC URL Inspection 真实收录率", _task_index_status))
register_task(TaskSpec("seo.dead_link_fix", "phase3", "死链整改：301 + sitemap + 收录提交", _task_dead_link_fix, cadence="on_demand", cacheable=False))
register_task(TaskSpec("seo.gsc_performance", "phase6", "GSC 点击/展现/CTR/均位", _task_gsc_performance))
register_task(TaskSpec("seo.serp_track", "phase6", "SERP 当日排名追踪", _task_serp_track))
register_task(TaskSpec("seo.trend_rising", "phase6", "Google Trends 飙升词", _task_trend_rising))
register_task(TaskSpec("seo.aeo_probe", "phase5", "AI 引擎可见度探测", _task_aeo_probe, cadence="weekly"))
register_task(TaskSpec("seo.m_t_score", "phase6", "M_t 综合评分（只读当日快照，不调 API）", _task_m_t_score, cacheable=False))


# ── 执行器 ────────────────────────────────────────────────────────────
async def run_task(
    name: str,
    *,
    site: str | None = None,
    runtime: Any = None,
    force: bool = False,
    **kwargs: Any,
) -> TaskResult:
    """跑一个工序。

    ``force=False``（默认）时先查快照——**这一步在发出任何外部请求之前**，
    这才是省 API 配额的位置。
    """
    from seoagents.agent.runtime import get_runtime

    rt = runtime or get_runtime()
    spec = get_task(name)
    if spec is None:
        return TaskResult(task=name, site=site or "", ok=False,
                          error=f"未知工序 {name}；可用：{sorted(SEO_TASKS)}")

    if spec.requires_site and not site:
        sites = list(rt.config.sites.monitored_sites)
        if not sites:
            return TaskResult(task=name, site="", ok=False, error="未配置 monitored_sites")
        site = sites[0].site_url

    site = site or ""
    store = _store(rt)

    if spec.cacheable and not force and store.should_skip(site=site, task_name=name):
        cached = store.read_snapshot(site=site, task_name=name)
        return TaskResult(
            task=name, site=site, ok=True, skipped=True,
            data_status=(cached or {}).get("data_status", DataStatus.REAL.value),
            data=(cached or {}).get("data"),
            meta={"reason": "cached_today", "cached_at": (cached or {}).get("created_at")},
        )

    t0 = time.time()
    try:
        out = spec.handler(rt, site, **kwargs)
        if inspect.isawaitable(out):
            out = await out
        data = out.get("data")
        status = out.get("data_status", DataStatus.REAL.value)
        elapsed = int((time.time() - t0) * 1000)
        if spec.cacheable or status != DataStatus.UNAVAILABLE.value:
            store.write_snapshot(site=site, task_name=name, data=data, data_status=status)
        return TaskResult(task=name, site=site, ok=True, data_status=status,
                          data=data, elapsed_ms=elapsed)
    except Exception as exc:  # noqa: BLE001 - 单个工序失败不该炸掉调用方
        LOGGER.exception(f"工序 {name} 执行失败")
        elapsed = int((time.time() - t0) * 1000)
        return TaskResult(task=name, site=site, ok=False,
                          data_status=DataStatus.UNAVAILABLE.value,
                          error=f"{type(exc).__name__}: {exc}", elapsed_ms=elapsed)


#: 每日巡检的默认顺序。有序但**不是硬依赖**——顺序只影响能不能复用当日快照
#: （如 index_status 复用 tech_crawl 的 URL 列表），任一步缺失后面照跑，
#: 缺什么就在结果里如实标 UNAVAILABLE。
DAILY_SEQUENCE = [
    "seo.tech_crawl",
    "seo.cwv_measure",
    "seo.dead_link_scan",
    "seo.index_status",
    "seo.gsc_performance",
    "seo.serp_track",
    "seo.trend_rising",
    "seo.m_t_score",
]

WEEKLY_SEQUENCE = ["seo.aeo_probe"]


async def run_daily_inspection(
    *, site: str | None = None, runtime: Any = None, force: bool = False,
    sequence: list[str] | None = None,
) -> dict[str, Any]:
    """按序跑一遍每日巡检。等价于 v1 的整条流水线，但每步都可单独重跑。"""
    from seoagents.agent.runtime import get_runtime

    rt = runtime or get_runtime()
    sites = [site] if site else [i.site_url for i in rt.config.sites.monitored_sites]
    seq = sequence or DAILY_SEQUENCE
    out: dict[str, Any] = {"sites": {}, "sequence": seq}

    for s in sites:
        results = []
        for name in seq:
            r = await run_task(name, site=s, runtime=rt, force=force)
            results.append(r.to_dict())
        out["sites"][s] = {
            "results": results,
            "ran": sum(1 for r in results if not r["skipped"] and r["ok"]),
            "skipped": sum(1 for r in results if r["skipped"]),
            "failed": sum(1 for r in results if not r["ok"]),
        }
    return out
