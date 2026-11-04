"""Minimal Discord REST client: auth header, pacing, retries and error mapping."""

import logging
import random
import time
from collections.abc import Callable
from typing import Any

import httpx

from discoop import __version__
from discoop.errors import DiscoopError, ExitCode, auth_required

logger = logging.getLogger("discoop.api")

ALLOWED_PARAM_KEYS = {"before", "after", "limit", "archived", "offset", "with_counts"}


def _format_params(params: Any) -> list[str]:
    if not params:
        return []
    if isinstance(params, dict):
        items = list(params.items())
    elif isinstance(params, (list, tuple)):
        items = list(params)
    elif hasattr(params, "items"):
        items = list(params.items())
    else:
        return []
    if not items:
        return []
    names = ",".join(str(k) for k, _ in items)
    res = [f"params={names}"]
    for k, v in items:
        if str(k) in ALLOWED_PARAM_KEYS and v is not None:
            res.append(f"{k}={v}")
    return res

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
        mode: str = "fast",
        max_retries: int = 3,
        transport: httpx.BaseTransport | None = None,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
        rand: random.Random | None = None,
        on_pause: Callable[[float, str], None] | None = None,
    ) -> None:
        headers = {"User-Agent": USER_AGENT}
        if token:
            headers["Authorization"] = token
        self._client = httpx.Client(
            base_url=API_BASE, headers=headers, timeout=20.0, transport=transport
        )
        self.delay = delay
        self.mode = mode
        self.page_size = 25 if mode == "safe" else 100
        self.max_retries = max_retries
        self._sleep = sleep
        self._clock = clock
        self.rand = rand if rand is not None else random.Random()
        self.on_pause = on_pause
        self._last_request: float | None = None
        self._requests_since_break = 0
        self._break_threshold = self.rand.randint(5, 8)

    def __enter__(self) -> "DiscordAPI":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def close(self) -> None:
        self._client.close()

    def request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        """Send a request. Retries 429, 5xx and network errors; maps 401 to AUTH_REQUIRED.

        Other 4xx responses are returned as they are, so callers can inspect them.
        `path` is relative to the API base: the token is never sent anywhere else (files come from the CDN through
        a separate client without it, see discoop.attachments).
        """
        if not path.startswith("/") or path.startswith("//"):
            raise ValueError(f"Not an API path: {path!r}. The token only goes to {API_BASE}.")
        self._pace()
        clean_path = path.split("?", 1)[0]
        param_parts = _format_params(kwargs.get("params"))
        attempt = 0
        while True:
            attempt_num = attempt + 1
            start = time.perf_counter()
            try:
                response = self._client.request(method, path, **kwargs)
                elapsed_ms = int((time.perf_counter() - start) * 1000)
            except httpx.TransportError as e:
                elapsed_ms = int((time.perf_counter() - start) * 1000)
                msg_parts = [
                    "api request",
                    f"method={method}",
                    f"path={clean_path}",
                ]
                if param_parts:
                    msg_parts.extend(param_parts)
                msg_parts.append(f"attempt={attempt_num}")
                msg_parts.append(f"error={type(e).__name__}")
                msg_parts.append(f"ms={elapsed_ms}")
                logger.debug(" ".join(msg_parts))

                if attempt >= self.max_retries:
                    raise DiscoopError(
                        ExitCode.NETWORK, f"Network error: {e}", "Check the connection and try again."
                    ) from e
                attempt += 1
                backoff = 2 ** (attempt - 1)
                logger.debug(
                    "api retry error=%s attempt=%d backoff=%ds",
                    type(e).__name__,
                    attempt_num,
                    backoff,
                )
                self._sleep(backoff)
                continue

            if logger.isEnabledFor(logging.DEBUG):  # parsing the body only to log it is wasted work otherwise
                msg_parts = [
                    "api request",
                    f"method={method}",
                    f"path={clean_path}",
                ]
                if param_parts:
                    msg_parts.extend(param_parts)
                msg_parts.append(f"attempt={attempt_num}")
                msg_parts.append(f"status={response.status_code}")
                msg_parts.append(f"ms={elapsed_ms}")
                msg_parts.append(f"bytes={len(response.content)}")
                try:
                    data = response.json()
                    if isinstance(data, (list, dict)):
                        if response.status_code < 400 or isinstance(data, list):
                            msg_parts.append(f"items={len(data)}")
                except Exception:
                    pass
                if response.status_code >= 400:
                    code, detail = error_details(response)
                    if code is not None:
                        msg_parts.append(f"code={code}")
                    if detail:
                        clean_detail = detail.replace("\n", " ").strip()
                        msg_parts.append(f'message="{clean_detail}"')
                logger.debug(" ".join(msg_parts))

            if response.status_code == 429:
                wait = _retry_after(response)
                if logger.isEnabledFor(logging.DEBUG):
                    is_global = False
                    try:
                        body = response.json()
                        if isinstance(body, dict):
                            is_global = bool(body.get("global", False))
                    except Exception:
                        pass
                    new_delay = self.delay * 2 if self.delay > 0.0 else self.delay
                    logger.debug(
                        "api rate_limit retry_after=%.3f global=%s delay=%.3f",
                        wait,
                        is_global,
                        new_delay,
                    )
                if attempt >= self.max_retries or wait > MAX_RETRY_WAIT:
                    raise DiscoopError(
                        ExitCode.RATE_LIMITED,
                        f"Rate limited by Discord (retry after {wait:.1f} s).",
                        "Try again later or increase --delay.",
                    )
                attempt += 1
                if self.delay > 0.0:
                    self.delay *= 2
                logger.debug("api pause seconds=%.3f reason=rate limited (429)", wait)
                if self.on_pause:
                    self.on_pause(wait, "rate limited (429)")
                self._sleep(wait)
                continue
            if response.status_code >= 500 and attempt < self.max_retries:
                attempt += 1
                backoff = 2 ** (attempt - 1)
                logger.debug(
                    "api retry status=%d attempt=%d backoff=%ds",
                    response.status_code,
                    attempt_num,
                    backoff,
                )
                self._sleep(backoff)
                continue
            if response.status_code == 401:
                raise auth_required("The stored token is invalid or expired.")
            return response

    def get_me(self) -> dict[str, Any]:
        response = self.request("GET", "/users/@me")
        raise_for_status(response)
        return response.json()

    def between_channels(self) -> None:
        """Pause when switching between channels (in safe mode)."""
        if self.mode != "safe" or self.delay <= 0.0:
            return
        pause = self.rand.uniform(3.0, 6.0) * self.delay
        logger.debug("api pause seconds=%.3f reason=between channels", pause)
        if self.on_pause:
            self.on_pause(pause, "switching channels")
        self._sleep(pause)
        self._last_request = self._clock()

    def between_files(self) -> None:
        """Pause between attachment downloads from CDN (in safe mode)."""
        if self.mode != "safe" or self.delay <= 0.0:
            return
        pause = self.rand.uniform(1.0, 3.0) * self.delay
        logger.debug("api pause seconds=%.3f reason=between files", pause)
        if self.on_pause:
            self.on_pause(pause, "downloading files")
        self._sleep(pause)

    def _pace(self) -> None:
        if self.delay <= 0.0:
            self._last_request = self._clock()
            return
        if self._last_request is not None:
            elapsed = self._clock() - self._last_request
            is_break = False
            if self.mode == "safe":
                self._requests_since_break += 1
                if self._requests_since_break >= self._break_threshold:
                    is_break = True
                    wait_target = self.rand.uniform(8.0, 15.0) * self.delay
                    self._requests_since_break = 0
                    self._break_threshold = self.rand.randint(5, 8)
                    if self.on_pause:
                        self.on_pause(wait_target, "reading pause")
                else:
                    wait_target = self.rand.uniform(2.0, 4.5) * self.delay
            else:
                wait_target = self.delay
            wait = wait_target - elapsed
            if wait > 0:
                reason = "reading pause" if is_break else "jitter"
                logger.debug("api pause seconds=%.3f reason=%s", wait, reason)
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
