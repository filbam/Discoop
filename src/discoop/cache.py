"""Local SQLite cache of servers, channels and threads, so names resolve without asking Discord every time.

The cache is disposable: login and logout delete it, and a schema change simply rebuilds it.

Schema 2 (schema 1 had no threads): channels also keep `last_message_id` and the forum tags, and `threads` holds
the threads of a parent channel. A list of threads is only valid for the part of history it was fetched for, so
`thread_lists` remembers where that part starts (`covered_from`), next to the usual `fetched` time.
"""

import json
import sqlite3
import time
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from discoop import paths
from discoop.models import Channel, ForumTag, Server, Thread
from discoop.snowflake import Window

SCHEMA_VERSION = 2
_SCHEMA = """
CREATE TABLE servers (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    member_count INTEGER
);
CREATE TABLE channels (
    id TEXT PRIMARY KEY,
    server_id TEXT NOT NULL,
    name TEXT NOT NULL,
    type INTEGER NOT NULL,
    parent_id TEXT,
    position INTEGER NOT NULL,
    topic TEXT,
    last_message_id TEXT,
    available_tags TEXT NOT NULL DEFAULT '[]'
);
CREATE INDEX channels_by_server ON channels (server_id);
CREATE TABLE threads (
    id TEXT PRIMARY KEY,
    parent_id TEXT NOT NULL,
    name TEXT NOT NULL,
    type INTEGER NOT NULL,
    created TEXT NOT NULL,
    last_activity TEXT NOT NULL,
    archived INTEGER NOT NULL,
    locked INTEGER NOT NULL,
    message_count INTEGER,
    owner_id TEXT,
    applied_tags TEXT NOT NULL,
    last_message_id TEXT
);
CREATE INDEX threads_by_parent ON threads (parent_id);
CREATE TABLE thread_lists (
    parent_id TEXT PRIMARY KEY,
    covered_from TEXT
);
CREATE TABLE fetched (
    what TEXT PRIMARY KEY,
    at REAL NOT NULL
);
"""
_CHANNEL_COLUMNS = "id, server_id, name, type, parent_id, position, topic, last_message_id, available_tags"
_THREAD_COLUMNS = (
    "id, parent_id, name, type, created, last_activity, archived, locked, message_count, owner_id, applied_tags,"
    " last_message_id"
)


def cache_path() -> Path:
    return paths.data_dir() / "cache.db"


def clear_cache() -> None:
    cache_path().unlink(missing_ok=True)


@dataclass(frozen=True)
class CachedThreads:
    """The cached threads of one parent channel and what they are good for."""

    threads: tuple[Thread, ...]  # newest activity first
    fetched_at: float  # Unix time
    covered_from: datetime | None  # the list holds every thread with activity since then; None: the whole history

    def age(self) -> float:
        """Seconds since the list was fetched."""
        return time.time() - self.fetched_at

    def covers(self, window: Window) -> bool:
        """Whether the list holds every thread that was active inside the window."""
        if self.covered_from is None:
            return True
        return window.start is not None and self.covered_from <= window.start


