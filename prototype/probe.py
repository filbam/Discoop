"""One-off probe of the open API questions (docs/analyzy/*.md, "verify with a prototype").

Run it yourself after `discoop login`:

    uv run python prototype/probe.py

It sends about 20 requests, one per second: GETs, plus one POST /attachments/refresh-urls.
It never acks, posts messages or changes anything. The report in prototype/out/ keeps
structure only: no token, names, message texts, user IDs or attachment URLs.
"""

import argparse
import json
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

import httpx
from rich.console import Console
from rich.table import Table

from discoop.api import USER_AGENT, DiscordAPI
from discoop.errors import DiscoopError
from discoop.remote_auth.trace import shape
from discoop.tokenstore import TokenStore

DEFAULT_GUILD = "461541385204400138"  # VUT FIT
DEFAULT_CHANNEL = "1282100102743330887"  # #2bit-general
OUT_DIR = Path(__file__).parent / "out"
DISCORD_EPOCH_MS = 1420070400000
HIDDEN_FLAG = 1 << 17


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


def ordering(ids: list[str]) -> str:
    values = [int(i) for i in ids]
    if len(values) < 2:
        return "n/a"
    if all(a > b for a, b in zip(values, values[1:])):
        return "newest first"
    if all(a < b for a, b in zip(values, values[1:])):
        return "oldest first"
    return "mixed"


def snowflake_ms(snowflake: str) -> int:
    return (int(snowflake) >> 22) + DISCORD_EPOCH_MS


def error_summary(response: httpx.Response) -> dict[str, Any]:
    data = body(response)
    if isinstance(data, dict):
        return {"error_code": data.get("code"), "error_message": str(data.get("message", ""))[:200]}
    return {}


def url_structure(url: str) -> dict[str, Any]:
    parts = urlsplit(url)
    query = parse_qs(parts.query)
    segments = parts.path.strip("/").split("/")
    result: dict[str, Any] = {
        "host": parts.netloc,
        "path_pattern": "/".join(["attachments", "{channel_id}", "{attachment_id}", "{filename}"])
        if segments[:1] == ["attachments"] and len(segments) == 4
        else f"{len(segments)} segments",
        "query_params": sorted(query),
    }
    try:
        issued, expires = int(query["is"][0], 16), int(query["ex"][0], 16)
        result["valid_hours"] = round((expires - issued) / 3600, 2)
        result["expires_in_hours_from_now"] = round((expires - time.time()) / 3600, 2)
    except (KeyError, ValueError):
        pass
    return result


