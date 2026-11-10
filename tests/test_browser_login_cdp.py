"""The DevTools client against the fake browser endpoint: commands, errors, events and a lost connection."""

import asyncio

import pytest
from fake_cdp import ENDPOINT_PATH, PAGE_ID, FakeCdpBrowser, no_session_left_behind  # noqa: F401
from websockets.asyncio.client import connect
from websockets.exceptions import InvalidStatus

from discoop.browser_login import CdpClient, CdpConnectionLost, CdpError, CdpEvent, CdpTimeout


def url(fake: FakeCdpBrowser) -> str:
    return f"ws://127.0.0.1:{fake.port}{ENDPOINT_PATH}"


async def test_a_command_returns_its_result():
    fake = FakeCdpBrowser()
    async with fake.running():
        client = await CdpClient.connect(url(fake))
        result = await client.send("Target.getTargets")
        await client.close()
    assert any(info["type"] == "page" for info in result["targetInfos"])
    assert fake.commands == [("Target.getTargets", None)]


async def test_no_origin_header_is_sent_and_the_endpoint_path_is_used():
    fake = FakeCdpBrowser()
    async with fake.running():
        client = await CdpClient.connect(url(fake))
        await client.close()
    assert fake.origins == [None]
    assert fake.paths == [ENDPOINT_PATH]


async def test_the_fake_really_refuses_a_foreign_origin_like_chrome():
    fake = FakeCdpBrowser()
    async with fake.running():
        with pytest.raises(InvalidStatus) as e:
            async with connect(url(fake), origin="http://example.invalid", proxy=None):
                pass
    assert e.value.response.status_code == 403


async def test_the_session_id_is_sent_with_a_page_level_command():
    fake = FakeCdpBrowser()
    async with fake.running():
        client = await CdpClient.connect(url(fake))
        session = (await client.send("Target.attachToTarget", {"targetId": PAGE_ID, "flatten": True}))["sessionId"]
        await client.send("DOMStorage.enable", session_id=session)
        await client.close()
    assert fake.commands[-1] == ("DOMStorage.enable", session)


async def test_an_error_response_raises_cdp_error_without_leaking_into_its_text():
    fake = FakeCdpBrowser(errors={"Target.getTargets": (-32000, "SECRET-DETAIL")})
    async with fake.running():
        client = await CdpClient.connect(url(fake))
        with pytest.raises(CdpError) as e:
            await client.send("Target.getTargets")
        await client.close()
    assert e.value.method == "Target.getTargets" and e.value.code == -32000
    assert "SECRET-DETAIL" not in str(e.value)  # the browser's own text is kept on the object only
    assert e.value.message == "SECRET-DETAIL"


async def test_an_unanswered_command_times_out():
    fake = FakeCdpBrowser(hang=("Target.getTargets",))
    async with fake.running():
        client = await CdpClient.connect(url(fake))
        with pytest.raises(CdpTimeout) as e:
            await client.send("Target.getTargets", timeout=0.1)
        # the connection is still fine afterwards
        assert (await client.send("Target.setDiscoverTargets")) == {}
        await client.close()
    assert e.value.method == "Target.getTargets"


async def test_events_are_queued_in_order_and_can_be_polled_or_awaited():
    fake = FakeCdpBrowser()
    async with fake.running():
        client = await CdpClient.connect(url(fake))
        await client.send("Target.setDiscoverTargets")
        assert client.pending_event() is None
        assert await client.next_event(0.05) is None  # nothing yet: times out
        await fake.emit("Test.first", {"n": 1}, "S1")
        await fake.emit("Test.second", {"n": 2})
        first = await client.next_event(1.0)
        second = None
        for _ in range(200):  # the second event is on its way
            second = client.pending_event()
            if second is not None:
                break
            await asyncio.sleep(0.01)
        await client.close()
    assert first == CdpEvent("Test.first", {"n": 1}, "S1")
    assert second == CdpEvent("Test.second", {"n": 2}, None)


async def test_event_parameters_stay_out_of_repr():
    event = CdpEvent("Network.requestWillBeSent", {"request": {"headers": {"Authorization": "SECRET"}}}, "S")
    assert "SECRET" not in repr(event) and "Network.requestWillBeSent" in repr(event)


async def test_a_lost_connection_fails_pending_and_later_commands_and_ends_the_event_stream():
    fake = FakeCdpBrowser(drop_after=1, hang=("Test.never",))
    async with fake.running():
        client = await CdpClient.connect(url(fake))
        await fake.emit("Test.before", {})
        assert (await client.send("Target.setDiscoverTargets")) == {}
        with pytest.raises(CdpConnectionLost):
            await client.send("Test.never", timeout=2.0)  # the fake aborts the connection while this is pending
        assert await client.wait_lost(1.0) and client.lost
        with pytest.raises(CdpConnectionLost):
            await client.send("Target.getTargets")
        # events that arrived before the loss are still delivered, then the loss is reported (every time)
        assert (await client.next_event(1.0)).method == "Test.before"
        with pytest.raises(CdpConnectionLost):
            await client.next_event(1.0)
        with pytest.raises(CdpConnectionLost):
            client.pending_event()
        await client.close()


async def test_wait_lost_times_out_while_the_connection_is_up():
    fake = FakeCdpBrowser()
    async with fake.running():
        client = await CdpClient.connect(url(fake))
        assert not client.lost
        assert await client.wait_lost(0.05) is False
        await client.close()
        assert await client.wait_lost(1.0) is True


async def test_close_is_idempotent_and_ends_the_session():
    fake = FakeCdpBrowser()
    async with fake.running():
        client = await CdpClient.connect(url(fake))
        await client.close()
        await client.close()
        with pytest.raises(CdpConnectionLost):
            await client.send("Target.getTargets")
        await asyncio.wait_for(fake.connection_closed.wait(), 2.0)


async def test_cancelling_a_waiting_command_leaves_the_client_usable():
    fake = FakeCdpBrowser(hang=("Test.never",))
    async with fake.running():
        client = await CdpClient.connect(url(fake))
        task = asyncio.create_task(client.send("Test.never", timeout=5.0))
        await asyncio.sleep(0.05)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert (await client.send("Target.setDiscoverTargets")) == {}
        await client.close()
