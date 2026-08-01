from dojocore.timeline.api import router as timeline_router
from seoagents.dashboard.routers import (
    agentops,
    audit,
    catalog_api,
    collab_api,
    config_api,
    gsc_api,
    metrics,
    workflow_api,
)

all_routers = [
    metrics.router,
    audit.router,
    agentops.router,
    config_api.router,
    gsc_api.router,
    catalog_api.router,
    collab_api.router,
    workflow_api.router,
    timeline_router,
]

__all__ = ["all_routers"]
