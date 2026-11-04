"""Plain data the commands work with: servers, channels and threads as cached locally, and messages."""

from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from discoop.snowflake import to_time

CHANNEL_TYPES = {
    0: "text",
    2: "voice",
    4: "category",
    5: "announcement",
    10: "announcement-thread",
    11: "thread",
    12: "private-thread",
    13: "stage",
    14: "directory",
    15: "forum",
    16: "media",
}
CATEGORY = 4
FORUM = 15
MEDIA = 16
# Channel types of threads: announcement thread, public thread (also every forum and media post), private thread.
THREAD_TYPES = {10, 11, 12}
# Channels whose posts are all threads.
FORUM_TYPES = {FORUM, MEDIA}
# Channels that can hold threads: text, announcement, forum and media channels.
THREAD_CONTAINER_TYPES = {0, 5, FORUM, MEDIA}
# Types `channels --type` accepts: everything /guilds/{id}/channels returns except categories.
LISTABLE_TYPES = {name: number for number, name in CHANNEL_TYPES.items() if number in {0, 2, 5, 13, 14, 15, 16}}
# Channels whose messages `messages` reads: text, voice and stage chat, announcements, threads.
MESSAGE_TYPES = {0, 2, 5, 10, 11, 12, 13}
# Message types that are not system messages: normal, reply, bot answers to slash and context-menu commands.
REGULAR_MESSAGE_TYPES = {0, 19, 20, 23}
_VOICE_LIKE = {2, 13}
_HIDDEN_FLAG = 1 << 17


@dataclass(frozen=True)
class Server:
    id: str
    name: str
    member_count: int | None = None


@dataclass(frozen=True)
class ForumTag:
    """A tag a forum offers for its posts (`available_tags`); posts carry the tag IDs (`applied_tags`)."""

    id: str
    name: str


@dataclass(frozen=True)
class Channel:
    id: str
    server_id: str
    name: str
    type: int
    parent_id: str | None = None
    position: int = 0
    topic: str | None = None
    # [OVERENÉ 2026-11-04] present on most channels (385 of 412) and equal to the newest message in 2 of 2 samples.
    # In a forum it is the ID of the newest post (a thread), not of a message.
    last_message_id: str | None = None
    available_tags: tuple[ForumTag, ...] = ()  # forums and media channels only

    @property
    def type_name(self) -> str:
        return CHANNEL_TYPES.get(self.type, f"type-{self.type}")

    def sort_key(self) -> tuple[int, int, int]:
        """Discord's sidebar order: text-like channels above voice ones, then position, then ID."""
        return (self.type in _VOICE_LIKE, self.position, int(self.id))

    def tag_names(self, tag_ids: Iterable[str]) -> tuple[str, ...]:
        """Names of the given tag IDs (a post's `applied_tags`); IDs the channel does not list any more are left out."""
        names = {tag.id: tag.name for tag in self.available_tags}
        return tuple(names[tag_id] for tag_id in tag_ids if tag_id in names)


def server_from_api(data: dict[str, Any]) -> Server:
    return Server(id=data["id"], name=data.get("name") or "", member_count=data.get("approximate_member_count"))


def channel_from_api(data: dict[str, Any], server_id: str) -> Channel:
    return Channel(
        id=data["id"],
        server_id=server_id,
        name=data.get("name") or "",
        type=int(data.get("type", 0)),
        parent_id=data.get("parent_id"),
        position=int(data.get("position") or 0),
        topic=data.get("topic"),
        last_message_id=_text_or_none(data.get("last_message_id")),
        available_tags=_tags_from_api(data.get("available_tags")),
    )


def _text_or_none(value: Any) -> str | None:
    return str(value) if value else None


def _tags_from_api(raw: Any) -> tuple[ForumTag, ...]:
    """Forum tags `{id, name, ...}`; entries without an ID are dropped, a missing list is no tags."""
    if not isinstance(raw, list):
        return ()
    tags = (tag for tag in raw if isinstance(tag, dict) and tag.get("id"))
    return tuple(ForumTag(str(tag["id"]), tag.get("name") or "") for tag in tags)


