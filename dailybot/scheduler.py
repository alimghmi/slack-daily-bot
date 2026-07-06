from __future__ import annotations

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from dailybot.config import AppConfig
from dailybot.service import DailyService


def create_scheduler(config: AppConfig, service: DailyService) -> BackgroundScheduler:
    scheduler = BackgroundScheduler(timezone=config.timezone)

    scheduler.add_job(
        service.send_daily_prompts,
        CronTrigger(
            hour=config.schedule.prompt_time.hour,
            minute=config.schedule.prompt_time.minute,
            timezone=config.timezone,
        ),
        id="daily_prompt",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    scheduler.add_job(
        service.send_reminders,
        CronTrigger(
            hour=config.schedule.reminder_time.hour,
            minute=config.schedule.reminder_time.minute,
            timezone=config.timezone,
        ),
        id="daily_reminder",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    scheduler.add_job(
        service.post_final_status,
        CronTrigger(
            hour=config.schedule.final_status_time.hour,
            minute=config.schedule.final_status_time.minute,
            timezone=config.timezone,
        ),
        id="daily_final_status",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    scheduler.add_job(
        service.retry_pending_reports,
        IntervalTrigger(minutes=5, timezone=config.timezone),
        id="retry_pending_reports",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )

    return scheduler
