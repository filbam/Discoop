"""The whole browser login against the fake DevTools endpoint and a fake browser process: where the token is found,
what happens when the window closes or the time runs out, that the browser is closed and the profile deleted in every
case, and that the token never reaches a log or a listener."""

import asyncio
import json
import logging
import time
from collections.abc import Callable
from contextlib import asynccontextmanager
from pathlib import Path

import pytest
from fake_cdp import (
    FAKE_TOKEN,
    OTHER_FAKE_TOKEN,
    PAGE_ID,
    SECOND_PAGE_ID,
    FakeCdpBrowser,
    FakeRequest,
    FakeSpawn,
    RecordingListener,
    discord_request,
    fast_timings,
    no_session_left_behind,  # noqa: F401
)

from discoop.browser_login import Browser, BrowserSession, flow, wait_for_browser_token
from discoop.browser_login.flow import (
    looks_like_token,
    token_from_request,
    token_from_storage,
    token_from_stored_value,
)
from discoop.errors import DiscoopError, ExitCode

BROWSER = Browser("Chrome", Path("/opt/chrome/chrome"))
CLOSED_MESSAGE = "The browser window was closed before the login finished."
CLOSED_HINT = "Run `discoop login --browser` again and finish the login in the window."
TIMEOUT_HINT = "Run `discoop login --browser` again; use --timeout to allow more time."
TRY_OTHER_HINT = "Try another browser with --browser-path, or use `discoop login --token`."
SETUP = [
    "Target.setDiscoverTargets",
    "Target.getTargets",
    "Target.attachToTarget",
    "DOMStorage.enable",
    "Network.enable",
]


class Rig:
    """A fake browser, a fake process launcher and a listener, wired into wait_for_browser_token."""

    def __init__(self, root: Path, fake: FakeCdpBrowser, spawn: FakeSpawn, timings) -> None:
        self.root = root
        self.fake = fake
        self.spawn = spawn
        self.timings = timings
        self.listener: RecordingListener

    def factory(self, browser: Browser) -> BrowserSession:
        return BrowserSession(browser, spawn=self.spawn, profile_root=self.root, timings=self.timings)

    def start(self, **kwargs) -> "asyncio.Task[str]":
        kwargs.setdefault("timeout", 5.0)
        kwargs.setdefault("poll_interval", 0.02)
        return asyncio.create_task(
            wait_for_browser_token(self.listener, browser=BROWSER, session_factory=self.factory, **kwargs)
        )

    async def run(self, **kwargs) -> str:
        return await asyncio.wait_for(self.start(**kwargs), 20)

    def profiles(self) -> list[str]:
        return sorted(p.name for p in self.root.glob("discoop-browser-*")) if self.root.exists() else []


@asynccontextmanager
async def rig(
    tmp_path: Path,
    *,
    spawn_kwargs: dict | None = None,
    timings=None,
    on_opened: Callable[[Rig], None] | None = None,
    on_captured: Callable[[Rig], None] | None = None,
    **fake_kwargs,
):
    fake = FakeCdpBrowser(**fake_kwargs)
    async with fake.running():
        r = Rig(tmp_path / "profiles", fake, FakeSpawn(fake, **(spawn_kwargs or {})), timings or fast_timings())
        hooks = {}
        if on_opened:
            hooks["on_opened"] = lambda: on_opened(r)
        if on_captured:
            hooks["on_captured"] = lambda: on_captured(r)
        r.listener = RecordingListener(**hooks)
        yield r


def assert_cleaned_up(r: Rig) -> None:
    assert r.profiles() == []
    assert all(process.returncode is not None for process in r.spawn.processes)


# -- the token is found ----------------------------------------------------------------------------------------