def run(probe: Probe, guild: str, channel: str, forum: str | None) -> dict[str, Any]:
    p = probe

    # 1. Account
    r = p.call("GET", "/users/@me")
    p.check("me", "GET /users/@me", r, fields=sorted(body(r) or {}))

    # 2. Servers over REST
    r = p.call("GET", "/users/@me/guilds")
    guilds = body(r) if r.status_code == 200 else []
    p.check(
        "guilds",
        "GET /users/@me/guilds",
        r,
        count=len(guilds),
        fields=fields(guilds),
        target_guild_present=any(g.get("id") == guild for g in guilds),
        **({} if r.status_code == 200 else error_summary(r)),
    )
    r = p.call("GET", "/users/@me/guilds", params={"with_counts": "true"})
    counted = body(r) if r.status_code == 200 else []
    p.check(
        "guilds_with_counts",
        "GET /users/@me/guilds?with_counts=true",
        r,
        has_member_counts=any("approximate_member_count" in g for g in counted),
    )

    # 3. Channels over REST
    r = p.call("GET", f"/guilds/{guild}/channels")
    channels = body(r) if r.status_code == 200 else []
    hidden = [c for c in channels if c.get("name") == "___hidden___" or (c.get("flags") or 0) & HIDDEN_FLAG]
    if forum is None:
        forum = next(
            (c["id"] for c in channels if c.get("type") == 15 and "help-center" in (c.get("name") or "")), None
        )
    p.check(
        "channels",
        f"GET /guilds/{guild}/channels",
        r,
        count=len(channels),
        by_type=dict(sorted(Counter(str(c.get("type")) for c in channels).items())),
        hidden_count=len(hidden),
        hidden_example=shape(hidden[0]) if hidden else None,
        hidden_names=sorted({c.get("name") for c in hidden}),
        fields=fields(channels),
        target_channel_present=any(c.get("id") == channel for c in channels),
        forum_found=forum,
        **({} if r.status_code == 200 else error_summary(r)),
    )

    # 4. Messages: page size and pagination order
    r = p.call("GET", f"/channels/{channel}/messages", params={"limit": 100})
    page = body(r) if r.status_code == 200 else []
    p.check(
        "messages_limit_100",
        f"GET /channels/{channel}/messages?limit=100",
        r,
        returned=len(page),
        order=ordering([m["id"] for m in page]),
        fields=fields(page),
        has_member_field=any("member" in m for m in page),
        message_types=dict(Counter(str(m.get("type")) for m in page)),
        replies_without_referenced_message=sum(
            1 for m in page if m.get("type") == 19 and "referenced_message" not in m
        ),
        with_attachments=sum(1 for m in page if m.get("attachments")),
        **({} if r.status_code == 200 else error_summary(r)),
    )
    r = p.call("GET", f"/channels/{channel}/messages", params={"limit": 101})
    over = body(r)
    p.check(
        "messages_limit_101",
        f"GET /channels/{channel}/messages?limit=101",
        r,
        returned=len(over) if isinstance(over, list) else None,
        **({} if r.status_code == 200 else error_summary(r)),
    )
    older: list[dict[str, Any]] = []
    if page:
        oldest = min(page, key=lambda m: int(m["id"]))["id"]
        r = p.call("GET", f"/channels/{channel}/messages", params={"before": oldest, "limit": 100})
        older = body(r) if r.status_code == 200 else []
        p.check(
            "messages_before",
            f"GET /channels/{channel}/messages?before=<oldest>&limit=100",
            r,
            returned=len(older),
            order=ordering([m["id"] for m in older]),
            all_older=all(int(m["id"]) < int(oldest) for m in older),
        )
        pivot = sorted(page, key=lambda m: int(m["id"]))[len(page) // 2]["id"]
        r = p.call("GET", f"/channels/{channel}/messages", params={"after": pivot, "limit": 10})
        newer = body(r) if r.status_code == 200 else []
        ids_after = sorted(int(m["id"]) for m in page if int(m["id"]) > int(pivot))
        p.check(
            "messages_after",
            f"GET /channels/{channel}/messages?after=<middle>&limit=10",
            r,
            returned=len(newer),
            order=ordering([m["id"] for m in newer]),
            all_newer=all(int(m["id"]) > int(pivot) for m in newer),
            returns_oldest_after_pivot=sorted(int(m["id"]) for m in newer) == ids_after[: len(newer)],
        )

    # 5. Pins
    r = p.call("GET", f"/channels/{channel}/messages/pins", params={"limit": 25})
    pins = body(r) if r.status_code == 200 else {}
    items = pins.get("items", []) if isinstance(pins, dict) else []
    p.check(
        "pins",
        f"GET /channels/{channel}/messages/pins?limit=25",
        r,
        returned=len(items),
        has_more=pins.get("has_more") if isinstance(pins, dict) else None,
        shape=shape(pins)
        if not isinstance(pins, dict)
        else {k: shape(v) for k, v in pins.items() if k != "items"},
    )
    if isinstance(pins, dict) and pins.get("has_more") and items:
        r = p.call(
            "GET", f"/channels/{channel}/messages/pins", params={"limit": 25, "before": items[-1]["pinned_at"]}
        )
        more = body(r) if r.status_code == 200 else {}
        p.check(
            "pins_page_2",
            f"GET /channels/{channel}/messages/pins?before=<pinned_at>",
            r,
            returned=len(more.get("items", [])) if isinstance(more, dict) else None,
        )

    # 6. Active threads over REST
    r = p.call("GET", f"/guilds/{guild}/threads/active")
    active = body(r) if r.status_code == 200 else {}
    threads = active.get("threads", []) if isinstance(active, dict) else []
    p.check(
        "guild_threads_active",
        f"GET /guilds/{guild}/threads/active",
        r,
        keys=sorted(active) if isinstance(active, dict) else None,
        threads=len(threads),
        in_target_channel=sum(1 for t in threads if t.get("parent_id") == channel),
        in_forum=sum(1 for t in threads if forum and t.get("parent_id") == forum),
        **({} if r.status_code == 200 else error_summary(r)),
    )
    search = {"archived": "false", "sort_by": "last_message_time", "sort_order": "desc", "limit": 25, "offset": 0}
    for name, target in (("forum", forum), ("channel", channel)):
        if not target:
            continue
        r = p.call("GET", f"/channels/{target}/threads/search", params=search)
        found = body(r) if r.status_code == 200 else {}
        found_threads = found.get("threads", []) if isinstance(found, dict) else []
        p.check(
            f"threads_search_active_{name}",
            f"GET /channels/{target}/threads/search?archived=false",
            r,
            keys=sorted(found) if isinstance(found, dict) else None,
            total_results=found.get("total_results") if isinstance(found, dict) else None,
            returned=len(found_threads),
            archived_flags=dict(
                Counter(str((t.get("thread_metadata") or {}).get("archived")) for t in found_threads)
            ),
            **({} if r.status_code == 200 else error_summary(r)),
        )

    # 7. Attachments: CDN without token, refresh-urls
    attachment = next((m["attachments"][0] for m in [*page, *older] if m.get("attachments")), None)
    if attachment is None:
        p.check("attachments", "-", None, skipped="no attachment in the fetched messages")
    else:
        url = attachment["url"]
        time.sleep(probe.delay)
        try:
            with httpx.Client(timeout=20, headers={"User-Agent": USER_AGENT}, follow_redirects=True) as cdn:
                with cdn.stream("GET", url) as response:
                    first = next(response.iter_bytes(1024), b"")
                    p.check(
                        "cdn_without_token",
                        "GET <attachment url> (no Authorization)",
                        response,
                        content_type=response.headers.get("content-type"),
                        content_length=response.headers.get("content-length"),
                        first_bytes_read=len(first),
                        url=url_structure(url),
                        attachment_fields=sorted(attachment),
                    )
        except httpx.HTTPError as e:
            p.check("cdn_without_token", "GET <attachment url> (no Authorization)", None, error=type(e).__name__)
        r = p.call("POST", "/attachments/refresh-urls", json={"attachment_urls": [url]})
        refreshed = body(r)
        findings: dict[str, Any] = {"shape": shape(refreshed)}
        try:
            new_url = refreshed["refreshed_urls"][0]["refreshed"]
            findings["refreshed_url"] = url_structure(new_url)
            findings["same_url"] = new_url == url
        except (KeyError, IndexError, TypeError):
            findings.update(error_summary(r))
        p.check("refresh_urls", "POST /attachments/refresh-urls", r, **findings)

    return {"forum": forum}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--guild", default=DEFAULT_GUILD)
    parser.add_argument("--channel", default=DEFAULT_CHANNEL, help="text channel for messages and pins")
    parser.add_argument("--forum", default=None, help="forum channel id (default: find 'help-center')")
    parser.add_argument("--delay", type=float, default=1.0, help="seconds between requests")
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
            extra = run(probe, args.guild, args.channel, args.forum)
        except DiscoopError as e:
            console.print(f"[red]Probe stopped:[/red] {e.message}")
            extra = {"stopped": f"{e.name}: {e.message}"}

    report = {
        "started_at": started.isoformat(timespec="seconds"),
        "duration_s": round((datetime.now(timezone.utc) - started).total_seconds(), 1),
        "targets": {"guild": args.guild, "channel": args.channel, **extra},
        "requests": probe.requests,
        "rate_limit_headers": sorted(h for h in probe.header_names if "ratelimit" in h or h == "retry-after"),
        "response_header_names": sorted(probe.header_names),
        "checks": probe.checks,
    }
    OUT_DIR.mkdir(exist_ok=True)
    path = OUT_DIR / f"probe-{started.strftime('%Y%m%d-%H%M%S')}.json"
    path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")

    table = Table(title="discoop probe")
    table.add_column("check")
    table.add_column("status")
    table.add_column("result")
    for c in probe.checks:
        detail = {k: v for k, v in c.items() if k in {"returned", "count", "threads", "total_results", "order", "skipped"}}
        table.add_row(c["check"], str(c["status"]), json.dumps(detail, ensure_ascii=False))
    console.print(table)
    console.print(f"Rate-limit headers seen: {report['rate_limit_headers'] or 'none'}")
    console.print(f"Report: [bold]{path}[/bold]")
    return 0


if __name__ == "__main__":
    sys.exit(main())
