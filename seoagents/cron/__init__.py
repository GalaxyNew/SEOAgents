"""L2 scheduling layer — APScheduler AsyncIO singleton with graceful fallback.

Notes:
  * async jobs require ``AsyncIOScheduler`` (the plain decorator form in the
    manual would fail on coroutines under BackgroundScheduler).
  * when APScheduler is not installed the layer degrades to a null scheduler:
    one-shot commands (``seoagents evolve`` / API triggers) keep working,
    only the nightly cron is disabled.
"""
from __future__ import annotations

from typing import Any

from dojocore.logging import LOGGER

try:  # pragma: no cover - environment dependent
    from apscheduler.schedulers.asyncio import AsyncIOScheduler

    scheduler: Any = AsyncIOScheduler(timezone="UTC")
    HAS_APSCHEDULER = True
except ImportError:  # pragma: no cover
    HAS_APSCHEDULER = False

    class _NullScheduler:
        """No-op stand-in so callers never crash on a slim install."""

        running = False

        def add_job(self, *args: Any, **kwargs: Any) -> None:
            LOGGER.warning(
                "APScheduler not installed — cron job NOT registered "
                "(pip install apscheduler to enable the nightly evolution pipeline)"
            )

        def get_jobs(self) -> list[Any]:
            return []

        def start(self) -> None:
            LOGGER.warning("APScheduler not installed — scheduler start skipped")

        def shutdown(self, wait: bool = False) -> None:
            return

    scheduler = _NullScheduler()


def start_scheduler() -> None:
    if not scheduler.running:
        scheduler.start()
        jobs = ", ".join(job.id for job in scheduler.get_jobs()) or "(none)"
        LOGGER.info(f"Scheduler started; jobs: {jobs}")


def shutdown_scheduler() -> None:
    if scheduler.running:
        scheduler.shutdown(wait=False)
        LOGGER.info("Scheduler stopped")


__all__ = ["HAS_APSCHEDULER", "scheduler", "shutdown_scheduler", "start_scheduler"]
