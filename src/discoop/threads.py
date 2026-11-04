"""Listing the threads and forum posts of a channel, newest activity first, inside a time window.

Source: `GET /channels/{parent_id}/threads/search?archived=true|false&sort_by=last_message_time&sort_order=desc
&limit=25&offset=N` (docs/analyzy/discord-analyza.md, sections 6 and 15; probe of 2026-11-04).

Verified [OVERENÉ]:
- it works with a user token for archived (`archived=true`) and active (`archived=false`) threads;
  `GET /guilds/{id}/threads/active` is for bots only (403, code 20002) and is not used,
- the answer has the keys `threads`, `members`, `has_more`, `total_results` and `first_messages`; a thread is a
  channel object with `id`, `type`, `name`, `parent_id`, `guild_id`, `owner_id`, `last_message_id`, `message_count`,
  `total_message_sent`, `member_count`, `rate_limit_per_user`, `flags`, `applied_tags` and `thread_metadata`
  (`archived`, `archive_timestamp`, `auto_archive_duration`, `create_timestamp`, `locked`),
- `limit=25` works; `limit=50` gives HTTP 400, code 50035 (Invalid Form Body), so the limit is always 25,
- `offset` paging works in steps of 25: 40 pages gave 1000 different threads and no duplicate, and offset 1808 of
  1833 results still returned a full page,
- `has_more` and `total_results` cannot be trusted. `has_more` was true on the last page (1808 + 25 = 1833), and
  an active search returned 12 threads with `total_results` 14 and `has_more` false. So neither ever decides
  anything here: `total_results` is only passed on as a rough progress hint,
- a text channel the user cannot read answers 403, code 50001 (Missing Access), like `scrape.fetch_messages`.

Not verified [PREDPOKLAD], the code tolerates every case:
- that text and announcement channels (not only forums) support `threads/search` for a user account,
- an HTTP 202 "not indexed yet" answer (known from message search; not seen in 53 requests): the listing stops and
  says so, no retry,
- private threads (type 12) and announcement threads (type 10): all 37 threads seen were public (type 11) and none
  was locked,
- that the sort key `last_message_time` is the time of `last_message_id`: the stop at the window start relies on it,
- the largest `offset` Discord accepts (1808 worked),
- that the client's extra parameter `tag_setting=match_some` is not needed: it is not sent and nothing failed.

A listing ends on exactly these: an empty page, a page shorter than the limit, a thread with its last activity before
the start of the window, or the hard page cap. Besides, it gives up on a page with no thread seen before (the
paging does not advance), on a 202 and on a body of the wrong shape, so a misbehaving answer cannot loop forever.
"""

import logging
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

import httpx

from discoop.api import BLOCKED_HINT, DiscordAPI, error_details, is_missing_access, raise_for_status
from discoop.errors import DiscoopError, ExitCode
from discoop.models import THREAD_CONTAINER_TYPES, Thread, thread_from_api
from discoop.snowflake import Window

logger = logging.getLogger("discoop.threads")

PAGE_SIZE = 25  # the only verified `limit`: 50 gives HTTP 400
MAX_PAGES = 200  # per kind of thread (active, archived): 5000 threads


class Stop(StrEnum):
    """Why a listing ended. The first two mean the list is complete for the window, the rest that it may not be."""

    END = "end"  # an empty page, or one shorter than the limit
    WINDOW = "window"  # reached threads whose last activity is before the start of the window
    PAGE_CAP = "page_cap"  # stopped at the page cap with results left
    NO_PROGRESS = "no_progress"  # a page without a single thread seen before: the paging does not advance
    NOT_INDEXED = "not_indexed"  # HTTP 202: Discord has not indexed the channel's threads yet [PREDPOKLAD]
    UNEXPECTED = "unexpected"  # not JSON, not an object, or no `threads` list


