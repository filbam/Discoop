"""One-off probe of thread and channel pagination and metadata questions.

Run it yourself after `discoop login`:

    uv run python prototype/probe_threads.py

It sends GET requests only, paced at 1 second per request:
- Thread search page size (limit=25 vs limit=50)
- Offset reachability (0, 25, 100, 500, end)
- Response 202 ("not indexed") detection
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

    if channel is None:
        channel = next((c["id"] for c in channels if c.get("type") == 0), DEFAULT_CHANNEL)

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
    if channel is not None:
        r_text_arch = p.call(
            "GET",
            f"/channels/{channel}/threads/search",
            params={
                "archived": "true",
                "sort_by": "last_message_time",
                "sort_order": "desc",
                "limit": 25,
                "offset": 0,
            },
        )
        if r_text_arch.status_code == 202:
            not_indexed_responses.append(r_text_arch)
        raw_ta = body(r_text_arch)
        data_ta = raw_ta if isinstance(raw_ta, dict) else {}
        text_threads_archived = data_ta.get("threads", []) if isinstance(data_ta.get("threads"), list) else []
        p.check(
            "threads_search_text_archived",
            f"GET /channels/{channel}/threads/search?archived=true&limit=25",
            r_text_arch,
            returned=len(text_threads_archived) if r_text_arch.status_code == 200 else None,
            has_more=data_ta.get("has_more"),
            total_results=data_ta.get("total_results"),
            **({} if r_text_arch.status_code in (200, 202) else error_summary(r_text_arch)),
        )

        r_text_act = p.call(
            "GET",
            f"/channels/{channel}/threads/search",
            params={
                "archived": "false",
                "sort_by": "last_message_time",
                "sort_order": "desc",
                "limit": 25,
                "offset": 0,
            },
        )
        if r_text_act.status_code == 202:
            not_indexed_responses.append(r_text_act)
        raw_tact = body(r_text_act)
        data_tact = raw_tact if isinstance(raw_tact, dict) else {}
        text_threads_active = data_tact.get("threads", []) if isinstance(data_tact.get("threads"), list) else []
        p.check(
            "threads_search_text_active",
            f"GET /channels/{channel}/threads/search?archived=false&limit=25",
            r_text_act,
            returned=len(text_threads_active) if r_text_act.status_code == 200 else None,
            has_more=data_tact.get("has_more"),
            total_results=data_tact.get("total_results"),
            **({} if r_text_act.status_code in (200, 202) else error_summary(r_text_act)),
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

    text_candidates = [c for c in channels_with_lmid if c.get("type") == 0][:3]
    comparisons: list[dict[str, Any]] = []

    for idx, c in enumerate(text_candidates):
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
        tested_channels=len(text_candidates),
        results=[item["result"] for item in comparisons],
        result_counts=dict(Counter(item["result"] for item in comparisons)),
        details=comparisons,
    )

    return {"forum": forum, "channel": channel}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--guild", default=DEFAULT_GUILD, help=f"guild ID to probe (default: {DEFAULT_GUILD})")
    parser.add_argument(
        "--channel",
        default=None,
        help=f"text channel ID (default: find first type 0, or {DEFAULT_CHANNEL})",
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
            }
        }
        table.add_row(c["check"], str(c["status"]), json.dumps(detail, ensure_ascii=False))
    console.print(table)
    console.print(f"Rate-limit headers seen: {report['rate_limit_headers'] or 'none'}")
    console.print(f"Report: [bold]{path}[/bold]")
    return 0


if __name__ == "__main__":
    sys.exit(main())
