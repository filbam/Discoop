"""One-off probe of thread and channel pagination and metadata questions.

Run it yourself after `discoop login`:

    uv run python prototype/probe_threads.py

It sends GET requests only, paced at 1 second per request (about 59 to 64 requests, roughly 1.5 minutes):
- Thread search page size (limit=25 vs limit=50)
- Offset reachability (0, 25, 100, 500, end)
- Response 202 ("not indexed") detection
- `first_messages` and `members` parts of a thread search response (counts and field names, no extra request)
- Thread search in text channels: up to 6 text/announcement channels with a last_message_id, newest first,
  tried until one answers 200 (`threads_search_text_candidates`), then the active search there
  (`threads_search_text_active`). `--channel` overrides the choice with exactly one channel.
- Short page vs end (`threads_search_after_short_page`): the next page (offset=25) of the forum's active search when
  that search returned fewer than 25 threads; past the end (`threads_search_past_end`): the archived forum search at
  offset=total_results and total_results+25
- Readable thread messages (`thread_messages_readable`): the oldest message of the newest archived forum thread
  and of the newest active one (`limit=1&after=0`), plus one `limit=100` call on the first thread
- Private threads presence and metadata attributes
- total_results vs returned & unique pagination comparison
- Channel last_message_id presence and comparison against latest message

The report in prototype/out/ keeps structure only: no token, names, message texts,
user IDs or URLs.
"""

import argparse
import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx
from rich.console import Console
from rich.table import Table

from discoop.api import DiscordAPI
from discoop.errors import DiscoopError
from discoop.tokenstore import TokenStore

DEFAULT_GUILD = "461541385204400138"  # VUT FIT
DEFAULT_CHANNEL = "1282100102743330887"  # #2bit-general
OUT_DIR = Path(__file__).parent / "out"
MAX_TEXT_CANDIDATES = 6
TEXT_CHANNEL_TYPES = (0, 5)  # text and announcement


