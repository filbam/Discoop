"""`login.browser_login` and its helpers: the browser lookup, the verification and storing of the token, the screens
(text and JSON progress), and the whole login through the real browser engine against a fake DevTools server."""

import json
import logging
import time
from pathlib import Path

import httpx
import pytest
from browser_rig import BROWSER, ME, NOTICES, OTHER_TOKEN, TOKEN, EngineRig, FakeDiscord, Listener
from fake_cdp import discord_request, no_session_left_behind  # noqa: F401

from discoop import login
from discoop.api import DiscordAPI
from discoop.browser_login import Browser
from discoop.config import Config
from discoop.errors import DiscoopError, ExitCode
from discoop.output import Output
from discoop.tokenstore import TokenStore


class Seams:
    """The `find` and `wait` seams of browser_login: they remember their arguments and play a scripted engine."""

    def __init__(self, token: str = TOKEN, wait_error: Exception | None = None, find_error: Exception | None = None):
        self.token = token
        self.wait_error = wait_error
        self.find_error = find_error
        self.asked: list = []  # the browser_path arguments of find
        self.waits: list = []  # (browser, timeout) of wait

    def find(self, browser_path):
        self.asked.append(browser_path)
        if self.find_error is not None:
            raise self.find_error
        return BROWSER

    async def wait(self, listener, *, browser, timeout):
        self.waits.append((browser, timeout))
        listener.on_launching(browser.name)
        if self.wait_error is not None:
            raise self.wait_error
        listener.on_captured()
        return self.token


def browser_login(seams: Seams, discord: FakeDiscord | None = None, listener: Listener | None = None, **kwargs):
    return login.browser_login(
        listener or Listener(),
        TokenStore.default(),
        api_factory=(discord or FakeDiscord()).api_factory,
        find=seams.find,
        wait=seams.wait,
        **kwargs,
    )


# -- browser_login with scripted seams ------------------------------------------------------------------------------


def test_browser_login_stores_the_token_and_returns_user_location_and_browser():
    seams, discord, listener = Seams(), FakeDiscord(), Listener()
    me, location, browser = browser_login(seams, discord, listener, browser_path="my-browser", timeout=123.0)
    assert me == ME
    assert browser == BROWSER
    assert location == TokenStore.default().keyring_name()
    assert TokenStore.default().load().token == TOKEN
    assert seams.asked == ["my-browser"]
    assert seams.waits == [(BROWSER, 123.0)]
    assert discord.requests == [("/api/v9/users/@me", TOKEN)]  # the one check of the token, nothing else
    assert listener.kinds == ["launching", "captured"]  # the listener reaches the engine


def test_browser_login_waits_five_minutes_by_default():
    seams = Seams()
    browser_login(seams)
    assert seams.waits == [(BROWSER, 300.0)]
    assert seams.asked == [None]


def test_a_token_that_discord_rejects_is_exit_code_2_and_nothing_is_stored():
    seams, discord = Seams(token=OTHER_TOKEN), FakeDiscord(accepts=TOKEN)
    with pytest.raises(DiscoopError) as e:
        browser_login(seams, discord)
    assert e.value.code == ExitCode.AUTH_REQUIRED
    assert e.value.message == "Discord did not accept the token read from the browser window."
    assert "`discoop login --browser`" in e.value.hint and "`discoop login --token`" in e.value.hint
    assert OTHER_TOKEN not in e.value.message and OTHER_TOKEN not in e.value.hint
    assert discord.requests == [("/api/v9/users/@me", OTHER_TOKEN)]
    assert TokenStore.default().load() is None


@pytest.mark.parametrize("code", [ExitCode.AUTH_REQUIRED, ExitCode.ERROR])
def test_the_errors_of_the_engine_pass_through_with_their_codes(code):
    error = DiscoopError(code, "The engine says no.", "The engine's hint.")
    seams, discord = Seams(wait_error=error), FakeDiscord()
    with pytest.raises(DiscoopError) as e:
        browser_login(seams, discord)
    assert e.value is error
    assert (e.value.code, e.value.message, e.value.hint) == (code, "The engine says no.", "The engine's hint.")
    assert discord.requests == []  # nothing to verify
    assert TokenStore.default().load() is None


def test_no_browser_is_exit_code_1_and_nothing_starts():
    error = DiscoopError(ExitCode.ERROR, "No supported browser was found (Chrome, Edge, Chromium or Brave).", "hint")
    seams, discord = Seams(find_error=error), FakeDiscord()
    with pytest.raises(DiscoopError) as e:
        browser_login(seams, discord, browser_path="nowhere")
    assert e.value is error
    assert seams.asked == ["nowhere"]
    assert seams.waits == []  # the engine never ran
    assert discord.requests == []


