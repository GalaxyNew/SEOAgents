"""Config API routes (L2) — redacted exposure only (never leak API keys)."""
from __future__ import annotations

from fastapi import APIRouter, Depends

from seoagents.agent.runtime import Runtime
from seoagents.dashboard.deps import runtime_dep

router = APIRouter(prefix="/api/config", tags=["config"])


@router.get("")
def get_config(rt: Runtime = Depends(runtime_dep)) -> dict:
    return {
        "redacted": rt.config_store.redacted(),
        "resolved": {
            "site": rt.config.sites.site_url,
            "gsc_property": rt.config.sites.gsc_property,
            "tracked_keywords": list(rt.config.sites.tracked_keywords),
            "provider": rt.provider.name,
            "seonaut_endpoint": rt.config.seo_credentials.seonaut_endpoint,
            "openserp_endpoint": rt.config.seo_credentials.openserp_endpoint,
            "tools": rt.registry.names(),
            "scoring": {
                "alpha": rt.config.scoring.alpha,
                "beta": rt.config.scoring.beta,
                "gamma": rt.config.scoring.gamma,
                "delta": rt.config.scoring.delta,
                "skill_compile_threshold": rt.config.scoring.skill_compile_threshold,
            },
        },
    }
