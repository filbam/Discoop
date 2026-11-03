"""The `json` format: one object with the query, a summary per channel and the normalized messages.

Message schema follows docs/navrh-nastroja.md, section 6.2. Attachments have no local `path` yet:
console output only lists their CDN URL (valid 12 to 24 h); downloading comes with --out/--zip.
"""

import json
from collections.abc import Sequence
from datetime import datetime, tzinfo
from typing import Any

from discoop.models import ChannelMessages, Message
from discoop.render import Query
from discoop.snowflake import to_local


def document(results: Sequence[ChannelMessages], query: Query, tz: tzinfo | None = None) -> dict[str, Any]:
    window = query.window
    return {
        "from": None if window.start is None else _time(window.start, tz),
        "to": _time(window.end, tz),
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
        "messages": [message(m, r, tz) for r in results for m in r.messages],
    }


def dumps(results: Sequence[ChannelMessages], query: Query, tz: tzinfo | None = None, indent: int | None = None) -> str:
    return json.dumps(document(results, query, tz), ensure_ascii=False, indent=indent)


def message(m: Message, where: ChannelMessages, tz: tzinfo | None = None) -> dict[str, Any]:
    return {
        "id": m.id,
        "type": m.type,
        "server": {"id": where.server.id, "name": where.server.name},
        "channel": {"id": where.channel.id, "name": where.channel.name},
        "thread": None,
        "time": _time(m.time, tz),
        "edited": None if m.edited is None else _time(m.edited, tz),
        "author": {"id": m.author.id, "name": m.author.name, "username": m.author.username, "bot": m.author.bot},
        "text": m.text,
        "reply_to": None
        if m.reply_to is None
        else {"id": m.reply_to.id, "author": m.reply_to.author, "text": m.reply_to.text},
        "attachments": [
            {"id": a.id, "filename": a.filename, "type": a.type, "size": a.size, "url": a.url} for a in m.attachments
        ],
        "links": [
            {"kind": link.kind, "url": link.url, "title": link.title, "description": link.description}
            for link in m.links
        ],
        "reactions": [{"emoji": r.emoji, "count": r.count} for r in m.reactions],
        "stickers": list(m.stickers),
        "pinned": m.pinned,
        "forwarded": m.forwarded,
        "has_thread": m.thread is not None,
    }


def _time(when: datetime, tz: tzinfo | None) -> str:
    return to_local(when, tz).isoformat(timespec="seconds")
