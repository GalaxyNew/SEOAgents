"""Metrics API routes (L2)."""
from __future__ import annotations

from fastapi import APIRouter, Depends

from seoagents.dashboard.deps import metrics_service_dep
from seoagents.dashboard.schemas import MetricsSummary
from seoagents.dashboard.services.metrics_service import MetricsService

router = APIRouter(prefix="/api/metrics", tags=["metrics"])


@router.get("/summary", response_model=MetricsSummary)
def metrics_summary(svc: MetricsService = Depends(metrics_service_dep)) -> dict:
    return svc.summary()


@router.get("/serp/{keyword}")
def serp_history(keyword: str, svc: MetricsService = Depends(metrics_service_dep)) -> list[dict]:
    return svc.serp_history(keyword)


@router.get("/deadlinks")
def dead_links(svc: MetricsService = Depends(metrics_service_dep)) -> list[dict]:
    return svc.dead_links()