async def test_token_from_local_storage_after_a_few_polls(tmp_path):
    async with rig(tmp_path, storage_token=FAKE_TOKEN, storage_after=2) as r:
        token = await r.run()
        assert token == FAKE_TOKEN  # exactly: no quotes, no padding
        assert r.listener.kinds == ["launching", "opened", "captured"]
        assert r.listener.events[0] == ("launching", "Chrome")
        assert r.fake.storage_reads == 3
        assert [name for name, _ in r.fake.commands[:5]] == SETUP
        assert r.fake.storage_shapes == ["securityOrigin"] * 3  # the first form is kept while it works
        # page-level commands go to the attached session, browser-level ones do not
        session = r.fake.commands[3][1]
        assert session is not None and r.fake.commands[4][1] == session
        assert all(s is None for name, s in r.fake.commands if name.startswith(("Target.", "Browser.")))
        assert r.fake.origins == [None]
    assert_cleaned_up(r)


async def test_token_from_the_authorization_header_when_it_is_not_in_storage(tmp_path):
    async with rig(tmp_path, requests=[discord_request(FAKE_TOKEN)]) as r:
        assert await r.run() == FAKE_TOKEN
        assert r.listener.kinds == ["launching", "opened", "captured"]
    assert_cleaned_up(r)


@pytest.mark.parametrize("header_name", ["authorization", "AUTHORIZATION", "Authorization"])
async def test_the_header_name_is_case_insensitive(tmp_path, header_name):
    async with rig(tmp_path, requests=[discord_request(FAKE_TOKEN, header_name)]) as r:
        assert await r.run() == FAKE_TOKEN


async def test_other_requests_and_other_headers_are_ignored(tmp_path):
    decoys = [
        FakeRequest("https://example.com/api/v9/users/@me", {"Authorization": OTHER_FAKE_TOKEN}),  # not Discord
        FakeRequest("https://discord.com/login", {"Authorization": OTHER_FAKE_TOKEN}),  # not the API
        FakeRequest("https://discord.com.evil.example/api/x", {"Authorization": OTHER_FAKE_TOKEN}),
        FakeRequest("https://discord.com/api/v9/auth/login", {"Content-Type": "application/json"}),  # no header
        FakeRequest("https://discord.com/api/v9/x", {"Authorization": "Bearer " + OTHER_FAKE_TOKEN}),  # whitespace
        FakeRequest("https://discord.com/api/v9/x", {"authorization": "short"}),  # too short
        FakeRequest("https://discord.com/api/v9/x", {"X-Super-Properties": OTHER_FAKE_TOKEN}),  # another header
        FakeRequest(
            "https://discord.com/api/v9/x", {"Authorization": OTHER_FAKE_TOKEN}, session="SOME-OTHER-SESSION"
        ),  # another session
    ]
    async with rig(tmp_path, requests=[*decoys, discord_request(FAKE_TOKEN)]) as r:
        assert await r.run() == FAKE_TOKEN


async def test_the_first_source_to_hit_wins(tmp_path):
    # the header arrives at once, the storage only after many polls
    late_storage = {"storage_token": OTHER_FAKE_TOKEN, "storage_after": 10_000}
    async with rig(tmp_path, requests=[discord_request(FAKE_TOKEN)], **late_storage) as r:
        assert await r.run() == FAKE_TOKEN
    # the storage has it at once, the header only much later
    async with rig(
        tmp_path, storage_token=FAKE_TOKEN, requests=[discord_request(OTHER_FAKE_TOKEN)], request_delay=3.0
    ) as r:
        assert await r.run() == FAKE_TOKEN


async def test_a_stored_value_that_is_not_json_is_used_as_it_is(tmp_path):
    async with rig(tmp_path, raw_storage_value=FAKE_TOKEN) as r:
        assert await r.run() == FAKE_TOKEN


