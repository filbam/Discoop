"""Servers and channels: answered from the cache, fetched from Discord when missing or asked to."""

import time
from collections.abc import Callable

from discoop.api import BLOCKED_HINT, DiscordAPI, is_missing_access, raise_for_status
from discoop.cache import Cache
from discoop.errors import DiscoopError, ExitCode
from discoop.models import CATEGORY, Channel, Server, channel_from_api, is_hidden, server_from_api
from discoop.resolve import NotFoundError, resolve_many, resolve_one


def describe_server(server: Server) -> str:
    return f"{server.name} ({server.id})"


def describe_channel(channel: Channel) -> str:
    return f"#{channel.name} ({channel.id}, {channel.type_name})"


class Directory:
    def __init__(self, cache: Cache, open_api: Callable[[], DiscordAPI]) -> None:
        self.cache = cache
        self._open_api = open_api
        self._api: DiscordAPI | None = None
        self.fetched: set[str] = set()  # what this run refreshed from Discord

    def __enter__(self) -> "Directory":
        return self

    def __exit__(self, *exc: object) -> None:
        if self._api is not None:
            self._api.close()

    def servers(self, refresh: bool = False) -> list[Server]:
        if refresh or self.cache.fetched_at("servers") is None:
            self._fetch_servers()
        return self.cache.servers()

    def server(self, query: str) -> Server:
        """Resolve a server; a name missing from the cache triggers one refresh before giving up."""
        while True:
            try:
                return resolve_one(query, self.servers(), "server", describe_server)
            except NotFoundError:
                if "servers" in self.fetched:
                    raise NotFoundError("server", query, "Run `discoop servers` to see your servers.") from None
                self._fetch_servers()

    def channels(self, server: Server, refresh: bool = False) -> list[Channel]:
        if refresh or self.cache.fetched_at(f"channels:{server.id}") is None:
            self._fetch_channels(server)
        return self.cache.channels(server.id)

    def find_channels(self, server: Server, query: str) -> list[Channel]:
        """Channels of a server matching an ID, a name or a glob; one refresh before giving up.

        Names and globs skip categories, so a category and a channel with the same name do not clash.
        """
        while True:
            items = self.channels(server)
            if not query.strip().isdigit():
                items = [c for c in items if c.type != CATEGORY]
            try:
                return resolve_many(query, items, "channel", describe_channel)
            except NotFoundError:
                if f"channels:{server.id}" in self.fetched:
                    raise NotFoundError(
                        "channel", query, f"Run `discoop channels -s {server.id}` to see the channels of {server.name}."
                    ) from None
                self._fetch_channels(server)

    def channel_by_id(self, channel_id: str) -> Channel:
        """A channel on any of your servers, by ID: from the cache, else asked from Discord."""
        cached = self.cache.channel(channel_id)
        if cached is not None:
            return cached
        response = self.api().request("GET", f"/channels/{channel_id}")
        if is_missing_access(response):
            raise DiscoopError(ExitCode.NO_ACCESS, f"No access to channel {channel_id}.")
        if response.status_code == 404:
            raise NotFoundError("channel", channel_id, "Check the ID, or list channels with `discoop channels`.")
        raise_for_status(response, BLOCKED_HINT if response.status_code == 403 else None)
        data = response.json()
        server_id = data.get("guild_id")
        if not server_id:
            raise DiscoopError(
                ExitCode.BAD_ARGS, f"Channel {channel_id} is not on a server.", "Direct messages are not supported."
            )
        server = self.server(server_id)
        refresh = f"channels:{server.id}" not in self.fetched
        for channel in self.channels(server, refresh=refresh):
            if channel.id == channel_id:
                return channel
        return channel_from_api(data, server.id)  # e.g. a thread: not in the server's channel list

    def cache_age(self, what: str) -> float | None:
        """Seconds since `what` was fetched, or None if this run fetched it."""
        fetched_at = self.cache.fetched_at(what)
        if what in self.fetched or fetched_at is None:
            return None
        return time.time() - fetched_at

    def api(self) -> DiscordAPI:
        """The API client, opened on first use and shared, so the request pacing covers every call."""
        if self._api is None:
            self._api = self._open_api()
        return self._api

    def _fetch_servers(self) -> None:
        response = self.api().request("GET", "/users/@me/guilds", params={"with_counts": "true"})
        raise_for_status(response)
        self.cache.replace_servers(server_from_api(data) for data in response.json())
        self.fetched.add("servers")

    def _fetch_channels(self, server: Server) -> None:
        response = self.api().request("GET", f"/guilds/{server.id}/channels")
        if response.status_code in (403, 404):
            raise DiscoopError(
                ExitCode.NO_ACCESS,
                f"No access to the channels of {describe_server(server)}.",
                "You may have left the server: run `discoop servers --refresh`.",
            )
        raise_for_status(response)
        channels = [channel_from_api(data, server.id) for data in response.json() if not is_hidden(data)]
        self.cache.replace_channels(server.id, channels)
        self.fetched.add(f"channels:{server.id}")
