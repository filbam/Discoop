"""Minimal Discord REST client: auth header, pacing, retries and error mapping."""

import time
from collections.abc import Callable
from typing import Any

import httpx

from discoop import __version__
from discoop.errors import DiscoopError, ExitCode, auth_required

API_BASE = "https://discord.com/api/v9"
USER_AGENT = f"discoop/{__version__}"
# Longer rate-limit waits than this abort instead of blocking the caller.
MAX_RETRY_WAIT = 60.0


class DiscordAPI:
    def __init__(
        self,
        token: str | None = None,
        *,
        delay: float = 0.0,
        max_retries: int = 3,
        transport: httpx.BaseTransport | None = None,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        headers = {"User-Agent": USER_AGENT}
        if token:
            headers["Authorization"] = token
        self._client = httpx.Client(
            base_url=API_BASE, headers=headers, timeout=20.0, transport=transport
        )
        self.delay = delay
        self.max_retries = max_retries
        self._sleep = sleep
        self._clock = clock
        self._last_request: float | None = None

    def __enter__(self) -> "DiscordAPI":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def close(self) -> None:
        self._client.close()

    def request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        """Send a request. Retries 429, 5xx and network errors; maps 401 to AUTH_REQUIRED.

        Other 4xx responses are returned as they are, so callers can inspect them.
        """
        attempt = 0
        while True:
            self._pace()
            try:
                response = self._client.request(method, path, **kwargs)
            except httpx.TransportError as e:
                if attempt >= self.max_retries:
                    raise DiscoopError(
                        ExitCode.NETWORK, f"Network error: {e}", "Check the connection and try again."
                    ) from e
                attempt += 1
                self._sleep(2 ** (attempt - 1))
                continue

            if response.status_code == 429:
                wait = _retry_after(response)
                if attempt >= self.max_retries or wait > MAX_RETRY_WAIT:
                    raise DiscoopError(
                        ExitCode.RATE_LIMITED,
                        f"Rate limited by Discord (retry after {wait:.1f} s).",
                        "Try again later or increase --delay.",
                    )
                attempt += 1
                self._sleep(wait)
                continue
            if response.status_code >= 500 and attempt < self.max_retries:
                attempt += 1
                self._sleep(2 ** (attempt - 1))
                continue
            if response.status_code == 401:
                raise auth_required("The stored token is invalid or expired.")
            return response

    def get_me(self) -> dict[str, Any]:
        response = self.request("GET", "/users/@me")
        raise_for_status(response)
        return response.json()

    def _pace(self) -> None:
        if self.delay and self._last_request is not None:
            wait = self.delay - (self._clock() - self._last_request)
            if wait > 0:
                self._sleep(wait)
        self._last_request = self._clock()


def raise_for_status(response: httpx.Response) -> None:
    if response.status_code < 400:
        return
    try:
        detail = response.json().get("message", "")
    except ValueError:
        detail = ""
    request = response.request
    raise DiscoopError(
        ExitCode.ERROR,
        f"Discord API error {response.status_code} on {request.method} {request.url.path}"
        + (f": {detail}" if detail else ""),
    )


def _retry_after(response: httpx.Response) -> float:
    try:
        return float(response.json()["retry_after"])
    except (ValueError, KeyError, TypeError):
        header = response.headers.get("Retry-After")
        return float(header) if header else 5.0