def test_other_errors_while_verifying_keep_their_code():
    def offline(token):
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("no network")

        return DiscordAPI(token, transport=httpx.MockTransport(handler), sleep=lambda seconds: None)

    seams = Seams()
    with pytest.raises(DiscoopError) as e:
        login.browser_login(Listener(), TokenStore.default(), api_factory=offline, find=seams.find, wait=seams.wait)
    assert e.value.code == ExitCode.NETWORK  # not turned into "the token was not accepted"
    assert TokenStore.default().load() is None


# -- the browser lookup ----------------------------------------------------------------------------------------------


@pytest.fixture
def asked_locator(monkeypatch):
    """Replaces the browser locator and records what find_login_browser asks it for."""
    asked: list = []

    def fake_find_browser(configured=None):
        asked.append(configured)
        return Browser("Chrome", Path("found-browser"))

    monkeypatch.setattr(login, "find_browser", fake_find_browser)
    return asked


def test_the_given_path_wins_then_the_setting_then_auto_detection(asked_locator):
    login.find_login_browser()
    assert asked_locator == [None]  # nothing given and nothing configured: the locator searches
    Config.default().set("browser-path", "/configured/browser")
    login.find_login_browser()
    login.find_login_browser(Path("/given/browser"))
    login.find_login_browser("")  # an empty path counts as not given
    login.find_login_browser(None)
    assert asked_locator == [
        None,
        "/configured/browser",  # the setting
        Path("/given/browser"),  # the given path wins over the setting
        "/configured/browser",  # an empty path counts as not given
        "/configured/browser",
    ]
    Config.default().unset("browser-path")
    login.find_login_browser()
    assert asked_locator[-1] is None


def test_the_real_locator_gets_a_given_file_and_a_configured_one(tmp_path, monkeypatch):
    monkeypatch.setenv("DISPLAY", ":0")  # on Linux the locator wants a desktop session
    program = tmp_path / "chrome.exe"
    program.write_text("not really a browser", encoding="utf-8")
    assert login.find_login_browser(program) == Browser("Chrome", program)
    assert login.find_login_browser(str(program)) == Browser("Chrome", program)

    Config.default().set("browser-path", str(program))
    assert login.find_login_browser() == Browser("Chrome", program)

    Config.default().set("browser-path", str(tmp_path / "gone.exe"))
    with pytest.raises(DiscoopError) as e:
        login.find_login_browser()
    assert e.value.code == ExitCode.ERROR
    assert e.value.message == f"Browser not found at {tmp_path / 'gone.exe'}."
    assert "browser-path" in e.value.hint


# -- the screens -----------------------------------------------------------------------------------------------------

def play(screen: login.BrowserScreen, seconds: float = 300.0) -> None:
    screen.on_launching("Chrome")
    screen.on_opened(time.monotonic() + seconds)
    screen.on_captured()


def test_the_text_screen_prints_its_notices_in_order_for_a_human(capsys):
    play(login.BrowserScreen(Output(plain=False)))
    captured = capsys.readouterr()
    assert captured.out == ""  # notices are not data: they go to stderr
    text = " ".join(captured.err.split())  # the terminal wraps long lines
    positions = [text.index(notice) for notice in NOTICES]
    assert positions == sorted(positions)


def test_the_text_screen_is_silent_in_plain_mode_unless_verbose(capsys):
    play(login.BrowserScreen(Output(plain=True)))
    captured = capsys.readouterr()
    assert (captured.out, captured.err) == ("", "")

    play(login.BrowserScreen(Output(plain=True, verbose=True)))
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err.splitlines() == NOTICES


@pytest.mark.parametrize(
    ("seconds", "shown"), [(300, "5:00"), (90, "1:30"), (1800, "30:00"), (45, "0:45"), (30, "0:30"), (-5, "0:00")]
)
def test_the_countdown_shows_minutes_and_seconds(capsys, seconds, shown):
    login.BrowserScreen(Output(plain=True, verbose=True)).on_opened(time.monotonic() + seconds)
    assert capsys.readouterr().err == f"Waiting up to {shown} for the login. Press Ctrl+C to cancel.\n"


