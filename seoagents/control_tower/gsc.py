"""Google Search Console 模块的确定性标准化逻辑。

本模块不持有凭证、不发网络请求。输入仅是已由 google_seo_monitor 从
Search Analytics API 取得的原始窗口和维度行；输出统一为模块合同及
MetricPoint。缺失窗口保留为 null，不向前借用日期、不生成模拟行。
"""
from __future__ import annotations

import datetime as dt
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from dojocore.quality import DataStatus
from seoagents.control_tower.models import MetricPoint, ModuleFinding, ModuleRun, utc_now

_PERIOD_KEYS = ("d0", "d1", "cur7", "prev7", "cur30", "prev30")
_DIMENSION_KEYS = ("daily", "queries", "pages", "countries", "devices")
_METRIC_META = {
    "clicks": ("自然搜索点击", "次"),
    "impressions": ("自然搜索展示", "次"),
    "ctr": ("点击率", "比例"),
    "weighted_position": ("加权平均位置", "位置"),
}


@dataclass(frozen=True)
class PeriodWindow:
    start: str
    end: str


def period_windows(d0: str) -> dict[str, PeriodWindow]:
    """由锁定的 D0 派生六个不重叠窗口。"""
    end = dt.date.fromisoformat(d0)

    def window(start_offset: int, end_offset: int) -> PeriodWindow:
        return PeriodWindow(
            start=(end - dt.timedelta(days=start_offset)).isoformat(),
            end=(end - dt.timedelta(days=end_offset)).isoformat(),
        )

    return {
        "d0": window(0, 0),
        "d1": window(1, 1),
        "cur7": window(6, 0),
        "prev7": window(13, 7),
        "cur30": window(29, 0),
        "prev30": window(59, 30),
    }


def aggregate_rows(rows: Sequence[Mapping[str, Any]]) -> dict[str, float]:
    """按 GSC 口径汇总行：CTR=点击/展示，位置按展示加权。"""
    clicks = sum(float(row.get("clicks") or 0.0) for row in rows)
    impressions = sum(float(row.get("impressions") or 0.0) for row in rows)
    weighted_sum = sum(
        float(row.get("position") or 0.0) * float(row.get("impressions") or 0.0)
        for row in rows
    )
    return {
        "clicks": clicks,
        "impressions": impressions,
        "ctr": clicks / impressions if impressions > 0 else 0.0,
        "weighted_position": weighted_sum / impressions if impressions > 0 else 0.0,
    }


def normalize_dimension_rows(
    raw: Mapping[str, Sequence[Mapping[str, Any]]],
    *,
    dimension_windows: Mapping[str, Mapping[str, str]],
) -> dict[str, list[dict[str, Any]]]:
    """字段白名单投影；每一行必须携带真实来源窗口。"""
    out: dict[str, list[dict[str, Any]]] = {}
    for key in _DIMENSION_KEYS:
        window = dimension_windows.get(key) or {}
        start = str(window.get("start") or "")
        end = str(window.get("end") or "")
        rows: list[dict[str, Any]] = []
        for raw_row in raw.get(key) or ():
            row = dict(raw_row)
            projected = {
                "key": str(row.get("key") or ""),
                "clicks": float(row.get("clicks") or 0.0),
                "impressions": float(row.get("impressions") or 0.0),
                "ctr": float(row.get("ctr") or 0.0),
                "weighted_position": float(
                    row.get("weighted_position", row.get("position")) or 0.0
                ),
                "window_start": start,
                "window_end": end,
            }
            rows.append(projected)
        out[key] = rows
    out["opportunities"] = []
    return out


