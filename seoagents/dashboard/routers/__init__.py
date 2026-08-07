from dojocore.timeline.api import router as timeline_router
from seoagents.dashboard.routers import (
    agent_jobs,
    agentops,
    audit,
    catalog_api,
    collab_api,
    config_api,
    control_tower_api,
    conversations,
    departments_api,
    gsc_api,
    kanban_api,
    keywords_api,
    metrics,
    public_seo_control_tower,
    skills_api,
    storage_api,
    timeline_cron_api,
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
    public_seo_control_tower.router,
    control_tower_api.router,
    catalog_api.router,
    collab_api.router,
    workflow_api.router,
    workflow_kanban_bridge.router,
    kanban_api.router,
    departments_api.router,
    storage_api.router,
    conversations.router,
    keywords_api.router,
    skills_api.router,
    # Must precede the legacy /api/timeline/{...} routes where paths overlap.
    timeline_cron_api.router,
    timeline_router,
]

__all__ = ["all_routers"]
