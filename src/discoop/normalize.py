"""Raw Discord message JSON into models.Message, with mentions and markup turned into readable text.

Rewrites (docs/navrh-nastroja.md, section 6.2): `<@id>` → `@name`, `<#id>` → `#channel`,
`<@&id>` → `@role:<id>` (role names are not fetched), `<:name:id>` → `:name:`,
`<t:unix:style>` → local time, `</command:id>` → `/command`. Blank lines at the start and the end of a text
are dropped, so they cannot pile up between messages in the output.
"""

import re
from collections.abc import Iterable, Mapping
from datetime import UTC, datetime, tzinfo
from typing import Any

from discoop.models import Attachment, Author, Link, Message, Reaction, ReplyTo, StartedThread
from discoop.snowflake import to_local, to_time

REPLY = 19
EXCERPT_LENGTH = 80
_FORWARD = 1  # message_reference.type of a forwarded message
_MARKUP = re.compile(
    r"<(?P<kind>@!?|@&|#)(?P<id>\d+)>"
    r"|<a?:(?P<emoji>\w+):\d+>"
    r"|<t:(?P<unix>-?\d+)(?::[tTdDfFsSR])?>"
    r"|</(?P<command>[\w -]+):\d+>"
)
_BLANK_EDGES = re.compile(r"\A(?:[^\S\n]*\n)+|\s+\Z")  # blank lines at the start, any whitespace at the end


def display_name(user: Mapping[str, Any]) -> str:
    return user.get("global_name") or user.get("username") or "?"


def known_users(messages: Iterable[Mapping[str, Any]]) -> dict[str, str]:
    """User ID → display name from authors and mentions, also those of replied-to messages."""
    users: dict[str, str] = {}
    for message in messages:
        for item in (message, message.get("referenced_message") or {}):
            for user in [item.get("author") or {}, *(item.get("mentions") or [])]:
                if user.get("id"):
                    users[user["id"]] = display_name(user)
    return users


class Normalizer:
    def __init__(self, channels: Mapping[str, str], users: Mapping[str, str], tz: tzinfo | None = None) -> None:
        self.channels = channels  # channel ID → name, for <#id>
        self.users = users
        self.tz = tz

    def message(self, data: Mapping[str, Any]) -> Message:
        text = self.text(data.get("content") or "")
        attachments = [_attachment(a) for a in data.get("attachments") or []]
        links = [self._link(e) for e in data.get("embeds") or []]
        reference = data.get("message_reference") or {}
        forwarded = reference.get("type") == _FORWARD and bool(data.get("message_snapshots"))
        snapshots = data.get("message_snapshots") if forwarded else None
        for snapshot in snapshots or []:
            original = snapshot.get("message") or {}
            text = "\n".join(t for t in (text, self.text(original.get("content") or "")) if t)
            attachments += [_attachment(a) for a in original.get("attachments") or []]
            links += [self._link(e) for e in original.get("embeds") or []]
        thread = data.get("thread")
        return Message(
            id=data["id"],
            type=int(data.get("type", 0)),
            time=_parse_time(data.get("timestamp")) or to_time(data["id"]),
            edited=_parse_time(data.get("edited_timestamp")),
            author=_author(data.get("author") or {}),
            text=text,
            reply_to=self._reply(data) if data.get("type") == REPLY else None,
            attachments=tuple(attachments),
            links=tuple(link for link in links if link.url or link.title or link.description),
            reactions=tuple(_reaction(r) for r in data.get("reactions") or []),
            stickers=tuple(s.get("name") or "?" for s in data.get("sticker_items") or []),
            pinned=bool(data.get("pinned")),
            forwarded=forwarded,
            thread=StartedThread(thread["id"], thread.get("name") or "", thread.get("message_count"))
            if thread
            else None,
        )

    def text(self, content: str) -> str:
        """Readable text: markup rewritten, line ends as \\n, no blank lines at the start or the end."""
        return _BLANK_EDGES.sub("", _MARKUP.sub(self._replace, content.replace("\r\n", "\n")))

    def _replace(self, match: re.Match[str]) -> str:
        kind, item_id = match.group("kind"), match.group("id")
        if kind == "#":
            return "#" + self.channels.get(item_id, f"channel:{item_id}")
        if kind == "@&":
            return f"@role:{item_id}"
        if kind:
            return "@" + self.users.get(item_id, f"user:{item_id}")
        if match.group("emoji"):
            return f":{match.group('emoji')}:"
        if match.group("unix"):
            when = datetime.fromtimestamp(int(match.group("unix")), tz=UTC)
            return to_local(when, self.tz).strftime("%Y-%m-%d %H:%M")
        return "/" + match.group("command")

    def _reply(self, data: Mapping[str, Any]) -> ReplyTo:
        original = data.get("referenced_message")
        reference_id = (data.get("message_reference") or {}).get("message_id") or ""
        if not original:
            return ReplyTo(reference_id, None, None)
        author = display_name(original.get("author") or {})
        return ReplyTo(original.get("id") or reference_id, author, excerpt(self.text(original.get("content") or "")))

    def _link(self, embed: Mapping[str, Any]) -> Link:
        kind = embed.get("type") or "rich"
        description = None
        if kind == "rich":
            fields = [f"{f.get('name', '')}: {f.get('value', '')}" for f in embed.get("fields") or []]
            parts = [self.text(part) for part in (embed.get("description") or "", *fields)]
            description = "\n".join(part for part in parts if part) or None
        return Link(kind, embed.get("url"), embed.get("title"), description)


def excerpt(text: str, length: int = EXCERPT_LENGTH) -> str:
    flat = " ".join(text.split())
    return flat if len(flat) <= length else flat[: length - 1].rstrip() + "…"


def _author(user: Mapping[str, Any]) -> Author:
    return Author(
        id=user.get("id") or "",
        name=display_name(user),
        username=user.get("username") or "?",
        bot=bool(user.get("bot")),
    )


def _attachment(data: Mapping[str, Any]) -> Attachment:
    return Attachment(
        id=data.get("id") or "",
        filename=data.get("filename") or "file",
        type=data.get("content_type"),
        size=int(data.get("size") or 0),
        url=data.get("url") or "",
    )


def _reaction(data: Mapping[str, Any]) -> Reaction:
    """One entry per emoji; super reactions are a part of its count (docs/analyzy/discord-analyza.md, section 4)."""
    emoji = data.get("emoji") or {}
    name = emoji.get("name") or "?"
    burst = (data.get("count_details") or {}).get("burst", data.get("burst_count"))
    return Reaction(f":{name}:" if emoji.get("id") else name, int(data.get("count") or 0), int(burst or 0))


def _parse_time(raw: str | None) -> datetime | None:
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw)
    except ValueError:
        return None