async def test_a_stored_value_that_is_no_token_never_ends_the_wait(tmp_path):
    no_tokens = (
        json.dumps("too short"),
        json.dumps("has a space in it, even if long enough"),
        "null",
        "12345678901234567890123",  # a JSON number
    )
    for value in no_tokens:
        async with rig(tmp_path, raw_storage_value=value) as r:
            with pytest.raises(DiscoopError) as e:
                await r.run(timeout=0.3, poll_interval=0.05)
            assert e.value.code == ExitCode.AUTH_REQUIRED and "not finished" in e.value.message


async def test_the_poll_interval_spaces_the_storage_reads(tmp_path):
    async with rig(tmp_path, storage_token=FAKE_TOKEN, storage_after=2) as r:
        started = time.monotonic()
        await r.run(poll_interval=0.15)
        assert time.monotonic() - started >= 0.28  # three reads, two waits of 0.15 s


async def test_a_page_that_shows_up_late_is_waited_for(tmp_path, monkeypatch):
    monkeypatch.setattr(flow, "PAGE_POLL", 0.01)
    async with rig(tmp_path, empty_polls=(1, 2, 3), storage_token=FAKE_TOKEN) as r:
        assert await r.run() == FAKE_TOKEN
        assert r.fake.get_targets_calls >= 4
    assert_cleaned_up(r)


# -- storage details -------------------------------------------------------------------------------------------


async def test_when_security_origin_is_rejected_storage_key_is_used_and_remembered(tmp_path):
    async with rig(tmp_path, reject_security_origin=True, storage_token=FAKE_TOKEN, storage_after=3) as r:
        assert await r.run() == FAKE_TOKEN
        assert r.fake.storage_shapes == ["securityOrigin", "storageKey", "storageKey", "storageKey", "storageKey"]


async def test_storage_errors_while_the_page_loads_only_mean_not_yet(tmp_path):
    async with rig(tmp_path, storage_errors=4, storage_token=FAKE_TOKEN) as r:
        assert await r.run() == FAKE_TOKEN
        assert r.fake.storage_shapes[:4] == ["securityOrigin", "storageKey", "securityOrigin", "storageKey"]


async def test_storage_that_never_works_does_not_hide_the_header(tmp_path):
    async with rig(tmp_path, storage_errors=10**6, requests=[discord_request(FAKE_TOKEN)]) as r:
        assert await r.run() == FAKE_TOKEN


async def test_storage_that_never_works_is_a_timeout_not_a_browser_error(tmp_path):
    async with rig(tmp_path, storage_errors=10**6) as r:
        with pytest.raises(DiscoopError) as e:
            await r.run(timeout=0.3, poll_interval=0.05)
        assert e.value.code == ExitCode.AUTH_REQUIRED


# -- the window goes away ------------------------------------------------------------------------------------


def assert_closed_error(e: pytest.ExceptionInfo[DiscoopError]) -> None:
    assert e.value.code == ExitCode.AUTH_REQUIRED
    assert e.value.message == CLOSED_MESSAGE
    assert e.value.hint == CLOSED_HINT


async def test_a_dropped_connection_means_the_window_was_closed(tmp_path):
    async with rig(tmp_path, drop_after=6) as r:  # after the five setup commands and one poll
        with pytest.raises(DiscoopError) as e:
            await r.run()
        assert_closed_error(e)
        assert r.listener.kinds == ["launching", "opened"]
    assert_cleaned_up(r)


async def test_no_page_for_two_polls_in_a_row_means_the_window_was_closed(tmp_path):
    async with rig(tmp_path, gone_after=3) as r:
        with pytest.raises(DiscoopError) as e:
            await r.run()
        assert_closed_error(e)
        assert r.fake.get_targets_calls == 5  # calls 4 and 5 listed no page: exactly two empty polls
    assert_cleaned_up(r)


async def test_a_single_empty_poll_is_not_enough(tmp_path):
    async with rig(tmp_path, empty_polls=(3,), storage_token=FAKE_TOKEN, storage_after=4) as r:
        assert await r.run() == FAKE_TOKEN
        assert r.fake.get_targets_calls >= 6


