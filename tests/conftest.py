from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pytest

from dailybot.config import AppConfig, parse_config
from dailybot.database import Database
from dailybot.service import DailyService


def make_config(overrides: dict[str, Any] | None = None) -> AppConfig:
    raw: dict[str, Any] = {
        "timezone": "Asia/Tehran",
        "channel": {"daily_channel_id": "CDAILY"},
        "admin": {"allowed_user_ids": ["UADMIN"]},
    }
    if overrides:
        raw = _deep_merge(raw, overrides)
    return parse_config(raw, require_channel=True)


@pytest.fixture
def members() -> list[dict[str, Any]]:
    return [
        {
            "id": "U1",
            "name": "ali",
            "profile": {"email": "ali@example.com", "display_name": "Ali"},
        },
        {
            "id": "U2",
            "name": "sara",
            "profile": {"email": "sara@example.com", "display_name": "Sara"},
        },
    ]


@pytest.fixture
def fake_slack(members: list[dict[str, Any]]) -> FakeSlack:
    return FakeSlack(members)


@pytest.fixture
def database(tmp_path: Path) -> Database:
    db = Database(tmp_path / "daily.db")
    db.initialize()
    return db


@pytest.fixture
def service(database: Database, fake_slack: FakeSlack) -> DailyService:
    return DailyService(
        config=make_config(),
        database=database,
        slack=fake_slack,
        clock=lambda: datetime(2026, 7, 6, 9, 30, tzinfo=ZoneInfo("Asia/Tehran")),
    )


class FakeSlack:
    def __init__(self, members: list[dict[str, Any]]) -> None:
        self.members = members
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.posted: list[dict[str, Any]] = []
        self.updated: list[dict[str, Any]] = []
        self.views: list[dict[str, Any]] = []
        self.fail_next_daily_posts = 0
        self.fail_next_updates_with_message_not_found = 0
        self._ts_counter = 0

    def call(self, method: str, **kwargs: Any) -> dict[str, Any]:
        self.calls.append((method, kwargs))
        if method == "users_list":
            return {"members": self.members, "response_metadata": {"next_cursor": ""}}
        if method == "users_info":
            user_id = kwargs["user"]
            for member in self.members:
                if member.get("id") == user_id:
                    return {"user": member}
            return {"user": {"id": user_id, "profile": {"display_name": user_id}}}
        if method == "conversations_open":
            return {"channel": {"id": f"D{kwargs['users']}"}}
        if method == "chat_postMessage":
            if kwargs["channel"] == "CDAILY" and self.fail_next_daily_posts:
                self.fail_next_daily_posts -= 1
                raise RuntimeError("temporary Slack failure")
            self._ts_counter += 1
            message = {**kwargs, "ts": f"{self._ts_counter}.000000"}
            self.posted.append(message)
            return {"ok": True, "channel": kwargs["channel"], "ts": message["ts"]}
        if method == "chat_update":
            if self.fail_next_updates_with_message_not_found:
                self.fail_next_updates_with_message_not_found -= 1
                raise FakeSlackApiError("message_not_found")
            self.updated.append(dict(kwargs))
            return {"ok": True, "channel": kwargs["channel"], "ts": kwargs["ts"]}
        if method == "views_open":
            self.views.append(dict(kwargs))
            return {"ok": True}
        raise AssertionError(f"Unexpected Slack method: {method}")


class FakeSlackApiError(Exception):
    def __init__(self, error: str) -> None:
        super().__init__(error)
        self.response = FakeSlackErrorResponse(error)


class FakeSlackErrorResponse:
    def __init__(self, error: str) -> None:
        self.data = {"ok": False, "error": error}

    def __getitem__(self, key: str) -> Any:
        return self.data[key]


def _deep_merge(base: dict[str, Any], overrides: dict[str, Any]) -> dict[str, Any]:
    result = dict(base)
    for key, value in overrides.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result
