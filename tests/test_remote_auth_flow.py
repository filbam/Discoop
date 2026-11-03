"""The whole QR login conversation against a local fake of Discord's remote auth gateway."""

import json

import pytest
from fake_gateway import TICKET, FakeGateway
from websockets.asyncio.server import serve

from discoop.errors import DiscoopError, ExitCode
from discoop.remote_auth.protocol import wait_for_ticket
from discoop.remote_auth.trace import Trace


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
        record["frame"]["op"]
        for record in map(json.loads, text.splitlines())
        if record["kind"] == "ws" and not record["frame"]["op"].startswith("heartbeat")
    ]
    assert ops[:5] == ["hello", "init", "nonce_proof", "nonce_proof", "pending_remote_init"]
    assert "pending_login" in ops
