from __future__ import annotations

import os

from dailybot.config import load_config
from dailybot.database import Database


def main() -> None:
    config_path = os.getenv("DAILY_BOT_CONFIG", "/app/config.yml")
    database_path = os.getenv("DAILY_BOT_DB", "/app/data/daily.db")
    load_config(config_path, require_channel=False)
    database = Database(database_path)
    database.initialize()


if __name__ == "__main__":
    main()
