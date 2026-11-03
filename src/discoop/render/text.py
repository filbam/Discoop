"""The `text` format (docs/navrh-nastroja.md, section 6.2): compact for agents, the same layout with colors for humans.

    === VUT FIT / #isc-public ===
    range: 2026-11-02 12:00 .. 2026-11-03 12:00 (UTC+01:00) | messages: 2 | files: 1

    [2026-11-02 14:03] Student A (@student_a) reply-to Student B: "kedy je deadline…"
    Do piatku 23:59, zadanie je v prílohe.
      [file] zadanie.pdf 412KB https://cdn.discordapp.com/attachments/...
      [reactions] ✅3 👍1
"""

from collections.abc import Sequence
from datetime import datetime, tzinfo

from rich.style import Style
from rich.text import Text

from discoop.models import REGULAR_MESSAGE_TYPES, ChannelMessages, Link, Message
from discoop.render import Query
from discoop.snowflake import to_local

Segment = tuple[str, str | Style | None]  # text and a Rich style (ignored in plain output)
Line = list[Segment]

_LINK_TAGS = {"link": "link", "article": "link", "gifv": "gif", "image": "image", "video": "video", "rich": "embed"}


def lines(
    results: Sequence[ChannelMessages], query: Query, tz: tzinfo | None = None, spaced: bool = False
) -> list[Line]:
    """All output lines. `spaced` puts a blank line between messages (human mode)."""
    out: list[Line] = []
    for index, result in enumerate(results):
        if index:
            out.append([])
        out.append([(f"=== {result.server.name} / #{result.channel.name} ===", "bold")])
        out.append([(_summary(result, query, tz), "dim")])
        out.append([])
        if not result.messages:
            out.append([("(no messages)", "dim")])
        for number, message in enumerate(result.messages):
            if spaced and number:
                out.append([])
            out += _message(message, tz)
    return out


def plain(results: Sequence[ChannelMessages], query: Query, tz: tzinfo | None = None) -> str:
    return "\n".join("".join(text for text, _ in line) for line in lines(results, query, tz))


def styled(results: Sequence[ChannelMessages], query: Query, tz: tzinfo | None = None) -> Text:
    rendered = [
        Text.assemble(*((text, style or "") for text, style in line)) for line in lines(results, query, tz, spaced=True)
    ]
    return Text("\n").join(rendered)



def _summary(result: ChannelMessages, query: Query, tz: tzinfo | None) -> str:
    window = query.window
    start = "all" if window.start is None else _time(window.start, tz)
    end = to_local(window.end, tz)
    parts = [f"range: {start} .. {_time(end, tz)} ({_zone(end)})"]
    if query.last is not None:
        parts.append(f"last: {query.last}")
    parts.append(f"messages: {len(result.messages)}")
    parts.append(f"files: {result.file_count}")
    if result.truncated:
        parts.append(f"truncated: yes (--max-messages {query.max_messages})")
    return " | ".join(parts)


def _message(message: Message, tz: tzinfo | None) -> list[Line]:
    author = message.author
    head: Line = [(f"[{_time(message.time, tz)}] ", "dim")]
    name = f"@{author.username}" if author.name == author.username else f"{author.name} (@{author.username})"
    head.append((name, "bold cyan"))
    if author.bot:
        head.append((" [bot]", "magenta"))
    if message.type not in REGULAR_MESSAGE_TYPES:
        head.append((f" (system message, type {message.type})", "yellow"))
    if message.forwarded:
        head.append((" (forwarded)", "yellow"))
    if message.edited:
        head.append((" (edited)", "dim"))
    if message.pinned:
        head.append((" (pinned)", "yellow"))
    if message.reply_to:
        reply = message.reply_to
        if reply.author is None:
            head.append((" reply-to (message not available)", "dim italic"))
        else:
            quote = f': "{reply.text}"' if reply.text else ""
            head.append((f" reply-to {reply.author}{quote}", "dim italic"))
    out = [head]
    out += [[(text_line, None)] for text_line in message.text.split("\n")] if message.text else []
    for attachment in message.attachments:
        out.append(
            [
                ("  [file] ", "green"),
                (f"{attachment.filename} {_size(attachment.size)} ", None),
                (attachment.url, Style(dim=True, link=attachment.url or None)),
            ]
        )
    for link in message.links:
        out += _link(link)
    for sticker in message.stickers:
        out.append([("  [sticker] ", "green"), (sticker, None)])
    if message.thread:
        count = f" {message.thread.message_count} messages" if message.thread.message_count is not None else ""
        out.append([("  [thread] ", "green"), (f'"{message.thread.name}"{count}', None)])
    if message.reactions:
        out.append([("  [reactions] ", "green"), (" ".join(f"{r.emoji}{r.count}" for r in message.reactions), None)])
    return out


def _link(link: Link) -> list[Line]:
    parts = [part for part in (link.url, f'"{link.title}"' if link.title else None) if part]
    out: list[Line] = [[(f"  [{_LINK_TAGS.get(link.kind, link.kind)}] ", "blue"), (" ".join(parts), None)]]
    if link.description:
        out += [[(f"    {text_line}", None)] for text_line in link.description.split("\n")]
    return out


def _time(when: datetime, tz: tzinfo | None) -> str:
    return to_local(when, tz).strftime("%Y-%m-%d %H:%M")


def _zone(when: datetime) -> str:
    offset = when.strftime("%z")  # +0100
    return f"UTC{offset[:3]}:{offset[3:]}" if offset else "UTC"


def _size(size: int) -> str:
    if size < 1024:
        return f"{size}B"
    if size < 1024 * 1024:
        return f"{round(size / 1024)}KB"
    return f"{size / (1024 * 1024):.1f}MB"
