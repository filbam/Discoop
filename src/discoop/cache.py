"""Local SQLite cache of servers and channels, so names resolve without asking Discord every time.

The cache is disposable: login and logout delete it, and a schema change simply rebuilds it.
"""

import sqlite3
import time
from collections.abc import Iterable
from pathlib import Path

from discoop import paths
from discoop.models import Channel, Server

SCHEMA_VERSION = 1
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
    topic TEXT
);
CREATE INDEX channels_by_server ON channels (server_id);
CREATE TABLE fetched (
    what TEXT PRIMARY KEY,
    at REAL NOT NULL
);
"""


def cache_path() -> Path:
    return paths.data_dir() / "cache.db"


def clear_cache() -> None:
    cache_path().unlink(missing_ok=True)


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
                "INSERT INTO channels (id, server_id, name, type, parent_id, position, topic)"
                " VALUES (?, ?, ?, ?, ?, ?, ?)",
                [(c.id, c.server_id, c.name, c.type, c.parent_id, c.position, c.topic) for c in channels],
            )
            self._mark_fetched(f"channels:{server_id}")

    def channels(self, server_id: str) -> list[Channel]:
        rows = self._db.execute(
            "SELECT id, server_id, name, type, parent_id, position, topic FROM channels WHERE server_id = ?",
            (server_id,),
        )
        return [Channel(*row) for row in rows]

    def channel(self, channel_id: str) -> Channel | None:
        """A cached channel of any server."""
        row = self._db.execute(
            "SELECT id, server_id, name, type, parent_id, position, topic FROM channels WHERE id = ?", (channel_id,)
        ).fetchone()
        return Channel(*row) if row else None

    def fetched_at(self, what: str) -> float | None:
        """Unix time of the last refresh of "servers" or "channels:<server_id>"."""
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
