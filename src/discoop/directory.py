"""Servers and channels: answered from the cache, fetched from Discord when missing or asked to."""

import time
from collections.abc import Callable

from discoop.api import DiscordAPI, raise_for_status
from discoop.cache import Cache
from discoop.errors import DiscoopError, ExitCode
from discoop.models import Channel, Server, channel_from_api, is_hidden, server_from_api
from discoop.resolve import NotFoundError, resolve_one


def describe_server(server: Server) -> str:
    return f"{server.name} ({server.id})"


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

    def cache_age(self, what: str) -> float | None:
        """Seconds since `what` was fetched, or None if this run fetched it."""
        fetched_at = self.cache.fetched_at(what)
        if what in self.fetched or fetched_at is None:
            return None
        return time.time() - fetched_at

    def _api_client(self) -> DiscordAPI:
        if self._api is None:
            self._api = self._open_api()
        return self._api

    def _fetch_servers(self) -> None:
        response = self._api_client().request("GET", "/users/@me/guilds", params={"with_counts": "true"})
        raise_for_status(response)
        self.cache.replace_servers(server_from_api(data) for data in response.json())
        self.fetched.add("servers")

    def _fetch_channels(self, server: Server) -> None:
        response = self._api_client().request("GET", f"/guilds/{server.id}/channels")
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
