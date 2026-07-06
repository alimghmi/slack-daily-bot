from __future__ import annotations

import pytest

from dailybot.config import ConfigError, parse_config


def test_config_validation_rejects_invalid_timezone() -> None:
    with pytest.raises(ConfigError, match="Invalid timezone"):
        parse_config({"timezone": "Mars/Otanami", "channel": {"daily_channel_id": "C1"}})


def test_config_validation_rejects_invalid_schedule_values() -> None:
    with pytest.raises(ConfigError, match="workdays"):
        parse_config(
            {
                "schedule": {"workdays": ["mon", "funday"]},
                "channel": {"daily_channel_id": "C1"},
            }
        )

    with pytest.raises(ConfigError, match="prompt_time"):
        parse_config(
            {
                "schedule": {"prompt_time": "25:99"},
                "channel": {"daily_channel_id": "C1"},
            }
        )


def test_config_validation_requires_channel_for_runtime() -> None:
    with pytest.raises(ConfigError, match="daily_channel_id"):
        parse_config({"channel": {"daily_channel_id": ""}}, require_channel=True)

    config = parse_config({"channel": {"daily_channel_id": ""}}, require_channel=False)
    assert config.channel.daily_channel_id == ""
