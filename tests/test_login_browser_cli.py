"""`discoop login --browser` through `cli.main`: the notices, the JSON result and the progress events, the option
checks, plain mode, the exit codes and the secrecy of the token. The browser engine is scripted (or the real one runs
against a fake DevTools server) and Discord is a fake: nothing here starts a browser or reaches the network."""

import functools
import json
import time
from pathlib import Path

import pytest
from browser_rig import BROWSER, DISPLAY_NAME, ME, NOTICES, OTHER_TOKEN, TOKEN, EngineRig, FakeDiscord
from fake_cdp import no_session_left_behind  # noqa: F401

from discoop import cli, login
from discoop.cache import cache_path
from discoop.config import Config
from discoop.errors import DiscoopError, ExitCode
from discoop.tokenstore import TokenStore

LOGGED_IN = f"Logged in as {DISPLAY_NAME}.\n"
PLAIN_REFUSAL = (
    "ERROR AUTH_REQUIRED: Login needs the human user: QR login shows a code to scan with their phone, "
    "and a token must not pass through an AI.\n"
    "HINT: Tell the user that a browser window will open in which they log in themselves; after they agree, "
    "run `discoop login --browser`. Or ask them to run `discoop login` in their own terminal.\n"
)
EVENTS = [
    {"event": "browser_launch", "browser": "chrome"},
    {"event": "browser_open", "timeout_seconds": 300},
    {"event": "token_captured"},
    {"event": "logged_in", "user_id": "42"},
]
CLOSED = DiscoopError(
    ExitCode.AUTH_REQUIRED,
    "The browser window was closed before the login finished.",
    "Run `discoop login --browser` again and finish the login in the window.",
)


def run(capsys, *args):
    with pytest.raises(SystemExit) as e:
        cli.main(list(args))
    captured = capsys.readouterr()
    return e.value.code, captured.out, captured.err


def keyring_name() -> str:
    return TokenStore.default().keyring_name()


def lines_of_json(text: str) -> list:
    return [json.loads(line) for line in text.splitlines()]


class LoginRig:
    """`login --browser` with a scripted browser engine (`script`) and a fake Discord."""

    def __init__(self) -> None:
        self.discord = FakeDiscord()
        self.asked: list = []  # the browser_path arguments of `find`
        self.waits: list = []  # (browser, timeout) of the engine
        self.script = self.captures_the_token

    def find(self, browser_path):
        self.asked.append(browser_path)
        return BROWSER

    def api_factory(self, token):
        return self.discord.api_factory(token)  # looked up on every call, so a test may swap the fake Discord

    async def wait(self, listener, *, browser, timeout):
        self.waits.append((browser, timeout))
        return await self.script(listener, browser, timeout)

    @staticmethod
    async def captures_the_token(listener, browser, timeout):
        listener.on_launching(browser.name)
        listener.on_opened(time.monotonic() + timeout)
        listener.on_captured()
        return TOKEN

    def install(self, monkeypatch, *, real_find: bool = False) -> "LoginRig":
        seams = {"api_factory": self.api_factory, "wait": self.wait}
        if not real_find:
            seams["find"] = self.find
        monkeypatch.setattr(cli.login_flow, "browser_login", functools.partial(login.browser_login, **seams))
        return self


def raising(error: BaseException, *, opened: bool = True):
    """An engine script that opens the window (or not) and then fails with `error`."""

    async def script(listener, browser, timeout):
        listener.on_launching(browser.name)
        if opened:
            listener.on_opened(time.monotonic() + timeout)
        raise error

    return script


@pytest.fixture
def rig(monkeypatch) -> LoginRig:
    return LoginRig().install(monkeypatch)


def assert_nothing_happened(rig: LoginRig) -> None:
    assert rig.asked == [] and rig.waits == []  # no browser was looked for, none was started
    assert rig.discord.requests == []
    assert TokenStore.default().load() is None


# -- the result ----------------------------------------------------------------------------------------------------


