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
# JSON error codes of a 403 that really mean "no permission" (Missing Access, Missing Permissions).
# Other 403 codes, e.g. 10008 from the anti-abuse system or 40333 from Cloudflare, are blocks, not missing
# access (docs/analyzy/pristup-ku-kanalom.md, section 7).
MISSING_ACCESS_CODES = {50001, 50013}
BLOCKED_HINT = (
    "It is not a missing permission. Discord may be blocking requests (anti-abuse or Cloudflare):"
    " wait a while, then try again with a longer delay, e.g. `discoop config set delay 2`."
)


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


def error_details(response: httpx.Response) -> tuple[int | None, str]:
    """The JSON error `code` and `message` of a failed response (None and "" if there are none)."""
    try:
        data = response.json()
    except ValueError:
        return None, ""
    if not isinstance(data, dict):
        return None, ""
    code = data.get("code")
    return (code if isinstance(code, int) else None), str(data.get("message") or "")


def is_missing_access(response: httpx.Response) -> bool:
    return response.status_code == 403 and error_details(response)[0] in MISSING_ACCESS_CODES


def raise_for_status(response: httpx.Response, hint: str | None = None) -> None:
    if response.status_code < 400:
        return
    code, detail = error_details(response)
    request = response.request
    if code is not None:
        detail = f"{detail} (code {code})" if detail else f"code {code}"
    raise DiscoopError(
        ExitCode.ERROR,
        f"Discord API error {response.status_code} on {request.method} {request.url.path}"
        + (f": {detail}" if detail else ""),
        hint,
    )


def _retry_after(response: httpx.Response) -> float:
    try:
        return float(response.json()["retry_after"])
    except (ValueError, KeyError, TypeError):
        header = response.headers.get("Retry-After")
        return float(header) if header else 5.0
