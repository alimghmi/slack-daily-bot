FROM ghcr.io/astral-sh/uv:0.5.31-python3.12-bookworm-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_LINK_MODE=copy

WORKDIR /app

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY dailybot ./dailybot
COPY README.md ./
RUN uv sync --frozen --no-dev

RUN useradd --create-home --shell /usr/sbin/nologin --uid 10001 dailybot \
    && mkdir -p /app/data \
    && chown -R dailybot:dailybot /app

USER dailybot

HEALTHCHECK --interval=30s --timeout=10s --start-period=20s --retries=3 \
    CMD ["/app/.venv/bin/python", "-m", "dailybot", "healthcheck"]

CMD ["/app/.venv/bin/python", "-m", "dailybot"]