def test_human_mode_prints_the_notices_and_the_result(rig, capsys):
    code, out, err = run(capsys, "--human", "login", "--browser")
    assert code == 0
    assert out == LOGGED_IN
    text = " ".join(err.split())  # the terminal wraps long lines
    expected = [*NOTICES, f"Token stored in {keyring_name()}."]
    positions = [text.index(line) for line in expected]
    assert positions == sorted(positions)  # in this order
    assert TokenStore.default().load().token == TOKEN
    assert rig.asked == [None] and rig.waits == [(BROWSER, 300.0)]
    assert rig.discord.requests == [("/api/v9/users/@me", TOKEN)]
    assert TOKEN not in out + err


@pytest.mark.parametrize("flag", ["--agent", "--plain"])
def test_browser_login_is_allowed_in_plain_mode(rig, capsys, flag):
    code, out, err = run(capsys, flag, "login", "--browser")
    assert code == 0
    assert out == LOGGED_IN
    assert err == ""  # the notices are progress: plain mode shows them only with --verbose
    assert TokenStore.default().load().token == TOKEN


def test_plain_mode_shows_the_notices_with_verbose(rig, capsys):
    code, out, err = run(capsys, "--plain", "-v", "login", "--browser")
    assert code == 0
    assert out == LOGGED_IN
    assert err.splitlines() == [*NOTICES, f"Token stored in {keyring_name()}."]


def test_login_clears_the_cache_like_the_other_logins(rig, capsys):
    cache_path().parent.mkdir(parents=True, exist_ok=True)
    cache_path().write_text("old servers", encoding="utf-8")
    code, _, _ = run(capsys, "--plain", "login", "--browser")
    assert code == 0
    assert not cache_path().exists()


@pytest.mark.parametrize("mode", ["--agent", "--human"])
def test_format_json_prints_only_the_json_object_on_stdout(rig, capsys, mode):
    code, out, err = run(capsys, mode, "login", "--browser", "--format", "json")
    assert code == 0
    expected = {
        "logged_in": "yes",
        "user": DISPLAY_NAME,
        "user_id": "42",
        "token_storage": keyring_name(),
        "browser": "chrome",
    }
    assert out == json.dumps(expected, ensure_ascii=False, indent=2) + "\n"
    assert "Logged in as" not in out + err and "Token stored" not in err  # the object says it all
    if mode == "--agent":
        assert err == ""
    assert TOKEN not in out + err


@pytest.mark.parametrize(("name", "browser_id"), [("Edge", "edge"), ("Chromium", "chromium"), ("Brave", "brave"), ("Browser", "browser")])
def test_format_json_uses_the_lower_case_browser_id(monkeypatch, capsys, name, browser_id):
    rig = LoginRig()
    rig.find = lambda path: login.Browser(name, Path("/opt/browser"))
    rig.install(monkeypatch)
    code, out, _ = run(capsys, "--agent", "login", "--browser", "--format", "json")
    assert code == 0
    assert json.loads(out)["browser"] == browser_id


def test_format_text_is_allowed_without_browser(capsys, monkeypatch):
    monkeypatch.setattr(cli.login_flow, "token_login", lambda store: (ME, keyring_name()))
    code, out, _ = run(capsys, "--human", "login", "--token", "--format", "text")
    assert code == 0
    assert out == LOGGED_IN


@pytest.mark.parametrize("mode", ["--agent", "--human"])
def test_progress_json_events_are_exactly_the_four_and_hold_no_names(rig, capsys, mode):
    code, out, err = run(capsys, mode, "login", "--browser", "--progress-json")
    assert code == 0
    assert lines_of_json(err) == EVENTS  # nothing else on stderr: no notice, no storage note
    assert out == LOGGED_IN
    for forbidden in ("Some User", "some_user", DISPLAY_NAME, TOKEN, "Chrome", "keyring", "Opening"):
        assert forbidden not in err


def test_progress_json_with_format_json(rig, capsys):
    code, out, err = run(capsys, "--agent", "login", "--browser", "--format", "json", "--progress-json")
    assert code == 0
    assert lines_of_json(err) == EVENTS
    assert json.loads(out)["user_id"] == "42" and "Some User" not in err


