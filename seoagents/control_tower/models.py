"""SEO 总控大屏模块运行的数据模型与强校验。"""
from __future__ import annotations

import datetime as dt
import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from dojocore.quality import DataStatus

SCHEMA_VERSION = "1.0"
MODULE_IDS = frozenset({
    "gsc", "ga4", "psi", "technical", "indexing", "content",
    "execution", "aeo", "inspection",
})
SEVERITIES = frozenset({"P0", "P1", "P2", "INFO"})


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def require_iso_date(value: str, *, field_name: str) -> str:
    try:
        dt.date.fromisoformat(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} 必须是 YYYY-MM-DD") from exc
    return value


def require_iso_datetime(value: str, *, field_name: str) -> str:
    try:
        parsed = dt.datetime.fromisoformat(str(value))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} 必须是带时区的 ISO 8601 时间") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{field_name} 必须是带时区的 ISO 8601 时间")
    return value


def strict_bool(value: Any, *, field_name: str) -> bool:
    if type(value) is not bool:
        raise TypeError(f"{field_name} 必须是布尔值")
    return value


def contains_non_null_metric(value: Any) -> bool:
    if isinstance(value, Mapping):
        return any(contains_non_null_metric(item) for item in value.values())
    if isinstance(value, (list, tuple)):
        return any(contains_non_null_metric(item) for item in value)
    return value is not None