_PROBLEMS = {
    Stop.PAGE_CAP: "stopped at the page limit, older threads are missing",
    Stop.NO_PROGRESS: "Discord kept repeating the same threads, older threads may be missing",
    Stop.NOT_INDEXED: "Discord has not indexed the threads of this channel yet (HTTP 202)",
    Stop.UNEXPECTED: "Discord answered in a shape this tool does not know",
}


@dataclass
class FetchedThreads:
    threads: list[Thread]  # newest activity first, each thread once, only those that overlap the window
    requests: int  # API requests made; 0 for a list answered from the cache
    stop: Stop
    # Discord's own count, a rough progress hint only: it is not reliable (it was 14 for 12 threads).
    total_results: int | None = None

    @property
    def complete(self) -> bool:
        """False when the list may miss threads, see `problem`."""
        return self.stop in (Stop.END, Stop.WINDOW)

    @property
    def problem(self) -> str | None:
        """Why the list may be incomplete, for a warning; None if it is complete."""
        return _PROBLEMS.get(self.stop)


def is_thread_container(channel_type: int) -> bool:
    """Whether a channel of this type can have threads: text, announcement, forum and media channels.

    Forums (15) are verified. [PREDPOKLAD] for the others that `threads/search` answers for a user account.
    """
    return channel_type in THREAD_CONTAINER_TYPES


def in_window(thread: Thread, window: Window) -> bool:
    """Whether the thread was alive during the window: created before its end, active since its start."""
    if window.start is not None and thread.last_activity < window.start:
        return False
    return thread.created < window.end


def fetch_threads(
    api: DiscordAPI,
    parent_id: str,
    window: Window,
    *,
    archived: bool,
    label: str | None = None,
    max_pages: int = MAX_PAGES,
    on_page: Callable[[int, int], None] | None = None,
) -> FetchedThreads:
    """The archived (`archived=True`) or the active threads of a channel that overlap the window.

    Newest activity first, 25 per request. Paging stops at the first page that reaches a thread with its last
    activity before `window.start` (a thread without a known last message does not count: its time is a guess), so a
    long history is not walked when only a few days are wanted. Threads created after `window.end` are skipped
    but do not stop the paging. `label` names the channel in errors; `on_page(kept, requests)` reports after each
    request that is followed by another one.

    Raises DiscoopError like `scrape.fetch_messages`: NO_ACCESS for a missing-access 403, ERROR for any other 403
    (a block, not a permission), NOT_FOUND for 404. A 202, a body of the wrong shape, a repeating page or the page
    cap do not raise: they end the listing with the matching `Stop` and whatever was found so far.
    """
    label = label or f"channel {parent_id}"
    seen: set[str] = set()
    kept: list[Thread] = []
    requests = 0
    offset = 0
    total_results: int | None = None
    stop = Stop.PAGE_CAP  # what remains if the loop ends by running out of pages
    while requests < max_pages:
        response = _get_page(api, parent_id, archived=archived, offset=offset, label=label)
        requests += 1
        if response.status_code == 202:
            stop = Stop.NOT_INDEXED
            break
        data = _json_object(response)
        items = data.get("threads") if data is not None else None
        if data is None or not isinstance(items, list):
            stop = Stop.UNEXPECTED
            break
        if isinstance(data.get("total_results"), int):
            total_results = data["total_results"]
        if not items:
            logger.debug("threads page parent_id=%s archived=%s threads=0 last=True", parent_id, archived)
            stop = Stop.END
            break
        fresh = [t for t in _parse(items, parent_id) if t.id not in seen]
        if not fresh:
            stop = Stop.NO_PROGRESS
            break
        seen.update(t.id for t in fresh)
        kept += [t for t in fresh if in_window(t, window)]
        # Only a thread with a known last message proves that the sort order has reached the window start.
        reached_start = window.start is not None and any(
            t.last_message_id and t.last_activity < window.start for t in fresh
        )
        logger.debug(
            "threads page parent_id=%s archived=%s threads=%d new=%d has_more=%s reached_start=%s",
            parent_id,
            archived,
            len(items),
            len(fresh),
            data.get("has_more"),
            reached_start,
        )
        if reached_start:
            stop = Stop.WINDOW
            break
        if len(items) < PAGE_SIZE:
            stop = Stop.END
            break
        offset += PAGE_SIZE
        if on_page and requests < max_pages:
            on_page(len(kept), requests)
    return FetchedThreads(_newest_first(kept), requests, stop, total_results)


