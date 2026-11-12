"""Offline tests for the passive CLI stderr update notice."""

from __future__ import annotations

import contextlib
import json
import re
import sys
import threading
import time
from typing import Any

import httpx
import pytest
import typer

from discoop import __version__, cli, paths, update_check
from discoop.api import DiscordAPI
from discoop.config import Config
from discoop.errors import ExitCode
from discoop.render import Query
from discoop.service import MessagesOutcome
from discoop.snowflake import Window
from discoop.tokenstore import TokenStore

ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")


def _newer_version() -> str:
    parsed = update_check.parse_version(__version__, allow_v=False)
    if parsed is None:
        return "99.0.0"
    return f"{parsed[0] + 1}.0.0"


def _strip_ansi(text: str) -> str:
    return ANSI_RE.sub("", text)


def _run_cli(capsys: pytest.CaptureFixture[str], *args: str) -> tuple[int, str, str]:
    with pytest.raises(SystemExit) as exc:
        cli.main(list(args))
    captured = capsys.readouterr()
    assert isinstance(exc.value.code, int)
    return exc.value.code, captured.out, captured.err


def _read_cache() -> dict[str, Any]:
    return json.loads((paths.data_dir() / "update-check.json").read_text(encoding="utf-8"))


def _write_cache(payload: dict[str, Any]) -> None:
    path = update_check.update_cache_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


