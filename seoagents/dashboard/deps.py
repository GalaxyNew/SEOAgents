"""FastAPI dependency accessors (L2) — DojoAgents ``deps.py`` convention."""
from __future__ import annotations

from seoagents.agent.runtime import Runtime, get_runtime
from seoagents.dashboard.services.metrics_service import MetricsService


def runtime_dep() -> Runtime:
    return get_runtime()


def metrics_service_dep() -> MetricsService:
    return MetricsService(get_runtime())
