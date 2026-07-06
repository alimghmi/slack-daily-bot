from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

from conftest import FakeSlack, make_config

from dailybot.constants import REPORT_TITLE_EMOJI
from dailybot.database import Database
from dailybot.service import DailyService


def test_schedule_runs_saturday_to_wednesday_and_skips_thursday_friday_and_holidays(
    database: Database, fake_slack: FakeSlack
) -> None:
    service = DailyService(
        config=make_config({"daily": {"skip_dates": ["2026-07-25"]}}),
        database=database,
        slack=fake_slack,
    )

    assert service.is_workday(date(2026, 7, 4))
    assert service.is_workday(date(2026, 7, 5))
    assert service.is_workday(date(2026, 7, 6))
    assert service.is_workday(date(2026, 7, 7))
    assert service.is_workday(date(2026, 7, 8))
    assert not service.is_workday(date(2026, 7, 9))
    assert not service.is_workday(date(2026, 7, 10))
    assert not service.is_workday(date(2026, 7, 25))


def test_audience_filtering_excludes_only_configured_users_and_system_accounts(
    database: Database,
) -> None:
    members = [
        {"id": "U1", "profile": {"email": "ALI@EXAMPLE.COM", "display_name": "Ali"}},
        {"id": "U2", "profile": {"email": "sara@example.com", "display_name": "Sara"}},
        {"id": "U3", "is_bot": True, "profile": {"email": "bot@example.com"}},
        {"id": "U4", "deleted": True, "profile": {"email": "deleted@example.com"}},
        {
            "id": "U5",
            "is_restricted": True,
            "profile": {"email": "guest@example.com", "display_name": "Guest"},
        },
        {"id": "U6", "is_app_user": True, "profile": {"email": "app@example.com"}},
        {
            "id": "U7",
            "is_admin": True,
            "profile": {"email": "admin@example.com", "display_name": "Admin"},
        },
        {
            "id": "U8",
            "is_owner": True,
            "profile": {"email": "owner@example.com", "display_name": "Owner"},
        },
    ]
    service = DailyService(
        config=make_config(
            {
                "audience": {
                    "include_user_ids": ["U2", "U7"],
                    "include_emails": ["ali@example.com", "guest@example.com"],
                    "exclude_user_ids": ["U2"],
                    "exclude_emails": ["owner@example.com"],
                    "exclude_admins": True,
                    "exclude_guests": True,
                    "exclude_owners": True,
                }
            }
        ),
        database=database,
        slack=FakeSlack(members),
    )

    assert [employee.user_id for employee in service.filter_members(members)] == [
        "U7",
        "U1",
        "U5",
    ]


def test_duplicate_prompt_prevention(service: DailyService, fake_slack: FakeSlack) -> None:
    work_date = date(2026, 7, 6)

    assert service.send_daily_prompts(force=True, work_date=work_date) == 2
    assert service.send_daily_prompts(force=True, work_date=work_date) == 0

    dm_posts = [message for message in fake_slack.posted if message["channel"].startswith("D")]
    assert len(dm_posts) == 2


def test_prompt_after_submission_uses_submitted_state(
    service: DailyService, fake_slack: FakeSlack
) -> None:
    work_date = date(2026, 7, 6)
    service.submit_daily(
        user_id="U1",
        answers={"yesterday": "Done", "today": "Deploy", "blockers": "No blockers"},
        work_date=work_date,
    )

    employee = service.eligible_employees()[0]
    assert service.send_prompt(employee, work_date)

    dm_posts = [message for message in fake_slack.posted if message["channel"] == "DU1"]
    assert dm_posts[-1]["blocks"][0]["text"]["text"].endswith(
        "Your daily is submitted. You can edit it for today."
    )
    assert dm_posts[-1]["blocks"][2]["elements"][0]["text"]["text"] == "Edit daily"


def test_duplicate_reminder_prevention(service: DailyService, fake_slack: FakeSlack) -> None:
    work_date = date(2026, 7, 6)

    assert service.send_reminders(force=True, work_date=work_date) == 2
    assert service.send_reminders(force=True, work_date=work_date) == 0

    reminder_posts = [
        message for message in fake_slack.posted if message["channel"].startswith("D")
    ]
    assert len(reminder_posts) == 2


def test_submission_creation_and_edit_updates_existing_daily_channel_message(
    service: DailyService, fake_slack: FakeSlack
) -> None:
    work_date = date(2026, 7, 6)
    first_answers = {
        "yesterday": "Implemented the authentication flow.",
        "today": "Setting up deployment and monitoring.",
        "blockers": "none",
    }
    second_answers = {
        "yesterday": "Implemented the authentication flow and tests.",
        "today": "Setting up deployment and monitoring.",
        "blockers": "No blockers",
    }

    result = service.submit_daily(user_id="U1", answers=first_answers, work_date=work_date)
    assert result.published
    assert result.entry.daily_channel_message_ts is not None

    daily_posts = [message for message in fake_slack.posted if message["channel"] == "CDAILY"]
    assert len(daily_posts) == 1
    title_prefix = f"{REPORT_TITLE_EMOJI} " if REPORT_TITLE_EMOJI else ""
    assert daily_posts[0]["blocks"][0]["text"]["text"] == (
        f"{title_prefix}*<@U1> Daily, July 6, 2026*"
    )
    assert daily_posts[0]["blocks"][1]["text"]["text"].startswith(
        ":white_check_mark: *Completed since the previous workday*"
    )
    assert daily_posts[0]["blocks"][2]["text"]["text"].startswith(":dart: *Working on today*")
    report_text = "\n".join(block["text"]["text"] for block in daily_posts[0]["blocks"])
    assert "Blockers" not in report_text
    assert "No blockers" not in report_text

    result = service.submit_daily(user_id="U1", answers=second_answers, work_date=work_date)
    assert result.published

    daily_posts = [message for message in fake_slack.posted if message["channel"] == "CDAILY"]
    daily_updates = [message for message in fake_slack.updated if message["channel"] == "CDAILY"]
    assert len(daily_posts) == 1
    assert len(daily_updates) == 1
    assert daily_updates[0]["ts"] == daily_posts[0]["ts"]
    assert daily_updates[0]["blocks"][0]["text"]["text"].startswith(f"{title_prefix}*<@U1> Daily")


