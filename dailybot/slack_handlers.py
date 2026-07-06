from __future__ import annotations

import json
import logging
from datetime import date
from typing import Any

from dailybot.constants import ACTION_SUBMIT_DAILY, ANSWER_ACTION_ID, VIEW_CALLBACK_DAILY
from dailybot.service import DailyService

logger = logging.getLogger(__name__)


def register_handlers(app: Any, service: DailyService) -> None:
    @app.action(ACTION_SUBMIT_DAILY)
    def handle_submit_daily_button(ack: Any, body: dict[str, Any]) -> None:
        ack()
        user_id = body["user"]["id"]
        work_date = _work_date_from_action(body) or service.current_work_date()
        opened = service.open_daily_modal(
            user_id=user_id,
            trigger_id=body["trigger_id"],
            work_date=work_date,
        )
        if not opened:
            logger.info(
                "Ignoring daily modal request for ineligible user",
                extra={"user_id": user_id},
            )

    @app.view(VIEW_CALLBACK_DAILY)
    def handle_daily_submission(ack: Any, body: dict[str, Any], view: dict[str, Any]) -> None:
        metadata = _metadata_from_view(view)
        user_id = metadata.get("user_id") or body["user"]["id"]
        work_date = date.fromisoformat(metadata["work_date"])
        answers = extract_answers(view)
        errors = service.validate_answers(answers)
        if errors:
            ack(response_action="errors", errors=errors)
            return

        ack()
        service.submit_daily(user_id=user_id, answers=answers, work_date=work_date)

    @app.command("/daily-now")
    def daily_now(ack: Any, body: dict[str, Any], respond: Any) -> None:
        ack()
        user_id = body["user_id"]
        if not service.is_admin(user_id):
            respond("Only configured daily bot admins can run this command.")
            return
        count = service.send_daily_prompts(force=True)
        respond(f"Sent today's daily prompt to {count} eligible employee(s).")

    @app.command("/daily-status")
    def daily_status(ack: Any, body: dict[str, Any], respond: Any) -> None:
        ack()
        user_id = body["user_id"]
        if not service.is_admin(user_id):
            respond("Only configured daily bot admins can run this command.")
            return
        respond(service.final_status_text())

    @app.command("/daily-final-status")
    def daily_final_status(ack: Any, body: dict[str, Any], respond: Any) -> None:
        ack()
        user_id = body["user_id"]
        if not service.is_admin(user_id):
            respond("Only configured daily bot admins can run this command.")
            return
        posted = service.post_final_status(force=True)
        respond("Posted the final daily status." if posted else "Final status was not posted.")

    @app.command("/daily-me")
    def daily_me(ack: Any, body: dict[str, Any], respond: Any) -> None:
        ack()
        opened = service.open_daily_modal(user_id=body["user_id"], trigger_id=body["trigger_id"])
        if not opened:
            respond("You are not eligible to submit a daily in this bot configuration.")


def extract_answers(view: dict[str, Any]) -> dict[str, str]:
    values = (view.get("state") or {}).get("values") or {}
    answers = {}
    for block_id, action_map in values.items():
        answer_payload = action_map.get(ANSWER_ACTION_ID)
        if answer_payload is None and action_map:
            answer_payload = next(iter(action_map.values()))
        answers[block_id] = str((answer_payload or {}).get("value") or "")
    return answers


def _work_date_from_action(body: dict[str, Any]) -> date | None:
    actions = body.get("actions") or []
    if not actions:
        return None
    try:
        payload = json.loads(actions[0].get("value") or "{}")
        return date.fromisoformat(payload["work_date"])
    except (KeyError, TypeError, ValueError, json.JSONDecodeError):
        return None


def _metadata_from_view(view: dict[str, Any]) -> dict[str, str]:
    try:
        metadata = json.loads(view.get("private_metadata") or "{}")
    except json.JSONDecodeError as exc:
        raise ValueError("Daily modal metadata was invalid JSON.") from exc
    if "work_date" not in metadata:
        raise ValueError("Daily modal metadata did not include work_date.")
    return metadata
