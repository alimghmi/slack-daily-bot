# Slack Daily Bot

Self-hosted Slack Socket Mode bot for collecting daily standup updates and immediately posting each submitted report to a configured daily channel.

The bot does not expose an HTTP port. Slack sends interactivity, modals, and slash commands through Socket Mode.

## What It Does

- Sends each eligible employee a private daily prompt on configured workdays.
- Opens a configurable Slack modal from the `Submit daily` button or `/daily-me`.
- Stores responses in SQLite with a unique `work_date + Slack user ID` key.
- Posts each employee report immediately to the configured daily channel.
- Uses `<@SLACK_USER_ID>` in the report title so the employee receives a real Slack mention notification.
- Updates the existing report with `chat.update` when the employee edits the same workday.
- Sends one reminder per employee per workday and survives restarts without duplicate prompts or reports.

## Slack App Setup

1. Go to `api.slack.com/apps` and create an app from `slack-app-manifest.yml`.
2. Keep Socket Mode enabled.
3. Keep Interactivity enabled.
4. Create a bot token from **OAuth & Permissions** after installing the app.
5. Create an app-level token from **Basic Information > App-Level Tokens** with `connections:write`; this is the `SLACK_APP_TOKEN`.
6. Required bot scopes are:
   - `chat:write`
   - `commands`
   - `im:write`
   - `users:read`
   - `users:read.email`
7. Install the app to the Otanami workspace.
8. Invite the bot to the configured daily channel with `/invite @Otanami Daily`.

Do not add channel history or private message history scopes.

## Finding IDs

Slack user IDs and channel IDs are required because display names and channel names can change.

- User ID: open a Slack profile, choose **More**, then **Copy member ID**.
- Channel ID: open channel details, scroll to the bottom, then copy the channel ID.

## Configuration

Create local files from the examples:

```bash
cp .env.example .env
cp config.example.yml config.yml
```

Set real values in `.env`:

```dotenv
SLACK_BOT_TOKEN=xoxb-...
SLACK_APP_TOKEN=xapp-...
DAILY_BOT_CONFIG=/app/config.yml
DAILY_BOT_DB=/app/data/daily.db
LOG_LEVEL=INFO
```

Set `channel.daily_channel_id` in `config.yml` to the Slack channel ID, not `#daily`.

Default workdays are Saturday through Wednesday in `Asia/Tehran`; Thursday and Friday are skipped. Add holidays with ISO dates:

```yaml
daily:
  skip_dates:
    - "2026-07-25"
```

By default, the bot prompts every active human workspace member. Use
`audience.exclude_user_ids` or `audience.exclude_emails` to skip specific people.

Use `admin.allowed_user_ids` for people who can run admin slash commands.

## Deploy

```bash
docker compose up -d --build
```

No ports are exposed. SQLite is stored in the `dailybot-data` Docker volume.

View logs:

```bash
docker compose logs -f dailybot
```

Restart after configuration changes:

```bash
docker compose restart dailybot
```

## Slash Commands

- `/daily-now`: admin-only; sends today's prompt immediately and bypasses scheduling restrictions.
- `/daily-status`: admin-only; shows eligible, submitted, and waiting users.
- `/daily-final-status`: admin-only; posts the final status message to the daily channel.
- `/daily-me`: available to eligible employees; opens today's daily form.

## SQLite Backups

With the container running:

```bash
docker compose exec dailybot sqlite3 /app/data/daily.db ".backup '/app/data/daily-backup.db'"
```

Then copy the backup out of the volume if needed.

## Development

Install dependencies and run checks with uv:

```bash
uv sync
uv run ruff check .
uv run pytest
docker compose config
```

## Security Notes

- Never commit `.env`, `config.yml`, or real Slack tokens.
- Store only Slack user IDs for mentions; never construct mentions from names.
- The report body escapes submitted answers so employee text cannot create broad Slack mentions.
- Keep the bot invited only to the daily channel it should post in.

## Troubleshooting

- `invalid_auth`: check `SLACK_BOT_TOKEN` and reinstall the Slack app if scopes changed.
- `not_in_channel`: invite the bot to the configured daily channel.
- Missing emails: confirm `users:read.email` is installed.
- Slash command does nothing: confirm Socket Mode is enabled and `SLACK_APP_TOKEN` has `connections:write`.
- Duplicate-looking prompts after manual testing: prompts are unique by work date and user; `/daily-now` still uses today's work date.
- SQLite lock warnings: keep a single bot container running against the database volume.
- Health check failing: verify `config.yml` is mounted and valid YAML.