@dataclass(frozen=True)
class Thread:
    """A thread or a forum post, as listed by `threads/search` (docs/analyses/discord-analysis.md, section 6).

    A thread is a channel of its own: its messages are read from `/channels/{id}/messages`. In a forum the post
    and its first message share the ID.
    """

    id: str
    parent_id: str  # the text, announcement, forum or media channel that holds it
    name: str
    # 11 public thread, forum posts too [OVERENÉ]; 10 announcement thread, 12 private thread [PREDPOKLAD]: not seen yet
    type: int
    created: datetime  # `thread_metadata.create_timestamp`, else the time in the ID; timezone-aware (UTC)
    last_activity: datetime  # time of `last_message_id`, never before `created`; timezone-aware (UTC)
    archived: bool = False
    locked: bool = False
    # Not counting the first message. [PREDPOKLAD] Discord's number is inaccurate above 50 for old threads.
    message_count: int | None = None
    owner_id: str | None = None
    applied_tags: tuple[str, ...] = ()  # forum tag IDs, see `Channel.tag_names`
    last_message_id: str | None = None

    @property
    def type_name(self) -> str:
        return CHANNEL_TYPES.get(self.type, f"type-{self.type}")

    def as_channel(self, server_id: str) -> Channel:
        """The thread as a channel, to read its messages like those of any other channel."""
        return Channel(
            self.id, server_id, self.name, self.type, parent_id=self.parent_id, last_message_id=self.last_message_id
        )


def thread_from_api(data: dict[str, Any], parent_id: str | None = None) -> Thread:
    """A thread from a channel object of type 10, 11 or 12.

    Only `id` is required (a missing or non-numeric one raises KeyError or ValueError); everything else falls back:
    `parent_id` to the argument, the times to the snowflakes, flags and counts to False and None.
    """
    thread_id = str(data["id"])
    metadata = data.get("thread_metadata")
    if not isinstance(metadata, dict):
        metadata = {}
    created = _aware_time(metadata.get("create_timestamp")) or to_time(thread_id)  # null in threads from before 2022
    last_message_id = _text_or_none(data.get("last_message_id"))
    last_activity = max(created, to_time(last_message_id)) if last_message_id else created
    message_count = data.get("message_count")
    tags = data.get("applied_tags")
    return Thread(
        id=thread_id,
        parent_id=str(data.get("parent_id") or parent_id or ""),
        name=data.get("name") or "",
        type=data["type"] if isinstance(data.get("type"), int) else 11,
        created=created,
        last_activity=last_activity,
        archived=bool(metadata.get("archived")),
        locked=bool(metadata.get("locked")),
        message_count=message_count if isinstance(message_count, int) else None,
        owner_id=_text_or_none(data.get("owner_id")),
        applied_tags=tuple(str(tag) for tag in tags) if isinstance(tags, list) else (),
        last_message_id=last_message_id,
    )


def _aware_time(raw: Any) -> datetime | None:
    """An ISO 8601 timestamp as a timezone-aware datetime (no zone means UTC); None if it is missing or unreadable."""
    if not isinstance(raw, str) or not raw:
        return None
    try:
        when = datetime.fromisoformat(raw)
    except ValueError:
        return None
    return when if when.tzinfo else when.replace(tzinfo=UTC)


def group_by_category(channels: Iterable[Channel]) -> list[tuple[Channel | None, list[Channel]]]:
    """Sidebar layout: channels without a category first, then each category in order."""
    channels = list(channels)
    categories = sorted((c for c in channels if c.type == CATEGORY), key=lambda c: (c.position, int(c.id)))
    category_ids = {c.id for c in categories}
    children: dict[str | None, list[Channel]] = defaultdict(list)
    for channel in channels:
        if channel.type != CATEGORY:
            children[channel.parent_id if channel.parent_id in category_ids else None].append(channel)
    groups: list[tuple[Channel | None, list[Channel]]] = [(None, sorted(children[None], key=Channel.sort_key))]
    groups += [(category, sorted(children[category.id], key=Channel.sort_key)) for category in categories]
    return groups