def fetch_all_threads(
    api: DiscordAPI,
    parent_id: str,
    window: Window,
    *,
    label: str | None = None,
    max_pages: int = MAX_PAGES,
    on_page: Callable[[int, int], None] | None = None,
) -> FetchedThreads:
    """The active threads first, then the archived ones, merged: each thread once, newest activity first.

    Same errors and `on_page` as `fetch_threads` (its counts run over both listings). `requests` is the total;
    `stop` is the first reason that makes the list incomplete, else that of the archived listing.
    """
    active = fetch_threads(api, parent_id, window, archived=False, label=label, max_pages=max_pages, on_page=on_page)

    def archived_progress(kept: int, requests: int) -> None:
        if on_page:
            on_page(len(active.threads) + kept, active.requests + requests)

    archived = fetch_threads(
        api, parent_id, window, archived=True, label=label, max_pages=max_pages, on_page=archived_progress
    )
    merged = {t.id: t for t in [*archived.threads, *active.threads]}  # a thread seen in both: the active record wins
    stop = next((r.stop for r in (active, archived) if not r.complete), archived.stop)
    totals = [r.total_results for r in (active, archived) if r.total_results is not None]
    return FetchedThreads(
        _newest_first(list(merged.values())),
        active.requests + archived.requests,
        stop,
        sum(totals) if totals else None,
    )


def _get_page(api: DiscordAPI, parent_id: str, *, archived: bool, offset: int, label: str) -> httpx.Response:
    response = api.request(
        "GET",
        f"/channels/{parent_id}/threads/search",
        params={
            "archived": "true" if archived else "false",
            "sort_by": "last_message_time",
            "sort_order": "desc",
            "limit": PAGE_SIZE,
            "offset": offset,
        },
    )
    if is_missing_access(response):
        raise DiscoopError(
            ExitCode.NO_ACCESS,
            f"No access to the threads of {label}.",
            "Discord lists channels you cannot read too. Check that you can open it in Discord.",
        )
    if response.status_code == 403:
        # Another 403 code (10008 anti-abuse, 40333 Cloudflare, ...) is a block, not missing access.
        code, detail = error_details(response)
        reason = f"code {code}" if code is not None else "no error code"
        raise DiscoopError(
            ExitCode.ERROR,
            f"Discord refused to list the threads of {label} (403, {reason}): {detail or 'no message'}.",
            BLOCKED_HINT,
        )
    if response.status_code == 404:
        raise DiscoopError(
            ExitCode.NOT_FOUND,
            f"Discord does not know {label}.",
            "It may have been deleted: run `discoop channels --refresh`.",
        )
    raise_for_status(response)
    return response


def _json_object(response: httpx.Response) -> dict[str, Any] | None:
    try:
        data = response.json()
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


def _parse(items: list[Any], parent_id: str) -> list[Thread]:
    """The usable threads of a page; an entry that is no object, has no ID or a broken one is skipped."""
    threads = []
    for item in items:
        if not isinstance(item, dict):
            continue
        try:
            threads.append(thread_from_api(item, parent_id))
        except (KeyError, ValueError, TypeError, OverflowError, OSError):
            continue
    return threads


def _newest_first(threads: list[Thread]) -> list[Thread]:
    return sorted(threads, key=lambda t: (t.last_activity, int(t.id) if t.id.isdigit() else 0), reverse=True)