def build_gsc_module_run(
    *,
    site_id: str,
    business_date: str,
    d0: str | None,
    period_rows: Mapping[str, Sequence[Mapping[str, Any]] | None],
    dimension_rows: Mapping[str, Sequence[Mapping[str, Any]]],
    dimension_windows: Mapping[str, Mapping[str, str]],
    collected_at: str = "",
    workflow_instance_id: str = "",
    timeline_node_id: str = "",
    asset_id: str = "",
    source_status: DataStatus | str = DataStatus.REAL,
    reason: str | None = None,
    truncated_dimensions: Sequence[str] = (),
) -> tuple[ModuleRun, tuple[MetricPoint, ...]]:
    """从已采集的真实 GSC 行构造标准信封和扁平指标点。"""
    status = DataStatus(source_status)
    collected_at = collected_at or utc_now()
    if status is DataStatus.UNAVAILABLE or not d0:
        unavailable_reason = reason or "GSC 未找到可用的完整数据日"
        run = ModuleRun(
            site_id=site_id,
            module_id="gsc",
            business_date=business_date,
            data_status=DataStatus.UNAVAILABLE,
            source="Google Search Console Search Analytics API",
            data_window={},
            reason=unavailable_reason,
            known_limitations=("GSC 通常延迟 2–3 日",),
            cross_validation="单源，未经外部 SERP 交叉验证",
            single_source_risk=True,
            collected_at=collected_at,
            workflow_instance_id=workflow_instance_id,
            timeline_node_id=timeline_node_id,
            asset_id=asset_id,
            metrics={},
            dimensions={},
        )
        run.validate()
        return run, ()

    assert d0 is not None
    windows = period_windows(d0)
    periods: dict[str, dict[str, float] | None] = {}
    points: list[MetricPoint] = []
    for period_key in _PERIOD_KEYS:
        rows = period_rows.get(period_key)
        if rows is None:
            periods[period_key] = None
            continue
        aggregate = aggregate_rows(rows)
        periods[period_key] = aggregate
        window = windows[period_key]
        for metric_key, value in aggregate.items():
            label, unit = _METRIC_META[metric_key]
            points.append(
                MetricPoint(
                    metric_key=metric_key,
                    metric_label=label,
                    period_key=period_key,
                    window_start=window.start,
                    window_end=window.end,
                    value_num=value,
                    unit=unit,
                    data_status=DataStatus.REAL,
                )
            )

    dimensions = normalize_dimension_rows(
        dimension_rows, dimension_windows=dimension_windows
    )
    limitations = ["GSC 通常延迟 2–3 日", "查询维度可能受隐私阈值影响"]
    effective_status = status
    effective_reason = reason
    if truncated_dimensions:
        effective_status = DataStatus.DEGRADED
        effective_reason = "以下维度达到行数上限，结果可能被截断：" + ", ".join(
            sorted({str(x) for x in truncated_dimensions})
        )
        limitations.append(effective_reason)

    if effective_status is not DataStatus.REAL:
        # Non-REAL first-party rows remain visible only in the upstream/archive
        # evidence envelope.  They must not enter ModuleRun trend payloads or
        # metric_points, where consumers could mistake them for scorable data.
        run = ModuleRun(
            site_id=site_id,
            module_id="gsc",
            business_date=business_date,
            data_status=effective_status,
            source="Google Search Console Search Analytics API",
            data_window={
                "d0": d0,
                "d1": (dt.date.fromisoformat(d0) - dt.timedelta(days=1)).isoformat(),
                "timezone": "UTC",
            },
            reason=effective_reason or f"GSC 数据状态为 {effective_status.value}",
            known_limitations=tuple(limitations),
            cross_validation="单源，未经外部 SERP 交叉验证",
            single_source_risk=True,
            collected_at=collected_at,
            workflow_instance_id=workflow_instance_id,
            timeline_node_id=timeline_node_id,
            asset_id=asset_id,
            metrics={},
            dimensions={},
            findings=(),
        )
        run.validate()
        return run, ()

    findings: tuple[ModuleFinding, ...] = ()
    if effective_status is DataStatus.REAL and not dimensions["queries"]:
        findings = (
            ModuleFinding(
                finding_key="query_privacy_threshold",
                severity="INFO",
                title="查询维度暂无可展示行",
                conclusion="待验证",
                evidence={"dimension": "queries", "d0": d0},
                recommendation="继续观察同口径窗口，不用模拟关键词补齐",
                expected_benefit="待验证，当前不能量化",
                verification_method="复查后续 14/28 日 GSC 查询维度",
            ),
        )
    run = ModuleRun(
        site_id=site_id,
        module_id="gsc",
        business_date=business_date,
        data_status=effective_status,
        source="Google Search Console Search Analytics API",
        data_window={
            "d0": d0,
            "d1": (dt.date.fromisoformat(d0) - dt.timedelta(days=1)).isoformat(),
            "timezone": "UTC",
        },
        reason=effective_reason,
        known_limitations=tuple(limitations),
        cross_validation="单源，未经外部 SERP 交叉验证",
        single_source_risk=True,
        collected_at=collected_at,
        workflow_instance_id=workflow_instance_id,
        timeline_node_id=timeline_node_id,
        asset_id=asset_id,
        metrics={"periods": periods},
        dimensions=dimensions,
        findings=findings,
    )
    run.validate()
    return run, tuple(points)


__all__ = [
    "PeriodWindow",
    "aggregate_rows",
    "build_gsc_module_run",
    "normalize_dimension_rows",
    "period_windows",
]