def is_hidden(data: dict[str, Any]) -> bool:
    """Channels the client gets obfuscated (docs/analyses/discord-analysis.md, section 3)."""
    return data.get("name") == "___hidden___" or bool((data.get("flags") or 0) & _HIDDEN_FLAG)


# Messages, normalized for output (docs/design.md, section 6.2). Built by discoop.normalize.


@dataclass(frozen=True)
class Author:
    id: str
    name: str  # global_name, else username
    username: str
    bot: bool = False


@dataclass(frozen=True)
class Attachment:
    id: str
    filename: str
    type: str | None
    size: int
    url: str
    path: str | None = None  # where an export saved the file, relative to the export folder (POSIX separators)


@dataclass(frozen=True)
class Link:
    kind: str  # embed type: link, article, video, gifv, image, rich, ...
    url: str | None
    title: str | None
    description: str | None = None  # only kept for rich embeds (bots post text there)


@dataclass(frozen=True)
class Reaction:
    emoji: str
    count: int  # everyone who reacted with this emoji, super reactions included
    burst: int = 0  # of those, super reactions (`count_details.burst` in the API)


@dataclass(frozen=True)
class ReplyTo:
    id: str
    author: str | None  # None when Discord did not send the original message
    text: str | None


@dataclass(frozen=True)
class StartedThread:
    id: str
    name: str
    message_count: int | None


@dataclass(frozen=True)
class Message:
    id: str
    type: int
    time: datetime
    edited: datetime | None
    author: Author
    text: str
    reply_to: ReplyTo | None = None
    attachments: tuple[Attachment, ...] = ()
    links: tuple[Link, ...] = ()
    reactions: tuple[Reaction, ...] = ()
    stickers: tuple[str, ...] = ()
    pinned: bool = False
    forwarded: bool = False
    thread: StartedThread | None = None  # a thread started from this message


@dataclass(frozen=True)
class ChannelMessages:
    """What `messages` fetched from one channel.

    A channel's threads (the posts of a forum, the threads of a text channel) are nested in `threads`, one
    `ChannelMessages` each, so a channel and its threads form one unit for rendering and for an export:

        thread_result = ChannelMessages(server, thread.as_channel(server.id), items, truncated, thread=thread)
        channel_result = ChannelMessages(server, channel, items, truncated, threads=(thread_result, ...))

    The `channel` of a nested item is the thread as a channel (`Thread.as_channel`: `parent_id` is the channel that
    holds it, type 10, 11 or 12); `thread` carries the rest of what is known about it (times, flags, forum tag IDs;
    the tag names come from the parent's `Channel.available_tags`). A thread has no threads of its own.
    `threads` are rendered and exported in the given order; a caller should sort them (oldest first).
    A forum channel itself has no messages: its `messages` stay empty and everything is in `threads`.
    """

    server: Server
    channel: Channel
    messages: tuple[Message, ...]
    truncated: bool = False  # stopped at --max-messages, older messages in the window are missing
    threads: tuple["ChannelMessages", ...] = ()
    thread: Thread | None = None  # only on a nested item: the thread's metadata

    @property
    def file_count(self) -> int:
        """Files of the channel and of its threads: they are all downloaded with it."""
        return sum(len(m.attachments) for m in self.messages) + sum(t.file_count for t in self.threads)

    @property
    def thread_message_count(self) -> int:
        """Messages in the threads, not counting those of the channel itself."""
        return sum(len(t.messages) for t in self.threads)

    @property
    def total_messages(self) -> int:
        """Messages of the channel and of its threads: the lines it adds to `messages.jsonl`."""
        return len(self.messages) + self.thread_message_count

    @property
    def any_truncated(self) -> bool:
        """True if the channel or any of its threads stopped at --max-messages."""
        return self.truncated or any(t.truncated for t in self.threads)

    def parts(self) -> tuple["ChannelMessages", ...]:
        """The channel itself, then its threads: every place that holds messages, in output order."""
        return (self, *self.threads)
