from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Any


@dataclass(frozen=True)
class Employee:
    user_id: str
    display_name: str
    email: str | None = None
    is_admin: bool = False
    is_owner: bool = False
    is_guest: bool = False


@dataclass(frozen=True)
class PromptLog:
    work_date: str
    user_id: str
    dm_channel_id: str | None
    prompt_message_ts: str | None
    prompted_at: str | None
    reminder_timestamp: str | None


@dataclass(frozen=True)
class DailyEntry:
    work_date: str
    user_id: str
    display_name: str
    answers: dict[str, str]
    submitted_at: str
    updated_at: str
    daily_channel_id: str | None
    daily_channel_message_ts: str | None
    report_status: str
    report_error: str | None

    @property
    def work_date_value(self) -> date:
        return date.fromisoformat(self.work_date)


@dataclass(frozen=True)
class SubmissionResult:
    entry: DailyEntry
    published: bool


@dataclass(frozen=True)
class FinalStatus:
    work_date: date
    eligible_count: int
    submitted_count: int
    waiting: list[Employee]

    @property
    def waiting_count(self) -> int:
        return len(self.waiting)


SlackResponse = dict[str, Any]
Clock = Any
AwareDateTime = datetime