class Cache:
    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(path)
        self._migrate()

    @classmethod
    def default(cls) -> "Cache":
        return cls(cache_path())

    def __enter__(self) -> "Cache":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def close(self) -> None:
        self._db.close()

    def replace_servers(self, servers: Iterable[Server]) -> None:
        with self._db:
            self._db.execute("DELETE FROM servers")
            self._db.executemany(
                "INSERT INTO servers (id, name, member_count) VALUES (?, ?, ?)",
                [(s.id, s.name, s.member_count) for s in servers],
            )
            self._mark_fetched("servers")

    def servers(self) -> list[Server]:
        rows = self._db.execute("SELECT id, name, member_count FROM servers ORDER BY name COLLATE NOCASE, id")
        return [Server(*row) for row in rows]

    def replace_channels(self, server_id: str, channels: Iterable[Channel]) -> None:
        with self._db:
            self._db.execute("DELETE FROM channels WHERE server_id = ?", (server_id,))
            self._db.executemany(
                f"INSERT INTO channels ({_CHANNEL_COLUMNS}) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [
                    (
                        c.id,
                        c.server_id,
                        c.name,
                        c.type,
                        c.parent_id,
                        c.position,
                        c.topic,
                        c.last_message_id,
                        json.dumps([{"id": t.id, "name": t.name} for t in c.available_tags], ensure_ascii=False),
                    )
                    for c in channels
                ],
            )
            self._mark_fetched(f"channels:{server_id}")

    def channels(self, server_id: str) -> list[Channel]:
        rows = self._db.execute(f"SELECT {_CHANNEL_COLUMNS} FROM channels WHERE server_id = ?", (server_id,))
        return [_channel(row) for row in rows]

    def channel(self, channel_id: str) -> Channel | None:
        """A cached channel of any server."""
        row = self._db.execute(f"SELECT {_CHANNEL_COLUMNS} FROM channels WHERE id = ?", (channel_id,)).fetchone()
        return _channel(row) if row else None

    def replace_threads(self, parent_id: str, threads: Iterable[Thread], *, covered_from: datetime | None) -> None:
        """Store the threads of one parent channel, dropping the ones stored before (other parents are untouched).

        `covered_from` says what the list is complete for: every thread with activity at or after that time is in it.
        None means the whole history. An empty list is a valid answer ("no threads") and has an age too.
        """
        with self._db:
            self._db.execute("DELETE FROM threads WHERE parent_id = ?", (parent_id,))
            self._db.executemany(
                f"INSERT OR REPLACE INTO threads ({_THREAD_COLUMNS}) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [
                    (
                        t.id,
                        parent_id,
                        t.name,
                        t.type,
                        _to_text(t.created),
                        _to_text(t.last_activity),
                        int(t.archived),
                        int(t.locked),
                        t.message_count,
                        t.owner_id,
                        json.dumps(list(t.applied_tags)),
                        t.last_message_id,
                    )
                    for t in threads
                ],
            )
            self._db.execute(
                "INSERT OR REPLACE INTO thread_lists (parent_id, covered_from) VALUES (?, ?)",
                (parent_id, None if covered_from is None else _to_text(covered_from)),
            )
            self._mark_fetched(f"threads:{parent_id}")

    def threads(self, parent_id: str) -> list[Thread]:
        """The cached threads of a parent channel, newest activity first (empty if never fetched)."""
        rows = self._db.execute(f"SELECT {_THREAD_COLUMNS} FROM threads WHERE parent_id = ?", (parent_id,))
        threads = [_thread(row) for row in rows]
        threads.sort(key=lambda t: (t.last_activity, int(t.id) if t.id.isdigit() else 0), reverse=True)
        return threads

    def thread(self, thread_id: str) -> Thread | None:
        """A cached thread of any parent channel."""
        row = self._db.execute(f"SELECT {_THREAD_COLUMNS} FROM threads WHERE id = ?", (thread_id,)).fetchone()
        return _thread(row) if row else None

    def cached_threads(self, parent_id: str) -> CachedThreads | None:
        """The threads of a parent channel with their age and coverage; None if they were never fetched."""
        row = self._db.execute("SELECT covered_from FROM thread_lists WHERE parent_id = ?", (parent_id,)).fetchone()
        fetched_at = self.fetched_at(f"threads:{parent_id}")
        if row is None or fetched_at is None:
            return None
        covered_from = None if row[0] is None else datetime.fromisoformat(row[0])
        return CachedThreads(tuple(self.threads(parent_id)), fetched_at, covered_from)

    def fetched_at(self, what: str) -> float | None:
        """Unix time of the last refresh of "servers", "channels:<server_id>" or "threads:<parent_id>"."""
        row = self._db.execute("SELECT at FROM fetched WHERE what = ?", (what,)).fetchone()
        return row[0] if row else None

    def _mark_fetched(self, what: str) -> None:
        self._db.execute("INSERT OR REPLACE INTO fetched (what, at) VALUES (?, ?)", (what, time.time()))

    def _migrate(self) -> None:
        (version,) = self._db.execute("PRAGMA user_version").fetchone()
        if version == SCHEMA_VERSION:
            return
        with self._db:
            for (table,) in self._db.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall():
                self._db.execute(f'DROP TABLE "{table}"')
            self._db.executescript(_SCHEMA)
            self._db.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")


def _channel(row: tuple) -> Channel:
    *fields, tags = row
    return Channel(*fields, available_tags=_load_tags(tags))


def _load_tags(raw: str) -> tuple[ForumTag, ...]:
    try:
        return tuple(ForumTag(tag["id"], tag["name"]) for tag in json.loads(raw))
    except (ValueError, TypeError, KeyError):  # the cache is disposable: a damaged cell is no tags
        return ()


def _thread(row: tuple) -> Thread:
    (thread_id, parent_id, name, kind, created, last_activity, archived, locked, count, owner_id, tags, last_id) = row
    return Thread(
        id=thread_id,
        parent_id=parent_id,
        name=name,
        type=kind,
        created=datetime.fromisoformat(created),
        last_activity=datetime.fromisoformat(last_activity),
        archived=bool(archived),
        locked=bool(locked),
        message_count=count,
        owner_id=owner_id,
        applied_tags=_load_tag_ids(tags),
        last_message_id=last_id,
    )


def _load_tag_ids(raw: str) -> tuple[str, ...]:
    try:
        return tuple(str(tag) for tag in json.loads(raw))
    except (ValueError, TypeError):
        return ()


def _to_text(when: datetime) -> str:
    """ISO 8601 in UTC: exact, readable, and a datetime that comes back equal."""
    return (when if when.tzinfo else when.replace(tzinfo=UTC)).astimezone(UTC).isoformat()
