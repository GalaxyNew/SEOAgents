from seoagents.dashboard.routers import (
    agentops,
    audit,
    catalog_api,
    config_api,
    gsc_api,
    metrics,
)

all_routers = [
    metrics.router,
    audit.router,
    agentops.router,
    config_api.router,
    gsc_api.router,
    catalog_api.router,
]

__all__ = ["all_routers"]
