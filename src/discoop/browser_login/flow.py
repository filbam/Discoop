"""Browser login: the user logs in to Discord in their own browser window, Discoop reads the token.

Two sources are watched at once and the first hit wins (docs/analyses/browser-login.md):
- the `token` key of Discord's localStorage, read with the DOMStorage domain (Discord hides `window.localStorage`
  from page scripts, so `Runtime.evaluate` is of no use);
- the `Authorization` header of the page's own requests to Discord's API, from the Network domain.

The caller verifies the token against Discord and stores it. The listener never receives the token, and nothing
that holds it (a header, a storage entry, a command result) is logged or put into an error message.
"""

import asyncio
import json
import time
from collections.abc import Callable
from typing import Any, Protocol

from discoop.browser_login._log import logger
from discoop.browser_login.cdp import CdpClient, CdpConnectionLost, CdpError, CdpEvent, CdpTimeout
from discoop.browser_login.launch import TRY_OTHER_HINT, BrowserSession
from discoop.browser_login.locate import Browser
from discoop.errors import DiscoopError, ExitCode

ORIGIN = "https://discord.com"
API_PREFIX = f"{ORIGIN}/api/"
MIN_TOKEN_LENGTH = 20
COMMAND_TIMEOUT = 10.0
PAGE_WAIT = 10.0  # seconds to wait for the browser to show its first page
PAGE_POLL = 0.2
TOKEN_KEY = "token"


class BrowserListener(Protocol):
    """Progress callbacks for the screen. None of them receives the token."""

    def on_launching(self, browser_name: str) -> None: ...  # just before the process starts
    def on_opened(self, deadline: float) -> None: ...  # window is up and attached; deadline is a time.monotonic() value
    def on_captured(self) -> None: ...  # token found, before the window is closed


def looks_like_token(value: object) -> bool:
    """A non-empty string without whitespace and of at least 20 characters. The caller verifies it with Discord."""
    return isinstance(value, str) and len(value) >= MIN_TOKEN_LENGTH and not any(c.isspace() for c in value)


def token_from_stored_value(value: object) -> str | None:
    """The `token` entry of localStorage holds a JSON-encoded string: the token inside double quotes."""
    if not isinstance(value, str):
        return None
    try:
        decoded: object = json.loads(value)
    except ValueError:
        decoded = value  # not JSON: take it as it is
    return decoded if isinstance(decoded, str) and looks_like_token(decoded) else None


def token_from_storage(entries: object) -> str | None:
    """The token from the `entries` of DOMStorage.getDOMStorageItems (a list of [key, value] pairs)."""
    if not isinstance(entries, list):
        return None
    for entry in entries:
        if isinstance(entry, (list, tuple)) and len(entry) == 2 and entry[0] == TOKEN_KEY:
            return token_from_stored_value(entry[1])
    return None


def token_from_request(params: object) -> str | None:
    """The token from the parameters of Network.requestWillBeSent, if the request goes to Discord's API and
    carries an Authorization header. Every other header is dropped here."""
    request = params.get("request") if isinstance(params, dict) else None
    if not isinstance(request, dict):
        return None
    url, headers = request.get("url"), request.get("headers")
    if not isinstance(url, str) or not url.startswith(API_PREFIX) or not isinstance(headers, dict):
        return None
    for name, value in headers.items():
        if isinstance(name, str) and name.lower() == "authorization":
            return value if looks_like_token(value) else None
    return None


def _closed_error() -> DiscoopError:
    return DiscoopError(
        ExitCode.AUTH_REQUIRED,
        "The browser window was closed before the login finished.",
        "Run `discoop login --browser` again and finish the login in the window.",
    )


def _timeout_error(timeout: float) -> DiscoopError:
    return DiscoopError(
        ExitCode.AUTH_REQUIRED,
        f"The login was not finished within {_describe(timeout)}.",
        "Run `discoop login --browser` again; use --timeout to allow more time.",
    )


