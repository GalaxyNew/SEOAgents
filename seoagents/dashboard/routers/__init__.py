from dojocore.timeline.api import router as timeline_router
from seoagents.dashboard.routers import (
    agent_jobs,
    agentops,
    audit,
    catalog_api,
    collab_api,
    config_api,
    conversations,
    departments_api,
    gsc_api,
    kanban_api,
    metrics,
    storage_api,
    workflow_api,
    workflow_kanban_bridge,
)

all_routers = [
    metrics.router,
    audit.router,
    agentops.router,
    agent_jobs.router,
    config_api.router,
    gsc_api.router,
    catalog_api.router,
    collab_api.router,
    workflow_api.router,
    workflow_kanban_bridge.router,
    kanban_api.router,
    departments_api.router,
    storage_api.router,
    conversations.router,
    timeline_router,
]

__all__ = ["all_routers"]
