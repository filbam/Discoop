"""Paging through a channel's messages, newest first, inside a time window.

Verified behaviour (docs/analyzy/discord-analyza.md, sections 4, 11 and 15):
- `GET /channels/{id}/messages?before=X&limit=N` returns up to N messages older than X, newest first,
- `limit` is at most 100 (101 gives 400),
- fewer messages than asked for means the start of the channel's history.

Errors (assumed, docs/analyzy/pristup-ku-kanalom.md, section 7): 403 with code 50001/50013 is missing access,
other 403 codes are blocks, 404 is an unknown channel. Without Read Message History Discord answers `[]`.
"""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from discoop.api import BLOCKED_HINT, DiscordAPI, error_details, is_missing_access, raise_for_status
from discoop.errors import DiscoopError, ExitCode
from discoop.models import REGULAR_MESSAGE_TYPES
from discoop.snowflake import Window

PAGE_SIZE = 100


@dataclass
class Fetched:
    messages: list[dict[str, Any]]  # oldest first
    hit_limit: bool  # stopped at `limit` with more messages left in the window
    requests: int
    nothing_before_end: bool = False  # the first page was empty: no readable message older than the window end


def is_system(message: dict[str, Any]) -> bool:
    return int(message.get("type", 0)) not in REGULAR_MESSAGE_TYPES


def fetch_messages(
    api: DiscordAPI,
    channel_id: str,
    window: Window,
    *,
    label: str,
    limit: int | None = None,
    page_size: int | None = None,
    include_system: bool = False,
    on_page: Callable[[int, int], None] | None = None,
) -> Fetched:
    """The newest `limit` messages (or all) with window.start <= time < window.end, oldest first.

    `label` names the channel in errors. `on_page(kept, oldest_id)` reports progress after each request.
    """
    lowest = window.after_id
    cursor = window.before_id
    kept: list[dict[str, Any]] = []
    requests = 0
    page_limit = page_size or getattr(api, "page_size", PAGE_SIZE)
    while True:
        # One extra message tells whether more exist after the limit is reached.
        size = page_limit if limit is None else min(page_limit, limit - len(kept) + 1)
        page = _get_page(api, channel_id, cursor, size, label)
        requests += 1
        if not page and requests == 1:
            return Fetched([], False, requests, nothing_before_end=True)
        page.sort(key=lambda m: int(m["id"]), reverse=True)
        inside = [m for m in page if lowest is None or int(m["id"]) >= lowest]
        wanted = [m for m in inside if include_system or not is_system(m)]
        if limit is not None and len(kept) + len(wanted) > limit:
            kept += wanted[: limit - len(kept)]
            return Fetched(kept[::-1], True, requests)
        kept += wanted
        if limit is not None and len(kept) == limit and len(inside) == len(page) == size:
            # Exactly at the limit with a full page: older messages may still be in the window.
            return Fetched(kept[::-1], True, requests)
        if not page or len(page) < size or len(inside) < len(page) or (limit is not None and len(kept) >= limit):
            return Fetched(kept[::-1], False, requests)
        cursor = int(page[-1]["id"])
        if on_page:
            on_page(len(kept), cursor)


def _get_page(api: DiscordAPI, channel_id: str, before: int, limit: int, label: str) -> list[dict[str, Any]]:
    response = api.request("GET", f"/channels/{channel_id}/messages", params={"before": str(before), "limit": limit})
    if is_missing_access(response):
        raise DiscoopError(
            ExitCode.NO_ACCESS,
            f"No access to the messages of {label}.",
            "Discord lists channels you cannot read too. Check that you can open it in Discord.",
        )
    if response.status_code == 403:
        # Another 403 code (10008 anti-abuse, 40333 Cloudflare, ...) is a block, not missing access.
        code, detail = error_details(response)
        reason = f"code {code}" if code is not None else "no error code"
        raise DiscoopError(
            ExitCode.ERROR, f"Discord refused to read {label} (403, {reason}): {detail or 'no message'}.", BLOCKED_HINT
        )
    if response.status_code == 404:
        raise DiscoopError(
            ExitCode.NOT_FOUND,
            f"Discord does not know {label}.",
            "It may have been deleted: run `discoop channels --refresh`.",
        )
    raise_for_status(response)
    data = response.json()
    if not isinstance(data, list):
        raise DiscoopError(ExitCode.ERROR, f"Unexpected answer from Discord for {label}: not a list of messages.")
    return data
