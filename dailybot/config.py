from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, time
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import yaml


class ConfigError(ValueError):
    """Raised when YAML configuration is missing or invalid."""


VALID_WORKDAYS = {"mon", "tue", "wed", "thu", "fri", "sat", "sun"}
QUESTION_KEY_RE = re.compile(r"^[A-Za-z0-9_-]{1,80}$")


@dataclass(frozen=True)
class ScheduleConfig:
    workdays: list[str] = field(default_factory=lambda: ["sat", "sun", "mon", "tue", "wed"])
    prompt_time: time = time(9, 30)
    reminder_time: time = time(11, 0)
    final_status_time: time = time(12, 0)
    reminders_enabled: bool = True
    final_status_enabled: bool = True


@dataclass(frozen=True)
class DailyConfig:
    title: str = "Otanami Daily"
    intro: str = "Share a brief update for today."
    questions: dict[str, str] = field(
        default_factory=lambda: {
            "yesterday": "What did you complete since the previous workday?",
            "today": "What will you work on today?",
            "blockers": "Are there any blockers or areas where you need help?",
        }
    )
    skip_dates: set[str] = field(default_factory=set)


@dataclass(frozen=True)
class AudienceConfig:
    include_user_ids: set[str] = field(default_factory=set)
    include_emails: set[str] = field(default_factory=set)
    exclude_user_ids: set[str] = field(default_factory=set)
    exclude_emails: set[str] = field(default_factory=set)
    exclude_admins: bool = False
    exclude_owners: bool = False
    exclude_guests: bool = True


@dataclass(frozen=True)
class ChannelConfig:
    daily_channel_id: str = ""


@dataclass(frozen=True)
class AdminConfig:
    allowed_user_ids: set[str] = field(default_factory=set)


@dataclass(frozen=True)
class AppConfig:
    timezone: str
    tzinfo: ZoneInfo
    schedule: ScheduleConfig
    daily: DailyConfig
    audience: AudienceConfig
    channel: ChannelConfig
    admin: AdminConfig


def load_config(path: str | Path, *, require_channel: bool = True) -> AppConfig:
    config_path = Path(path)
    if not config_path.exists():
        raise ConfigError(f"Config file does not exist: {config_path}")

    with config_path.open("r", encoding="utf-8") as handle:
        raw = yaml.safe_load(handle) or {}

    if not isinstance(raw, dict):
        raise ConfigError("Config root must be a YAML mapping.")

    return parse_config(raw, require_channel=require_channel)


def parse_config(raw: dict, *, require_channel: bool = True) -> AppConfig:
    timezone_name = str(raw.get("timezone", "Asia/Tehran"))
    try:
        tzinfo = ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError as exc:
        raise ConfigError(f"Invalid timezone: {timezone_name}") from exc

    schedule = _parse_schedule(raw.get("schedule") or {})
    daily = _parse_daily(raw.get("daily") or {})
    audience = _parse_audience(raw.get("audience") or {})
    channel = ChannelConfig(
        daily_channel_id=str((raw.get("channel") or {}).get("daily_channel_id", ""))
    )
    admin = AdminConfig(
        allowed_user_ids=set(_string_list((raw.get("admin") or {}).get("allowed_user_ids")))
    )

    if require_channel and not channel.daily_channel_id:
        raise ConfigError("channel.daily_channel_id must be set to a Slack channel ID.")

    return AppConfig(
        timezone=timezone_name,
        tzinfo=tzinfo,
        schedule=schedule,
        daily=daily,
        audience=audience,
        channel=channel,
        admin=admin,
    )


def _parse_schedule(raw: dict) -> ScheduleConfig:
    default_workdays = ["sat", "sun", "mon", "tue", "wed"]
    workdays = [day.lower() for day in _string_list(raw.get("workdays"), default=default_workdays)]
    invalid = sorted(set(workdays) - VALID_WORKDAYS)
    if invalid:
        raise ConfigError(f"Invalid schedule.workdays value(s): {', '.join(invalid)}")

    return ScheduleConfig(
        workdays=workdays,
        prompt_time=_parse_hhmm(raw.get("prompt_time", "09:30"), "schedule.prompt_time"),
        reminder_time=_parse_hhmm(raw.get("reminder_time", "11:00"), "schedule.reminder_time"),
        final_status_time=_parse_hhmm(
            raw.get("final_status_time", "12:00"), "schedule.final_status_time"
        ),
        reminders_enabled=bool(raw.get("reminders_enabled", True)),
        final_status_enabled=bool(raw.get("final_status_enabled", True)),
    )


def _parse_daily(raw: dict) -> DailyConfig:
    questions_raw = raw.get("questions")
    if questions_raw is None:
        questions = DailyConfig().questions
    elif isinstance(questions_raw, dict):
        questions = {str(key): str(value) for key, value in questions_raw.items()}
    else:
        raise ConfigError("daily.questions must be a YAML mapping.")

    if not questions:
        raise ConfigError("daily.questions must contain at least one question.")

    for key, question in questions.items():
        if not QUESTION_KEY_RE.fullmatch(key):
            raise ConfigError(
                "daily.questions keys must be 1-80 chars and use letters, numbers, '_' or '-'."
            )
        if not question.strip():
            raise ConfigError(f"daily.questions.{key} must not be empty.")

    skip_dates = set(_string_list(raw.get("skip_dates")))
    for skip_date in skip_dates:
        try:
            date.fromisoformat(skip_date)
        except ValueError as exc:
            raise ConfigError(f"Invalid ISO date in daily.skip_dates: {skip_date}") from exc

    return DailyConfig(
        title=str(raw.get("title", "Otanami Daily")),
        intro=str(raw.get("intro", "Share a brief update for today.")),
        questions=questions,
        skip_dates=skip_dates,
    )


def _parse_audience(raw: dict) -> AudienceConfig:
    return AudienceConfig(
        include_user_ids=set(_string_list(raw.get("include_user_ids"))),
        include_emails={email.lower() for email in _string_list(raw.get("include_emails"))},
        exclude_user_ids=set(_string_list(raw.get("exclude_user_ids"))),
        exclude_emails={email.lower() for email in _string_list(raw.get("exclude_emails"))},
        exclude_admins=bool(raw.get("exclude_admins", False)),
        exclude_owners=bool(raw.get("exclude_owners", False)),
        exclude_guests=bool(raw.get("exclude_guests", True)),
    )


def _parse_hhmm(raw: object, field_name: str) -> time:
    if not isinstance(raw, str):
        raise ConfigError(f"{field_name} must be a HH:MM string.")
    try:
        hour_text, minute_text = raw.split(":", maxsplit=1)
        parsed = time(hour=int(hour_text), minute=int(minute_text))
    except (ValueError, TypeError) as exc:
        raise ConfigError(f"{field_name} must be a valid HH:MM time.") from exc
    return parsed


def _string_list(raw: object, default: list[str] | None = None) -> list[str]:
    if raw is None:
        return list(default or [])
    if not isinstance(raw, list):
        raise ConfigError("Expected a YAML list.")
    result = []
    for value in raw:
        if value is None:
            continue
        text = str(value).strip()
        if text:
            result.append(text)
    return result
