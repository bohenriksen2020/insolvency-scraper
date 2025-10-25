"""APScheduler integration for the aggregator."""

from __future__ import annotations

import logging
from typing import Callable, Optional

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from pytz import timezone

logger = logging.getLogger(__name__)

_scheduler: Optional[BackgroundScheduler] = None


def start_scheduler(job_func: Callable[[], None]) -> BackgroundScheduler:
    """Start the APScheduler with the provided job function."""
    global _scheduler

    if _scheduler and _scheduler.running:
        logger.debug("Scheduler already running")
        return _scheduler

    cet = timezone("Europe/Copenhagen")
    scheduler = BackgroundScheduler(timezone=cet)
    scheduler.add_job(
        job_func,
        trigger=CronTrigger(hour=6, minute=0),
        name="daily_insolvency_ingestion",
        next_run_time=None,
        replace_existing=True,
    )
    scheduler.start()

    _scheduler = scheduler
    logger.info("Scheduler started with daily ingestion job at 06:00 CET")
    return scheduler


def shutdown_scheduler() -> None:
    """Shutdown the APScheduler if it's running."""
    global _scheduler
    if _scheduler and _scheduler.running:
        logger.info("Shutting down scheduler")
        _scheduler.shutdown(wait=False)
        _scheduler = None
