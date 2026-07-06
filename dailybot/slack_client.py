from __future__ import annotations

import logging
import time
from collections.abc import Callable
from typing import Any

try:
    from slack_sdk.errors import SlackApiError
except Exception:  # pragma: no cover - only used when slack-sdk is unavailable
    SlackApiError = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)


class RetryingSlackClient:
    def __init__(
        self,
        web_client: Any,
        *,
        max_attempts: int = 3,
        sleeper: Callable[[float], None] = time.sleep,
    ) -> None:
        self.web_client = web_client
        self.max_attempts = max_attempts
        self.sleeper = sleeper

    def call(self, method: str, **kwargs: Any) -> dict[str, Any]:
        attempt = 1
        while True:
            try:
                response = getattr(self.web_client, method)(**kwargs)
                return _response_to_dict(response)
            except Exception as exc:
                if not self._is_retryable_rate_limit(exc) or attempt >= self.max_attempts:
                    raise
                retry_after = self._retry_after(exc)
                logger.warning(
                    "Slack rate limited request; retrying",
                    extra={"method": method, "attempt": attempt, "retry_after": retry_after},
                )
                self.sleeper(retry_after)
                attempt += 1

    def _is_retryable_rate_limit(self, exc: Exception) -> bool:
        if getattr(exc, "status_code", None) == 429:
            return True
        if SlackApiError is not None and isinstance(exc, SlackApiError):
            response = getattr(exc, "response", None)
            return getattr(response, "status_code", None) == 429
        response = getattr(exc, "response", None)
        return getattr(response, "status_code", None) == 429

    def _retry_after(self, exc: Exception) -> float:
        explicit = getattr(exc, "retry_after", None)
        if explicit is not None:
            return float(explicit)

        response = getattr(exc, "response", None)
        headers = getattr(response, "headers", {}) or {}
        retry_after = headers.get("Retry-After") or headers.get("retry-after") or 1
        try:
            return float(retry_after)
        except (TypeError, ValueError):
            return 1.0


def _response_to_dict(response: Any) -> dict[str, Any]:
    data = getattr(response, "data", None)
    if isinstance(data, dict):
        return dict(data)
    if isinstance(response, dict):
        return dict(response)
    return dict(response)
