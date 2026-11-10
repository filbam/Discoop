"""`discoop login`: QR login, browser login or a pasted token, verified against Discord and stored."""

import asyncio
import getpass
import json
import os
import sys
import time
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from rich.console import Console, Group
from rich.live import Live
from rich.text import Text

from discoop.api import DiscordAPI, raise_for_status
from discoop.browser_login import Browser, BrowserListener, find_browser, wait_for_browser_token
from discoop.config import Config
from discoop.errors import DiscoopError, ExitCode
from discoop.output import Output
from discoop.qr import qr_text
from discoop.remote_auth.crypto import UserPayload
from discoop.remote_auth.protocol import GATEWAY_URL, TOKEN_HINT, LoginTicket, wait_for_ticket
from discoop.remote_auth.trace import Trace
from discoop.tokenstore import TokenStore

ApiFactory = Callable[[str | None], DiscordAPI]
BrowserPath = str | os.PathLike[str] | None

BROWSER_TIMEOUT = 300.0  # seconds `login --browser` waits for the human by default
MIN_BROWSER_TIMEOUT = 30.0
MAX_BROWSER_TIMEOUT = 1800.0
BROWSER_HINT = (
    "Log in through a browser window instead, where the captcha can be solved: `discoop login --browser`. "
    "As a last resort use `discoop login --token`."
)


class CaptchaRequired(DiscoopError):
    """Discord asked for a captcha instead of a token. A terminal cannot solve one, a browser window can."""

    def __init__(self) -> None:
        super().__init__(
            ExitCode.ERROR, "Discord asked for a captcha, which cannot be solved in a terminal.", BROWSER_HINT
        )


class QrScreen:
    """Live terminal view: QR code, countdown and status. Transient, so the code vanishes afterwards."""

    def __init__(self, console: Console, show_qr: bool = True) -> None:
        self.console = console
        self.show_qr = show_qr
        self.qr: Text | None = None
        self.deadline: float | None = None
        self.status = "Connecting to Discord..."
        self._live = Live(console=console, get_renderable=self._render, refresh_per_second=2, transient=True)

    def __enter__(self) -> "QrScreen":
        self._live.start()
        return self

    def __exit__(self, *exc: object) -> None:
        self._live.stop()

    def on_connecting(self, session: int) -> None:
        self.qr = None
        if session > 1:
            self.status = "Getting a new QR code..."

    def on_qr(self, url: str, deadline: float | None) -> None:
        self.qr = qr_text(url) if self.show_qr else None
        self.deadline = deadline
        self.status = "Scan this QR code with the Discord mobile app."

    def on_scanned(self, user: UserPayload) -> None:
        self.qr = None
        self.status = f"Logging in as {user.username}. Confirm the login on your phone."

    def on_restart(self, reason: str) -> None:
        self.qr = None
        self.status = f"{reason[:1].upper()}{reason[1:]}, getting a new QR code..."

    def _render(self) -> Group:
        parts: list[Any] = []
        if self.qr is not None:
            parts += [self.qr, Text("")]
        parts.append(Text(self.status, style="bold"))
        if self.qr is not None:
            if self.deadline is not None:
                left = max(0, int(self.deadline - time.monotonic()))
                parts.append(Text(f"The code expires in {left // 60}:{left % 60:02d}.", style="dim"))
            parts.append(Text("Discord app: Settings > Scan QR Code. Press Ctrl+C to cancel.", style="dim"))
        return Group(*parts)


class BrowserScreen:
    """The notices of `login --browser` in the terminal, in order: what is about to open, how long Discoop waits,
    that the login was seen. They go through `Output.note`: dim on stderr for a human, and in plain mode only with
    --verbose (an AI agent has told the user before it ran the command)."""

    def __init__(self, out: Output) -> None:
        self.out = out

    def on_launching(self, browser_name: str) -> None:
        self.out.note(
            f"Opening {browser_name}. A browser window will open: log in to Discord there yourself "
            "(password or QR code) and solve a captcha if one appears."
        )
        self.out.note(
            "If your system asks for a passkey or security key, you can cancel that dialog and log in with the "
            "password or the QR code on the page."
        )

    def on_opened(self, deadline: float) -> None:
        left = max(0, round(deadline - time.monotonic()))
        self.out.note(f"Waiting up to {left // 60}:{left % 60:02d} for the login. Press Ctrl+C to cancel.")

    def on_captured(self) -> None:
        self.out.note("Login detected, closing the browser window...")


def _emit_json_line(data: dict[str, Any]) -> None:
    print(json.dumps(data, ensure_ascii=False), file=sys.stderr, flush=True)


