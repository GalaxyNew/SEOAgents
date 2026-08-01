"""Metric engines — each department scores itself, the framework guards the inputs.

SEO computes M_t from clicks, index coverage, SERP positions and technical
defects. Search computes a retrieval score from click retention, semantic
similarity, latency and crawl failure rate. The formulas have nothing in common
and should not be forced into one shape.

What *is* common, and what belongs here, is the rule that produced this module:
**a score may only be computed from fully trustworthy inputs.** A number
assembled from a hashed SERP position and an offline estimate looks exactly like
a real one, and once persisted it gets charted and used to decide whether a
change worked. So the gate lives in the framework, and only the arithmetic is
departmental.
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from dojocore.quality import DataStatus, all_real, worst_status

__all__ = ["MetricEngine", "MetricResult", "score_gate"]


@dataclass(frozen=True)
class MetricResult:
    """A score, or an explicit refusal to produce one."""

    value: float | None
    name: str = "score"
    status: str = "OK"                     # OK | PARTIAL
    excluded: tuple[str, ...] = ()
    breakdown: Mapping[str, Any] = field(default_factory=dict)

    @property
    def scorable(self) -> bool:
        return self.value is not None

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "value": round(self.value, 4) if self.value is not None else None,
            "status": self.status,
            "excluded": list(self.excluded),
            "breakdown": dict(self.breakdown),
        }


def score_gate(sources: Mapping[str, str] | None, *, name: str = "score") -> MetricResult | None:
    """Return a refusal when any input is not REAL, otherwise None.

    Departments call this first and return its result unchanged if it is not
    None. Centralising it means a new department cannot forget the rule, and a
    reader can see in one place why a score is missing.
    """
    if sources is None or all_real(sources):
        return None
    excluded = tuple(
        sorted(k for k, v in sources.items() if DataStatus(v) is not DataStatus.REAL)
    )
    return MetricResult(
        value=None,
        name=name,
        status="PARTIAL",
        excluded=excluded,
        breakdown={
            "sources": dict(sources),
            "worst_status": worst_status(sources.values()).value,
            "reason": f"{name} 拒绝计算:以下输入非 REAL —— " + ", ".join(excluded),
        },
    )


@runtime_checkable
class MetricEngine(Protocol):
    """What a department must provide to be scored.

    Implementations are expected to call :func:`score_gate` before doing any
    arithmetic.
    """

    name: str

    def compute(self, *, sources: Mapping[str, str] | None = None, **inputs: Any) -> MetricResult:
        ...

    def should_distil_skill(self, result: MetricResult) -> bool:
        """Whether this result is good enough to freeze the trace into a skill.

        Never true for an unscorable result — distilling a "high-performing"
        procedure out of data that could not be scored is how a mock pipeline
        teaches itself its own noise.
        """
        ...
