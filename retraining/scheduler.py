"""
APScheduler-backed background retraining scheduler.
Triggers retrain_job.py periodically (e.g. nightly after market close).
"""
from __future__ import annotations

import logging
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from config.settings import TRAINING
from retraining.retrain_job import run_retraining_job

logger = logging.getLogger("scheduler")

_scheduler = None


def start_scheduler():
    global _scheduler
    if _scheduler is not None and _scheduler.running:
        logger.info("Retraining scheduler already running.")
        return _scheduler

    _scheduler = BackgroundScheduler()

    # Parse cron expression e.g. "0 18 * * 1-5" (6 PM MON-FRI)
    cron_expr = TRAINING.retrain_schedule_cron
    parts = cron_expr.split()
    if len(parts) == 5:
        minute, hour, day, month, day_of_week = parts
        trigger = CronTrigger(minute=minute, hour=hour, day=day, month=month, day_of_week=day_of_week)
    else:
        trigger = CronTrigger(hour=18, minute=0, day_of_week="mon-fri")

    _scheduler.add_job(run_retraining_job, trigger=trigger, id="scheduled_model_retrain", replace_existing=True)
    _scheduler.start()

    logger.info("Retraining scheduler started with cron trigger '%s'", cron_expr)
    return _scheduler


def stop_scheduler():
    global _scheduler
    if _scheduler and _scheduler.running:
        _scheduler.shutdown()
        logger.info("Retraining scheduler stopped.")
        _scheduler = None