def test_excluded_user_cannot_submit_even_with_stale_modal(
    database: Database, fake_slack: FakeSlack
) -> None:
    service = DailyService(
        config=make_config({"audience": {"exclude_user_ids": ["U1"]}}),
        database=database,
        slack=fake_slack,
    )

    try:
        service.submit_daily(
            user_id="U1",
            answers={"yesterday": "Done", "today": "Deploy", "blockers": "No blockers"},
            work_date=date(2026, 7, 6),
        )
    except PermissionError:
        pass
    else:
        raise AssertionError("Excluded user submission should be rejected.")

    assert service.database.get_daily_entry("2026-07-06", "U1") is None
    assert not [message for message in fake_slack.posted if message["channel"] == "CDAILY"]


def test_message_not_found_posts_replacement_report(
    service: DailyService, fake_slack: FakeSlack
) -> None:
    work_date = date(2026, 7, 6)
    first_answers = {"yesterday": "Done", "today": "Deploy", "blockers": "No blockers"}
    second_answers = {"yesterday": "Really done", "today": "Deploy", "blockers": "No blockers"}

    first_result = service.submit_daily(user_id="U1", answers=first_answers, work_date=work_date)
    old_ts = first_result.entry.daily_channel_message_ts
    fake_slack.fail_next_updates_with_message_not_found = 1

    second_result = service.submit_daily(user_id="U1", answers=second_answers, work_date=work_date)

    daily_posts = [message for message in fake_slack.posted if message["channel"] == "CDAILY"]
    update_calls = [method for method, _kwargs in fake_slack.calls if method == "chat_update"]
    assert second_result.published
    assert len(update_calls) == 1
    assert len(daily_posts) == 2
    assert second_result.entry.daily_channel_message_ts != old_ts
    assert second_result.entry.daily_channel_message_ts == daily_posts[-1]["ts"]


def test_deleted_prompt_confirmation_message_posts_private_fallback(
    service: DailyService, fake_slack: FakeSlack
) -> None:
    work_date = date(2026, 7, 6)
    employee = service.eligible_employees()[0]
    assert service.send_prompt(employee, work_date)
    fake_slack.fail_next_updates_with_message_not_found = 1

    result = service.submit_daily(
        user_id="U1",
        answers={"yesterday": "Done", "today": "Deploy", "blockers": "No blockers"},
        work_date=work_date,
    )

    assert result.published
    dm_posts = [message for message in fake_slack.posted if message["channel"] == "DU1"]
    assert len(dm_posts) == 2
    assert dm_posts[-1]["text"] == "Your daily was submitted and posted."


def test_pending_report_retry_after_post_failure(
    service: DailyService, fake_slack: FakeSlack
) -> None:
    fake_slack.fail_next_daily_posts = 1
    work_date = date(2026, 7, 6)
    answers = {"yesterday": "Done", "today": "Deploy", "blockers": "No blockers"}

    result = service.submit_daily(user_id="U1", answers=answers, work_date=work_date)
    assert not result.published
    assert result.entry.report_status == "pending"

    assert service.retry_pending_reports() == 1
    entry = service.database.get_daily_entry(work_date.isoformat(), "U1")
    assert entry is not None
    assert entry.report_status == "posted"


def test_final_status_counts_only_waiting_eligible_users(service: DailyService) -> None:
    work_date = date(2026, 7, 6)
    service.submit_daily(
        user_id="U1",
        answers={"yesterday": "Done", "today": "Deploy", "blockers": "No blockers"},
        work_date=work_date,
    )

    status = service.final_status(work_date=work_date)
    assert status.eligible_count == 2
    assert status.submitted_count == 1
    assert [employee.user_id for employee in status.waiting] == ["U2"]
    assert "Daily status: 1 of 2 submitted." in service.final_status_text(work_date=work_date)
    assert "- <@U2>" in service.final_status_text(work_date=work_date)


def test_manual_daily_modal_is_prepopulated(database: Database, fake_slack: FakeSlack) -> None:
    service = DailyService(
        config=make_config(),
        database=database,
        slack=fake_slack,
        clock=lambda: datetime(2026, 7, 6, 9, 30, tzinfo=ZoneInfo("Asia/Tehran")),
    )
    service.submit_daily(
        user_id="U1",
        answers={"yesterday": "Done", "today": "Deploy", "blockers": "No blockers"},
        work_date=date(2026, 7, 6),
    )

    assert service.open_daily_modal(user_id="U1", trigger_id="trigger", work_date=date(2026, 7, 6))
    view = fake_slack.views[-1]["view"]
    first_input = view["blocks"][0]["element"]
    assert first_input["initial_value"] == "Done"
