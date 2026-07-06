from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from dailybot.models import DailyEntry, PromptLog


class Database:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def initialize(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS daily_entries (
                    work_date TEXT NOT NULL,
                    user_id TEXT NOT NULL,
                    display_name TEXT NOT NULL,
                    answers_json TEXT NOT NULL,
                    submitted_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    daily_channel_id TEXT,
                    daily_channel_message_ts TEXT,
                    report_status TEXT NOT NULL DEFAULT 'pending',
                    report_error TEXT,
                    PRIMARY KEY (work_date, user_id)
                );

                CREATE TABLE IF NOT EXISTS prompt_log (
                    work_date TEXT NOT NULL,
                    user_id TEXT NOT NULL,
                    dm_channel_id TEXT,
                    prompt_message_ts TEXT,
                    prompted_at TEXT,
                    reminder_timestamp TEXT,
                    PRIMARY KEY (work_date, user_id)
                );

                CREATE INDEX IF NOT EXISTS idx_daily_entries_status
                    ON daily_entries (report_status, work_date);
                """
            )

    def reserve_prompt(self, work_date: str, user_id: str, prompted_at: str) -> bool:
        with self._connect() as connection:
            cursor = connection.execute(
                """
                INSERT OR IGNORE INTO prompt_log (work_date, user_id, prompted_at)
                VALUES (?, ?, ?)
                """,
                (work_date, user_id, prompted_at),
            )
            return cursor.rowcount == 1

    def complete_prompt(
        self,
        work_date: str,
        user_id: str,
        dm_channel_id: str,
        prompt_message_ts: str,
        prompted_at: str,
    ) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE prompt_log
                   SET dm_channel_id = ?,
                       prompt_message_ts = ?,
                       prompted_at = ?
                 WHERE work_date = ? AND user_id = ?
                """,
                (dm_channel_id, prompt_message_ts, prompted_at, work_date, user_id),
            )

    def get_prompt(self, work_date: str, user_id: str) -> PromptLog | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT work_date, user_id, dm_channel_id, prompt_message_ts, prompted_at,
                       reminder_timestamp
                  FROM prompt_log
                 WHERE work_date = ? AND user_id = ?
                """,
                (work_date, user_id),
            ).fetchone()
        return _prompt_from_row(row) if row else None

    def mark_reminder_sent_once(self, work_date: str, user_id: str, timestamp: str) -> bool:
        with self._connect() as connection:
            inserted = connection.execute(
                """
                INSERT OR IGNORE INTO prompt_log (work_date, user_id, reminder_timestamp)
                VALUES (?, ?, ?)
                """,
                (work_date, user_id, timestamp),
            )
            if inserted.rowcount == 1:
                return True
            updated = connection.execute(
                """
                UPDATE prompt_log
                   SET reminder_timestamp = ?
                 WHERE work_date = ? AND user_id = ? AND reminder_timestamp IS NULL
                """,
                (timestamp, work_date, user_id),
            )
            return updated.rowcount == 1

    def save_daily_entry(
        self,
        *,
        work_date: str,
        user_id: str,
        display_name: str,
        answers: dict[str, str],
        timestamp: str,
    ) -> DailyEntry:
        answers_json = json.dumps(answers, ensure_ascii=False)
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO daily_entries (
                    work_date, user_id, display_name, answers_json, submitted_at, updated_at,
                    report_status, report_error
                )
                VALUES (?, ?, ?, ?, ?, ?, 'pending', NULL)
                ON CONFLICT(work_date, user_id) DO UPDATE SET
                    display_name = excluded.display_name,
                    answers_json = excluded.answers_json,
                    updated_at = excluded.updated_at,
                    report_status = 'pending',
                    report_error = NULL
                """,
                (work_date, user_id, display_name, answers_json, timestamp, timestamp),
            )
        entry = self.get_daily_entry(work_date, user_id)
        if entry is None:
            raise RuntimeError("Daily entry was not persisted.")
        return entry

    def get_daily_entry(self, work_date: str, user_id: str) -> DailyEntry | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT work_date, user_id, display_name, answers_json, submitted_at, updated_at,
                       daily_channel_id, daily_channel_message_ts, report_status, report_error
                  FROM daily_entries
                 WHERE work_date = ? AND user_id = ?
                """,
                (work_date, user_id),
            ).fetchone()
        return _entry_from_row(row) if row else None

    def mark_report_posted(
        self, work_date: str, user_id: str, channel_id: str, message_ts: str
    ) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE daily_entries
                   SET daily_channel_id = ?,
                       daily_channel_message_ts = ?,
                       report_status = 'posted',
                       report_error = NULL
                 WHERE work_date = ? AND user_id = ?
                """,
                (channel_id, message_ts, work_date, user_id),
            )

    def mark_report_pending(self, work_date: str, user_id: str, error: str) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE daily_entries
                   SET report_status = 'pending',
                       report_error = ?
                 WHERE work_date = ? AND user_id = ?
                """,
                (error[:1000], work_date, user_id),
            )

    def has_submission(self, work_date: str, user_id: str) -> bool:
        return self.get_daily_entry(work_date, user_id) is not None

    def list_entries_for_date(self, work_date: str) -> list[DailyEntry]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT work_date, user_id, display_name, answers_json, submitted_at, updated_at,
                       daily_channel_id, daily_channel_message_ts, report_status, report_error
                  FROM daily_entries
                 WHERE work_date = ?
                 ORDER BY display_name COLLATE NOCASE
                """,
                (work_date,),
            ).fetchall()
        return [_entry_from_row(row) for row in rows]

    def list_pending_reports(self) -> list[DailyEntry]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT work_date, user_id, display_name, answers_json, submitted_at, updated_at,
                       daily_channel_id, daily_channel_message_ts, report_status, report_error
                  FROM daily_entries
                 WHERE report_status = 'pending'
                 ORDER BY work_date, display_name COLLATE NOCASE
                """
            ).fetchall()
        return [_entry_from_row(row) for row in rows]

    def _connect(self) -> sqlite3.Connection:
        if str(self.path) != ":memory:":
            self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA busy_timeout=5000")
        connection.execute("PRAGMA foreign_keys=ON")
        return connection


def _entry_from_row(row: sqlite3.Row) -> DailyEntry:
    return DailyEntry(
        work_date=row["work_date"],
        user_id=row["user_id"],
        display_name=row["display_name"],
        answers=json.loads(row["answers_json"]),
        submitted_at=row["submitted_at"],
        updated_at=row["updated_at"],
        daily_channel_id=row["daily_channel_id"],
        daily_channel_message_ts=row["daily_channel_message_ts"],
        report_status=row["report_status"],
        report_error=row["report_error"],
    )


def _prompt_from_row(row: sqlite3.Row) -> PromptLog:
    return PromptLog(
        work_date=row["work_date"],
        user_id=row["user_id"],
        dm_channel_id=row["dm_channel_id"],
        prompt_message_ts=row["prompt_message_ts"],
        prompted_at=row["prompted_at"],
        reminder_timestamp=row["reminder_timestamp"],
    )
