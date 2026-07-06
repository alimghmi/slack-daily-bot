from __future__ import annotations

from typing import Any

from dailybot.slack_client import RetryingSlackClient


class FakeRateLimitError(Exception):
    status_code = 429
    retry_after = 0


class FlakyWebClient:
    def __init__(self) -> None:
        self.calls = 0

    def chat_postMessage(self, **kwargs: Any) -> dict[str, Any]:
        self.calls += 1
        if self.calls == 1:
            raise FakeRateLimitError
        return {"ok": True, "ts": "1.000000", **kwargs}


class SlackResponseLike:
    def __init__(self, data: dict[str, Any]) -> None:
        self.data = data

    def __iter__(self) -> Any:
        return iter(self.data)


class SlackResponseWebClient:
    def users_info(self, **_kwargs: Any) -> SlackResponseLike:
        return SlackResponseLike({"ok": True, "user": {"id": "U123", "name": "ali"}})


def test_retrying_slack_client_respects_rate_limit_retry() -> None:
    sleeps: list[float] = []
    web_client = FlakyWebClient()
    client = RetryingSlackClient(web_client, sleeper=sleeps.append)

    response = client.call("chat_postMessage", channel="C1", text="hello")

    assert response["ok"] is True
    assert web_client.calls == 2
    assert sleeps == [0.0]


def test_retrying_slack_client_reads_slack_response_data() -> None:
    client = RetryingSlackClient(SlackResponseWebClient())

    response = client.call("users_info", user="U123")

    assert response == {"ok": True, "user": {"id": "U123", "name": "ali"}}
