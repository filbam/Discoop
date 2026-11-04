"""Anonymized threads and a fake `threads/search` for tests.

Shapes follow docs/analyses/discord-analysis.md (section 6). Names and IDs are made up.
"""

from datetime import datetime, timedelta
from typing import Any

import httpx

from discoop.snowflake import from_time
from fake_messages import FIT, USER_A

PARENT = "300"  # the forum or text channel the threads belong to


def thread(
    last: datetime,
    *,
    created: datetime | None = None,
    seq: int = 0,
    parent_id: str = PARENT,
    archived: bool = True,
    **fields: Any,
) -> dict:
    """A raw thread as `threads/search` gives it.

    The ID encodes `created` (default: an hour before `last`) and `last_message_id` encodes `last`, like real
    snowflakes. `seq` keeps IDs apart when times are equal. Times must be whole seconds to compare exactly.
    """
    created = created or last - timedelta(hours=1)
    data: dict[str, Any] = {
        "id": str(from_time(created) | seq),
        "type": 11,
        "guild_id": FIT,
        "parent_id": parent_id,
        "name": f"thread {seq}",
        "owner_id": USER_A["id"],
        "last_message_id": str(from_time(last) | seq),
        "message_count": 3,
        "total_message_sent": 4,
        "member_count": 2,
        "rate_limit_per_user": 0,
        "flags": 0,
        "applied_tags": [],
        "thread_metadata": {
            "archived": archived,
            "auto_archive_duration": 4320,
            "archive_timestamp": last.isoformat(),
            "create_timestamp": created.isoformat(),
            "locked": False,
            "invitable": True,
        },
    }
    data.update(fields)
    return data


def series(count: int, *, newest: datetime, step: timedelta, archived: bool = True, first_seq: int = 0) -> list[dict]:
    """`count` threads, the newest last active at `newest`, then one every `step` back in time (newest first)."""
    return [
        thread(newest - i * step, seq=first_seq + i, archived=archived, name=f"thread {first_seq + i}")
        for i in range(count)
    ]


class FakeThreadSearch:
    """Answers `GET /channels/{parent}/threads/search` from the given threads, served in the given order.

    Paging follows the real thing: `offset` and `limit`, `has_more`, `total_results`. The switches make it
    misbehave in the ways the fetching must survive.
    """

    def __init__(self, threads: list[dict]) -> None:
        self.threads = threads
        self.requests: list[dict[str, str]] = []
        self.status: int | tuple[int, int] | None = None  # forced for every request (and a JSON error code)
        self.status_at: dict[int, int] = {}  # forced for single requests, by their number (1 is the first)
        self.body: Any = None  # answered with status 200 instead of a page
        self.raw: bytes | None = None  # answered as a 200 that is not JSON
        self.overlap = 0  # every page starts this many threads early, so it repeats the end of the one before
        self.always_has_more = False  # `has_more` is true even after the last thread
        self.never_has_more = False  # `has_more` is false although more threads follow
        self.total_results: int | None = None  # a count that differs from the truth
        self.omit_has_more = False  # no `has_more` key
        self.ignore_offset = False  # always the first page

    def respond(self, request: httpx.Request) -> httpx.Response:
        params = dict(request.url.params)
        self.requests.append(params)
        number = len(self.requests)
        forced = self.status_at.get(number, self.status)
        if forced is not None:
            status, code = forced if isinstance(forced, tuple) else (forced, {403: 50001, 404: 10003}.get(forced, 0))
            return httpx.Response(status, json={"message": "forced", "code": code})
        if self.raw is not None:
            return httpx.Response(200, content=self.raw)
        if self.body is not None:
            return httpx.Response(200, json=self.body)
        if int(params["limit"]) > 25:  # verified: limit=50 gives 400, Invalid Form Body
            return httpx.Response(400, json={"message": "Invalid Form Body", "code": 50035})
        archived = params["archived"] == "true"
        matching = [t for t in self.threads if t["thread_metadata"]["archived"] == archived]
        offset = 0 if self.ignore_offset else max(int(params.get("offset", "0")) - self.overlap, 0)
        page = matching[offset : offset + int(params["limit"])]
        answer: dict[str, Any] = {
            "threads": page,
            "members": [],
            "total_results": len(matching) if self.total_results is None else self.total_results,
            "first_messages": [],
        }
        if not self.omit_has_more:
            more = self.always_has_more or offset + len(page) < len(matching)
            answer["has_more"] = more and not self.never_has_more
        return httpx.Response(200, json=answer)

    def handler(self, parent_id: str = PARENT):
        """A transport handler that also checks the method and the path."""

        def handle(request: httpx.Request) -> httpx.Response:
            assert request.method == "GET"
            assert request.url.path == f"/api/v9/channels/{parent_id}/threads/search"
            return self.respond(request)

        return handle