def test_the_timeout_option_reaches_the_engine_and_the_events(rig, capsys):
    code, _, err = run(capsys, "--agent", "login", "--browser", "--timeout", "45", "--progress-json")
    assert code == 0
    assert rig.waits == [(BROWSER, 45.0)]
    assert lines_of_json(err)[1] == {"event": "browser_open", "timeout_seconds": 45}


@pytest.mark.parametrize("seconds", ["30", "1800", "30.5"])
def test_the_edges_of_the_timeout_range_are_allowed(rig, capsys, seconds):
    code, _, _ = run(capsys, "--agent", "login", "--browser", "--timeout", seconds)
    assert code == 0
    assert rig.waits == [(BROWSER, float(seconds))]


def test_a_timeout_in_the_text_screen(rig, capsys):
    code, _, err = run(capsys, "--plain", "-v", "login", "--browser", "--timeout", "90")
    assert code == 0
    assert "Waiting up to 1:30 for the login." in err


# -- the option checks -----------------------------------------------------------------------------------------------

BAD_OPTIONS = [
    (["--browser", "--token"], "--browser cannot be used with --token."),
    (["--browser", "--trace", "trace.jsonl"], "--browser cannot be used with --trace."),
    (["--browser", "--handshake-only"], "--browser cannot be used with --handshake-only."),
    (["--browser-path", "some-browser"], "--browser-path only works with --browser."),
    (["--browser-path", ""], "--browser-path only works with --browser."),
    (["--timeout", "60"], "--timeout only works with --browser."),
    (["--progress-json"], "--progress-json only works with --browser."),
    (["--format", "json"], "--format json only works with --browser."),
    (["--browser", "--timeout", "29"], "--timeout must be between 30 and 1800 seconds."),
    (["--browser", "--timeout", "1801"], "--timeout must be between 30 and 1800 seconds."),
    (["--browser", "--timeout", "0"], "--timeout must be between 30 and 1800 seconds."),
    (["--browser", "--timeout", "-5"], "--timeout must be between 30 and 1800 seconds."),
    (["--browser", "--timeout", "nan"], "--timeout must be between 30 and 1800 seconds."),
    (["--browser", "--timeout", "inf"], "--timeout must be between 30 and 1800 seconds."),
    (["--browser", "--timeout", "-inf"], "--timeout must be between 30 and 1800 seconds."),
    (["--browser", "--format", "xml"], 'Unknown format "xml".'),
]


@pytest.mark.parametrize("mode", ["--agent", "--human"])
@pytest.mark.parametrize(("args", "message"), BAD_OPTIONS, ids=[" ".join(args) for args, _ in BAD_OPTIONS])
def test_bad_option_combinations_are_exit_code_8(rig, capsys, mode, args, message):
    code, out, err = run(capsys, mode, "login", *args)
    assert code == 8
    assert out == ""
    assert message in err
    assert "HINT:" in err or "Hint:" in err  # says what to do
    assert_nothing_happened(rig)  # also in plain mode: a bad option is not the plain-mode refusal


def test_the_error_texts_and_hints_of_the_option_checks(rig, capsys):
    _, _, err = run(capsys, "--agent", "login", "--browser", "--token")
    assert err == (
        "ERROR BAD_ARGS: --browser cannot be used with --token.\n"
        "HINT: Choose one way to log in: the QR code (no option), --browser or --token.\n"
    )
    _, _, err = run(capsys, "--agent", "login", "--timeout", "60")
    assert err == (
        "ERROR BAD_ARGS: --timeout only works with --browser.\n"
        "HINT: Add --browser to log in through a browser window, or drop --timeout.\n"
    )
    _, _, err = run(capsys, "--agent", "login", "--browser", "--timeout", "29")
    assert err == (
        "ERROR BAD_ARGS: --timeout must be between 30 and 1800 seconds.\n"
        "HINT: Use for example --timeout 300 (5 minutes).\n"
    )


