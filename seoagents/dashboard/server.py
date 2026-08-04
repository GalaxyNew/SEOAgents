"""Dashboard app factory (L2) — FastAPI + lifespan wiring + static L1 assets."""
from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from dojocore.logging import LOGGER
from seoagents import __version__
from seoagents.agent.runtime import get_runtime
from seoagents.cron import shutdown_scheduler, start_scheduler
from seoagents.cron.seo_evo_jobs import register_jobs
from seoagents.dashboard.routers import all_routers

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


from seoagents.dashboard.auth import AuthMiddleware
from seoagents.dashboard.auth import router as auth_router


def create_app() -> FastAPI:
    app = FastAPI(
        title="SEOAgents Dashboard",
        version=__version__,
        description="Self-evolving SEO/AEO agent cluster — seven-layer DojoAgents architecture",
        lifespan=_lifespan,
    )
    # 鉴权中间件要在路由之前挂:它得看到每一个请求,包括 /docs 与 /openapi.json
    # —— 那两个页面能直接发 POST,漏掉它们等于门锁上了但窗户开着。
    app.add_middleware(AuthMiddleware)
    app.include_router(auth_router)
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

    @app.get("/console", include_in_schema=False)
    def console() -> FileResponse:
        """Zero-build department console.

        Served as a single static file on purpose: every step added to the
        deployment path (install node, run a build, ship the bundle) is another
        day before anyone can actually look at the thing.
        """
        return FileResponse(_STATIC_DIR / "console.html")

    @app.get("/login", include_in_schema=False)
    def login_page() -> FileResponse:
        """Cyberpunk login page — raw HTML, no React."""
        return FileResponse(_STATIC_DIR / "login.html")

    @app.get("/healthz", include_in_schema=False)
    def healthz() -> dict:
        return {"ok": True, "version": __version__}


    return app


__all__ = ["create_app"]
