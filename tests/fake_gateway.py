"""A local fake of Discord's remote auth gateway for tests."""

import asyncio
import base64
import hashlib
import json
import os
import threading
from collections.abc import Iterator
from contextlib import contextmanager

from cryptography.hazmat.primitives import serialization
from websockets.asyncio.server import serve

from discoop.remote_auth.crypto import OAEP_SHA256, b64url

TICKET = "TICKET-SECRET-VALUE"


class FakeGateway:
    """Plays one scripted session per connection: complete, expire, cancel, qr_only or odd_op."""

    def __init__(self, *sessions: str) -> None:
        self.sessions = list(sessions)
        self.origins: list[str | None] = []
        self.public_keys: list = []
        self.proofs_ok = 0
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
                await ws.send(json.dumps({"op": "heartbeat_ack"}))
            elif op == "init":
                spki = base64.b64decode(message["encoded_public_key"])
                public_key = serialization.load_der_public_key(spki)
                self.public_keys.append(public_key)
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


@contextmanager
def gateway_in_thread(gateway: FakeGateway) -> Iterator[str]:
    """Serve the fake gateway from a background thread (for code that calls asyncio.run itself)."""
    started = threading.Event()
    state: dict = {}

    def runner() -> None:
        async def main() -> None:
            state["loop"] = asyncio.get_running_loop()
            state["stop"] = asyncio.Event()
            async with serve(gateway.handler, "127.0.0.1", 0) as server:
                state["port"] = server.sockets[0].getsockname()[1]
                started.set()
                await state["stop"].wait()

        asyncio.run(main())

    thread = threading.Thread(target=runner, daemon=True)
    thread.start()
    assert started.wait(5), "fake gateway did not start"
    try:
        yield f"ws://127.0.0.1:{state['port']}"
    finally:
        state["loop"].call_soon_threadsafe(state["stop"].set)
        thread.join(5)