def test_a_timeout_that_is_no_number_is_a_usage_error(rig, capsys):
    code, _, err = run(capsys, "--agent", "login", "--browser", "--timeout", "soon")
    assert code == 8
    assert err.startswith("ERROR BAD_ARGS:")
    assert_nothing_happened(rig)


def test_a_folder_is_not_a_browser_path(rig, capsys, tmp_path):
    code, _, err = run(capsys, "--agent", "login", "--browser", "--browser-path", str(tmp_path))
    assert code == 8
    assert err.startswith("ERROR BAD_ARGS:")
    assert_nothing_happened(rig)


# -- plain mode keeps refusing the other ways to log in --------------------------------------------------------------


@pytest.mark.parametrize("args", [["login"], ["login", "--token"], ["login", "--trace", "trace.jsonl"]])
@pytest.mark.parametrize("flag", ["--agent", "--plain"])
def test_plain_mode_refuses_the_qr_and_the_token_login(rig, capsys, flag, args):
    code, out, err = run(capsys, flag, *args)
    assert code == 2
    assert out == ""
    assert err == PLAIN_REFUSAL
    assert_nothing_happened(rig)


def test_the_plain_mode_refusal_is_the_same_when_plain_comes_from_the_environment(rig, capsys, monkeypatch):
    monkeypatch.setenv("DISCOOP_PLAIN", "1")
    code, _, err = run(capsys, "login", "--token")
    assert (code, err) == (2, PLAIN_REFUSAL)


# -- exit codes ------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("code", "message"),
    [
        (ExitCode.AUTH_REQUIRED, "The login was not finished within 5 minutes."),
        (ExitCode.ERROR, "No supported browser was found (Chrome, Edge, Chromium or Brave)."),
        (ExitCode.ERROR, "Chrome could not be started: the file was not found."),
    ],
)
def test_the_errors_of_the_engine_keep_their_exit_codes(rig, capsys, code, message):
    rig.script = raising(DiscoopError(code, message, "Some hint."))
    exit_code, out, err = run(capsys, "--agent", "login", "--browser")
    assert exit_code == int(code)
    assert out == ""
    assert err == f"ERROR {code.name}: {message}\nHINT: Some hint.\n"
    assert TokenStore.default().load() is None


def test_errors_are_text_even_with_progress_json(rig, capsys):
    rig.script = raising(CLOSED)
    code, out, err = run(capsys, "--agent", "login", "--browser", "--progress-json")
    assert code == 2
    assert out == ""
    lines = err.splitlines()
    assert lines_of_json("\n".join(lines[:2])) == EVENTS[:2]  # what happened before the failure
    assert lines[2:] == [
        "ERROR AUTH_REQUIRED: The browser window was closed before the login finished.",
        "HINT: Run `discoop login --browser` again and finish the login in the window.",
    ]


def test_a_token_that_discord_rejects_is_exit_code_2_and_is_not_stored(rig, capsys):
    rig.discord = FakeDiscord(accepts=OTHER_TOKEN)  # the page held a token, but not one this Discord accepts
    code, out, err = run(capsys, "--agent", "login", "--browser", "--progress-json")
    assert code == 2
    assert out == ""
    assert lines_of_json("\n".join(err.splitlines()[:3])) == EVENTS[:3]  # the token was captured ...
    assert err.splitlines()[3:] == [  # ... and then refused: no logged_in event, an error in text
        "ERROR AUTH_REQUIRED: Discord did not accept the token read from the browser window.",
        "HINT: Run `discoop login --browser` again. If it keeps failing, use `discoop login --token`.",
    ]
    assert rig.discord.requests == [("/api/v9/users/@me", TOKEN)]
    assert TokenStore.default().load() is None
    assert TOKEN not in err


@pytest.mark.parametrize("mode", ["--agent", "--human"])
def test_ctrl_c_is_exit_code_130(rig, capsys, mode):
    rig.script = raising(KeyboardInterrupt(), opened=True)  # what asyncio.run raises once the cleanup has finished
    code, out, err = run(capsys, mode, "login", "--browser")
    assert code == 130  # as for the other commands
    assert out == "" and "Traceback" not in err
    assert TokenStore.default().load() is None
    assert rig.discord.requests == []  # nothing was verified or stored