async def test_the_destroyed_page_event_triggers_an_immediate_poll(tmp_path):
    def close_first_page_soon(r: Rig) -> None:
        async def after_the_first_read() -> None:
            while r.fake.storage_reads < 1:
                await asyncio.sleep(0.005)
            await r.fake.destroy_page()  # the flow is idle now, waiting for its next poll

        r.fake._tasks.add(asyncio.get_running_loop().create_task(after_the_first_read()))

    async with rig(
        tmp_path, second_page=True, storage_token=FAKE_TOKEN, storage_after=1, on_opened=close_first_page_soon
    ) as r:
        started = time.monotonic()
        # a normal poll would only come after half a minute: the event makes the flow look at the targets at once
        assert await r.run(poll_interval=30.0, timeout=10.0) == FAKE_TOKEN
        assert time.monotonic() - started < 5
        assert SECOND_PAGE_ID in r.fake.attached.values()


async def test_when_the_page_goes_away_but_another_one_is_open_it_attaches_to_that(tmp_path):
    async with rig(
        tmp_path, gone_after=2, second_page=True, emit_destroyed=True, storage_token=FAKE_TOKEN, storage_after=1
    ) as r:
        assert await r.run() == FAKE_TOKEN
        assert list(r.fake.attached.values()) == [PAGE_ID, SECOND_PAGE_ID]
        assert len(r.fake.commands_named("Network.enable")) == 2
        assert len(r.fake.commands_named("DOMStorage.enable")) == 2
    assert_cleaned_up(r)


async def test_the_page_that_shows_discord_is_preferred_from_the_start(tmp_path):
    async with rig(
        tmp_path, page_urls={PAGE_ID: "chrome://newtab/"}, second_page_from=1, storage_token=FAKE_TOKEN
    ) as r:
        assert await r.run() == FAKE_TOKEN
        assert list(r.fake.attached.values()) == [SECOND_PAGE_ID]


async def test_it_follows_the_page_that_shows_discord_when_the_watched_one_is_elsewhere(tmp_path):
    # the first page is not on Discord; a second one that is opens a moment later (the first one stays open)
    async with rig(
        tmp_path, page_urls={PAGE_ID: "chrome://welcome/"}, second_page_from=3, storage_token=FAKE_TOKEN
    ) as r:
        assert await r.run() == FAKE_TOKEN
        assert list(r.fake.attached.values()) == [PAGE_ID, SECOND_PAGE_ID]


async def test_it_stays_on_a_page_that_shows_discord_even_if_another_one_does_too(tmp_path):
    async with rig(tmp_path, second_page_from=2, storage_token=FAKE_TOKEN, storage_after=3) as r:
        assert await r.run() == FAKE_TOKEN
        assert list(r.fake.attached.values()) == [PAGE_ID]  # no flapping between the two


async def test_the_process_exiting_means_the_window_was_closed(tmp_path):
    def close_window(r: Rig) -> None:
        r.spawn.processes[0].exit(0)  # the connection is still up: only the process tells

    async with rig(tmp_path, on_opened=close_window) as r:
        with pytest.raises(DiscoopError) as e:
            await r.run()
        assert_closed_error(e)
    assert_cleaned_up(r)


# -- time runs out -----------------------------------------------------------------------------------------------


async def test_timeout(tmp_path):
    async with rig(tmp_path) as r:
        before = time.monotonic()
        with pytest.raises(DiscoopError) as e:
            await r.run(timeout=0.3, poll_interval=0.05)
        after = time.monotonic()
        assert e.value.code == ExitCode.AUTH_REQUIRED
        assert e.value.message == "The login was not finished within 0.3 seconds."
        assert e.value.hint == TIMEOUT_HINT
        assert before + 0.3 <= r.listener.deadline <= after + 0.3  # a time.monotonic() value
        assert 0.3 <= after - before < 5
        assert r.listener.kinds == ["launching", "opened"]
    assert_cleaned_up(r)


