from __future__ import annotations

import logging
import os

from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler
from slack_sdk import WebClient

from dailybot.config import ConfigError, load_config
from dailybot.database import Database
from dailybot.logging_config import configure_logging
from dailybot.scheduler import create_scheduler
from dailybot.service import DailyService
from dailybot.slack_client import RetryingSlackClient
from dailybot.slack_handlers import register_handlers

logger = logging.getLogger(__name__)


def main() -> None:
    configure_logging()
    bot_token = _required_env("SLACK_BOT_TOKEN")
    app_token = _required_env("SLACK_APP_TOKEN")
    config_path = os.getenv("DAILY_BOT_CONFIG", "/app/config.yml")
    database_path = os.getenv("DAILY_BOT_DB", "/app/data/daily.db")

    try:
        config = load_config(config_path, require_channel=True)
    except ConfigError:
        logger.exception("Invalid daily bot configuration")
        raise

    database = Database(database_path)
    database.initialize()

    bolt_app = App(token=bot_token)
    slack = RetryingSlackClient(WebClient(token=bot_token))
    service = DailyService(config=config, database=database, slack=slack)
    register_handlers(bolt_app, service)

    scheduler = create_scheduler(config, service)
    scheduler.start()
    logger.info("Daily bot scheduler started")

    try:
        SocketModeHandler(bolt_app, app_token).start()
    finally:
        scheduler.shutdown(wait=False)
        logger.info("Daily bot scheduler stopped")


def _required_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"{name} must be set.")
    return value
