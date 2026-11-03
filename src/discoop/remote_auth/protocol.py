"""Client for Discord's remote auth gateway (QR login), protocol v2.

hello -> init -> nonce_proof (both ways) -> pending_remote_init (QR is shown)
-> pending_ticket (phone scanned) -> pending_login (phone confirmed, carries the ticket).
Details: docs/analyzy/discord-login.md, section 2.
"""

import asyncio
import json
import random
import time
from dataclasses import dataclass
from typing import Any, Protocol

from websockets.asyncio.client import ClientConnection, connect
from websockets.exceptions import ConnectionClosed, InvalidHandshake, InvalidStatus

from discoop.api import USER_AGENT
from discoop.errors import DiscoopError, ExitCode
from discoop.remote_auth.crypto import RemoteAuthKeys, UserPayload, parse_user_payload, qr_url
from discoop.remote_auth.trace import Trace

GATEWAY_URL = "wss://remote-auth-gateway.discord.gg/?v=2"
ORIGIN = "https://discord.com"
CLOSE_HANDSHAKE_TIMEOUT = 4003
TOKEN_HINT = "If QR login keeps failing, use `discoop login --token`."


class Listener(Protocol):
    def on_connecting(self, session: int) -> None: ...
    def on_qr(self, url: str, deadline: float | None) -> None: ...
    def on_scanned(self, user: UserPayload) -> None: ...
    def on_restart(self, reason: str) -> None: ...


@dataclass
class LoginTicket:
    ticket: str
    keys: RemoteAuthKeys
    user: UserPayload | None


class _Restart(Exception):
    """The session ended in a way the web client recovers from: start a new one (new QR)."""


@dataclass
class _HeartbeatState:
    waiting_for_ack: bool = False
    missed_ack: bool = False


async def wait_for_ticket(
    listener: Listener,
    *,
    trace: Trace | None = None,
    url: str = GATEWAY_URL,
    max_sessions: int = 3,
    stop_after_qr: bool = False,
) -> LoginTicket | None:
    """Run QR sessions until the phone confirms. Returns None only with stop_after_qr."""
    trace = trace or Trace(None)
    for session in range(1, max_sessions + 1):
        listener.on_connecting(session)
        trace.event("session", number=session)
        try:
            return await _session(listener, trace, url, stop_after_qr)
        except _Restart as restart:
            trace.event("restart", reason=str(restart))
            if session < max_sessions:
                listener.on_restart(str(restart))
    raise DiscoopError(
        ExitCode.AUTH_REQUIRED,
        f"Not logged in: no QR code was confirmed in {max_sessions} attempts.",
        "Run `discoop login` again and scan the code before it expires.",
    )


async def _session(listener: Listener, trace: Trace, url: str, stop_after_qr: bool) -> LoginTicket | None:
    keys = RemoteAuthKeys()
    try:
        async with connect(url, origin=ORIGIN, user_agent_header=USER_AGENT, open_timeout=15) as ws:
            return await _converse(ws, keys, listener, trace, stop_after_qr)
    except InvalidStatus as e:
        status = e.response.status_code
        trace.event("refused", status=status)
        raise DiscoopError(
            ExitCode.ERROR, f"The QR login gateway refused the connection (HTTP {status}).", TOKEN_HINT
        ) from e
    except (InvalidHandshake, OSError, TimeoutError) as e:
        raise DiscoopError(
            ExitCode.NETWORK, f"Could not reach the QR login gateway: {e}", "Check the connection and try again."
        ) from e


async def _converse(
    ws: ClientConnection, keys: RemoteAuthKeys, listener: Listener, trace: Trace, stop_after_qr: bool
) -> LoginTicket | None:
    state = _HeartbeatState()
    heartbeat: asyncio.Task[None] | None = None
    deadline: float | None = None
    user: UserPayload | None = None

    async def send(payload: dict[str, Any]) -> None:
        trace.frame("out", payload)
        await ws.send(json.dumps(payload))

    try:
        async for raw in ws:
            message = json.loads(raw)
            trace.frame("in", message)
            op = message.get("op")
            if op == "hello":
                if "timeout_ms" in message:
                    deadline = time.monotonic() + message["timeout_ms"] / 1000
                interval = message["heartbeat_interval"] / 1000
                heartbeat = asyncio.create_task(_beat(ws, send, interval, state))
                await send({"op": "init", "encoded_public_key": keys.public_key_b64})
            elif op == "nonce_proof":
                await send({"op": "nonce_proof", "nonce": keys.nonce_proof(message["encrypted_nonce"])})
            elif op == "pending_remote_init":
                if message.get("fingerprint") != keys.fingerprint:
                    raise _Restart("fingerprint mismatch")
                listener.on_qr(qr_url(keys.fingerprint), deadline)
                if stop_after_qr:
                    await ws.close()
                    return None
            elif op == "heartbeat_ack":
                state.waiting_for_ack = False
            elif op == "pending_ticket":
                payload = keys.decrypt(message["encrypted_user_payload"]).decode("utf-8")
                user = parse_user_payload(payload)
                listener.on_scanned(user)
            elif op == "pending_login":
                ticket = message.get("ticket")
                if not ticket:
                    raise _Restart("no login ticket")
                await ws.close()
                return LoginTicket(ticket, keys, user)
            elif op == "cancel":
                raise _Restart("login cancelled on the phone")
            # Like the web client, ignore other ops; the trace still records them.
    except ConnectionClosed:
        pass
    finally:
        if heartbeat is not None:
            heartbeat.cancel()

    trace.close(ws.close_code, ws.close_reason)
    if state.missed_ack:
        raise _Restart("heartbeat not acknowledged")
    if ws.close_code == CLOSE_HANDSHAKE_TIMEOUT:
        raise _Restart("QR code expired")
    reason = f": {ws.close_reason}" if ws.close_reason else ""
    raise DiscoopError(
        ExitCode.ERROR,
        f"The QR login gateway closed the connection (code {ws.close_code}{reason}).",
        TOKEN_HINT,
    )


async def _beat(ws: ClientConnection, send: Any, interval: float, state: _HeartbeatState) -> None:
    """First heartbeat after a random part of the interval, then every interval."""
    try:
        await asyncio.sleep(random.random() * interval)
        while True:
            if state.waiting_for_ack:
                state.missed_ack = True
                await ws.close()
                return
            state.waiting_for_ack = True
            await send({"op": "heartbeat"})
            await asyncio.sleep(interval)
    except ConnectionClosed:
        pass
