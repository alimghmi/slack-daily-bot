from __future__ import annotations

import logging
from collections.abc import Callable, Iterable
from datetime import date, datetime
from typing import Any, Protocol

from dailybot.config import AppConfig
from dailybot.constants import SLACK_INPUT_MAX_LENGTH
from dailybot.database import Database
from dailybot.models import DailyEntry, Employee, FinalStatus, SlackResponse, SubmissionResult
from dailybot.slack_views import (
    daily_modal_view,
    final_status_blocks,
    format_report_date,
    prompt_blocks,
    report_blocks,
    report_fallback_text,
)

logger = logging.getLogger(__name__)

WEEKDAY_NAMES = {
    0: "mon",
    1: "tue",
    2: "wed",
    3: "thu",
    4: "fri",
    5: "sat",
    6: "sun",
}


class SlackApi(Protocol):
    def call(self, method: str, **kwargs: Any) -> SlackResponse:
        """Call a Slack Web API method."""


class DailyService:
    def __init__(
        self,
        *,
        config: AppConfig,
        database: Database,
        slack: SlackApi,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.config = config
        self.database = database
        self.slack = slack
        self.clock = clock

    def now(self) -> datetime:
        current = self.clock() if self.clock else datetime.now(self.config.tzinfo)
        if current.tzinfo is None:
            return current.replace(tzinfo=self.config.tzinfo)
        return current.astimezone(self.config.tzinfo)

    def current_work_date(self) -> date:
        return self.now().date()

    def is_workday(self, work_date: date) -> bool:
        return (
            WEEKDAY_NAMES[work_date.weekday()] in self.config.schedule.workdays
            and work_date.isoformat() not in self.config.daily.skip_dates
        )

    def is_admin(self, user_id: str) -> bool:
        return user_id in self.config.admin.allowed_user_ids

    def fetch_members(self) -> list[dict[str, Any]]:
        members: list[dict[str, Any]] = []
        cursor: str | None = None
        while True:
            kwargs: dict[str, Any] = {"limit": 200}
            if cursor:
                kwargs["cursor"] = cursor
            response = self.slack.call("users_list", **kwargs)
            members.extend(response.get("members", []))
            cursor = (response.get("response_metadata") or {}).get("next_cursor") or ""
            if not cursor:
                return members

    def eligible_employees(self) -> list[Employee]:
        return self.filter_members(self.fetch_members())

    def filter_members(self, members: Iterable[dict[str, Any]]) -> list[Employee]:
        employees = []
        audience = self.config.audience

        for member in members:
            user_id = str(member.get("id") or "")
            if not user_id or user_id == "USLACKBOT":
                continue
            if member.get("deleted") or member.get("is_bot") or member.get("is_app_user"):
                continue

            profile = member.get("profile") or {}
            email = _normalize_email(profile.get("email"))
            is_owner = bool(member.get("is_owner") or member.get("is_primary_owner"))
            is_guest = bool(member.get("is_restricted") or member.get("is_ultra_restricted"))
            employee = Employee(
                user_id=user_id,
                display_name=_display_name(member),
                email=email,
                is_admin=bool(member.get("is_admin")),
                is_owner=is_owner,
                is_guest=is_guest,
            )

            if user_id in audience.exclude_user_ids:
                continue
            if email is not None and email in audience.exclude_emails:
                continue

            employees.append(employee)

        return sorted(employees, key=lambda employee: employee.display_name.lower())

    def get_employee_by_id(self, user_id: str) -> Employee | None:
        try:
            response = self.slack.call("users_info", user=user_id)
        except Exception:
            logger.exception("Failed to load Slack user info", extra={"user_id": user_id})
            return None
        eligible = self.filter_members([response.get("user") or {}])
        return eligible[0] if eligible else None

    def send_daily_prompts(self, *, force: bool = False, work_date: date | None = None) -> int:
        target_date = work_date or self.current_work_date()
        if not force and not self.is_workday(target_date):
            logger.info(
                "Skipping daily prompt on non-workday",
                extra={"work_date": target_date.isoformat()},
            )
            return 0

        sent_count = 0
        for employee in self.eligible_employees():
            try:
                if self.send_prompt(employee, target_date):
                    sent_count += 1
            except Exception:
                logger.exception(
                    "Failed to send daily prompt",
                    extra={"work_date": target_date.isoformat(), "user_id": employee.user_id},
                )
        return sent_count

    def send_prompt(self, employee: Employee, work_date: date) -> bool:
        work_date_text = work_date.isoformat()
        existing = self.database.get_prompt(work_date_text, employee.user_id)
        if existing and existing.prompt_message_ts:
            return False
        if existing is None:
            self.database.reserve_prompt(work_date_text, employee.user_id, self.now().isoformat())

        dm_response = self.slack.call("conversations_open", users=employee.user_id)
        dm_channel_id = (dm_response.get("channel") or {}).get("id")
        if not dm_channel_id:
            raise RuntimeError(f"Slack did not return a DM channel for {employee.user_id}.")

        submitted = self.database.has_submission(work_date_text, employee.user_id)
        response = self.slack.call(
            "chat_postMessage",
            channel=dm_channel_id,
            text=f"{self.config.daily.title} - {format_report_date(work_date)}",
            blocks=prompt_blocks(self.config, work_date, submitted=submitted),
        )
        message_ts = response.get("ts")
        if not message_ts:
            raise RuntimeError("Slack did not return a message timestamp for the prompt.")

        self.database.complete_prompt(
            work_date_text,
            employee.user_id,
            dm_channel_id,
            str(message_ts),
            self.now().isoformat(),
        )
        return True

    def send_reminders(self, *, force: bool = False, work_date: date | None = None) -> int:
        target_date = work_date or self.current_work_date()
        if not force and (
            not self.config.schedule.reminders_enabled or not self.is_workday(target_date)
        ):
            return 0

        sent_count = 0
        work_date_text = target_date.isoformat()
        for employee in self.eligible_employees():
            if self.database.has_submission(work_date_text, employee.user_id):
                continue
            if not self.database.mark_reminder_sent_once(
                work_date_text, employee.user_id, self.now().isoformat()
            ):
                continue
            try:
                self._send_reminder(employee, target_date)
                sent_count += 1
            except Exception:
                logger.exception(
                    "Failed to send daily reminder",
                    extra={"work_date": work_date_text, "user_id": employee.user_id},
                )
        return sent_count

    def _send_reminder(self, employee: Employee, work_date: date) -> None:
        dm_response = self.slack.call("conversations_open", users=employee.user_id)
        dm_channel_id = (dm_response.get("channel") or {}).get("id")
        if not dm_channel_id:
            raise RuntimeError(f"Slack did not return a DM channel for {employee.user_id}.")
        self.slack.call(
            "chat_postMessage",
            channel=dm_channel_id,
            text=f"Reminder: {self.config.daily.title}",
            blocks=prompt_blocks(self.config, work_date),
        )

    def open_daily_modal(
        self, *, user_id: str, trigger_id: str, work_date: date | None = None
    ) -> bool:
        target_date = work_date or self.current_work_date()
        employee = self.get_employee_by_id(user_id)
        if employee is None:
            return False

        existing = self.database.get_daily_entry(target_date.isoformat(), user_id)
        self.slack.call(
            "views_open",
            trigger_id=trigger_id,
            view=daily_modal_view(
                self.config,
                work_date=target_date,
                user_id=user_id,
                existing_answers=existing.answers if existing else None,
            ),
        )
        return True

    def validate_answers(self, answers: dict[str, str]) -> dict[str, str]:
        errors = {}
        for key in self.config.daily.questions:
            answer = answers.get(key, "")
            if not answer.strip():
                errors[key] = "Please answer this question."
            elif len(answer) > SLACK_INPUT_MAX_LENGTH:
                errors[key] = f"Please keep this answer under {SLACK_INPUT_MAX_LENGTH} characters."
        return errors

    def submit_daily(
        self,
        *,
        user_id: str,
        answers: dict[str, str],
        work_date: date | None = None,
        display_name: str | None = None,
    ) -> SubmissionResult:
        target_date = work_date or self.current_work_date()
        errors = self.validate_answers(answers)
        if errors:
            raise ValueError(f"Invalid daily submission: {errors}")

        employee = self.get_employee_by_id(user_id)
        if display_name is None:
            display_name = employee.display_name if employee else user_id

        ordered_answers = {key: answers[key].strip() for key in self.config.daily.questions}
        entry = self.database.save_daily_entry(
            work_date=target_date.isoformat(),
            user_id=user_id,
            display_name=display_name,
            answers=ordered_answers,
            timestamp=self.now().isoformat(),
        )

        published = self.publish_report(entry)
        self.confirm_submission(entry, published=published)
        refreshed = self.database.get_daily_entry(target_date.isoformat(), user_id)
        return SubmissionResult(entry=refreshed or entry, published=published)

    def publish_report(self, entry: DailyEntry) -> bool:
        channel_id = entry.daily_channel_id or self.config.channel.daily_channel_id
        try:
            if entry.daily_channel_message_ts:
                try:
                    response = self.slack.call(
                        "chat_update",
                        channel=channel_id,
                        ts=entry.daily_channel_message_ts,
                        text=report_fallback_text(entry),
                        blocks=report_blocks(self.config, entry),
                        metadata=_report_metadata(entry),
                    )
                    message_ts = response.get("ts") or entry.daily_channel_message_ts
                except Exception as exc:
                    if _slack_error_code(exc) != "message_not_found":
                        raise
                    logger.warning(
                        "Stored daily report message was not found; posting replacement",
                        extra={"work_date": entry.work_date, "user_id": entry.user_id},
                    )
                    response = self._post_report(channel_id, entry)
                    message_ts = response.get("ts")
            else:
                response = self._post_report(channel_id, entry)
                message_ts = response.get("ts")
            if not message_ts:
                raise RuntimeError("Slack did not return a daily report message timestamp.")
            self.database.mark_report_posted(
                entry.work_date, entry.user_id, channel_id, str(message_ts)
            )
            return True
        except Exception as exc:
            self.database.mark_report_pending(entry.work_date, entry.user_id, str(exc))
            logger.exception(
                "Failed to publish daily report; leaving report pending",
                extra={"work_date": entry.work_date, "user_id": entry.user_id},
            )
            return False

    def _post_report(self, channel_id: str, entry: DailyEntry) -> dict[str, Any]:
        return self.slack.call(
            "chat_postMessage",
            channel=channel_id,
            text=report_fallback_text(entry),
            blocks=report_blocks(self.config, entry),
            metadata=_report_metadata(entry),
        )

    def retry_pending_reports(self) -> int:
        published = 0
        for entry in self.database.list_pending_reports():
            if self.publish_report(entry):
                published += 1
        return published

    def confirm_submission(self, entry: DailyEntry, *, published: bool) -> None:
        prompt = self.database.get_prompt(entry.work_date, entry.user_id)
        submitted_text = (
            "Your daily was submitted and posted."
            if published
            else "Your daily was saved. Posting to the daily channel is pending retry."
        )
        try:
            if prompt and prompt.dm_channel_id and prompt.prompt_message_ts:
                self.slack.call(
                    "chat_update",
                    channel=prompt.dm_channel_id,
                    ts=prompt.prompt_message_ts,
                    text=submitted_text,
                    blocks=prompt_blocks(self.config, entry.work_date_value, submitted=True),
                )
            else:
                dm_response = self.slack.call("conversations_open", users=entry.user_id)
                dm_channel_id = (dm_response.get("channel") or {}).get("id")
                if dm_channel_id:
                    self.slack.call(
                        "chat_postMessage",
                        channel=dm_channel_id,
                        text=submitted_text,
                    )
        except Exception:
            logger.exception(
                "Failed to send private submission confirmation",
                extra={"work_date": entry.work_date, "user_id": entry.user_id},
            )

    def final_status(self, *, work_date: date | None = None) -> FinalStatus:
        target_date = work_date or self.current_work_date()
        work_date_text = target_date.isoformat()
        employees = self.eligible_employees()
        eligible_user_ids = {employee.user_id for employee in employees}
        submitted_user_ids = {
            entry.user_id
            for entry in self.database.list_entries_for_date(work_date_text)
            if entry.user_id in eligible_user_ids
        }
        waiting = [employee for employee in employees if employee.user_id not in submitted_user_ids]
        return FinalStatus(
            work_date=target_date,
            eligible_count=len(employees),
            submitted_count=len(submitted_user_ids),
            waiting=waiting,
        )

    def final_status_text(self, *, work_date: date | None = None) -> str:
        status = self.final_status(work_date=work_date)
        lines = [
            f"Daily status: {status.submitted_count} of {status.eligible_count} submitted.",
        ]
        if status.waiting:
            lines.append("")
            lines.append("Waiting for:")
            lines.extend(f"- {employee.display_name}" for employee in status.waiting)
        return "\n".join(lines)

    def post_final_status(self, *, force: bool = False, work_date: date | None = None) -> bool:
        target_date = work_date or self.current_work_date()
        if not force and (
            not self.config.schedule.final_status_enabled or not self.is_workday(target_date)
        ):
            return False

        text = self.final_status_text(work_date=target_date)
        self.slack.call(
            "chat_postMessage",
            channel=self.config.channel.daily_channel_id,
            text=text,
            blocks=final_status_blocks(text),
        )
        return True


def _normalize_email(raw: object) -> str | None:
    if not raw:
        return None
    email = str(raw).strip().lower()
    return email or None


def _display_name(member: dict[str, Any]) -> str:
    profile = member.get("profile") or {}
    for key in ("display_name_normalized", "display_name", "real_name_normalized", "real_name"):
        value = profile.get(key)
        if value:
            return str(value)
    return str(member.get("real_name") or member.get("name") or member.get("id") or "Unknown")


def _report_metadata(entry: DailyEntry) -> dict[str, Any]:
    return {
        "event_type": "dailybot_report",
        "event_payload": {
            "work_date": entry.work_date,
            "user_id": entry.user_id,
        },
    }


def _slack_error_code(exc: Exception) -> str | None:
    response = getattr(exc, "response", None)
    data = getattr(response, "data", None)
    if isinstance(data, dict):
        error = data.get("error")
        return str(error) if error else None
    if isinstance(response, dict):
        error = response.get("error")
        return str(error) if error else None
    try:
        error = response["error"]
    except (KeyError, TypeError):
        return None
    return str(error) if error else None
