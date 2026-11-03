"""`discoop login`: QR login (or a pasted token), verified against Discord and stored."""

import asyncio
import getpass
import sys
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from rich.console import Console, Group
from rich.live import Live
from rich.text import Text

from discoop.api import DiscordAPI, raise_for_status
from discoop.errors import DiscoopError, ExitCode
from discoop.qr import qr_text
from discoop.remote_auth.crypto import UserPayload
from discoop.remote_auth.protocol import GATEWAY_URL, TOKEN_HINT, LoginTicket, wait_for_ticket
from discoop.remote_auth.trace import Trace
from discoop.tokenstore import TokenStore

ApiFactory = Callable[[str | None], DiscordAPI]


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
        raise DiscoopError(
            ExitCode.ERROR, "Discord asked for a captcha, which cannot be solved in a terminal.", TOKEN_HINT
        )
    raise_for_status(response)
    encrypted = body.get("encrypted_token") if isinstance(body, dict) else None
    if not encrypted:
        raise DiscoopError(ExitCode.ERROR, "Discord did not return a token.", TOKEN_HINT)
    return ticket.keys.decrypt(encrypted).decode("utf-8")


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
