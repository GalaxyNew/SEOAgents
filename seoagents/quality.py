"""Data-integrity contract (cross-layer) — the ``data_status`` envelope.

Every tool result that can possibly be degraded or unavailable MUST declare how
trustworthy it is. This exists because silent degradation is the single most
dangerous failure mode in an autonomous SEO pipeline: a dashboard that shows
fabricated keyword rows, or an "AI visibility" metric that is really a hash with
a daily upward drift, is worse than no metric at all — it launders synthetic
numbers into decisions that look evidence-based.

Four states::

    REAL         real source, collection succeeded            -> any use
    DEGRADED     real but with a known defect / fallback path  -> display with a
                                                                  badge; MUST NOT
                                                                  feed the M_t score
    UNAVAILABLE  could not be obtained                         -> empty state only,
                                                                  never zero-filled
    DISPUTED     multiple providers disagree beyond tolerance  -> show the divergence,
                                                                  never average or
                                                                  silently pick a winner

Three enforcement gates:

1. **Tool layer**   — :func:`validate_tool_output` rejects any spec result that
   omits ``data_status``. Wired into ``ToolExecutor``.
2. **Scoring layer** — ``SeoScoreEngine.compute_m_t`` refuses to produce a score
   when any input is not ``REAL``.
3. **Asset layer**  — the Asset Hub lineage trigger refuses to let a ``REAL``
   asset derive from a non-``REAL`` parent (external, see the Asset Hub design).
"""
from __future__ import annotations

import datetime as _dt
import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

__all__ = [
    "DataIntegrityError",
    "DataStatus",
    "all_real",
    "degraded",
    "disputed",
    "envelope",
    "extract_status",
    "real",
    "unavailable",
    "validate_tool_output",
    "window_iso",
    "worst_status",
]


class DataStatus(str, Enum):
    """How much a caller is allowed to trust this payload."""

    REAL = "REAL"
    DEGRADED = "DEGRADED"
    UNAVAILABLE = "UNAVAILABLE"
    DISPUTED = "DISPUTED"

    @property
    def scorable(self) -> bool:
        """Only fully real data may contribute to the M_t evolution score."""
        return self is DataStatus.REAL

    @property
    def displayable(self) -> bool:
        """UNAVAILABLE renders as an empty state, never as a zero."""
        return self is not DataStatus.UNAVAILABLE


class DataIntegrityError(ValueError):
    """Raised when a tool result violates the data-status contract."""


# Ordering used by :func:`worst_status` — later entries dominate.
_SEVERITY: tuple[DataStatus, ...] = (
    DataStatus.REAL,
    DataStatus.DEGRADED,
    DataStatus.DISPUTED,
    DataStatus.UNAVAILABLE,
)


def window_iso(start: _dt.datetime | None = None, end: _dt.datetime | None = None) -> str:
    """Return an ISO-8601 interval string ``<start>/<end>``.

    Reports without an explicit data window invite "it went up" comparisons
    across mismatched periods, so every envelope carries one.
    """
    end = end or _dt.datetime.now(_dt.timezone.utc)
    start = start or end
    return f"{start.isoformat()}/{end.isoformat()}"


@dataclass(frozen=True)
class _Envelope:
    data_status: DataStatus
    source: str
    data_window: str
    degraded_reason: str | None = None
    payload: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = dict(self.payload)
        out["data_status"] = self.data_status.value
        out["source"] = self.source
        out["data_window"] = self.data_window
        if self.degraded_reason:
            out["degraded_reason"] = self.degraded_reason
        return out


def envelope(
    payload: Mapping[str, Any] | None = None,
    *,
    status: DataStatus | str,
    source: str,
    data_window: str | None = None,
    degraded_reason: str | None = None,
) -> dict[str, Any]:
    """Wrap a payload in the data-status envelope.

    ``DEGRADED`` / ``UNAVAILABLE`` / ``DISPUTED`` all require a reason: a caller
    that cannot say *why* the data is untrustworthy has not actually understood
    the failure, and downstream agents need the reason to report it verbatim.
    """
    st = status if isinstance(status, DataStatus) else DataStatus(status)
    if st is not DataStatus.REAL and not degraded_reason:
        raise DataIntegrityError(f"status={st.value} requires a degraded_reason")
    return _Envelope(
        data_status=st,
        source=source,
        data_window=data_window or window_iso(),
        degraded_reason=degraded_reason,
        payload=payload or {},
    ).to_dict()


def real(
    payload: Mapping[str, Any], *, source: str, data_window: str | None = None
) -> dict[str, Any]:
    """Shorthand for a trustworthy result."""
    return envelope(payload, status=DataStatus.REAL, source=source, data_window=data_window)


def degraded(
    payload: Mapping[str, Any],
    *,
    source: str,
    reason: str,
    data_window: str | None = None,
) -> dict[str, Any]:
    """Real data obtained through a fallback / partially failed path."""
    return envelope(
        payload,
        status=DataStatus.DEGRADED,
        source=source,
        data_window=data_window,
        degraded_reason=reason,
    )


def unavailable(*, source: str, reason: str, **extra: Any) -> dict[str, Any]:
    """No data. Callers must render an empty state — never substitute zero."""
    return envelope(extra, status=DataStatus.UNAVAILABLE, source=source, degraded_reason=reason)


def disputed(payload: Mapping[str, Any], *, source: str, reason: str) -> dict[str, Any]:
    """Providers disagree beyond tolerance. Never average, never pick a winner."""
    return envelope(payload, status=DataStatus.DISPUTED, source=source, degraded_reason=reason)


def extract_status(raw: Any) -> DataStatus | None:
    """Best-effort read of ``data_status`` from a tool result (dict or JSON str)."""
    data: Any = raw
    if isinstance(raw, (str, bytes)):
        try:
            data = json.loads(raw)
        except (json.JSONDecodeError, UnicodeDecodeError):
            return None
    if not isinstance(data, Mapping):
        return None
    value = data.get("data_status")
    if value is None:
        return None
    try:
        return DataStatus(value)
    except ValueError:
        return None


def validate_tool_output(tool_name: str, raw: Any) -> DataStatus:
    """Gate 1. Raise unless the result declares a valid ``data_status``.

    Enforced centrally in ``ToolExecutor`` so a new tool cannot bypass the
    contract by forgetting to add the field.
    """
    status = extract_status(raw)
    if status is None:
        raise DataIntegrityError(
            f"tool '{tool_name}' returned a result without a valid 'data_status' field; "
            f"build results with seoagents.quality.real()/degraded()/unavailable()"
        )
    return status


def worst_status(statuses: Any) -> DataStatus:
    """Combine statuses, most severe wins. Empty input counts as UNAVAILABLE."""
    resolved = [s if isinstance(s, DataStatus) else DataStatus(s) for s in statuses]
    if not resolved:
        return DataStatus.UNAVAILABLE
    return max(resolved, key=_SEVERITY.index)


def all_real(statuses: Mapping[str, Any] | Any) -> bool:
    """True only when every input is REAL. Used by the scoring gate."""
    values = statuses.values() if isinstance(statuses, Mapping) else statuses
    return all(
        (s if isinstance(s, DataStatus) else DataStatus(s)) is DataStatus.REAL for s in values
    )
