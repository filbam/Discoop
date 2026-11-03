"""The `text` format (docs/navrh-nastroja.md, section 6.2): compact for agents, the same layout with colors for humans,
and as Markdown (`md`, used by exports).

    === VUT FIT / #isc-public ===
    range: 2026-11-02 12:00 .. 2026-11-03 12:00 (UTC+01:00) | messages: 2 | files: 1

    [2026-11-02 14:03] Student A (@student_a) reply-to Student B: "kedy je deadline…"
    Do piatku 23:59, zadanie je v prílohe. https://www.fit.vut.cz/study/
      [file] zadanie.pdf 412KB https://cdn.discordapp.com/attachments/...
      [link] "Studium"
      [reactions] ✅3 🔥5 (2 super)

An embed does not repeat a URL the message already shows: `[link] "Studium"` above is the preview of the URL
in the text, and an image posted as a bare URL (an embed without a title) gets no embed line at all.
The `json` format keeps every embed URL.

A file saved by an export shows its path instead of the URL: `[file] zadanie.pdf 412KB files/isc-public/<id>_zadanie.pdf`.

Markdown has the same lines with a `# server / #channel` heading, a blank line between messages and `- ` instead of
the two-space indent, so the details form a list. A saved file is a link, an image is shown inline:
`- [file] ![graf.png](files/isc-public/<id>_graf.png) 120KB`. Message texts stay as they are: Discord uses Markdown.
"""

import re
from collections.abc import Sequence
from datetime import datetime, tzinfo

from rich.style import Style
from rich.text import Text

from discoop.models import REGULAR_MESSAGE_TYPES, Attachment, ChannelMessages, Link, Message, Reaction
from discoop.render import Query
from discoop.snowflake import to_local

Segment = tuple[str, str | Style | None]  # text and a Rich style (ignored in plain output)
Line = list[Segment]

_LINK_TAGS = {"link": "link", "article": "link", "gifv": "gif", "image": "image", "video": "video", "rich": "embed"}
_URL = re.compile(r"https?://[^\s<>]+")
_AFTER_URL = ".,;:!?)]}'\""  # punctuation that may follow a URL in a sentence or a Markdown link


def lines(
    results: Sequence[ChannelMessages],
    query: Query,
    tz: tzinfo | None = None,
    spaced: bool = False,
    markdown: bool = False,
    link_prefix: str = "",
) -> list[Line]:
    """All output lines. `spaced` puts a blank line between messages (human mode, Markdown).

    `markdown` gives the `md` layout; `link_prefix` goes in front of saved file paths there (`../` for channels/*.md).
    """
    out: list[Line] = []
    for index, result in enumerate(results):
        if index:
            out.append([])
        title = f"{result.server.name} / #{result.channel.name}"
        out.append([(f"# {title}" if markdown else f"=== {title} ===", "bold")])
        out.append([(_summary(result, query, tz), "dim")])
        out.append([])
        if not result.messages:
            out.append([("(no messages)", "dim")])
        for number, message in enumerate(result.messages):
            if spaced and number:
                out.append([])
            out += _message(message, tz, markdown, link_prefix)
    return out


def plain(results: Sequence[ChannelMessages], query: Query, tz: tzinfo | None = None) -> str:
    return "\n".join("".join(text for text, _ in line) for line in lines(results, query, tz))


def styled(results: Sequence[ChannelMessages], query: Query, tz: tzinfo | None = None) -> Text:
    rendered = [
        Text.assemble(*((text, style or "") for text, style in line)) for line in lines(results, query, tz, spaced=True)
    ]
    return Text("\n").join(rendered)


def markdown(results: Sequence[ChannelMessages], query: Query, tz: tzinfo | None = None, link_prefix: str = "") -> str:
    """The `md` format. `link_prefix` is put in front of saved file paths, e.g. `../` for a file in channels/."""
    out = lines(results, query, tz, spaced=True, markdown=True, link_prefix=link_prefix)
    return "\n".join("".join(text for text, _ in line) for line in out)


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


