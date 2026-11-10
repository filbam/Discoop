"""Shared rigging for the `login --browser` tests: a fake Discord that accepts one token, and the real browser engine
wired to the fake DevTools server of fake_cdp.py. No real browser is started and Discord is never contacted."""

import asyncio
import threading
from collections.abc import Awaitable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import httpx
from fake_cdp import FAKE_TOKEN, FakeCdpBrowser, FakeSpawn, fast_timings

from discoop.api import DiscordAPI
from discoop.browser_login import Browser, BrowserSession, wait_for_browser_token

TOKEN = FAKE_TOKEN
OTHER_TOKEN = "FAKE-OTHER-TOKEN-1111.zyxwvutsrqponm.9876543210"
ME = {"id": "42", "username": "some_user", "global_name": "Some User"}
DISPLAY_NAME = "Some User (@some_user)"
BROWSER = Browser("Chrome", Path("/opt/chrome/chrome"))

# What the text screen says, in order, for a Chrome window that is given 5 minutes.
NOTICES = [
    "Opening Chrome. A browser window will open: log in to Discord there yourself (password or QR code) and solve "
    "a captcha if one appears.",
    "If your system asks for a passkey or security key, you can cancel that dialog and log in with the password or "
    "the QR code on the page.",
    "Waiting up to 5:00 for the login. Press Ctrl+C to cancel.",
    "Login detected, closing the browser window...",
]


class FakeDiscord:
    """A fake `GET /users/@me` that accepts exactly one token (anything else gets a 401) and remembers every request."""

    def __init__(self, accepts: str | None = TOKEN, user: dict[str, Any] | None = None) -> None:
        self.accepts = accepts
        self.user = ME if user is None else user
        self.requests: list[tuple[str, str | None]] = []  # (path, Authorization header)

    def handler(self, request: httpx.Request) -> httpx.Response:
        authorization = request.headers.get("Authorization")
        self.requests.append((request.url.path, authorization))
        if request.url.path.endswith("/users/@me"):
            if self.accepts is not None and authorization == self.accepts:
                return httpx.Response(200, json=self.user)
            return httpx.Response(401, json={"message": "401: Unauthorized", "code": 0})
        return httpx.Response(404)

    def api_factory(self, token: str | None) -> DiscordAPI:
        return DiscordAPI(token, transport=httpx.MockTransport(self.handler), sleep=lambda seconds: None)


class Listener:
    """Remembers the progress callbacks it gets."""

    def __init__(self) -> None:
        self.events: list[tuple[Any, ...]] = []

    def on_launching(self, browser_name: str) -> None:
        self.events.append(("launching", browser_name))

    def on_opened(self, deadline: float) -> None:
        self.events.append(("opened", deadline))

    def on_captured(self) -> None:
        self.events.append(("captured",))

    @property
    def kinds(self) -> list[str]:
        return [event[0] for event in self.events]


class EngineRig:
    """The real engine (`wait_for_browser_token`) against a fake DevTools server and a fake browser process.

    `login.browser_login` starts its own event loop with asyncio.run, so the fake server runs in a background thread
    (the same way as the fake QR gateway). Use `wait` as the `wait=` seam of `browser_login`.
    """

    def __init__(self, root: Path, **fake_kwargs: Any) -> None:
        self.fake = FakeCdpBrowser(**fake_kwargs)
        self.spawn = FakeSpawn(self.fake)
        self.root = root / "browser-profiles"

    def factory(self, browser: Browser) -> BrowserSession:
        return BrowserSession(browser, spawn=self.spawn, profile_root=self.root, timings=fast_timings())

    def wait(self, listener: Any, *, browser: Browser, timeout: float) -> Awaitable[str]:
        return wait_for_browser_token(
            listener, browser=browser, timeout=timeout, poll_interval=0.02, session_factory=self.factory
        )

    def profiles(self) -> list[str]:
        return sorted(p.name for p in self.root.glob("discoop-browser-*")) if self.root.exists() else []

    @contextmanager
    def serving(self) -> Iterator["EngineRig"]:
        started = threading.Event()
        state: dict[str, Any] = {}

        def runner() -> None:
            async def main() -> None:
                state["loop"] = asyncio.get_running_loop()
                state["stop"] = asyncio.Event()
                async with self.fake.running():
                    started.set()
                    await state["stop"].wait()

            asyncio.run(main())

        thread = threading.Thread(target=runner, daemon=True)
        thread.start()
        assert started.wait(5), "the fake DevTools server did not start"
        try:
            yield self
        finally:
            state["loop"].call_soon_threadsafe(state["stop"].set)
            thread.join(5)