@pytest.mark.parametrize(
    ("seconds", "text"),
    [
        (300, "5 minutes"),
        (60, "1 minute"),
        (120.0, "2 minutes"),
        (90, "90 seconds"),
        (45, "45 seconds"),
        (1, "1 second"),
        (0.5, "0.5 seconds"),
    ],
)
def test_the_timeout_is_described_in_words(seconds, text):
    assert flow._describe(seconds) == text


# -- unexpected browser behaviour ----------------------------------------------------------------------------------


@pytest.mark.parametrize("method", SETUP)
async def test_a_refused_command_is_an_error_that_names_only_the_command(tmp_path, method):
    async with rig(tmp_path, errors={method: (-32601, "SECRET-DETAIL-FROM-THE-BROWSER")}) as r:
        with pytest.raises(DiscoopError) as e:
            await r.run()
        assert e.value.code == ExitCode.ERROR
        assert e.value.message == f"The browser did not respond as expected ({method} failed)."
        assert e.value.hint == TRY_OTHER_HINT
        assert "SECRET" not in e.value.message and "SECRET" not in str(e.value)
    assert_cleaned_up(r)


async def test_an_unanswered_command_is_an_error_too(tmp_path, monkeypatch):
    monkeypatch.setattr(flow, "COMMAND_TIMEOUT", 0.2)
    async with rig(tmp_path, hang=("Target.getTargets",)) as r:
        with pytest.raises(DiscoopError) as e:
            await r.run()
        assert e.value.code == ExitCode.ERROR
        assert e.value.message == "The browser did not respond as expected (Target.getTargets failed)."
    assert_cleaned_up(r)


async def test_a_browser_without_any_page_is_an_error(tmp_path, monkeypatch):
    monkeypatch.setattr(flow, "PAGE_WAIT", 0.2)
    monkeypatch.setattr(flow, "PAGE_POLL", 0.02)
    async with rig(tmp_path, gone_after=0) as r:
        with pytest.raises(DiscoopError) as e:
            await r.run()
        assert e.value.code == ExitCode.ERROR
        assert e.value.message == "Chrome did not start in time."
        assert r.listener.kinds == ["launching"]
    assert_cleaned_up(r)


# -- the browser cannot be started -------------------------------------------------------------------------------


async def test_a_browser_that_cannot_be_started_is_an_error_before_anything_opens(tmp_path):
    async with rig(tmp_path, spawn_kwargs={"error": FileNotFoundError(2, "No such file or directory")}) as r:
        with pytest.raises(DiscoopError) as e:
            await r.run()
        assert e.value.code == ExitCode.ERROR
        assert e.value.message == "Chrome could not be started: the file was not found."
        assert e.value.hint == TRY_OTHER_HINT
        assert r.listener.kinds == ["launching"]
    assert_cleaned_up(r)


async def test_a_browser_that_exits_at_once_is_an_error(tmp_path):
    async with rig(tmp_path, spawn_kwargs={"exit_code": 1, "port_file": "none"}) as r:
        with pytest.raises(DiscoopError) as e:
            await r.run()
        assert e.value.message == "Chrome could not be started: it exited right away (code 1)."
    assert_cleaned_up(r)


async def test_a_browser_that_never_writes_its_port_is_an_error(tmp_path):
    async with rig(tmp_path, spawn_kwargs={"port_file": "none"}, timings=fast_timings(port_wait=0.2)) as r:
        with pytest.raises(DiscoopError) as e:
            await r.run()
        assert e.value.message == "Chrome did not start in time."
    assert_cleaned_up(r)


async def test_edge_style_relaunch_works_from_start_to_finish(tmp_path):
    async with rig(tmp_path, spawn_kwargs={"exit_code": 0, "port_delay": 0.05}, storage_token=FAKE_TOKEN) as r:
        assert await r.run() == FAKE_TOKEN
        assert r.fake.close_requested  # the real browser was closed over DevTools
    assert r.profiles() == []


