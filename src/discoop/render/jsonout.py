"""The `json` and `jsonl` formats: normalized messages (docs/navrh-nastroja.md, section 6.2).

`json` is one object with the query, a summary per channel and the messages. `jsonl` has one message object per
line and nothing else; an export keeps the query and the summary in its manifest.

`attachments[].path` is where an export saved the file, relative to the export folder; it is null in console output
(the CDN `url` is valid for 12 to 24 hours) and for files that were not downloaded.
Unlike the `text` format, `links` keep every embed URL, also one the message text already has.
"""

import json
from collections.abc import Sequence
from datetime import datetime, tzinfo
from typing import Any

from discoop.models import ChannelMessages, Message
from discoop.render import Query
from discoop.snowflake import to_local


def header(results: Sequence[ChannelMessages], query: Query, tz: tzinfo | None = None) -> dict[str, Any]:
    """The query and a summary per channel: everything of `document` except the messages."""
    window = query.window
    return {
        "from": None if window.start is None else iso_time(window.start, tz),
        "to": iso_time(window.end, tz),
        "last": query.last,
        "truncated": any(r.truncated for r in results),
        "channels": [
            {
                "server": {"id": r.server.id, "name": r.server.name},
                "channel": {"id": r.channel.id, "name": r.channel.name},
                "messages": len(r.messages),
                "files": r.file_count,
                "truncated": r.truncated,
            }
            for r in results
        ],
    }


def document(results: Sequence[ChannelMessages], query: Query, tz: tzinfo | None = None) -> dict[str, Any]:
    return header(results, query, tz) | {"messages": [message(m, r, tz) for r in results for m in r.messages]}


def dumps(results: Sequence[ChannelMessages], query: Query, tz: tzinfo | None = None, indent: int | None = None) -> str:
    return json.dumps(document(results, query, tz), ensure_ascii=False, indent=indent)


def lines(results: Sequence[ChannelMessages], tz: tzinfo | None = None) -> list[str]:
    """The `jsonl` format: one compact JSON message per line."""
    return [json.dumps(message(m, r, tz), ensure_ascii=False) for r in results for m in r.messages]


def message(m: Message, where: ChannelMessages, tz: tzinfo | None = None) -> dict[str, Any]:
    return {
        "id": m.id,
        "type": m.type,
        "server": {"id": where.server.id, "name": where.server.name},
        "channel": {"id": where.channel.id, "name": where.channel.name},
        "thread": None,
        "time": iso_time(m.time, tz),
        "edited": None if m.edited is None else iso_time(m.edited, tz),
        "author": {"id": m.author.id, "name": m.author.name, "username": m.author.username, "bot": m.author.bot},
        "text": m.text,
        "reply_to": None
        if m.reply_to is None
        else {"id": m.reply_to.id, "author": m.reply_to.author, "text": m.reply_to.text},
        "attachments": [
            {"id": a.id, "filename": a.filename, "type": a.type, "size": a.size, "url": a.url, "path": a.path}
            for a in m.attachments
        ],
        "links": [
            {"kind": link.kind, "url": link.url, "title": link.title, "description": link.description}
            for link in m.links
        ],
        # `count` includes the super reactions, `super` says how many of them there are.
        "reactions": [{"emoji": r.emoji, "count": r.count, "super": r.burst} for r in m.reactions],
        "stickers": list(m.stickers),
        "pinned": m.pinned,
        "forwarded": m.forwarded,
        "has_thread": m.thread is not None,
    }


def iso_time(when: datetime, tz: tzinfo | None = None) -> str:
    return to_local(when, tz).isoformat(timespec="seconds")