class Probe:
    def __init__(self, api: DiscordAPI, delay: float) -> None:
        self.api = api
        self.delay = delay
        self.checks: list[dict[str, Any]] = []
        self.header_names: set[str] = set()
        self.requests = 0

    def call(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        response = self.api.request(method, path, **kwargs)
        self.requests += 1
        self.header_names.update(name.lower() for name in response.headers)
        return response

    def check(self, name: str, request: str, response: httpx.Response | None, **findings: Any) -> None:
        status = response.status_code if response is not None else None
        self.checks.append({"check": name, "request": request, "status": status, **findings})


def body(response: httpx.Response) -> Any:
    try:
        return response.json()
    except ValueError:
        return None


def fields(objects: list[dict[str, Any]]) -> list[str]:
    return sorted(set().union(*(o.keys() for o in objects))) if objects else []


def error_summary(response: httpx.Response) -> dict[str, Any]:
    data = body(response)
    if isinstance(data, dict):
        return {"error_code": data.get("code"), "error_message": str(data.get("message", ""))[:200]}
    return {}


def snowflake(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def thread_list(data: dict[str, Any]) -> list[dict[str, Any]]:
    threads = data.get("threads")
    return [t for t in threads if isinstance(t, dict)] if isinstance(threads, list) else []


def first_thread_id(threads: list[dict[str, Any]]) -> str | None:
    return str(threads[0]["id"]) if threads and isinstance(threads[0], dict) and "id" in threads[0] else None


def search_params(archived: bool, offset: int = 0, limit: int = 25) -> dict[str, Any]:
    return {
        "archived": "true" if archived else "false",
        "sort_by": "last_message_time",
        "sort_order": "desc",
        "limit": limit,
        "offset": offset,
    }


def pick_text_candidates(channels: list[dict[str, Any]], limit: int = MAX_TEXT_CANDIDATES) -> list[dict[str, Any]]:
    """Text and announcement channels that have a last_message_id, newest last message first."""
    keyed: list[tuple[int, dict[str, Any]]] = []
    for c in channels:
        if not isinstance(c, dict) or c.get("type") not in TEXT_CHANNEL_TYPES or not c.get("id"):
            continue
        key = snowflake(c.get("last_message_id"))
        if key:
            keyed.append((key, c))
    keyed.sort(key=lambda item: item[0], reverse=True)
    return [c for _, c in keyed[:limit]]


def search_summary(response: httpx.Response) -> dict[str, Any]:
    """Error code, number of threads and presence of the `threads` key of a threads/search response."""
    data = body(response)
    data = data if isinstance(data, dict) else {}
    threads = data.get("threads")
    summary: dict[str, Any] = {
        "error_code": None if response.status_code in (200, 202) else data.get("code"),
        "returned": len(threads) if response.status_code == 200 and isinstance(threads, list) else None,
        "has_threads_key": "threads" in data,
    }
    if response.status_code == 202:
        summary["keys"] = sorted(data.keys())
    return summary


def objects_of(raw: Any) -> list[dict[str, Any]]:
    """Objects held by a JSON array or by the values of a JSON object."""
    items = raw.values() if isinstance(raw, dict) else raw if isinstance(raw, list) else []
    return [i for i in items if isinstance(i, dict)]


def first_messages_summary(data: dict[str, Any], threads: list[dict[str, Any]]) -> dict[str, Any]:
    """Counts and field names of the `first_messages` and `members` parts of a threads/search response."""
    raw = data.get("first_messages")
    messages = objects_of(raw)
    members = objects_of(data.get("members"))
    thread_ids = {str(t["id"]) for t in threads if "id" in t}
    return {
        "container": "missing" if raw is None else type(raw).__name__,
        "threads": len(thread_ids),
        "first_messages": len(messages),
        "message_id_equals_thread_id": sum(1 for m in messages if str(m.get("id")) in thread_ids),
        "message_channel_is_thread": sum(1 for m in messages if str(m.get("channel_id")) in thread_ids),
        "message_types": dict(sorted(Counter(str(m.get("type")) for m in messages).items())),
        "message_fields": fields(messages),
        "members": len(members) if isinstance(data.get("members"), (dict, list)) else None,
        "member_fields": fields(members),
    }


def page_findings(response: httpx.Response, *, with_has_more: bool = False) -> dict[str, Any]:
    """Status and number of threads of a threads/search page (`has_more` only on request). No IDs or names."""
    data = body(response)
    data = data if isinstance(data, dict) else {}
    threads = data.get("threads")
    findings: dict[str, Any] = {
        "status": response.status_code,
        "returned": len(threads) if response.status_code == 200 and isinstance(threads, list) else None,
    }
    if with_has_more:
        findings["has_more"] = data.get("has_more")
    if response.status_code not in (200, 202):
        findings["error_code"] = data.get("code")
    return findings


def message_sample(response: httpx.Response, thread_id: str, limit: int) -> dict[str, Any]:
    """Structure of a /channels/{thread}/messages response. Counts, types and booleans only: no IDs or texts."""
    sample: dict[str, Any] = {"limit": limit, "status": response.status_code}
    data = body(response)
    if response.status_code != 200 or not isinstance(data, list):
        sample["returned"] = None
        if response.status_code != 200:
            sample.update(error_summary(response))
        return sample
    messages = [m for m in data if isinstance(m, dict)]
    ids = [i for i in (snowflake(m.get("id")) for m in messages) if i is not None]
    thread_key = snowflake(thread_id)
    sample["returned"] = len(messages)
    if limit == 1:
        sample["first_message_id_equals_thread_id"] = (
            snowflake(messages[0].get("id")) == thread_key if messages else None
        )
        sample["message_type"] = messages[0].get("type") if messages else None
    else:
        complete = len(messages) < limit  # the batch then holds the whole thread, so its oldest message is the first
        sample["more_than_one"] = len(messages) > 1
        sample["types"] = dict(sorted(Counter(str(m.get("type")) for m in messages).items()))
        sample["message_fields"] = fields(messages)
        sample["batch_complete"] = complete
        sample["oldest_message_id_equals_thread_id"] = (min(ids) == thread_key) if complete and ids else None
    return sample


def run(
    probe: Probe,
    guild: str,
    channel: str | None,
    forum: str | None,
    max_pages: int = 40,
) -> dict[str, Any]:
    p = probe
    not_indexed_responses: list[httpx.Response] = []

    # 0. Discover channels to resolve forum and text channel if not explicitly specified
    r_channels = p.call("GET", f"/guilds/{guild}/channels")
    channels = body(r_channels) if r_channels.status_code == 200 else []

    if forum is None:
        forum = next(
            (c["id"] for c in channels if c.get("type") == 15 and "help-center" in (c.get("name") or "").lower()),
            None,
        )
        if forum is None:
            forum = next((c["id"] for c in channels if c.get("type") == 15), None)

    # Text channels for the thread search: an explicit --channel wins, otherwise the text and announcement channels
    # with the newest last_message_id (most likely readable and active), at most MAX_TEXT_CANDIDATES.
    if channel is not None:
        text_candidates: list[dict[str, Any]] = [{"id": channel}]
    elif r_channels.status_code != 200:
        text_candidates = [{"id": DEFAULT_CHANNEL}]
    else:
        text_candidates = pick_text_candidates(channels)

    # 1. Thread search page size (limit 25 and limit 50)
    data25: dict[str, Any] | None = None
    r25: httpx.Response | None = None
    threads25: list[dict[str, Any]] = []
    total_results_first: int | None = None

    if forum is None:
        p.check("threads_search_limit_25", "GET /channels/<forum>/threads/search", None, skipped="no forum channel found")
        p.check("threads_search_limit_50", "GET /channels/<forum>/threads/search", None, skipped="no forum channel found")
    else:
        r25 = p.call(
            "GET",
            f"/channels/{forum}/threads/search",
            params={
                "archived": "true",
                "sort_by": "last_message_time",
                "sort_order": "desc",
                "limit": 25,
                "offset": 0,
            },
        )
        if r25.status_code == 202:
            not_indexed_responses.append(r25)
        raw25 = body(r25)
        data25 = raw25 if isinstance(raw25, dict) else {}
        threads25 = data25.get("threads", []) if isinstance(data25.get("threads"), list) else []
        has_more25 = data25.get("has_more")
        total_results25 = data25.get("total_results")
        if isinstance(total_results25, int):
            total_results_first = total_results25
        p.check(
            "threads_search_limit_25",
            f"GET /channels/{forum}/threads/search?archived=true&sort_by=last_message_time&sort_order=desc&limit=25&offset=0",
            r25,
            returned=len(threads25) if r25.status_code == 200 else None,
            has_more=has_more25,
            total_results=total_results25,
            keys=sorted(data25.keys()) if isinstance(data25, dict) else None,
            **({} if r25.status_code in (200, 202) else error_summary(r25)),
        )
        if r25.status_code == 200:
            p.check(
                "threads_search_first_messages",
                "parts of the threads_search_limit_25 response (no extra request)",
                r25,
                **first_messages_summary(data25, threads25),
            )

        r50 = p.call(
            "GET",
            f"/channels/{forum}/threads/search",
            params={
                "archived": "true",
                "sort_by": "last_message_time",
                "sort_order": "desc",
                "limit": 50,
                "offset": 0,
            },
        )
        if r50.status_code == 202:
            not_indexed_responses.append(r50)
        raw50 = body(r50)
        data50 = raw50 if isinstance(raw50, dict) else {}
        threads50 = data50.get("threads", []) if isinstance(data50.get("threads"), list) else []
        p.check(
            "threads_search_limit_50",
            f"GET /channels/{forum}/threads/search?archived=true&sort_by=last_message_time&sort_order=desc&limit=50&offset=0",
            r50,
            returned=len(threads50) if r50.status_code == 200 else None,
            has_more=data50.get("has_more"),
            total_results=data50.get("total_results"),
            keys=sorted(data50.keys()) if isinstance(data50, dict) else None,
            **({} if r50.status_code in (200, 202) else error_summary(r50)),
        )

    # 2. Offset reachability (0, 25, 100, 500, and end if total_results > 500)
    offsets = [0, 25, 100, 500]
    if total_results_first is not None and total_results_first > 500:
        end_offset = max(0, total_results_first - 25)
        if end_offset not in offsets:
            offsets.append(end_offset)

    if forum is None:
        for off in offsets:
            p.check(f"threads_search_offset_{off}", f"GET .../threads/search?offset={off}", None, skipped="no forum channel found")
    else:
        for off in offsets:
            if off == 0 and r25 is not None:
                r_off = r25
            else:
                r_off = p.call(
                    "GET",
                    f"/channels/{forum}/threads/search",
                    params={
                        "archived": "true",
                        "sort_by": "last_message_time",
                        "sort_order": "desc",
                        "limit": 25,
                        "offset": off,
                    },
                )
            if r_off.status_code == 202:
                not_indexed_responses.append(r_off)
            raw_off = body(r_off)
            data_off = raw_off if isinstance(raw_off, dict) else {}
            threads_off = data_off.get("threads", []) if isinstance(data_off.get("threads"), list) else []

            findings_off: dict[str, Any] = {
                "offset": off,
                "returned": len(threads_off) if r_off.status_code == 200 else None,
                "has_more": data_off.get("has_more"),
                "total_results": data_off.get("total_results"),
            }
            if r_off.status_code != 200:
                findings_off.update(error_summary(r_off))
            if r_off.status_code == 202:
                findings_off["keys"] = sorted(data_off.keys())

            p.check(
                f"threads_search_offset_{off}",
                f"GET /channels/{forum}/threads/search?archived=true&sort_by=last_message_time&sort_order=desc&limit=25&offset={off}",
                r_off,
                **findings_off,
            )

    # 3. Response 202 ("not indexed") summary
    sample_202 = not_indexed_responses[0] if not_indexed_responses else None
    body_202 = body(sample_202) if sample_202 is not None else None
    p.check(
        "threads_search_not_indexed_202",
        "GET .../threads/search (status 202 'not indexed' summary)",
        sample_202,
        received_202=bool(sample_202),
        count_202=len(not_indexed_responses),
        keys=sorted(body_202.keys()) if isinstance(body_202, dict) else None,
        **({} if not sample_202 else error_summary(sample_202)),
    )

    # 4. Private threads and thread metadata across active and search endpoints
    r_active = p.call("GET", f"/guilds/{guild}/threads/active")
    raw_active = body(r_active)
    data_active = raw_active if isinstance(raw_active, dict) else {}
    guild_active_threads = data_active.get("threads", []) if isinstance(data_active.get("threads"), list) else []
    p.check(
        "guild_threads_active",
        f"GET /guilds/{guild}/threads/active",
        r_active,
        keys=sorted(data_active.keys()) if isinstance(data_active, dict) else None,
        threads=len(guild_active_threads),
        **({} if r_active.status_code == 200 else error_summary(r_active)),
    )

    text_threads_archived: list[dict[str, Any]] = []
    text_threads_active: list[dict[str, Any]] = []
    text_records: list[dict[str, Any]] = []
    text_ok_index: int | None = None
    text_ok_id: str | None = None
    for idx, candidate in enumerate(text_candidates, start=1):
        r_cand = p.call("GET", f"/channels/{candidate['id']}/threads/search", params=search_params(archived=True))
        if r_cand.status_code == 202:
            not_indexed_responses.append(r_cand)
        text_records.append({"index": idx, "status": r_cand.status_code, **search_summary(r_cand)})
        if r_cand.status_code == 200:
            text_ok_index, text_ok_id = idx, str(candidate["id"])
            raw_cand = body(r_cand)
            text_threads_archived = thread_list(raw_cand if isinstance(raw_cand, dict) else {})
            break

    if not text_candidates:
        p.check(
            "threads_search_text_candidates",
            "GET /channels/<text candidate>/threads/search",
            None,
            skipped="no text or announcement channel with a last_message_id found",
        )
    else:
        p.check(
            "threads_search_text_candidates",
            "GET /channels/<text candidate>/threads/search?archived=true&sort_by=last_message_time&sort_order=desc"
            "&limit=25&offset=0 (candidates in order of newest last_message_id, stops at the first 200)",
            None,
            override=channel is not None,
            candidates=len(text_candidates),
            tried=len(text_records),
            first_ok_index=text_ok_index,
            status_counts=dict(sorted(Counter(str(r["status"]) for r in text_records).items())),
            details=text_records,
        )

    if text_ok_id is None:
        p.check(
            "threads_search_text_active",
            "GET /channels/<first text candidate that answered 200>/threads/search?archived=false",
            None,
            skipped="no text channel candidate answered 200",
        )
    else:
        r_text_act = p.call("GET", f"/channels/{text_ok_id}/threads/search", params=search_params(archived=False))
        if r_text_act.status_code == 202:
            not_indexed_responses.append(r_text_act)
        raw_tact = body(r_text_act)
        text_threads_active = thread_list(raw_tact if isinstance(raw_tact, dict) else {})
        p.check(
            "threads_search_text_active",
            f"GET /channels/<text candidate {text_ok_index}>/threads/search?archived=false&sort_by=last_message_time"
            "&sort_order=desc&limit=25&offset=0",
            r_text_act,
            candidate_index=text_ok_index,
            **search_summary(r_text_act),
        )

    forum_threads_active: list[dict[str, Any]] = []
    if forum is not None:
        r_forum_act = p.call(
            "GET",
            f"/channels/{forum}/threads/search",
            params={
                "archived": "false",
                "sort_by": "last_message_time",
                "sort_order": "desc",
                "limit": 25,
                "offset": 0,
            },
        )
        if r_forum_act.status_code == 202:
            not_indexed_responses.append(r_forum_act)
        raw_fa = body(r_forum_act)
        data_fa = raw_fa if isinstance(raw_fa, dict) else {}
        forum_threads_active = data_fa.get("threads", []) if isinstance(data_fa.get("threads"), list) else []
        p.check(
            "threads_search_forum_active",
            f"GET /channels/{forum}/threads/search?archived=false&limit=25",
            r_forum_act,
            returned=len(forum_threads_active) if r_forum_act.status_code == 200 else None,
            has_more=data_fa.get("has_more"),
            total_results=data_fa.get("total_results"),
            **({} if r_forum_act.status_code in (200, 202) else error_summary(r_forum_act)),
        )

        # Does a page shorter than 25 really mean the end? Ask for the next page of the same search.
        if r_forum_act.status_code == 200 and len(forum_threads_active) < 25:
            r_after_short = p.call("GET", f"/channels/{forum}/threads/search", params=search_params(archived=False, offset=25))
            p.check(
                "threads_search_after_short_page",
                f"GET /channels/{forum}/threads/search?archived=false&sort_by=last_message_time&sort_order=desc"
                "&limit=25&offset=25 (next page after the short forum_active page)",
                r_after_short,
                short_page_returned=len(forum_threads_active),
                **page_findings(r_after_short, with_has_more=True),
            )
        else:
            p.check(
                "threads_search_after_short_page",
                "GET /channels/<forum>/threads/search?archived=false&offset=25",
                None,
                skipped="the forum_active page was not a successful page shorter than 25",
            )
    else:
        p.check(
            "threads_search_after_short_page",
            "GET /channels/<forum>/threads/search?archived=false&offset=25",
            None,
            skipped="no forum channel found",
        )

    # Collect and deduplicate all discovered threads for structural analysis
    threads_by_id: dict[str, dict[str, Any]] = {}
    for t in [
        *guild_active_threads,
        *threads25,
        *text_threads_archived,
        *text_threads_active,
        *forum_threads_active,
    ]:
        if isinstance(t, dict) and "id" in t:
            threads_by_id[str(t["id"])] = t
    unique_threads = list(threads_by_id.values())

    metadata_list = [
        t.get("thread_metadata")
        for t in unique_threads
        if isinstance(t.get("thread_metadata"), dict)
    ]

    p.check(
        "threads_private_and_types",
        "thread structure analysis across active and searched threads",
        None,
        total_inspected=len(unique_threads),
        has_private_threads=any(t.get("type") == 12 for t in unique_threads),
        private_threads_count=sum(1 for t in unique_threads if t.get("type") == 12),
        type_counts=dict(sorted(Counter(str(t.get("type")) for t in unique_threads).items())),
        locked_counts=dict(
            sorted(Counter(str((t.get("thread_metadata") or {}).get("locked")) for t in unique_threads).items())
        ),
        flags_counts=dict(sorted(Counter(str(t.get("flags")) for t in unique_threads).items())),
        thread_fields=fields(unique_threads),
        thread_metadata_fields=fields(metadata_list),
    )

    # 4b. Can thread messages be read? The oldest message (limit=1&after=0) of the newest archived forum thread and of
    # the newest active one, then 100 newest messages of the first thread. Only counts, types and booleans are kept.
    message_targets: list[tuple[str, str]] = []
    archived_thread_id = first_thread_id(threads25)
    if archived_thread_id:
        message_targets.append(("archived_forum", archived_thread_id))
    for label, pool in (("active_forum", forum_threads_active), ("active_text", text_threads_active)):
        active_thread_id = first_thread_id(pool)
        if active_thread_id:
            message_targets.append((label, active_thread_id))
            break

    if not message_targets:
        p.check(
            "thread_messages_readable",
            "GET /channels/<thread>/messages",
            None,
            skipped="no thread found",
        )
    else:
        message_samples: list[dict[str, Any]] = []
        statuses: list[int] = []
        for position, (label, thread_id) in enumerate(message_targets):
            r_oldest = p.call("GET", f"/channels/{thread_id}/messages", params={"limit": 1, "after": 0})
            sample: dict[str, Any] = {"thread": label, "oldest_message": message_sample(r_oldest, thread_id, 1)}
            statuses.append(r_oldest.status_code)
            if position == 0:
                r_batch = p.call("GET", f"/channels/{thread_id}/messages", params={"limit": 100})
                sample["newest_100"] = message_sample(r_batch, thread_id, 100)
                statuses.append(r_batch.status_code)
            message_samples.append(sample)
        p.check(
            "thread_messages_readable",
            "GET /channels/<thread>/messages?limit=1&after=0 (oldest message), then ?limit=100 on the first thread",
            None,
            threads_tested=len(message_samples),
            statuses=statuses,
            samples=message_samples,
        )

    # 4c. Past the end of the archived list: offset = total_results and total_results + 25 (the first page's total).
    if forum is None:
        past_end_skip: str | None = "no forum channel found"
    elif total_results_first is None:
        past_end_skip = "total_results of the first search is unknown"
    else:
        past_end_skip = None
    if past_end_skip is not None:
        p.check(
            "threads_search_past_end",
            "GET /channels/<forum>/threads/search?archived=true&offset=<total_results>",
            None,
            skipped=past_end_skip,
        )
    else:
        past_end_pages: list[dict[str, Any]] = []
        for label, off in (("total_results", total_results_first), ("total_results_plus_25", total_results_first + 25)):
            r_past = p.call("GET", f"/channels/{forum}/threads/search", params=search_params(archived=True, offset=off))
            past_end_pages.append({"offset_kind": label, "offset": off, **page_findings(r_past)})
        p.check(
            "threads_search_past_end",
            f"GET /channels/{forum}/threads/search?archived=true&sort_by=last_message_time&sort_order=desc&limit=25"
            "&offset=<total_results> and <total_results + 25>",
            None,
            total_results=total_results_first,
            statuses=[page["status"] for page in past_end_pages],
            returned=[page["returned"] for page in past_end_pages],
            pages=past_end_pages,
        )

    # 5. Difference between total_results and returned/unique threads across pagination
    if forum is None:
        p.check(
            "threads_pagination_total_vs_returned",
            "GET .../threads/search?archived=true pagination",
            None,
            skipped="no forum channel found",
        )
    else:
        seen_pagination_ids: set[str] = set()
        total_returned_pagination = 0
        pages_fetched = 0
        initial_total_results: int | None = total_results_first
        latest_total_results: int | None = total_results_first
        stop_reason = "completed"

        page_offset = 0
        while pages_fetched < max_pages:
            if page_offset == 0 and r25 is not None and r25.status_code == 200:
                r_page = r25
            else:
                r_page = p.call(
                    "GET",
                    f"/channels/{forum}/threads/search",
                    params={
                        "archived": "true",
                        "sort_by": "last_message_time",
                        "sort_order": "desc",
                        "limit": 25,
                        "offset": page_offset,
                    },
                )
            if r_page.status_code == 202:
                not_indexed_responses.append(r_page)
                stop_reason = "202_not_indexed"
                break
            if r_page.status_code != 200:
                stop_reason = f"http_{r_page.status_code}"
                break

            raw_page = body(r_page)
            if not isinstance(raw_page, dict):
                stop_reason = "invalid_json"
                break

            page_threads = raw_page.get("threads", []) if isinstance(raw_page.get("threads"), list) else []
            page_has_more = bool(raw_page.get("has_more"))
            page_total = raw_page.get("total_results")
            if initial_total_results is None and isinstance(page_total, int):
                initial_total_results = page_total
            if isinstance(page_total, int):
                latest_total_results = page_total

            pages_fetched += 1
            total_returned_pagination += len(page_threads)
            for pt in page_threads:
                if isinstance(pt, dict) and "id" in pt:
                    seen_pagination_ids.add(str(pt["id"]))

            if not page_has_more:
                stop_reason = "has_more_false"
                break
            if len(page_threads) == 0:
                stop_reason = "zero_threads_returned"
                break

            page_offset += 25
        else:
            stop_reason = "max_pages_reached"

        diff_returned = (
            (initial_total_results - total_returned_pagination)
            if initial_total_results is not None
            else None
        )
        diff_unique = (
            (initial_total_results - len(seen_pagination_ids))
            if initial_total_results is not None
            else None
        )

        p.check(
            "threads_pagination_total_vs_returned",
            f"GET /channels/{forum}/threads/search?archived=true&sort_by=last_message_time&sort_order=desc&limit=25 (pagination)",
            None,
            pages_fetched=pages_fetched,
            initial_total_results=initial_total_results,
            latest_total_results=latest_total_results,
            total_threads_returned=total_returned_pagination,
            unique_threads_count=len(seen_pagination_ids),
            duplicates_count=total_returned_pagination - len(seen_pagination_ids),
            difference_total_vs_returned=diff_returned,
            difference_total_vs_unique=diff_unique,
            stop_reason=stop_reason,
        )

    # 6. Channels with last_message_id and comparison with latest message
    channels_with_lmid = [c for c in channels if c.get("last_message_id")]
    p.check(
        "channels_last_message_id",
        f"GET /guilds/{guild}/channels",
        r_channels,
        total_channels=len(channels),
        with_last_message_id=len(channels_with_lmid),
        without_last_message_id=len(channels) - len(channels_with_lmid),
        by_type_with_last_message_id=dict(
            sorted(Counter(str(c.get("type")) for c in channels_with_lmid).items())
        ),
        by_type_all=dict(sorted(Counter(str(c.get("type")) for c in channels).items())),
        **({} if r_channels.status_code == 200 else error_summary(r_channels)),
    )

    lmid_samples = [c for c in channels_with_lmid if c.get("type") == 0][:3]
    comparisons: list[dict[str, Any]] = []

    for idx, c in enumerate(lmid_samples):
        cid = c.get("id")
        c_lmid = c.get("last_message_id")
        r_msg = p.call("GET", f"/channels/{cid}/messages", params={"limit": 1})
        if r_msg.status_code == 200:
            msgs = body(r_msg)
            if isinstance(msgs, list) and len(msgs) > 0 and isinstance(msgs[0], dict) and "id" in msgs[0]:
                try:
                    latest_id = int(msgs[0]["id"])
                    channel_lmid_val = int(c_lmid)
                    if channel_lmid_val == latest_id:
                        cmp_res = "zhoduje sa"
                    elif channel_lmid_val < latest_id:
                        cmp_res = "je staršie"
                    else:
                        cmp_res = "je novšie"
                except (ValueError, TypeError):
                    cmp_res = "chýba"
            else:
                cmp_res = "chýba"
        else:
            cmp_res = "chýba"

        comparisons.append({
            "channel_index": idx + 1,
            "status": r_msg.status_code,
            "result": cmp_res,
        })

    p.check(
        "channels_last_message_vs_latest",
        "GET /channels/{id}/messages?limit=1 (compare last_message_id on 3 text channels)",
        None,
        tested_channels=len(lmid_samples),
        results=[item["result"] for item in comparisons],
        result_counts=dict(Counter(item["result"] for item in comparisons)),
        details=comparisons,
    )

    text_channel = text_ok_id or (str(text_candidates[0]["id"]) if text_candidates else None)
    return {"forum": forum, "channel": text_channel}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--guild", default=DEFAULT_GUILD, help=f"guild ID to probe (default: {DEFAULT_GUILD})")
    parser.add_argument(
        "--channel",
        default=None,
        help=(
            "text channel ID for the thread search; skips the automatic choice "
            f"(default: up to {MAX_TEXT_CANDIDATES} newest text/announcement channels, or {DEFAULT_CHANNEL} "
            "when the channel list fails)"
        ),
    )
    parser.add_argument(
        "--forum",
        default=None,
        help="forum channel ID (default: find channel with 'help-center' or first type 15)",
    )
    parser.add_argument("--delay", type=float, default=1.0, help="seconds between requests (default: 1.0)")
    parser.add_argument(
        "--max-pages",
        type=int,
        default=40,
        help="maximum pagination pages for check 5 (default: 40)",
    )
    args = parser.parse_args()

    console = Console()
    stored = TokenStore.default().load()
    if stored is None:
        console.print("[red]Not logged in.[/red] Run `uv run discoop login` first.")
        return 2

    started = datetime.now(timezone.utc)
    with DiscordAPI(stored.token, delay=args.delay) as api:
        probe = Probe(api, args.delay)
        try:
            extra = run(probe, args.guild, args.channel, args.forum, max_pages=args.max_pages)
        except DiscoopError as e:
            console.print(f"[red]Probe stopped:[/red] {e.message}")
            extra = {"stopped": f"{e.name}: {e.message}"}

    report = {
        "started_at": started.isoformat(timespec="seconds"),
        "duration_s": round((datetime.now(timezone.utc) - started).total_seconds(), 1),
        "targets": {"guild": args.guild, **extra},
        "requests": probe.requests,
        "rate_limit_headers": sorted(h for h in probe.header_names if "ratelimit" in h or h == "retry-after"),
        "response_header_names": sorted(probe.header_names),
        "checks": probe.checks,
    }
    OUT_DIR.mkdir(exist_ok=True)
    path = OUT_DIR / f"probe-threads-{started.strftime('%Y%m%d-%H%M%S')}.json"
    path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")

    table = Table(title="discoop threads probe")
    table.add_column("check")
    table.add_column("status")
    table.add_column("result")
    for c in probe.checks:
        detail = {
            k: v
            for k, v in c.items()
            if k
            in {
                "returned",
                "count",
                "threads",
                "total_results",
                "has_more",
                "skipped",
                "pages_fetched",
                "unique_threads_count",
                "difference_total_vs_returned",
                "with_last_message_id",
                "results",
                "has_private_threads",
                "received_202",
                "tried",
                "first_ok_index",
                "status_counts",
                "statuses",
                "first_messages",
                "message_id_equals_thread_id",
                "short_page_returned",
            }
        }
        table.add_row(c["check"], str(c["status"]), json.dumps(detail, ensure_ascii=False))
    console.print(table)
    console.print(f"Rate-limit headers seen: {report['rate_limit_headers'] or 'none'}")
    console.print(f"Report: [bold]{path}[/bold]")
    return 0


if __name__ == "__main__":
    sys.exit(main())
