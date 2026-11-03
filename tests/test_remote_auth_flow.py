"""The whole QR login conversation against a local fake of Discord's remote auth gateway."""

import base64
import hashlib
import json
import os

import pytest
from cryptography.hazmat.primitives import serialization
from websockets.asyncio.server import serve

from discoop.errors import DiscoopError, ExitCode
from discoop.remote_auth.crypto import OAEP_SHA256, b64url
from discoop.remote_auth.protocol import wait_for_ticket
from discoop.remote_auth.trace import Trace

TICKET = "TICKET-SECRET-VALUE"


class FakeGateway:
    """Plays one scripted session per connection: complete, expire, cancel, qr_only or odd_op."""

    def __init__(self, *sessions: str) -> None:
        self.sessions = list(sessions)
        self.origins: list[str | None] = []
        self.proofs_ok = 0
        self.heartbeats = 0
        self.secrets: list[str] = []

    async def handler(self, ws) -> None:
        behavior = self.sessions.pop(0)
        self.origins.append(ws.request.headers.get("Origin"))
        await ws.send(json.dumps({"op": "hello", "heartbeat_interval": 50, "timeout_ms": 120000}))
        nonce = os.urandom(190)
        public_key = None
        async for raw in ws:
            message = json.loads(raw)
            op = message["op"]
            if op == "heartbeat":
                self.heartbeats += 1
                await ws.send(json.dumps({"op": "heartbeat_ack"}))
            elif op == "init":
                spki = base64.b64decode(message["encoded_public_key"])
                public_key = serialization.load_der_public_key(spki)
                encrypted = base64.b64encode(public_key.encrypt(nonce, OAEP_SHA256)).decode()
                self.secrets += [message["encoded_public_key"], encrypted]
                await ws.send(json.dumps({"op": "nonce_proof", "encrypted_nonce": encrypted}))
            elif op == "nonce_proof":
                if message["nonce"] == b64url(nonce):
                    self.proofs_ok += 1
                fingerprint = b64url(hashlib.sha256(spki).digest())
                self.secrets += [message["nonce"], fingerprint]
                await ws.send(json.dumps({"op": "pending_remote_init", "fingerprint": fingerprint}))
                if behavior == "expire":
                    await ws.close(4003, "Handshake Timeout")
                    return
                if behavior == "cancel":
                    await ws.send(json.dumps({"op": "cancel"}))
                elif behavior == "odd_op":
                    await ws.send(json.dumps({"op": "something_new"}))
                    await ws.close(4000, "Odd")
                    return
                elif behavior == "complete":
                    payload = public_key.encrypt(b"123456789:0:0:some_user", OAEP_SHA256)
                    encrypted_payload = base64.b64encode(payload).decode()
                    self.secrets.append(encrypted_payload)
                    await ws.send(json.dumps({"op": "pending_ticket", "encrypted_user_payload": encrypted_payload}))
                    await ws.send(json.dumps({"op": "pending_login", "ticket": TICKET}))


class RecordingListener:
    def __init__(self) -> None:
        self.events: list[tuple] = []

    def on_connecting(self, session):
        self.events.append(("connecting", session))

    def on_qr(self, url, deadline):
        self.events.append(("qr", url))

    def on_scanned(self, user):
        self.events.append(("scanned", user.username))

    def on_restart(self, reason):
        self.events.append(("restart", reason))


async def run(gateway: FakeGateway, **kwargs):
    listener = RecordingListener()
    async with serve(gateway.handler, "127.0.0.1", 0) as server:
        port = server.sockets[0].getsockname()[1]
        result = await wait_for_ticket(listener, url=f"ws://127.0.0.1:{port}", **kwargs)
    return result, listener


async def test_complete_login():
    gateway = FakeGateway("complete")
    result, listener = await run(gateway)
    assert result is not None and result.ticket == TICKET
    assert result.user is not None and result.user.username == "some_user"
    assert gateway.origins == ["https://discord.com"]
    assert gateway.proofs_ok == 1
    kinds = [e[0] for e in listener.events]
    assert kinds == ["connecting", "qr", "scanned"]
    assert listener.events[1][1] == f"https://discord.com/ra/{result.keys.fingerprint}"


async def test_expired_qr_starts_a_new_session():
    result, listener = await run(FakeGateway("expire", "complete"))
    assert result is not None and result.ticket == TICKET
    assert ("restart", "QR code expired") in listener.events
    assert sum(1 for e in listener.events if e[0] == "qr") == 2


async def test_cancel_on_phone_starts_a_new_session():
    result, listener = await run(FakeGateway("cancel", "complete"))
    assert result is not None
    assert ("restart", "login cancelled on the phone") in listener.events


async def test_gives_up_after_max_sessions():
    with pytest.raises(DiscoopError) as e:
        await run(FakeGateway("expire", "expire"), max_sessions=2)
    assert e.value.code == ExitCode.AUTH_REQUIRED


async def test_unknown_close_code_is_an_error_with_token_hint():
    with pytest.raises(DiscoopError) as e:
        await run(FakeGateway("odd_op"))
    assert "code 4000" in e.value.message
    assert "--token" in (e.value.hint or "")


async def test_stop_after_qr():
    result, listener = await run(FakeGateway("qr_only"), stop_after_qr=True)
    assert result is None
    assert [e[0] for e in listener.events] == ["connecting", "qr"]


async def test_trace_has_shapes_but_no_secrets(tmp_path):
    gateway = FakeGateway("complete")
    path = tmp_path / "trace.jsonl"
    with Trace(path) as trace:
        await run(gateway, trace=trace)
    text = path.read_text(encoding="utf-8")
    for secret in [TICKET, *gateway.secrets]:
        assert secret not in text
    ops = [
        record["frame"]["op"] for record in map(json.loads, text.splitlines()) if record["kind"] == "ws"
    ]
    assert ops[:5] == ["hello", "init", "nonce_proof", "nonce_proof", "pending_remote_init"]
    assert "pending_login" in ops