def validate_json_object(value: Mapping[str, Any], *, field_name: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise TypeError(f"{field_name} 必须是对象")
    out = dict(value)
    try:
        json.dumps(out, ensure_ascii=False, allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} 必须是有限值组成的 JSON 对象") from exc
    return out


@dataclass(frozen=True)
class MetricPoint:
    metric_key: str
    metric_label: str
    period_key: str
    window_start: str
    window_end: str
    unit: str
    value_num: float | None = None
    value_text: str | None = None
    dimensions: Mapping[str, Any] = field(default_factory=dict)
    data_status: DataStatus = DataStatus.REAL

    def validate(self) -> None:
        for name, value in (
            ("metric_key", self.metric_key),
            ("metric_label", self.metric_label),
            ("period_key", self.period_key),
            ("unit", self.unit),
        ):
            if not str(value).strip():
                raise ValueError(f"{name} 不能为空")
        require_iso_date(self.window_start, field_name="window_start")
        require_iso_date(self.window_end, field_name="window_end")
        if self.window_start > self.window_end:
            raise ValueError("window_start 不能晚于 window_end")
        if self.value_num is None and self.value_text is None:
            raise ValueError("指标必须有 value_num 或 value_text；缺失指标不要创建指标点")
        if self.value_num is not None:
            # allow_nan=False additionally rejects NaN and infinity.
            json.dumps(float(self.value_num), allow_nan=False)
        validate_json_object(self.dimensions, field_name="dimensions")

    def to_dict(self) -> dict[str, Any]:
        self.validate()
        return {
            "metric_key": self.metric_key,
            "metric_label": self.metric_label,
            "period_key": self.period_key,
            "window_start": self.window_start,
            "window_end": self.window_end,
            "value_num": self.value_num,
            "value_text": self.value_text,
            "unit": self.unit,
            "dimensions": dict(self.dimensions),
            "data_status": DataStatus(self.data_status).value,
        }


@dataclass(frozen=True)
class ModuleFinding:
    finding_key: str
    severity: str
    title: str
    conclusion: str
    evidence: Mapping[str, Any]
    recommendation: str
    expected_benefit: str
    verification_method: str
    approval_required: bool = False

    def validate(self) -> None:
        if self.severity not in SEVERITIES:
            raise ValueError(f"未知严重级别: {self.severity}")
        for name, value in (
            ("finding_key", self.finding_key),
            ("title", self.title),
            ("conclusion", self.conclusion),
            ("recommendation", self.recommendation),
            ("expected_benefit", self.expected_benefit),
            ("verification_method", self.verification_method),
        ):
            if not str(value).strip():
                raise ValueError(f"{name} 不能为空")
        validate_json_object(self.evidence, field_name="evidence")

    def to_dict(self) -> dict[str, Any]:
        self.validate()
        return {
            "finding_key": self.finding_key,
            "severity": self.severity,
            "title": self.title,
            "conclusion": self.conclusion,
            "evidence": dict(self.evidence),
            "recommendation": self.recommendation,
            "expected_benefit": self.expected_benefit,
            "verification_method": self.verification_method,
            "approval_required": self.approval_required,
        }


@dataclass(frozen=True)
class ModuleRun:
    site_id: str
    module_id: str
    business_date: str
    data_status: DataStatus
    source: str
    data_window: Mapping[str, Any]
    reason: str | None = None
    known_limitations: tuple[str, ...] = ()
    cross_validation: str = ""
    single_source_risk: bool = False
    collected_at: str = field(default_factory=utc_now)
    workflow_instance_id: str = ""
    timeline_node_id: str = ""
    asset_id: str = ""
    metrics: Mapping[str, Any] = field(default_factory=dict)
    dimensions: Mapping[str, Any] = field(default_factory=dict)
    findings: tuple[ModuleFinding, ...] = ()
    schema_version: str = SCHEMA_VERSION

    def validate(self) -> None:
        if not self.site_id.strip():
            raise ValueError("site_id 不能为空")
        if self.module_id not in MODULE_IDS:
            raise ValueError(f"未知模块: {self.module_id}")
        require_iso_date(self.business_date, field_name="business_date")
        require_iso_datetime(self.collected_at, field_name="collected_at")
        if not self.source.strip():
            raise ValueError("source 不能为空")
        validate_json_object(self.data_window, field_name="data_window")
        metrics = validate_json_object(self.metrics, field_name="metrics")
        dimensions = validate_json_object(self.dimensions, field_name="dimensions")
        try:
            status = DataStatus(self.data_status)
        except ValueError as exc:
            raise ValueError(f"未知 data_status: {self.data_status}") from exc
        if status is not DataStatus.REAL and not (self.reason or "").strip():
            raise ValueError(f"{status.value} 必须说明 reason")
        if status is DataStatus.UNAVAILABLE and (
            contains_non_null_metric(metrics)
            or contains_non_null_metric(dimensions)
            or bool(self.findings)
        ):
            raise ValueError("UNAVAILABLE 的 metrics/dimensions/findings 只能为空或 null")
        strict_bool(self.single_source_risk, field_name="single_source_risk")
        if not self.cross_validation.strip():
            raise ValueError("cross_validation 不能为空")
        if any(not str(x).strip() for x in self.known_limitations):
            raise ValueError("known_limitations 不允许空项")
        if self.schema_version != SCHEMA_VERSION:
            raise ValueError(f"不支持 schema_version={self.schema_version}")
        for finding in self.findings:
            finding.validate()

    def to_dict(self) -> dict[str, Any]:
        self.validate()
        return {
            "schema_version": self.schema_version,
            "module_id": self.module_id,
            "site_id": self.site_id,
            "business_date": self.business_date,
            "data_status": DataStatus(self.data_status).value,
            "source": self.source,
            "data_window": dict(self.data_window),
            "reason": self.reason,
            "known_limitations": list(self.known_limitations),
            "cross_validation": self.cross_validation,
            "single_source_risk": self.single_source_risk,
            "collected_at": self.collected_at,
            "workflow_instance_id": self.workflow_instance_id,
            "timeline_node_id": self.timeline_node_id,
            "asset_id": self.asset_id,
            "metrics": dict(self.metrics),
            "dimensions": dict(self.dimensions),
            "findings": [x.to_dict() for x in self.findings],
        }

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> ModuleRun:
        findings = tuple(ModuleFinding(**item) for item in (raw.get("findings") or ()))
        run = cls(
            site_id=str(raw.get("site_id", "")),
            module_id=str(raw.get("module_id", "")),
            business_date=str(raw.get("business_date", "")),
            data_status=DataStatus(str(raw.get("data_status", "UNAVAILABLE"))),
            source=str(raw.get("source", "")),
            data_window=dict(raw.get("data_window") or {}),
            reason=raw.get("reason"),
            known_limitations=tuple(str(x) for x in (raw.get("known_limitations") or ())),
            cross_validation=str(raw.get("cross_validation", "")),
            single_source_risk=strict_bool(
                raw.get("single_source_risk", False), field_name="single_source_risk"
            ),
            collected_at=str(raw.get("collected_at") or utc_now()),
            workflow_instance_id=str(raw.get("workflow_instance_id", "")),
            timeline_node_id=str(raw.get("timeline_node_id", "")),
            asset_id=str(raw.get("asset_id", "")),
            metrics=dict(raw.get("metrics") or {}),
            dimensions=dict(raw.get("dimensions") or {}),
            findings=findings,
            schema_version=str(raw.get("schema_version", SCHEMA_VERSION)),
        )
        run.validate()
        return run


__all__ = [
    "MODULE_IDS", "SCHEMA_VERSION", "MetricPoint", "ModuleFinding", "ModuleRun",
]