@pytest.fixture
def tty_notifier(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> list[httpx.Request]:
    """Enable the CLI update notifier with a TTY stderr and a mock GitHub transport."""
    monkeypatch.delenv("DISCOOP_NO_UPDATE_NOTIFIER", raising=False)
    monkeypatch.delenv("CI", raising=False)
    stderr_cls = type(sys.stderr)
    orig_isatty = stderr_cls.isatty
    # Pytest replaces sys.stderr between fixture setup and test call, so match the active stderr stream.
    monkeypatch.setattr(
        stderr_cls,
        "isatty",
        lambda self: True if self is sys.stderr else orig_isatty(self),
    )

    newer = _newer_version()
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(
            200,
            json={
                "tag_name": f"v{newer}",
                "html_url": f"https://github.com/filbam/Discoop/releases/tag/v{newer}",
            },
        )

    transport = httpx.MockTransport(handler)
    monkeypatch.setattr(cli, "_update_transport", lambda: transport)
    return calls


def _mock_messages_runtime(monkeypatch: pytest.MonkeyPatch) -> None:
    @contextlib.contextmanager
    def fake_directory(**_kwargs: Any):
        yield object()

    def fake_run_messages(*_args: Any, **_kwargs: Any) -> MessagesOutcome:
        return MessagesOutcome(results=[], skipped=[], exported=None, query=Query(Window(None, None)))

    monkeypatch.setattr(cli, "_directory", fake_directory)
    monkeypatch.setattr(cli, "run_messages", fake_run_messages)


def test_cli_notice_human_mode_yellow_on_tty(capsys: pytest.CaptureFixture[str], tty_notifier: list[httpx.Request]):
    newer = _newer_version()
    code, out, err = _run_cli(capsys, "--human", "logout")
    assert code == 0
    assert out == "Not logged in, nothing to remove.\n"
    assert len(tty_notifier) == 1

    # Command stderr note comes first, followed by the 3 yellow-styled notice lines.
    raw_lines = err.splitlines()
    assert len(raw_lines) >= 4
    assert "The Discord session stays active" in _strip_ansi("\n".join(raw_lines[:-3]))
    notice_raw = raw_lines[-3:]
    assert all("\x1b[33m" in line for line in notice_raw)
    assert [_strip_ansi(line) for line in notice_raw] == [
        f"A new release of discoop is available: {__version__} -> {newer}",
        "To upgrade, run: uv tool upgrade discoop",
        f"https://github.com/filbam/Discoop/releases/tag/v{newer}",
    ]
    assert _read_cache()["notified_at"] is not None


def test_cli_notice_plain_mode_unstyled_on_tty(capsys: pytest.CaptureFixture[str], tty_notifier: list[httpx.Request]):
    newer = _newer_version()
    code, out, err = _run_cli(capsys, "--plain", "logout")
    assert code == 0
    assert out == "Not logged in, nothing to remove.\n"
    assert len(tty_notifier) == 1
    assert "\x1b" not in err
    assert err.splitlines() == [
        f"A new release of discoop is available: {__version__} -> {newer}",
        "To upgrade, run: uv tool upgrade discoop",
        f"https://github.com/filbam/Discoop/releases/tag/v{newer}",
    ]
    assert _read_cache()["notified_at"] is not None


def test_cli_notice_url_never_wraps_on_narrow_console(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
):
    from rich.console import Console

    from discoop.output import Output

    monkeypatch.setattr(sys.stderr, "isatty", lambda: True)
    out = Output(plain=False)
    out.err_console = Console(stderr=True, highlight=False, width=40)
    long_url = "https://github.com/filbam/Discoop/releases/tag/v999.888.777-long-release-tag"
    info = update_check.UpdateInfo(latest_version="999.888.777", current_version="1.0.0", url=long_url)
    out.update_notice(update_check.format_cli_notice_lines(info))
    err = capsys.readouterr().err
    lines = _strip_ansi(err).splitlines()
    assert len(lines) == 3
    assert lines[2] == long_url


def test_cli_notice_skipped_when_stderr_not_tty(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.delenv("DISCOOP_NO_UPDATE_NOTIFIER", raising=False)
    monkeypatch.delenv("CI", raising=False)
    calls: list[httpx.Request] = []
    transport = httpx.MockTransport(lambda req: calls.append(req) or httpx.Response(200, json={"tag_name": "v99.0.0"}))
    monkeypatch.setattr(cli, "_update_transport", lambda: transport)
    monkeypatch.setattr(sys.stderr, "isatty", lambda: False)

    code, out, err = _run_cli(capsys, "--plain", "logout")
    assert code == 0
    assert out == "Not logged in, nothing to remove.\n"
    assert err == ""
    assert calls == []
    assert not update_check.update_cache_path().exists()


def test_stderr_is_tty_handles_missing_or_broken_isatty(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(sys, "stderr", None)
    assert cli._stderr_is_tty() is False

    class NoTtyAttr:
        pass

    monkeypatch.setattr(sys, "stderr", NoTtyAttr())
    assert cli._stderr_is_tty() is False

    class BrokenTty:
        def isatty(self) -> bool:
            raise ValueError("closed stream")

    monkeypatch.setattr(sys, "stderr", BrokenTty())
    assert cli._stderr_is_tty() is False


def test_cli_notice_disabled_by_env_ci_and_config(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    tty_notifier: list[httpx.Request],
):
    monkeypatch.setenv("DISCOOP_NO_UPDATE_NOTIFIER", "1")
    code, _, err = _run_cli(capsys, "--plain", "logout")
    assert (code, err, tty_notifier) == (0, "", [])

    monkeypatch.delenv("DISCOOP_NO_UPDATE_NOTIFIER")
    monkeypatch.setenv("CI", "true")
    code, _, err = _run_cli(capsys, "--plain", "logout")
    assert (code, err, tty_notifier) == (0, "", [])

    monkeypatch.delenv("CI")
    Config.default().set("update-check", "off")
    code, _, err = _run_cli(capsys, "--plain", "logout")
    assert (code, err, tty_notifier) == (0, "", [])

    # Turning update-check back on confirms the fixture triggers normally.
    Config.default().unset("update-check")
    code, _, err = _run_cli(capsys, "--plain", "logout")
    assert code == 0
    assert len(tty_notifier) == 1
    assert "A new release of discoop is available:" in err


@pytest.mark.parametrize("argv", [["--human", "ui"], ["--human", "--ui"], ["--ui"]])
def test_cli_notice_skipped_for_ui(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    tty_notifier: list[httpx.Request],
    argv: list[str],
):
    called = False

    def fake_run_app() -> None:
        nonlocal called
        called = True

    if "--human" not in argv:
        monkeypatch.setattr(sys.stdout, "isatty", lambda: True)
    monkeypatch.setattr("discoop.tui.app.run_app", fake_run_app)
    code, _, err = _run_cli(capsys, *argv)
    assert code == 0
    assert called
    assert err == ""
    assert tty_notifier == []


@pytest.mark.parametrize("argv", [["--plain", "ui"], ["--plain", "--ui"]])
def test_cli_notice_skipped_for_ui_plain_error(
    capsys: pytest.CaptureFixture[str],
    tty_notifier: list[httpx.Request],
    argv: list[str],
):
    code, _, err = _run_cli(capsys, *argv)
    assert code == int(ExitCode.BAD_ARGS)
    assert "ERROR BAD_ARGS: discoop ui requires an interactive terminal." in err
    assert "A new release of discoop is available" not in err
    assert tty_notifier == []


@pytest.mark.parametrize(
    "argv",
    [
        [],
        ["--plain"],
        ["--version"],
        ["--plain", "--version"],
        ["--help"],
        ["-h"],
        ["status", "--help"],
        ["status", "-h"],
        ["config", "--help"],
        ["config", "list", "--help"],
        ["profiles", "--help"],
        ["nope"],
        ["status", "--bogus-option"],
        ["config"],
    ],
)
def test_cli_notice_skipped_for_version_help_bare_and_usage_errors(
    capsys: pytest.CaptureFixture[str],
    tty_notifier: list[httpx.Request],
    argv: list[str],
):
    code, _, err = _run_cli(capsys, *argv)
    assert "A new release of discoop is available" not in err
    assert tty_notifier == []
    if argv in (["nope"], ["status", "--bogus-option"], ["config"]):
        assert code == int(ExitCode.BAD_ARGS)
    else:
        assert code == 0


def test_cli_notice_skipped_for_format_json_and_jsonl_and_progress_json(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    tty_notifier: list[httpx.Request],
):
    TokenStore.default().save("tok")
    discord_transport = httpx.MockTransport(
        lambda _req: httpx.Response(200, json={"id": "42", "username": "alice", "global_name": "Alice"})
    )
    monkeypatch.setattr(cli, "DiscordAPI", lambda token, **kw: DiscordAPI(token, transport=discord_transport))
    _mock_messages_runtime(monkeypatch)
    monkeypatch.setattr(
        cli.login_flow,
        "browser_login",
        lambda *_a, **_kw: ({"id": "42", "username": "alice"}, "keyring", type("B", (), {"name": "Chrome"})()),
    )

    cases = [
        ["--plain", "status", "--format", "json"],
        ["--plain", "status", "--format=json"],
        ["status", "--format", "json", "--plain"],
        ["--plain", "config", "list", "--format", "json"],
        ["--plain", "config", "list", "--format=JSON"],
        ["--plain", "profiles", "--format", "json"],
        ["--plain", "profiles", "list", "--format", "json"],
        ["--plain", "profiles", "--format=json", "list"],
        ["--plain", "messages", "-c", "general", "--format", "jsonl"],
        ["--plain", "messages", "-c", "general", "--format=jsonl"],
        ["--plain", "messages", "-c", "general", "--progress-json"],
        ["messages", "-c", "general", "--progress-json", "--plain"],
        ["--plain", "login", "--browser", "--progress-json"],
        ["--plain", "login", "--browser", "--format", "json"],
    ]
    for argv in cases:
        code, _, err = _run_cli(capsys, *argv)
        assert code == 0, argv
        assert "A new release of discoop is available" not in err, argv
        assert tty_notifier == [], argv
    assert not update_check.update_cache_path().exists()


def test_cli_notice_shown_when_channel_is_named_json(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    tty_notifier: list[httpx.Request],
):
    _mock_messages_runtime(monkeypatch)
    newer = _newer_version()
    code, _, err = _run_cli(capsys, "--plain", "messages", "-c", "json")
    assert code == 0
    assert len(tty_notifier) == 1
    assert f"A new release of discoop is available: {__version__} -> {newer}" in err


@pytest.mark.parametrize("exc", [KeyboardInterrupt(), typer.Abort()])
def test_cli_notice_suppressed_on_ctrl_c_exit_130(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    tty_notifier: list[httpx.Request],
    exc: BaseException,
):
    newer = _newer_version()
    _write_cache({
        "checked_at": time.time(),
        "latest_version": newer,
        "latest_url": f"https://github.com/filbam/Discoop/releases/tag/v{newer}",
        "failed_at": None,
        "notified_at": None,
    })
    TokenStore.default().save("tok")

    def boom(_self: Any) -> dict[str, Any]:
        raise exc

    monkeypatch.setattr("discoop.api.DiscordAPI.get_me", boom)
    code, _, err = _run_cli(capsys, "--plain", "status")
    assert code == 130
    if isinstance(exc, typer.Abort):
        assert "ERROR ERROR: Interrupted." in err
    assert "A new release of discoop is available" not in err
    assert _read_cache()["notified_at"] is None
    assert tty_notifier == []


def test_cli_notice_printed_after_error_message_and_preserves_exit_code(
    capsys: pytest.CaptureFixture[str],
    tty_notifier: list[httpx.Request],
):
    TokenStore.default().delete()
    newer = _newer_version()

    code, out, err = _run_cli(capsys, "--plain", "status")
    assert code == int(ExitCode.AUTH_REQUIRED)
    assert out == ""
    assert len(tty_notifier) == 1

    lines = err.splitlines()
    assert lines[0].startswith("ERROR AUTH_REQUIRED: Not logged in.")
    assert lines[1].startswith("HINT: ")
    assert lines[2:] == [
        f"A new release of discoop is available: {__version__} -> {newer}",
        "To upgrade, run: uv tool upgrade discoop",
        f"https://github.com/filbam/Discoop/releases/tag/v{newer}",
    ]


def test_cli_notice_printed_after_bad_args_discoop_error(
    capsys: pytest.CaptureFixture[str],
    tty_notifier: list[httpx.Request],
):
    newer = _newer_version()
    code, out, err = _run_cli(capsys, "--plain", "messages")
    assert code == int(ExitCode.BAD_ARGS)
    assert out == ""
    assert len(tty_notifier) == 1
    lines = err.splitlines()
    assert lines[0].startswith("ERROR BAD_ARGS:")
    assert lines[1].startswith("HINT: ")
    assert lines[2:] == [
        f"A new release of discoop is available: {__version__} -> {newer}",
        "To upgrade, run: uv tool upgrade discoop",
        f"https://github.com/filbam/Discoop/releases/tag/v{newer}",
    ]


def test_cli_notice_24h_notified_at_throttling_and_fresh_cache_no_http(
    capsys: pytest.CaptureFixture[str],
    tty_notifier: list[httpx.Request],
):
    newer = _newer_version()
    url = f"https://github.com/filbam/Discoop/releases/tag/v{newer}"
    now = time.time()
    _write_cache({
        "checked_at": now,
        "latest_version": newer,
        "latest_url": url,
        "failed_at": None,
        "notified_at": None,
    })

    # 1. Fresh cache without notified_at prints immediately with zero HTTP requests.
    code1, _, err1 = _run_cli(capsys, "--plain", "logout")
    assert code1 == 0
    assert tty_notifier == []
    assert f"A new release of discoop is available: {__version__} -> {newer}" in err1
    assert _read_cache()["notified_at"] is not None

    # 2. Within 24h, does not notify again and makes zero HTTP requests.
    code2, _, err2 = _run_cli(capsys, "--plain", "logout")
    assert code2 == 0
    assert tty_notifier == []
    assert err2 == ""

    # 3. After 24h since notified_at (with fresh checked_at), notifies again without HTTP.
    _write_cache({
        "checked_at": now,
        "latest_version": newer,
        "latest_url": url,
        "failed_at": None,
        "notified_at": now - update_check.NOTIFY_INTERVAL - 10.0,
    })
    code3, _, err3 = _run_cli(capsys, "--plain", "logout")
    assert code3 == 0
    assert tty_notifier == []
    assert f"A new release of discoop is available: {__version__} -> {newer}" in err3


def test_cli_notice_slow_check_hits_wait_cap_without_blocking_or_failing(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.delenv("DISCOOP_NO_UPDATE_NOTIFIER", raising=False)
    monkeypatch.delenv("CI", raising=False)
    monkeypatch.setattr(sys.stderr, "isatty", lambda: True)

    release = threading.Event()

    def slow_handler(_request: httpx.Request) -> httpx.Response:
        release.wait(timeout=5.0)
        return httpx.Response(200, json={"tag_name": f"v{_newer_version()}"})

    transport = httpx.MockTransport(slow_handler)
    monkeypatch.setattr(cli, "_update_transport", lambda: transport)
    assert cli.CLI_NOTICE_WAIT_TIMEOUT == 1.0

    try:
        started = time.monotonic()
        code, out, err = _run_cli(capsys, "--plain", "logout")
        elapsed = time.monotonic() - started
    finally:
        release.set()

    assert code == 0
    assert out == "Not logged in, nothing to remove.\n"
    assert err == ""
    assert 0.8 <= elapsed < 2.5


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(200, json={"tag_name": f"v{__version__}"}),
        httpx.Response(404),
        httpx.Response(503),
        httpx.ConnectError("offline"),
    ],
)
def test_cli_notice_silent_on_up_to_date_404_and_errors(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    response: httpx.Response | Exception,
):
    monkeypatch.delenv("DISCOOP_NO_UPDATE_NOTIFIER", raising=False)
    monkeypatch.delenv("CI", raising=False)
    monkeypatch.setattr(sys.stderr, "isatty", lambda: True)

    def handler(_request: httpx.Request) -> httpx.Response:
        if isinstance(response, Exception):
            raise response
        return response

    transport = httpx.MockTransport(handler)
    monkeypatch.setattr(cli, "_update_transport", lambda: transport)

    code, _, err = _run_cli(capsys, "--plain", "logout")
    assert code == 0
    assert err == ""


def test_cli_notice_swallows_unexpected_notifier_exceptions(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    tty_notifier: list[httpx.Request],
):
    # 1. Start failure
    monkeypatch.setattr(cli, "_start_cli_update_check", lambda: (_ for _ in ()).throw(RuntimeError("boom")))
    code, _, err = _run_cli(capsys, "--plain", "logout")
    assert (code, err) == (0, "")

    # 2. Wait failure
    class BrokenHandle:
        def wait(self, timeout: float = 1.0) -> None:
            raise RuntimeError("wait boom")

        def mark_notified(self) -> None:
            pass

    monkeypatch.setattr(cli, "_start_cli_update_check", lambda: BrokenHandle())
    code, _, err = _run_cli(capsys, "--plain", "logout")
    assert (code, err) == (0, "")

    # 3. mark_notified failure still leaves exit code 0
    class BrokenMarkHandle:
        def wait(self, timeout: float = 1.0) -> update_check.UpdateInfo:
            return update_check.UpdateInfo(
                latest_version=_newer_version(),
                current_version=__version__,
                url=f"https://github.com/filbam/Discoop/releases/tag/v{_newer_version()}",
            )

        def mark_notified(self) -> None:
            raise RuntimeError("mark boom")

    monkeypatch.setattr(cli, "_start_cli_update_check", lambda: BrokenMarkHandle())
    code, _, err = _run_cli(capsys, "--plain", "logout")
    assert code == 0
    assert "A new release of discoop is available" in err


def test_cli_notice_works_for_profiles_root_and_config_list(
    capsys: pytest.CaptureFixture[str],
    tty_notifier: list[httpx.Request],
):
    newer = _newer_version()

    code1, _, err1 = _run_cli(capsys, "--plain", "profiles")
    assert code1 == 0
    assert len(tty_notifier) == 1
    assert f"A new release of discoop is available: {__version__} -> {newer}" in err1

    # Reset notified_at to verify config list is also eligible (uses fresh cache).
    _write_cache({
        "checked_at": time.time(),
        "latest_version": newer,
        "latest_url": f"https://github.com/filbam/Discoop/releases/tag/v{newer}",
        "failed_at": None,
        "notified_at": None,
    })
    code2, _, err2 = _run_cli(capsys, "--plain", "config", "list")
    assert code2 == 0
    assert len(tty_notifier) == 1
    assert f"A new release of discoop is available: {__version__} -> {newer}" in err2


def test_cli_notice_works_for_agent_guide_on_tty(
    capsys: pytest.CaptureFixture[str],
    tty_notifier: list[httpx.Request],
):
    newer = _newer_version()
    code, out, err = _run_cli(capsys, "--plain", "agent-guide")
    assert code == 0
    assert "DISCOOP AI AGENT GUIDE" in out
    assert "\x1b" not in out
    assert len(tty_notifier) == 1
    assert err.splitlines() == [
        f"A new release of discoop is available: {__version__} -> {newer}",
        "To upgrade, run: uv tool upgrade discoop",
        f"https://github.com/filbam/Discoop/releases/tag/v{newer}",
    ]
