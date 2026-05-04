from __future__ import annotations

import logging

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger

from .config import Settings
from .db import Database
from .runner import run_daily

LOGGER = logging.getLogger(__name__)


def start_scheduler(settings: Settings, db: Database) -> None:
    hour, minute = settings.schedule_time.split(":", 1)
    scheduler = BlockingScheduler(timezone=settings.timezone)
    trigger = CronTrigger(hour=int(hour), minute=int(minute), timezone=settings.timezone)

    def job() -> None:
        try:
            result = run_daily(settings, db, dry_run=settings.dry_run)
            LOGGER.info(result)
        except Exception as exc:  # APScheduler should keep running after a single failure.
            LOGGER.exception("Scheduled outreach run failed")
            db.log("error", "Scheduled outreach run failed", repr(exc))

    scheduler.add_job(job, trigger=trigger, id="daily_outreach", replace_existing=True, max_instances=1)
    LOGGER.info("Scheduler started for %s daily in %s", settings.schedule_time, settings.timezone)
    scheduler.start()
