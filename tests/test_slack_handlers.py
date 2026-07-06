from __future__ import annotations

from dailybot.constants import ANSWER_ACTION_ID
from dailybot.slack_handlers import extract_answers, submission_context


def test_submission_context_ignores_private_metadata_user_id() -> None:
    body = {"user": {"id": "UREAL"}}
    view = {"private_metadata": '{"work_date": "2026-07-06", "user_id": "UVICTIM"}'}

    user_id, work_date = submission_context(body, view)

    assert user_id == "UREAL"
    assert work_date.isoformat() == "2026-07-06"


def test_extract_answers_requires_expected_action_id() -> None:
    view = {
        "state": {
            "values": {
                "yesterday": {ANSWER_ACTION_ID: {"value": "Done"}},
                "today": {"unexpected_action": {"value": "Tampered"}},
            }
        }
    }

    assert extract_answers(view) == {"yesterday": "Done", "today": ""}