# -- --browser-path and the setting reach the browser lookup --------------------------------------------------------


def test_the_option_the_setting_and_auto_detection_reach_the_locator(monkeypatch, capsys, tmp_path):
    asked: list = []
    monkeypatch.setattr(login, "find_browser", lambda configured=None: asked.append(configured) or BROWSER)
    LoginRig().install(monkeypatch, real_find=True)  # the real find_login_browser, a fake locator behind it
    configured = tmp_path / "configured-chrome.exe"
    given = tmp_path / "given-edge.exe"
    for program in (configured, given):
        program.write_text("not really a browser", encoding="utf-8")

    assert run(capsys, "--agent", "login", "--browser")[0] == 0  # nothing given, nothing configured
    assert asked == [None]

    code, out, _ = run(capsys, "--agent", "config", "set", "browser-path", str(configured))
    assert (code, out) == (0, f"browser-path = {configured}\n")
    assert run(capsys, "--agent", "login", "--browser")[0] == 0  # the setting
    assert asked[-1] == str(configured)

    assert run(capsys, "--agent", "login", "--browser", "--browser-path", str(given))[0] == 0  # the option wins
    assert Path(asked[-1]) == given
    assert Config.default().get("browser-path") == str(configured)  # and does not change the setting

    assert run(capsys, "--agent", "login", "--browser", "--browser-path", "")[0] == 0  # empty counts as not given
    assert asked[-1] == str(configured)
    assert run(capsys, "--agent", "login", "--browser", "--browser-path", "   ")[0] == 0
    assert asked[-1] == str(configured)

    run(capsys, "--agent", "config", "unset", "browser-path")
    assert run(capsys, "--agent", "login", "--browser", "--browser-path", "")[0] == 0
    assert asked[-1] is None
    assert run(capsys, "--agent", "login", "--browser")[0] == 0
    assert asked[-1] is None


def test_a_browser_path_that_is_no_file_is_exit_code_1(monkeypatch, capsys, tmp_path):
    rig = LoginRig().install(monkeypatch, real_find=True)
    monkeypatch.setenv("DISPLAY", ":0")  # on Linux the real locator wants a desktop session
    missing = tmp_path / "no-such-browser.exe"
    code, out, err = run(capsys, "--agent", "login", "--browser", "--browser-path", str(missing))
    assert code == 1
    assert err.splitlines()[0] == f"ERROR ERROR: Browser not found at {missing}."
    assert "--browser-path" in err and "browser-path" in err
    assert rig.waits == []
    assert TokenStore.default().load() is None


# -- the setting -----------------------------------------------------------------------------------------------------


def test_config_set_stores_an_absolute_path(capsys, monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "bin").mkdir()
    (tmp_path / "bin" / "chrome.exe").write_text("not really a browser", encoding="utf-8")
    code, out, _ = run(capsys, "--agent", "config", "set", "browser-path", "bin/chrome.exe")
    absolute = str((tmp_path / "bin" / "chrome.exe").resolve())
    assert (code, out) == (0, f"browser-path = {absolute}\n")
    assert Config.default().get("browser-path") == absolute
    assert run(capsys, "--agent", "config", "get", "browser-path")[1] == f"{absolute}\n"


def test_config_list_shows_the_key_in_text_and_json(capsys, tmp_path):
    code, out, _ = run(capsys, "--agent", "config", "list")
    assert code == 0
    row = next(line for line in out.splitlines() if line.startswith("browser-path\t"))
    key, value, description = row.split("\t")
    assert value == ""  # not set
    assert "login --browser" in description and "auto-detected" in description

    code, out, _ = run(capsys, "--agent", "config", "list", "--format", "json")
    assert json.loads(out)["browser-path"] is None
    program = tmp_path / "brave.exe"
    program.write_text("x", encoding="utf-8")
    run(capsys, "--agent", "config", "set", "browser-path", str(program))
    assert json.loads(run(capsys, "--agent", "config", "list", "--format", "json")[1])["browser-path"] == str(program)
    assert run(capsys, "--agent", "config", "unset", "browser-path")[1] == "browser-path reset to its default.\n"
    assert Config.default().get("browser-path") is None


