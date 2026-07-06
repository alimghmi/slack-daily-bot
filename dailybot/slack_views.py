from __future__ import annotations

import calendar
import json
from datetime import date

from dailybot.config import AppConfig
from dailybot.constants import (
    ACTION_SUBMIT_DAILY,
    ANSWER_ACTION_ID,
    DEFAULT_QUESTION_HEADINGS,
    NO_BLOCKERS_VALUES,
    REPORT_SECTION_EMOJIS,
    REPORT_TITLE_EMOJI,
    SLACK_INPUT_MAX_LENGTH,
    VIEW_CALLBACK_DAILY,
)
from dailybot.models import DailyEntry


def format_report_date(work_date: date) -> str:
    return f"{calendar.month_name[work_date.month]} {work_date.day}, {work_date.year}"


def prompt_blocks(config: AppConfig, work_date: date, *, submitted: bool = False) -> list[dict]:
    status_text = (
        "Your daily is submitted. You can edit it for today." if submitted else config.daily.intro
    )
    return [
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"*{_escape(config.daily.title)}*\n{_escape(status_text)}",
            },
        },
        {
            "type": "context",
            "elements": [{"type": "mrkdwn", "text": _escape(format_report_date(work_date))}],
        },
        {
            "type": "actions",
            "elements": [
                {
                    "type": "button",
                    "text": {
                        "type": "plain_text",
                        "text": "Edit daily" if submitted else "Submit daily",
                    },
                    "style": "primary",
                    "action_id": ACTION_SUBMIT_DAILY,
                    "value": json.dumps({"work_date": work_date.isoformat()}),
                }
            ],
        },
    ]


def daily_modal_view(
    config: AppConfig,
    *,
    work_date: date,
    user_id: str,
    existing_answers: dict[str, str] | None = None,
) -> dict:
    existing_answers = existing_answers or {}
    blocks = []
    for key, question in config.daily.questions.items():
        element = {
            "type": "plain_text_input",
            "action_id": ANSWER_ACTION_ID,
            "multiline": True,
            "max_length": SLACK_INPUT_MAX_LENGTH,
        }
        if existing_answers.get(key):
            element["initial_value"] = existing_answers[key]
        blocks.append(
            {
                "type": "input",
                "block_id": key,
                "optional": False,
                "label": {"type": "plain_text", "text": question[:200]},
                "element": element,
            }
        )

    return {
        "type": "modal",
        "callback_id": VIEW_CALLBACK_DAILY,
        "title": {"type": "plain_text", "text": config.daily.title[:24]},
        "submit": {"type": "plain_text", "text": "Submit"},
        "close": {"type": "plain_text", "text": "Cancel"},
        "private_metadata": json.dumps({"work_date": work_date.isoformat(), "user_id": user_id}),
        "blocks": blocks,
    }


def report_blocks(config: AppConfig, entry: DailyEntry) -> list[dict]:
    formatted_date = format_report_date(entry.work_date_value)
    title_prefix = f"{REPORT_TITLE_EMOJI} " if REPORT_TITLE_EMOJI else ""
    blocks: list[dict] = [
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"{title_prefix}*<@{entry.user_id}> Daily, {formatted_date}*",
            },
        },
    ]

    for key, question in config.daily.questions.items():
        heading = DEFAULT_QUESTION_HEADINGS.get(key, question)
        answer = entry.answers.get(key, "").strip()
        if key.lower() == "blockers" and _has_no_blockers(answer):
            continue
        blocks.append(
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": _section_text(
                        heading,
                        answer or "No answer provided.",
                        emoji=REPORT_SECTION_EMOJIS.get(key),
                    ),
                },
            }
        )
    return blocks


def _has_no_blockers(answer: str) -> bool:
    return not answer.strip() or answer.strip().lower() in NO_BLOCKERS_VALUES


def report_fallback_text(entry: DailyEntry) -> str:
    return f"<@{entry.user_id}> Daily, {format_report_date(entry.work_date_value)}"


def final_status_blocks(status_text: str) -> list[dict]:
    return [{"type": "section", "text": {"type": "mrkdwn", "text": status_text}}]


def _section_text(heading: str, answer: str, *, emoji: str | None = None) -> str:
    prefix = f"{emoji} " if emoji else ""
    text = f"{prefix}*{_escape(heading)}*\n{_escape(answer)}"
    if len(text) <= 3000:
        return text
    return text[:2997] + "..."


def _escape(text: str) -> str:
    escaped = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    for token in ("@channel", "@here", "@everyone"):
        escaped = escaped.replace(token, token.replace("@", "@\u200b"))
    return escaped
