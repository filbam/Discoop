"""The `json` and `jsonl` formats: normalized messages (docs/design.md, section 6.2).

`json` is one object with the query, a summary per channel and the messages. `jsonl` has one message object per
line and nothing else; an export keeps the query and the summary in its manifest.

`attachments[].path` is where an export saved the file, relative to the export folder; it is null in console output
(the CDN `url` is valid for 12 to 24 hours) and for files that were not downloaded.
Unlike the `text` format, `links` keep every embed URL, also one the message text already has.

Threads (forum posts, threads of text channels) are flat, never nested: the messages of a channel come first, then
those of each of its threads in the order of `ChannelMessages.threads`, one list. A message posted in a thread has

    "channel": {"id": <the channel that holds the thread>, "name": ...},
    "thread": {"id": <thread id>, "name": ..., "parent_id": <the same channel id>, "tags": ["Solved"]},

while `thread` is null for a message posted in the channel itself (it always was null before threads were fetched).
`tags` are the forum tag names of the post, an empty list outside forums. `has_thread` is true for a message that
started a thread and says nothing about where the message was posted; the two are independent.

In the summaries (`channels[]` here and in an export's manifest) `messages` counts the messages posted in the channel
itself, `files` also those of its threads, and `truncated` is true if the channel or one of its threads is. A channel
with threads adds `threads` (their number) and `thread_messages` (messages in all of them); without threads these
two keys are absent.
"""

import json
from collections.abc import Iterator, Sequence
from datetime import datetime, tzinfo
from typing import Any

from discoop.models import Channel, ChannelMessages, Message
from discoop.render import Query
from discoop.snowflake import to_local


def header(results: Sequence[ChannelMessages], query: Query, tz: tzinfo | None = None) -> dict[str, Any]:
    """The query and a summary per channel: everything of `document` except the messages."""
    window = query.window
    return {
        "from": None if window.start is None else iso_time(window.start, tz),
        "to": iso_time(window.end, tz),
        "last": query.last,
        "truncated": any(r.any_truncated for r in results),
        "channels": [_summary(r) for r in results],
    }


def _summary(r: ChannelMessages) -> dict[str, Any]:
    entry: dict[str, Any] = {
        "server": {"id": r.server.id, "name": r.server.name},
        "channel": {"id": r.channel.id, "name": r.channel.name},
        "messages": len(r.messages),
    }
    if r.threads:
        entry["threads"] = len(r.threads)
        entry["thread_messages"] = r.thread_message_count
    entry["files"] = r.file_count
    entry["truncated"] = r.any_truncated
    return entry


def document(results: Sequence[ChannelMessages], query: Query, tz: tzinfo | None = None) -> dict[str, Any]:
    messages = [message(m, where, tz, parent) for m, where, parent in _flat(results)]
    return header(results, query, tz) | {"messages": messages}


def dumps(results: Sequence[ChannelMessages], query: Query, tz: tzinfo | None = None, indent: int | None = None) -> str:
    return json.dumps(document(results, query, tz), ensure_ascii=False, indent=indent)


def lines(results: Sequence[ChannelMessages], tz: tzinfo | None = None) -> list[str]:
    """The `jsonl` format: one compact JSON message per line."""
    return [json.dumps(message(m, where, tz, parent), ensure_ascii=False) for m, where, parent in _flat(results)]


def _flat(results: Sequence[ChannelMessages]) -> Iterator[tuple[Message, ChannelMessages, ChannelMessages | None]]:
    """Every message with the place it was posted in and, for a thread, the channel that holds it: each channel's own
    messages, then those of its threads."""
    for result in results:
        for part in result.parts():
            parent = None if part is result else result
            for m in part.messages:
                yield m, part, parent


def message(
    m: Message, where: ChannelMessages, tz: tzinfo | None = None, parent: ChannelMessages | None = None
) -> dict[str, Any]:
    """One message. `where` is the channel or thread it was posted in; for a thread `parent` is the channel that holds
    it, which then is the `channel` of the message."""
    channel = where.channel if parent is None else parent.channel
    return {
        "id": m.id,
        "type": m.type,
        "server": {"id": where.server.id, "name": where.server.name},
        "channel": {"id": channel.id, "name": channel.name},
        "thread": None if parent is None else _thread(where, channel),
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


def _thread(where: ChannelMessages, parent: Channel) -> dict[str, Any]:
    tags = parent.tag_names(where.thread.applied_tags) if where.thread else ()
    return {"id": where.channel.id, "name": where.channel.name, "parent_id": parent.id, "tags": list(tags)}


def iso_time(when: datetime, tz: tzinfo | None = None) -> str:
    return to_local(when, tz).isoformat(timespec="seconds")
