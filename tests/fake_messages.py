"""Anonymized Discord messages and a fake `/channels/{id}/messages` endpoint for tests.

Shapes follow docs/analyzy/discord-analyza.md (sections 4, 5, 15). Names and texts are made up.
"""

from datetime import UTC, datetime, timedelta
from typing import Any

import httpx

from discoop.snowflake import from_time

NOW = datetime(2026, 11, 3, 11, 0, tzinfo=UTC)  # 12:00 in the test zone (UTC+01:00)

USER_A = {"id": "900000000000000001", "username": "student_a", "global_name": "Student A", "discriminator": "0"}
USER_B = {"id": "900000000000000002", "username": "student_b", "global_name": None, "discriminator": "0"}
BOT = {"id": "900000000000000003", "username": "fit_bot", "global_name": None, "bot": True}


def message(when: datetime, content: str = "", *, seq: int = 0, author: dict | None = None, **fields: Any) -> dict:
    """A raw message as Discord sends it; the ID encodes `when` like a real snowflake."""
    data: dict[str, Any] = {
        "id": str(from_time(when) | seq),
        "type": 0,
        "channel_id": "200",
        "content": content,
        "author": author or USER_A,
        "timestamp": when.isoformat(),
        "edited_timestamp": None,
        "attachments": [],
        "embeds": [],
        "mentions": [],
        "mention_roles": [],
        "pinned": False,
        "flags": 0,
        "components": [],
    }
    data.update(fields)
    return data


def series(count: int, *, newest: datetime, step: timedelta) -> list[dict]:
    """`count` messages, the newest at `newest`, then one every `step` back in time."""
    return [message(newest - i * step, f"message {i}") for i in range(count)]


class FakeChannel:
    """Answers `GET /channels/{id}/messages?before=&limit=` like Discord: newest first, at most `limit`."""

    def __init__(self, messages: list[dict]) -> None:
        self.messages = sorted(messages, key=lambda m: int(m["id"]), reverse=True)
        self.requests: list[dict[str, str]] = []

    def respond(self, request: httpx.Request) -> httpx.Response:
        params = dict(request.url.params)
        self.requests.append(params)
        limit = int(params.get("limit", "50"))
        if not 1 <= limit <= 100:
            return httpx.Response(400, json={"message": "Invalid Form Body", "code": 50035})
        before = int(params["before"]) if "before" in params else None
        older = [m for m in self.messages if before is None or int(m["id"]) < before]
        return httpx.Response(200, json=older[:limit])