def _message(message: Message, tz: tzinfo | None, markdown: bool = False, link_prefix: str = "") -> list[Line]:
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
    bullet = "- " if markdown else "  "  # Markdown: the details are a list under the message
    for attachment in message.attachments:
        out.append(_attachment(attachment, bullet, markdown, link_prefix))
    shown = _urls(message.text)
    for link in message.links:
        out += _link(link, shown, bullet)
    for sticker in message.stickers:
        out.append([(f"{bullet}[sticker] ", "green"), (sticker, None)])
    if message.thread:
        count = f" {message.thread.message_count} messages" if message.thread.message_count is not None else ""
        out.append([(f"{bullet}[thread] ", "green"), (f'"{message.thread.name}"{count}', None)])
    if message.reactions:
        out.append([(f"{bullet}[reactions] ", "green"), (" ".join(_reaction(r) for r in message.reactions), None)])
    return out


def _attachment(attachment: Attachment, bullet: str, markdown: bool, link_prefix: str) -> Line:
    """`[file] name size` and where it is: the saved file's path, or the Discord URL when it was not saved."""
    line: Line = [(f"{bullet}[file] ", "green")]
    size = size_label(attachment.size)
    if attachment.path is None:
        url = attachment.url
        return line + [(f"{attachment.filename} {size} ", None), (url, Style(dim=True, link=url or None))]
    if not markdown:
        return line + [(f"{attachment.filename} {size} ", None), (attachment.path, "dim")]
    image = "!" if (attachment.type or "").startswith("image/") else ""
    target = _link_target(link_prefix + attachment.path)
    return line + [(f"{image}[{_link_label(attachment.filename)}]({target}) {size}", None)]


def _link_label(text: str) -> str:
    """Markdown link text: brackets and backslashes escaped."""
    return text.replace("\\", "\\\\").replace("[", "\\[").replace("]", "\\]")


def _link_target(path: str) -> str:
    """Markdown link destination; `<...>` keeps spaces and parentheses in file names working."""
    return f"<{path}>" if any(char in path for char in " ()") else path


def _link(link: Link, shown: set[str], bullet: str = "  ") -> list[Line]:
    """One embed. A URL already in `shown` (the text or an earlier embed) is left out, a new one is added there.

    An embed with nothing left to show (no title, no description) gives no line at all.
    """
    url = None if link.url in shown else link.url
    if link.url:
        shown.add(link.url)
    parts = [part for part in (url, f'"{link.title}"' if link.title else None) if part]
    if not parts and not link.description:
        return []
    head: Line = [(f"{bullet}[{_LINK_TAGS.get(link.kind, link.kind)}]", "blue")]
    if parts:
        head.append((" " + " ".join(parts), None))
    out = [head]
    if link.description:
        out += [[(f"    {text_line}", None)] for text_line in link.description.split("\n")]
    return out


def _urls(text: str) -> set[str]:
    """URLs written in a message text, each also without the punctuation right after it."""
    found = _URL.findall(text)
    return {*found, *(url.rstrip(_AFTER_URL) for url in found)}


def _reaction(reaction: Reaction) -> str:
    """`✅3`, with super reactions `🔥5 (2 super)`: 5 in all, 2 of them super."""
    return f"{reaction.emoji}{reaction.count}" + (f" ({reaction.burst} super)" if reaction.burst else "")


def _time(when: datetime, tz: tzinfo | None) -> str:
    return to_local(when, tz).strftime("%Y-%m-%d %H:%M")


def _zone(when: datetime) -> str:
    offset = when.strftime("%z")  # +0100
    return f"UTC{offset[:3]}:{offset[3:]}" if offset else "UTC"


def size_label(size: int) -> str:
    if size < 1024:
        return f"{size}B"
    if size < 1024 * 1024:
        return f"{round(size / 1024)}KB"
    return f"{size / (1024 * 1024):.1f}MB"