def _unexpected(method: str) -> DiscoopError:
    """The browser answered in a way we do not understand. Names the command only, never parameters or results."""
    return DiscoopError(ExitCode.ERROR, f"The browser did not respond as expected ({method} failed).", TRY_OTHER_HINT)


def _describe(seconds: float) -> str:
    if seconds >= 60 and seconds % 60 == 0:
        minutes = int(seconds // 60)
        return f"{minutes} minute{'s' if minutes != 1 else ''}"
    if seconds >= 1:
        whole = round(seconds)
        return f"{whole} second{'s' if whole != 1 else ''}"
    return f"{seconds:g} seconds"


def _shows_discord(page: dict[str, Any]) -> bool:
    url = page.get("url")
    return isinstance(url, str) and url.startswith(f"{ORIGIN}/")


def _pick_page(pages: list[dict[str, Any]]) -> dict[str, Any]:
    """Prefer the page that shows Discord; otherwise the first one."""
    for page in pages:
        if _shows_discord(page):
            return page
    return pages[0]


class _Watch:
    """Follows one browser window until the token shows up or the window goes away."""

    def __init__(self, cdp: CdpClient, session: BrowserSession, browser_name: str, poll_interval: float) -> None:
        self._cdp = cdp
        self._session = session
        self._name = browser_name
        self._poll_interval = poll_interval
        self._target_id: str | None = None
        self._session_id: str | None = None
        self._storage_shape = "securityOrigin"  # the storageId form that worked last; tried first
        self._storage_readable: bool | None = None  # only to log changes
        self._no_page_polls = 0
        self._poll_now = False

    async def attach_first_page(self) -> None:
        try:
            await self._call("Target.setDiscoverTargets", {"discover": True})
            end = time.monotonic() + PAGE_WAIT
            while not (pages := await self._pages()):
                if self._session.exited:
                    raise _closed_error()
                if time.monotonic() >= end:
                    raise DiscoopError(ExitCode.ERROR, f"{self._name} did not start in time.", TRY_OTHER_HINT)
                await asyncio.sleep(PAGE_POLL)
            await self._attach(_pick_page(pages))
        except CdpConnectionLost:
            raise _closed_error() from None

    async def run(self, deadline: float, timeout: float) -> tuple[str, str]:
        """Wait for the token. Returns (token, source) where source is "storage" or "header"."""
        try:
            return await self._loop(deadline, timeout)
        except CdpConnectionLost:
            raise _closed_error() from None

    async def _loop(self, deadline: float, timeout: float) -> tuple[str, str]:
        next_poll = 0.0
        while True:
            while (event := self._cdp.pending_event()) is not None:
                token = self._on_event(event)
                if token is not None:
                    return token, "header"
            if self._session.exited:
                raise _closed_error()
            now = time.monotonic()
            if now >= deadline:
                raise _timeout_error(timeout)
            if self._poll_now or now >= next_poll:
                self._poll_now = False
                token = await self._poll(deadline)
                if token is not None:
                    return token, "storage"
                next_poll = time.monotonic() + self._poll_interval
                continue
            event = await self._cdp.next_event(min(next_poll, deadline) - now)
            if event is not None:
                token = self._on_event(event)
                if token is not None:
                    return token, "header"

    def _on_event(self, event: CdpEvent) -> str | None:
        if event.method == "Network.requestWillBeSent":
            if event.session_id == self._session_id:
                return token_from_request(event.params)
        elif event.method == "Target.targetDestroyed":
            if event.params.get("targetId") == self._target_id:
                self._poll_now = True  # confirm with Target.getTargets right away
        elif event.method == "Target.detachedFromTarget":
            if event.params.get("sessionId") == self._session_id:
                self._poll_now = True
        return None

    async def _poll(self, deadline: float) -> str | None:
        pages = await self._pages()
        if not pages:
            # Closing the last window does not quit the browser on macOS: two empty polls in a row mean it is closed.
            self._no_page_polls += 1
            if self._no_page_polls >= 2:
                raise _closed_error()
            return None
        self._no_page_polls = 0
        watched = next((page for page in pages if page["targetId"] == self._target_id), None)
        wanted = _pick_page(pages)
        if watched is None or (not _shows_discord(watched) and _shows_discord(wanted)):
            # The page we watched is gone, or is somewhere else while another page shows Discord: follow Discord.
            await self._attach(wanted)
        return await self._read_storage(deadline)

    async def _read_storage(self, deadline: float) -> str | None:
        """Read Discord's localStorage. An error is normal while the page is still loading or not on Discord yet
        (no frame has that origin), so it only means "not now"; the header source keeps working meanwhile."""
        timeout = max(0.05, min(COMMAND_TIMEOUT, deadline - time.monotonic()))
        shapes = ["securityOrigin", "storageKey"]
        if self._storage_shape == "storageKey":
            shapes.reverse()
        for shape in shapes:
            # Chrome documents `securityOrigin` as superseded by `storageKey`: use whichever the browser accepts.
            storage_id = {"isLocalStorage": True, shape: ORIGIN if shape == "securityOrigin" else f"{ORIGIN}/"}
            try:
                result = await self._cdp.send(
                    "DOMStorage.getDOMStorageItems",
                    {"storageId": storage_id},
                    session_id=self._session_id,
                    timeout=timeout,
                )
            except CdpError:
                continue
            except CdpTimeout:
                break
            self._storage_shape = shape
            self._note_storage(True)
            return token_from_storage(result.get("entries"))
        self._note_storage(False)
        return None

    def _note_storage(self, readable: bool) -> None:
        if readable != self._storage_readable:
            self._storage_readable = readable
            logger.debug("storage readable=%s", str(readable).lower())

    async def _pages(self) -> list[dict[str, Any]]:
        result = await self._call("Target.getTargets")
        infos = result.get("targetInfos")
        return [
            info
            for info in (infos if isinstance(infos, list) else [])
            if isinstance(info, dict) and info.get("type") == "page" and isinstance(info.get("targetId"), str)
        ]

    async def _attach(self, page: dict[str, Any]) -> None:
        target_id = page["targetId"]
        result = await self._call("Target.attachToTarget", {"targetId": target_id, "flatten": True})
        session_id = result.get("sessionId")
        if not isinstance(session_id, str) or not session_id:
            raise _unexpected("Target.attachToTarget")
        self._target_id, self._session_id = target_id, session_id
        await self._call("DOMStorage.enable", session_id=session_id)
        await self._call("Network.enable", session_id=session_id)
        logger.debug("page attached")

    async def _call(self, method: str, params: dict[str, Any] | None = None, *, session_id: str | None = None) -> dict:
        """Run a command that must work. A refusal or a timeout ends the login; the browser's text is not kept."""
        try:
            return await self._cdp.send(method, params, session_id=session_id, timeout=COMMAND_TIMEOUT)
        except (CdpError, CdpTimeout) as e:
            logger.debug("cdp command failed method=%s", method)
            raise _unexpected(method) from e


async def wait_for_browser_token(
    listener: BrowserListener,
    *,
    browser: Browser,
    timeout: float = 300.0,
    poll_interval: float = 1.0,
    session_factory: Callable[..., BrowserSession] = BrowserSession,
) -> str:
    """Open the browser on Discord's login page and return the token once the user has logged in.

    The browser is closed and its temporary profile deleted BEFORE this returns or raises. Raises DiscoopError:
    AUTH_REQUIRED if the window is closed or the time is up, ERROR if the browser cannot be started or does not
    behave as expected.
    """
    listener.on_launching(browser.name)
    logger.debug("launching browser=%s", browser.name)
    session = session_factory(browser)
    async with session as cdp:
        watch = _Watch(cdp, session, browser.name, poll_interval)
        await watch.attach_first_page()
        deadline = time.monotonic() + timeout
        listener.on_opened(deadline)
        token, source = await watch.run(deadline, timeout)
        logger.debug("token found source=%s", source)
        listener.on_captured()
        return token
