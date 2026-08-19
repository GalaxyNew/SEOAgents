from dojocore.federation_api import router as federation_router
from dojocore.taskcard.api import router as taskcard_router
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
    ga4_api,
    gsc_api,
    kanban_api,
    keywords_api,
    keywords_pool_api,
    metrics,
    public_seo_control_tower,
    seo_tasks_api,
    skills_api,
    storage_api,
    timeline_cron_api,
    workflow_api,
    workflow_kanban_bridge,
)

all_routers = [
    # 必须在 collab_api 之前：否则 /inbox/{request_id} 会吃掉 /inbox/summary
    federation_router,
    # 同理：静态路径 /summary /audit /stalled 在 api.py 内先于 /{card_id} 注册
    taskcard_router,
    metrics.router,
    audit.router,
    agentops.router,
    agent_jobs.router,
    config_api.router,
    gsc_api.router,
    ga4_api.router,
    ga4_api.router_v1,
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
    keywords_pool_api.router,
    keywords_pool_api.router_v1,
    seo_tasks_api.router,
    skills_api.router,
    # Must precede the legacy /api/timeline/{...} routes where paths overlap.
    timeline_cron_api.router,
    timeline_router,
]

__all__ = ["all_routers"]