@pytest.mark.parametrize("make", ["", "  ", "folder", "missing"])
def test_config_set_rejects_what_is_no_browser_program(capsys, tmp_path, make):
    (tmp_path / "folder").mkdir()
    value = {"": "", "  ": "  ", "folder": str(tmp_path / "folder"), "missing": str(tmp_path / "missing.exe")}[make]
    code, out, err = run(capsys, "--agent", "config", "set", "browser-path", value)
    assert code == 8
    assert out == "" and err.startswith("ERROR BAD_ARGS:")
    assert Config.default().get("browser-path") is None


def test_the_unknown_setting_hint_lists_the_new_key(capsys):
    code, _, err = run(capsys, "--agent", "config", "set", "colour", "red")
    assert code == 8
    assert "browser-path" in err


# -- the real engine behind the command: Ctrl+C, the token and the logs ---------------------------------------------


def use_the_real_engine(monkeypatch, engine: EngineRig, discord: FakeDiscord, wait=None) -> None:
    """`login --browser` runs the real engine against the fake DevTools server of `engine`."""
    monkeypatch.setattr(
        cli.login_flow,
        "browser_login",
        functools.partial(
            login.browser_login, api_factory=discord.api_factory, find=lambda path: BROWSER, wait=wait or engine.wait
        ),
    )


def test_the_token_never_reaches_the_log_or_any_output(monkeypatch, capsys, tmp_path):
    engine = EngineRig(tmp_path, storage_token=TOKEN, storage_after=1)
    use_the_real_engine(monkeypatch, engine, FakeDiscord())
    log_file = tmp_path / "discoop.log"
    with engine.serving():
        code, out, err = run(
            capsys, "--debug", "--log", str(log_file), "--human", "login", "--browser", "--timeout", "30"
        )
    assert code == 0
    assert out == LOGGED_IN
    assert TokenStore.default().load().token == TOKEN
    log = log_file.read_text(encoding="utf-8")
    assert "launching browser=Chrome" in log  # the engine's own events do go to the log ...
    assert "token found source=storage" in log
    assert "profile_removed=true" in log
    for text in (log, out, err):  # ... and the token is nowhere
        assert TOKEN not in text
    assert engine.fake.close_requested and engine.profiles() == []


def test_ctrl_c_with_the_real_engine_closes_the_window_and_deletes_the_profile(monkeypatch, capsys, tmp_path):
    engine = EngineRig(tmp_path)  # nobody ever logs in
    discord = FakeDiscord()

    async def wait(listener, *, browser, timeout):
        class PressesCtrlC:  # Ctrl+C right after the window opened
            on_launching = staticmethod(listener.on_launching)
            on_captured = staticmethod(listener.on_captured)

            def on_opened(self, deadline: float) -> None:
                listener.on_opened(deadline)
                raise KeyboardInterrupt

        return await engine.wait(PressesCtrlC(), browser=browser, timeout=timeout)

    use_the_real_engine(monkeypatch, engine, discord, wait)
    with engine.serving():
        code, out, _ = run(capsys, "--agent", "login", "--browser")
    assert code == 130
    assert out == ""
    assert engine.fake.close_requested  # the window was closed ...
    assert engine.profiles() == []  # ... and the temporary profile deleted, before the command ended
    assert TokenStore.default().load() is None and discord.requests == []


def test_the_whole_login_through_the_real_engine_in_plain_mode(monkeypatch, capsys, tmp_path):
    engine = EngineRig(tmp_path, storage_token=TOKEN, storage_after=1)
    use_the_real_engine(monkeypatch, engine, FakeDiscord())
    with engine.serving():
        code, out, err = run(capsys, "--agent", "login", "--browser", "--format", "json", "--progress-json")
    assert code == 0
    assert lines_of_json(err) == EVENTS
    assert json.loads(out)["logged_in"] == "yes"
    assert TokenStore.default().load().token == TOKEN
    assert engine.profiles() == []
