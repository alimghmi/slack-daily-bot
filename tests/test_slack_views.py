from __future__ import annotations

from conftest import make_config

from dailybot.models import DailyEntry
from dailybot.slack_views import report_blocks


def test_report_blocks_escape_user_supplied_mentions() -> None:
    entry = DailyEntry(
        work_date="2026-07-06",
        user_id="U1",
        display_name="Ali",
        answers={
            "yesterday": "Shipped <@U999> and @channel notes",
            "today": "Review <!here> and @here pings",
            "blockers": "Need <!subteam^S123> help",
        },
        submitted_at="2026-07-06T08:00:00+03:30",
        updated_at="2026-07-06T08:00:00+03:30",
        daily_channel_id=None,
        daily_channel_message_ts=None,
        report_status="pending",
        report_error=None,
    )

    text = "\n".join(
        block["text"]["text"] for block in report_blocks(make_config(), entry) if "text" in block
    )

    assert "<@U999>" not in text
    assert "<!here>" not in text
    assert "<!subteam^S123>" not in text
    assert "&lt;@U999&gt;" in text
    assert "&lt;!here&gt;" in text
    assert "&lt;!subteam^S123&gt;" in text
    assert "@\u200bchannel" in text
    assert "@\u200bhere" in text