def test_the_progress_screen_emits_the_four_events():
    events: list = []
    progress = login.BrowserProgressJson(300.0, events.append)
    progress.on_launching("Chrome")
    progress.on_opened(time.monotonic() + 300)
    progress.on_captured()
    progress.logged_in("42")
    assert events == [
        {"event": "browser_launch", "browser": "chrome"},
        {"event": "browser_open", "timeout_seconds": 300},
        {"event": "token_captured"},
        {"event": "logged_in", "user_id": "42"},
    ]
    assert isinstance(events[1]["timeout_seconds"], int)


def test_the_progress_screen_writes_compact_json_lines_to_stderr_only(capsys):
    progress = login.BrowserProgressJson(45.5)
    progress.on_launching("Edge")
    progress.on_opened(0.0)
    captured = capsys.readouterr()
    assert captured.out == ""
    assert [json.loads(line) for line in captured.err.splitlines()] == [
        {"event": "browser_launch", "browser": "edge"},
        {"event": "browser_open", "timeout_seconds": 45.5},
    ]


# -- the whole login through the real engine, against a fake DevTools server ------------------------------------------


@pytest.mark.parametrize(
    ("fake_kwargs", "source"),
    [
        ({"storage_token": TOKEN, "storage_after": 1}, "storage"),
        ({"requests": [discord_request(TOKEN)]}, "header"),
    ],
    ids=["localStorage", "Authorization header"],
)
def test_the_whole_login_through_the_real_engine(tmp_path, caplog, fake_kwargs, source):
    caplog.set_level(logging.DEBUG)
    rig, discord, listener = EngineRig(tmp_path, **fake_kwargs), FakeDiscord(), Listener()
    with rig.serving():
        me, location, browser = login.browser_login(
            listener,
            TokenStore.default(),
            timeout=10.0,
            api_factory=discord.api_factory,
            find=lambda path: BROWSER,
            wait=rig.wait,
        )
    assert me == ME and browser == BROWSER
    assert location == TokenStore.default().keyring_name()
    assert TokenStore.default().load().token == TOKEN  # stored like after the QR login
    assert discord.requests == [("/api/v9/users/@me", TOKEN)]  # verified with the token that was found
    assert listener.kinds == ["launching", "opened", "captured"]
    assert listener.events[0] == ("launching", "Chrome")
    assert rig.fake.close_requested  # the window was closed over DevTools
    assert rig.profiles() == []  # and the temporary profile deleted
    messages = [record.getMessage() for record in caplog.records if record.name == "discoop.browser_login"]
    assert f"token found source={source}" in messages
    assert TOKEN not in caplog.text and TOKEN not in repr(listener.events)


def test_the_real_engine_reports_a_closed_window_as_exit_code_2(tmp_path):
    rig, discord = EngineRig(tmp_path, gone_after=3), FakeDiscord()
    with rig.serving(), pytest.raises(DiscoopError) as e:
        login.browser_login(
            Listener(),
            TokenStore.default(),
            timeout=10.0,
            api_factory=discord.api_factory,
            find=lambda path: BROWSER,
            wait=rig.wait,
        )
    assert e.value.code == ExitCode.AUTH_REQUIRED
    assert e.value.message == "The browser window was closed before the login finished."
    assert discord.requests == []
    assert TokenStore.default().load() is None
    assert rig.profiles() == []


def test_the_real_engine_reports_the_end_of_the_time_as_exit_code_2(tmp_path):
    rig, discord = EngineRig(tmp_path), FakeDiscord()
    with rig.serving(), pytest.raises(DiscoopError) as e:
        login.browser_login(
            Listener(),
            TokenStore.default(),
            timeout=0.3,
            api_factory=discord.api_factory,
            find=lambda path: BROWSER,
            wait=rig.wait,
        )
    assert e.value.code == ExitCode.AUTH_REQUIRED
    assert e.value.message.startswith("The login was not finished within")
    assert TokenStore.default().load() is None
    assert rig.profiles() == []


def test_a_token_the_page_holds_but_discord_rejects_stores_nothing(tmp_path):
    rig, discord = EngineRig(tmp_path, storage_token=OTHER_TOKEN), FakeDiscord(accepts=TOKEN)
    with rig.serving(), pytest.raises(DiscoopError) as e:
        login.browser_login(
            Listener(),
            TokenStore.default(),
            timeout=10.0,
            api_factory=discord.api_factory,
            find=lambda path: BROWSER,
            wait=rig.wait,
        )
    assert e.value.code == ExitCode.AUTH_REQUIRED
    assert OTHER_TOKEN not in e.value.message + e.value.hint
    assert TokenStore.default().load() is None
    assert rig.profiles() == []
