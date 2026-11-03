"""Anonymized Discord messages, a fake Discord API and a fake CDN for tests.

Shapes follow docs/analyzy/discord-analyza.md (sections 4, 5, 15). Names, texts and files are made up.
"""

import json
from collections import Counter
from datetime import UTC, datetime, timedelta, timezone
from typing import Any

import httpx

from discoop.snowflake import from_time

NOW = datetime(2026, 11, 3, 11, 0, tzinfo=UTC)  # 12:00 in the test zone (UTC+01:00)
CET = timezone(timedelta(hours=1))

USER_A = {"id": "900000000000000001", "username": "student_a", "global_name": "Student A", "discriminator": "0"}
USER_B = {"id": "900000000000000002", "username": "student_b", "global_name": None, "discriminator": "0"}
BOT = {"id": "900000000000000003", "username": "fit_bot", "global_name": None, "bot": True}

FIT = "461541385204400138"
GUILDS = [{"id": FIT, "name": "VUT FIT", "approximate_member_count": 5000}]
CHANNELS = [
    {"id": "100", "type": 4, "name": "general", "position": 1},
    {"id": "200", "type": 0, "name": "2bit-general", "parent_id": "100", "position": 0},
    {"id": "202", "type": 0, "name": "2bit-terminy", "parent_id": "100", "position": 1},
    {"id": "203", "type": 0, "name": "general", "parent_id": "100", "position": 2},
    {"id": "204", "type": 15, "name": "help-center", "position": 3},
    {"id": "205", "type": 5, "name": "2bit-info", "parent_id": "100", "position": 4},
]
ERROR_CODES = {401: 0, 403: 50001, 404: 10003}  # Missing Access, Unknown Channel
CDN = "https://cdn.discordapp.com"


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


def signed_url(channel_id: str, attachment_id: str, filename: str, *, expires: datetime, signature: str = "a1") -> str:
    """A CDN URL like Discord's: `ex`/`is` are hex unix seconds, `is` 24 h before `ex`, ending with `&`."""
    ex = int(expires.timestamp())
    return f"{CDN}/attachments/{channel_id}/{attachment_id}/{filename}?ex={ex:x}&is={ex - 86400:x}&hm={signature}&"


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


class FakeDiscord:
    """The API part: servers, channels, messages and `POST /attachments/refresh-urls`."""

    def __init__(self, channels: dict[str, FakeChannel] | None = None) -> None:
        self.calls: Counter = Counter()
        self.channels = channels or {}
        self.status: dict[str, int | tuple[int, int]] = {}  # channel ID -> forced status (and JSON error code)
        self.refresh_batches: list[list[str]] = []
        self.refresh_status = 200
        self.refreshed: dict[str, str] = {}  # what the next refresh answers per original URL; default: re-signed

    def handle(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path.removeprefix("/api/v9")
        self.calls[path] += 1
        if path == "/users/@me/guilds":
            return httpx.Response(200, json=GUILDS)
        if path == f"/guilds/{FIT}/channels":
            return httpx.Response(200, json=CHANNELS)
        if path == "/attachments/refresh-urls" and request.method == "POST":
            return self._refresh(request)
        parts = path.strip("/").split("/")
        if parts[0] == "channels":
            channel_id = parts[1]
            if channel_id in self.status:
                forced = self.status[channel_id]
                status, code = forced if isinstance(forced, tuple) else (forced, ERROR_CODES[forced])
                return httpx.Response(status, json={"message": "error", "code": code})
            if len(parts) == 2:
                known = next((c for c in CHANNELS if c["id"] == channel_id), None)
                if known:
                    return httpx.Response(200, json={**known, "guild_id": FIT})
                return httpx.Response(404, json={"message": "Unknown Channel", "code": 10003})
            if parts[2] == "messages" and channel_id in self.channels:
                return self.channels[channel_id].respond(request)
        return httpx.Response(404, json={"message": "Unknown Channel", "code": 10003})

    def _refresh(self, request: httpx.Request) -> httpx.Response:
        urls = json.loads(request.content)["attachment_urls"]
        self.refresh_batches.append(urls)
        if self.refresh_status != 200:
            return httpx.Response(self.refresh_status, json={"message": "error", "code": 0})
        pairs = [{"original": url, "refreshed": self.refreshed.get(url, resign(url))} for url in urls]
        return httpx.Response(200, json={"refreshed_urls": pairs})


def resign(url: str) -> str:
    """The URL with a fresh signature, valid 24 h after NOW, as refresh-urls gives it."""
    parsed = httpx.URL(url)
    ex = int((NOW + timedelta(hours=24)).timestamp())
    return f"{CDN}{parsed.path}?ex={ex:x}&is={ex - 86400:x}&hm=fresh&"


class FakeCDN:
    """Files by URL path. Rejects expired signatures (403) and the signatures in `revoked`, like the real CDN."""

    def __init__(self) -> None:
        self.files: dict[str, bytes] = {}
        self.revoked: set[str] = set()  # signatures (hm) the CDN refuses
        self.missing: set[str] = set()  # paths that always give 404
        self.flaky: Counter = Counter()  # path -> number of 503 answers before the file comes
        self.requests: list[httpx.Request] = []

    def add(self, url: str, content: bytes) -> None:
        self.files[httpx.URL(url).path] = content

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        path, params = request.url.path, request.url.params
        if path in self.missing or path not in self.files:
            return httpx.Response(404, text="Not Found")
        if self.flaky[path]:
            self.flaky[path] -= 1
            return httpx.Response(503, text="Service Unavailable")
        expired = "ex" in params and int(params["ex"], 16) <= NOW.timestamp()
        if expired or params.get("hm") in self.revoked:
            return httpx.Response(403, text="This content is no longer available.")
        return httpx.Response(200, content=self.files[path])


class Network:
    """One transport for the API and the CDN that logs every request, to check where the token goes."""

    def __init__(self, discord: FakeDiscord, cdn: FakeCDN) -> None:
        self.discord = discord
        self.cdn = cdn
        self.log: list[httpx.Request] = []

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.log.append(request)
        if request.url.host == "discord.com":
            return self.discord.handle(request)
        if request.url.host in ("cdn.discordapp.com", "media.discordapp.net"):
            return self.cdn.handle(request)
        raise AssertionError(f"unexpected host {request.url.host}")
