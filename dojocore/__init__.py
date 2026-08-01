"""DojoCore — the department-agnostic framework.

Everything here is shared by every department built on it. What is *not* here,
by design, is any department's vocabulary, tools, pipelines or scoring formula:
those are declared in a :class:`~dojocore.department.DepartmentProfile`, and a
new department is a profile plus its own tool specs, not a fork of this package.

    dojocore.quality      data-status contract (REAL / DEGRADED / UNAVAILABLE / DISPUTED)
    dojocore.capability   capability vocabulary, registered by departments
    dojocore.department   what a department declares to become one
    dojocore.metrics      metric-engine protocol + the "only score real data" gate
    dojocore.collab       cross-department inbox / outbox contract
    dojocore.workflow     pipeline engine composed from generic nodes
    dojocore.context      how the framework reaches the host's configuration
"""
from __future__ import annotations

from dojocore.capability import Capability, CapabilityRegistry, capabilities
from dojocore.context import get_config, reset_config_provider, set_config_provider
from dojocore.department import (
    DepartmentBuilder,
    DepartmentProfile,
    active_department,
    departments,
)
from dojocore.metrics import MetricEngine, MetricResult, score_gate
from dojocore.quality import (
    DataIntegrityError,
    DataStatus,
    degraded,
    real,
    unavailable,
    validate_tool_output,
)

__all__ = [
    "Capability",
    "CapabilityRegistry",
    "DataIntegrityError",
    "DataStatus",
    "DepartmentBuilder",
    "DepartmentProfile",
    "MetricEngine",
    "MetricResult",
    "active_department",
    "capabilities",
    "degraded",
    "departments",
    "get_config",
    "real",
    "reset_config_provider",
    "score_gate",
    "set_config_provider",
    "unavailable",
    "validate_tool_output",
]