# -- the browser is closed and the profile deleted, always ----------------------------------------------------------


async def test_the_browser_is_closed_and_the_profile_gone_before_the_function_returns(tmp_path):
    seen: dict[str, bool] = {}

    def at_capture(r: Rig) -> None:
        seen["closed_already"] = r.fake.close_requested
        seen["profile_there"] = bool(r.profiles())

    async with rig(tmp_path, storage_token=FAKE_TOKEN, on_captured=at_capture) as r:
        await r.run()
        # on_captured comes first: the window is still open and the profile still there
        assert seen == {"closed_already": False, "profile_there": True}
        # when the call returns, both are done
        assert r.fake.close_requested
        assert r.spawn.processes[0].returncode == 0
        assert r.profiles() == []


async def test_cancelling_while_waiting_closes_the_browser_and_deletes_the_profile(tmp_path):
    async with rig(tmp_path) as r:
        task = r.start(timeout=60.0)
        await asyncio.wait_for(r.listener.opened.wait(), 5)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert r.fake.close_requested
        assert r.spawn.processes[0].returncode == 0
    assert_cleaned_up(r)


async def test_an_error_in_the_listener_still_cleans_up(tmp_path):
    def explode(r: Rig) -> None:
        raise RuntimeError("the screen broke")

    async with rig(tmp_path, on_opened=explode) as r:
        with pytest.raises(RuntimeError, match="the screen broke"):
            await r.run()
    assert_cleaned_up(r)


async def test_a_browser_that_ignores_browser_close_does_not_keep_the_profile(tmp_path):
    async with rig(tmp_path, ignore_close=True, storage_token=FAKE_TOKEN) as r:
        assert await r.run() == FAKE_TOKEN
        process = r.spawn.processes[0]
        assert process.terminate_calls == 1 and process.returncode == -15
    assert r.profiles() == []


# -- the token stays out of logs, messages and the listener -------------------------------------------------------


def everything_in(record: logging.LogRecord) -> str:
    return " ".join([record.getMessage(), str(record.args), str(record.exc_text), str(record.__dict__)])


@pytest.mark.parametrize("source", ["storage", "header"])
async def test_the_token_never_reaches_a_log_record_or_the_listener(tmp_path, caplog, source):
    caplog.set_level(logging.DEBUG)  # the root logger at DEBUG: websockets would log every frame if it could
    kwargs = {"storage_token": FAKE_TOKEN} if source == "storage" else {"requests": [discord_request(FAKE_TOKEN)]}
    async with rig(tmp_path, **kwargs) as r:
        assert await r.run() == FAKE_TOKEN
        root = str(r.root)
        profile_name = r.spawn.profiles[0].name

    ours = [rec for rec in caplog.records if rec.name == "discoop.browser_login"]
    assert ours, "the engine should log its short events at DEBUG"
    messages = [rec.getMessage() for rec in ours]
    assert "launching browser=Chrome" in messages
    assert f"token found source={source}" in messages
    assert "profile_removed=true" in messages
    for record in caplog.records:
        text = everything_in(record)
        assert FAKE_TOKEN not in text, record.name
        assert root not in text and profile_name not in text and "DevToolsActivePort" not in text
    assert FAKE_TOKEN not in caplog.text
    assert not [rec for rec in caplog.records if rec.name.startswith("websockets")]
    assert FAKE_TOKEN not in repr(r.listener.events)
    assert all(isinstance(part, (str, float)) for event in r.listener.events for part in event)


