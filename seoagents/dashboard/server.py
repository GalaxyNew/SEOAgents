"""Dashboard app factory (L2) — FastAPI + lifespan wiring + static L1 assets."""
from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from seoagents import __version__
from seoagents.agent.runtime import get_runtime
from seoagents.cron import shutdown_scheduler, start_scheduler
from seoagents.cron.seo_evo_jobs import register_jobs
from seoagents.dashboard.routers import all_routers
from seoagents.logging import LOGGER

_STATIC_DIR = Path(__file__).parent / "static"


@asynccontextmanager
async def _lifespan(app: FastAPI):
    runtime = get_runtime()
    mounted = await runtime.mount_mcp()
    if mounted:
        LOGGER.info(f"MCP bridge mounted {mounted} external tools")
    if runtime.config.scheduler.enabled:
        register_jobs(runtime)
        start_scheduler()
    LOGGER.info("SEOAgents dashboard ready")
    try:
        yield
    finally:
        shutdown_scheduler()


def create_app() -> FastAPI:
    app = FastAPI(
        title="SEOAgents Dashboard",
        version=__version__,
        description="Self-evolving SEO/AEO agent cluster — seven-layer DojoAgents architecture",
        lifespan=_lifespan,
    )
    for router in all_routers:
        app.include_router(router)

    app.mount("/static", StaticFiles(directory=_STATIC_DIR), name="static")
    app_dir = _STATIC_DIR / "app"
    if (app_dir / "assets").exists():
        app.mount("/assets", StaticFiles(directory=app_dir / "assets"), name="assets")


    @app.get("/", include_in_schema=False)
    def index() -> FileResponse:
        react_app = _STATIC_DIR / "app" / "index.html"
        if react_app.exists():
            return FileResponse(react_app)
        return FileResponse(_STATIC_DIR / "index.html")

    @app.get("/healthz", include_in_schema=False)
    def healthz() -> dict:
        return {"ok": True, "version": __version__}


    return app


__all__ = ["create_app"]