class BrowserProgressJson:
    """`--progress-json` for `login --browser`: one compact JSON object per line on stderr, like the events of
    `messages`. IDs and numbers only: never a name, a path or a token."""

    def __init__(self, timeout: float, emit: Callable[[dict[str, Any]], None] = _emit_json_line) -> None:
        self.timeout = timeout
        self._emit = emit

    def on_launching(self, browser_name: str) -> None:
        self._emit({"event": "browser_launch", "browser": browser_name.lower()})

    def on_opened(self, deadline: float) -> None:
        seconds = int(self.timeout) if self.timeout == int(self.timeout) else self.timeout
        self._emit({"event": "browser_open", "timeout_seconds": seconds})

    def on_captured(self) -> None:
        self._emit({"event": "token_captured"})

    def logged_in(self, user_id: object) -> None:
        self._emit({"event": "logged_in", "user_id": user_id})


def qr_login(
    console: Console,
    store: TokenStore,
    *,
    trace_path: Path | None = None,
    handshake_only: bool = False,
    api_factory: ApiFactory = DiscordAPI,
    url: str = GATEWAY_URL,
) -> tuple[dict[str, Any], str] | None:
    """Log in via QR code. Returns (user, token location), or None with handshake_only."""
    with Trace(trace_path) as trace:
        with QrScreen(console, show_qr=not handshake_only) as screen:
            ticket = asyncio.run(wait_for_ticket(screen, trace=trace, url=url, stop_after_qr=handshake_only))
            if ticket is None:
                return None
            screen.status = "Confirmed on the phone, finishing the login..."
            with api_factory(None) as api:
                token = exchange_ticket(ticket, api, trace)
        return verify_and_store(token, store, api_factory)


def exchange_ticket(ticket: LoginTicket, api: DiscordAPI, trace: Trace) -> str:
    """POST the ticket from `pending_login` and decrypt the returned token."""
    path = "/users/@me/remote-auth/login"
    response = api.request("POST", path, json={"ticket": ticket.ticket})
    try:
        body = response.json()
    except ValueError:
        body = None
    trace.http("POST", path, response.status_code, body)
    if response.status_code == 400 and isinstance(body, dict) and "captcha_key" in body:
        raise CaptchaRequired()
    raise_for_status(response)
    encrypted = body.get("encrypted_token") if isinstance(body, dict) else None
    if not encrypted:
        raise DiscoopError(ExitCode.ERROR, "Discord did not return a token.", TOKEN_HINT)
    return ticket.keys.decrypt(encrypted).decode("utf-8")


def find_login_browser(browser_path: BrowserPath = None) -> Browser:
    """The browser to log in with: the given path first, then the `browser-path` setting, then auto-detection
    (Chrome, Edge, Chromium or Brave). Raises DiscoopError (exit code 1) if there is none."""
    if browser_path is None or os.fspath(browser_path) == "":
        browser_path = Config.default().get("browser-path")
    return find_browser(browser_path)


def browser_login(
    listener: BrowserListener,
    store: TokenStore,
    *,
    browser_path: BrowserPath = None,
    timeout: float = BROWSER_TIMEOUT,
    api_factory: ApiFactory = DiscordAPI,
    find: Callable[[BrowserPath], Browser] = find_login_browser,
    wait: Callable[..., Awaitable[str]] = wait_for_browser_token,
) -> tuple[dict[str, Any], str, Browser]:
    """Log in through the user's own browser window. Returns (user, token location, browser).

    Blocks until the human has logged in, the window is closed (exit code 2) or `timeout` seconds have passed
    (exit code 2). A missing or broken browser is exit code 1. `find` and `wait` are test seams.
    """
    browser = find(browser_path)
    token = asyncio.run(wait(listener, browser=browser, timeout=timeout))
    try:
        me, location = verify_and_store(token, store, api_factory)
    except DiscoopError as e:
        if e.code != ExitCode.AUTH_REQUIRED:
            raise
        raise DiscoopError(
            ExitCode.AUTH_REQUIRED,
            "Discord did not accept the token read from the browser window.",
            "Run `discoop login --browser` again. If it keeps failing, use `discoop login --token`.",
        ) from e
    return me, location, browser


def token_login(store: TokenStore, *, api_factory: ApiFactory = DiscordAPI) -> tuple[dict[str, Any], str]:
    """Read a token from a hidden prompt (terminal) or stdin (pipe), never from arguments."""
    if sys.stdin.isatty():
        raw = getpass.getpass("Discord token (input is hidden): ")
    else:
        raw = sys.stdin.readline()
    token = raw.strip().strip('"')
    if not token:
        raise DiscoopError(ExitCode.BAD_ARGS, "No token was given.")
    return verify_and_store(token, store, api_factory)


def verify_and_store(token: str, store: TokenStore, api_factory: ApiFactory) -> tuple[dict[str, Any], str]:
    with api_factory(token) as api:
        me = api.get_me()
    return me, store.save(token)