async def test_errors_and_logs_never_carry_what_the_browser_said(tmp_path, caplog):
    caplog.set_level(logging.DEBUG)
    async with rig(tmp_path, errors={"Network.enable": (-32000, "SECRET-DETAIL-FROM-THE-BROWSER")}) as r:
        with pytest.raises(DiscoopError) as e:
            await r.run()
    assert "SECRET" not in e.value.message and "SECRET" not in (e.value.hint or "")
    for record in caplog.records:
        assert "SECRET" not in everything_in(record)
    assert any(rec.getMessage() == "cdp command failed method=Network.enable" for rec in caplog.records)


async def test_a_wrong_token_in_the_header_stays_out_of_the_logs_too(tmp_path, caplog):
    caplog.set_level(logging.DEBUG)
    decoy = FakeRequest(
        "https://discord.com/api/v9/x", {"Authorization": OTHER_FAKE_TOKEN}, session="SOME-OTHER-SESSION"
    )
    async with rig(tmp_path, requests=[decoy, discord_request(FAKE_TOKEN)]) as r:
        await r.run()
    assert OTHER_FAKE_TOKEN not in caplog.text and FAKE_TOKEN not in caplog.text


# -- the pure helpers --------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (FAKE_TOKEN, True),
        ("x" * 20, True),
        ("x" * 19, False),
        ("", False),
        ("a" * 10 + " " + "b" * 20, False),
        ("a" * 30 + "\n", False),
        (None, False),
        (12345678901234567890, False),
        (["x" * 30], False),
    ],
)
def test_looks_like_token(value, expected):
    assert looks_like_token(value) is expected


@pytest.mark.parametrize(
    ("stored", "expected"),
    [
        (json.dumps(FAKE_TOKEN), FAKE_TOKEN),
        (FAKE_TOKEN, FAKE_TOKEN),  # not JSON at all: used as it is
        (json.dumps("short"), None),
        (json.dumps(["x" * 30]), None),
        (json.dumps({"token": "x" * 30}), None),
        ("null", None),
        ("", None),
        (None, None),
        (12345, None),
    ],
)
def test_token_from_stored_value(stored, expected):
    assert token_from_stored_value(stored) == expected


def test_token_from_storage_looks_only_at_the_token_key():
    entries = [
        ["Token", json.dumps(OTHER_FAKE_TOKEN)],
        ["other", json.dumps(OTHER_FAKE_TOKEN)],
        ["token", json.dumps(FAKE_TOKEN)],
    ]
    assert token_from_storage(entries) == FAKE_TOKEN
    assert token_from_storage(entries[:2]) is None
    assert token_from_storage([]) is None
    assert token_from_storage(None) is None
    assert token_from_storage({"token": FAKE_TOKEN}) is None
    assert token_from_storage([["token"], "token", ["token", json.dumps(FAKE_TOKEN), "extra"]]) is None


def test_token_from_request_needs_a_discord_api_url_and_an_authorization_header():
    def params(url, headers):
        return {"request": {"url": url, "headers": headers}}

    api = "https://discord.com/api/v9/users/@me"
    assert token_from_request(params(api, {"Authorization": FAKE_TOKEN})) == FAKE_TOKEN
    assert token_from_request(params(api, {"aUtHoRiZaTiOn": FAKE_TOKEN})) == FAKE_TOKEN
    assert token_from_request(params("https://discord.com/api/", {"Authorization": FAKE_TOKEN})) == FAKE_TOKEN
    assert token_from_request(params("https://discord.com/apiary", {"Authorization": FAKE_TOKEN})) is None
    assert token_from_request(params("https://cdn.discordapp.com/api/x", {"Authorization": FAKE_TOKEN})) is None
    assert token_from_request(params(api, {"Authorization": "Bot " + "x" * 30})) is None
    assert token_from_request(params(api, {"Cookie": FAKE_TOKEN})) is None
    assert token_from_request(params(api, {})) is None
    assert token_from_request(params(api, None)) is None
    assert token_from_request(params(None, {"Authorization": FAKE_TOKEN})) is None
    assert token_from_request({"request": None}) is None
    assert token_from_request(None) is None
    assert token_from_request("Authorization") is None
