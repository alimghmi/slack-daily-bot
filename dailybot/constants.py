ACTION_SUBMIT_DAILY = "dailybot_submit_daily"
ANSWER_ACTION_ID = "dailybot_answer"
VIEW_CALLBACK_DAILY = "dailybot_daily_submission"

DEFAULT_QUESTION_HEADINGS = {
    "yesterday": "Completed since the previous workday",
    "today": "Working on today",
    "blockers": "Blockers",
}

REPORT_TITLE_EMOJI = ""  # ":sunny:"

REPORT_SECTION_EMOJIS = {
    "yesterday": ":white_check_mark:",
    "today": ":dart:",
    "blockers": ":construction:",
}

NO_BLOCKERS_VALUES = {
    "no",
    "none",
    "n/a",
    "na",
    "no blockers",
    "nothing",
    "not blocked",
}

SLACK_INPUT_MAX_LENGTH = 3000
