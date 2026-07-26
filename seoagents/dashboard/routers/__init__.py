from seoagents.dashboard.routers import agentops, audit, config_api, metrics

all_routers = [metrics.router, audit.router, agentops.router, config_api.router]

__all__ = ["all_routers"]
