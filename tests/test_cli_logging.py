"""Tests for CLI diagnostic logging flags (--debug, --log), environment variables, and cleanup."""

import io
import logging
from pathlib import Path
from unittest.mock import MagicMock

import httpx
import pytest

from discoop import cli
from discoop.api import DiscordAPI
from discoop.cli import _CliEvents
from discoop.errors import ExitCode
from discoop.models import Channel, Server
from discoop.output import Output
from discoop.tokenstore import TokenStore


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    """Ensure logging environment variables are cleared before each test."""
    monkeypatch.delenv("DISCOOP_DEBUG", raising=False)
    monkeypatch.delenv("DISCOOP_LOG", raising=False)


@pytest.fixture
def fake_discord(monkeypatch):
    """Fake Discord API answering /users/@me for status command."""
    TokenStore.default().save("test-token-value")

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v9/users/@me":
            return httpx.Response(200, json={"id": "111222333", "username": "testuser", "global_name": "Test User"})
        return httpx.Response(404, json={"message": "Not Found"})

    transport = httpx.MockTransport(handler)
    monkeypatch.setattr(cli, "DiscordAPI", lambda token, **kw: DiscordAPI(token, transport=transport, **kw))


def test_debug_and_log_flags_before_subcommand(capsys, fake_discord, tmp_path: Path):
    log_file = tmp_path / "diag.log"
    with pytest.raises(SystemExit) as exc_info:
        cli.main(["--plain", "--debug", "--log", str(log_file), "status"])
    assert exc_info.value.code == 0

    assert log_file.exists()
    content = log_file.read_text(encoding="utf-8")
    assert "discoop" in content
    assert "IDs in this log identify private servers and channels" in content
    assert "path=/users/@me" in content

    captured = capsys.readouterr()
    assert "logged_in: yes" in captured.out
    assert "discoop" in captured.err
    assert "path=/users/@me" in captured.err


def test_debug_and_log_flags_after_subcommand(capsys, fake_discord, tmp_path: Path):
    log_file = tmp_path / "diag_after.log"
    with pytest.raises(SystemExit) as exc_info:
        cli.main(["status", "--plain", "--debug", "--log", str(log_file)])
    assert exc_info.value.code == 0

    assert log_file.exists()
    content = log_file.read_text(encoding="utf-8")
    assert "path=/users/@me" in content

    captured = capsys.readouterr()
    assert "logged_in: yes" in captured.out
    assert "path=/users/@me" in captured.err


def test_log_equals_syntax_after_subcommand(capsys, fake_discord, tmp_path: Path):
    log_file = tmp_path / "diag_equals.log"
    with pytest.raises(SystemExit) as exc_info:
        cli.main(["status", "--plain", f"--log={log_file}"])
    assert exc_info.value.code == 0

    assert log_file.exists()
    content = log_file.read_text(encoding="utf-8")
    assert "path=/users/@me" in content

    # Since --debug was not passed, diagnostic logs do NOT go to stderr
    captured = capsys.readouterr()
    assert "path=/users/@me" not in captured.err


def test_log_space_syntax_after_subcommand(capsys, fake_discord, tmp_path: Path):
    log_file = tmp_path / "diag_space.log"
    with pytest.raises(SystemExit) as exc_info:
        cli.main(["status", "--plain", "--log", str(log_file)])
    assert exc_info.value.code == 0

    assert log_file.exists()
    content = log_file.read_text(encoding="utf-8")
    assert "path=/users/@me" in content

    captured = capsys.readouterr()
    assert "path=/users/@me" not in captured.err


def test_env_vars_debug_and_log(capsys, fake_discord, monkeypatch, tmp_path: Path):
    env_log = tmp_path / "env_log.log"
    monkeypatch.setenv("DISCOOP_DEBUG", "1")
    monkeypatch.setenv("DISCOOP_LOG", str(env_log))

    with pytest.raises(SystemExit) as exc_info:
        cli.main(["--plain", "status"])
    assert exc_info.value.code == 0

    assert env_log.exists()
    content = env_log.read_text(encoding="utf-8")
    assert "path=/users/@me" in content

    captured = capsys.readouterr()
    assert "path=/users/@me" in captured.err


def test_cli_flag_precedence_over_env_log(fake_discord, monkeypatch, tmp_path: Path):
    env_log = tmp_path / "env_log.log"
    cli_log = tmp_path / "cli_log.log"
    monkeypatch.setenv("DISCOOP_LOG", str(env_log))

    with pytest.raises(SystemExit) as exc_info:
        cli.main(["--plain", "--log", str(cli_log), "status"])
    assert exc_info.value.code == 0

    assert cli_log.exists()
    assert not env_log.exists()


@pytest.mark.parametrize("val", ["true", "True", "yes", "YES", "on", "1"])
def test_truthy_env_debug_values(val, capsys, fake_discord, monkeypatch):
    monkeypatch.setenv("DISCOOP_DEBUG", val)
    with pytest.raises(SystemExit) as exc_info:
        cli.main(["--plain", "status"])
    assert exc_info.value.code == 0

    captured = capsys.readouterr()
    assert "path=/users/@me" in captured.err


@pytest.mark.parametrize("val", ["false", "no", "off", "0", "random"])
def test_falsy_env_debug_values(val, capsys, fake_discord, monkeypatch):
    monkeypatch.setenv("DISCOOP_DEBUG", val)
    with pytest.raises(SystemExit) as exc_info:
        cli.main(["--plain", "status"])
    assert exc_info.value.code == 0

    captured = capsys.readouterr()
    assert "path=/users/@me" not in captured.err


def test_ui_subcommand_with_debug_flag_rejected(capsys):
    with pytest.raises(SystemExit) as exc_info:
        cli.main(["--human", "ui", "--debug"])
    assert exc_info.value.code == int(ExitCode.BAD_ARGS)

    captured = capsys.readouterr()
    assert "discoop ui cannot be used with --debug." in captured.err
    assert "Use --log FILE: the terminal UI owns the screen." in captured.err


def test_ui_flag_with_debug_flag_rejected(capsys):
    with pytest.raises(SystemExit) as exc_info:
        cli.main(["--ui", "--debug"])
    assert exc_info.value.code == int(ExitCode.BAD_ARGS)

    captured = capsys.readouterr()
    assert "discoop ui cannot be used with --debug." in captured.err
    assert "Use --log FILE: the terminal UI owns the screen." in captured.err


def test_ui_with_env_debug_rejected(capsys, monkeypatch):
    monkeypatch.setenv("DISCOOP_DEBUG", "1")
    with pytest.raises(SystemExit) as exc_info:
        cli.main(["--human", "ui"])
    assert exc_info.value.code == int(ExitCode.BAD_ARGS)

    captured = capsys.readouterr()
    assert "discoop ui cannot be used with --debug." in captured.err
    assert "Use --log FILE: the terminal UI owns the screen." in captured.err


def test_ui_with_log_file_allowed(monkeypatch, tmp_path: Path):
    log_file = tmp_path / "ui.log"
    run_app_called = False

    def fake_run_app():
        nonlocal run_app_called
        run_app_called = True
        logger = logging.getLogger("discoop")
        logger.info("UI started successfully")

    monkeypatch.setattr("discoop.tui.app.run_app", fake_run_app)

    with pytest.raises(SystemExit) as exc_info:
        cli.main(["--human", "--log", str(log_file), "ui"])
    assert exc_info.value.code == 0
    assert run_app_called
    assert log_file.exists()
    assert "UI started successfully" in log_file.read_text(encoding="utf-8")


def test_handlers_cleaned_up_after_successful_run(fake_discord, tmp_path: Path):
    log_file = tmp_path / "cleanup.log"
    with pytest.raises(SystemExit) as exc_info:
        cli.main(["--plain", "--debug", "--log", str(log_file), "status"])
    assert exc_info.value.code == 0

    discoop_logger = logging.getLogger("discoop")
    assert len(discoop_logger.handlers) == 0


def test_handlers_cleaned_up_after_cli_error():
    # Calling messages without required --channel option causes a bad arguments error
    with pytest.raises(SystemExit) as exc_info:
        cli.main(["--plain", "--debug", "messages"])
    assert exc_info.value.code != 0

    discoop_logger = logging.getLogger("discoop")
    assert len(discoop_logger.handlers) == 0


def test_no_logs_when_disabled(capsys, fake_discord, tmp_path: Path):
    with pytest.raises(SystemExit) as exc_info:
        cli.main(["--plain", "status"])
    assert exc_info.value.code == 0

    captured = capsys.readouterr()
    assert captured.err == ""
    assert len(logging.getLogger("discoop").handlers) == 0


def test_log_is_directory_rejected_from_cli(tmp_path: Path):
    with pytest.raises(SystemExit) as exc_info:
        cli.main(["--plain", "--log", str(tmp_path), "status"])
    assert exc_info.value.code == int(ExitCode.BAD_ARGS)


def test_log_is_directory_rejected_from_env(capsys, monkeypatch, tmp_path: Path):
    monkeypatch.setenv("DISCOOP_LOG", str(tmp_path))
    with pytest.raises(SystemExit) as exc_info:
        cli.main(["--plain", "status"])
    assert exc_info.value.code == int(ExitCode.BAD_ARGS)

    captured = capsys.readouterr()
    assert f'Log path "{tmp_path}" is a directory, not a file.' in captured.err


def test_no_spinner_in_human_mode_when_debug_enabled():
    out = Output(plain=False)
    out.debug = True

    events = _CliEvents(out)
    from discoop.cli import _AgentDownloads
    assert isinstance(events.downloads, _AgentDownloads)

    server = Server(id="1", name="Guild")
    channel = Channel(id="2", server_id="1", name="general", type=0)
    events.channel_start(1, 1, server, channel)
    assert events._status is None
    events.page(10, 100000000)
    assert events._status is None
    events.pause(1.5, "reading pause")
    assert events._status is None
    events.close()


def test_hoist_mode_flags_preserves_post_separator_args():
    from discoop.cli import _hoist_mode_flags

    # Arguments after '--' should not be hoisted
    args = ["messages", "-c", "general", "--debug", "--log", "out.log", "--", "--debug", "--log", "ignored.log"]
    hoisted = _hoist_mode_flags(args)
    assert hoisted == [
        "--debug",
        "--log",
        "out.log",
        "messages",
        "-c",
        "general",
        "--",
        "--debug",
        "--log",
        "ignored.log",
    ]


def test_handlers_cleaned_up_after_interrupt(fake_discord, monkeypatch):
    monkeypatch.setattr("discoop.api.DiscordAPI.get_me", MagicMock(side_effect=KeyboardInterrupt))
    with pytest.raises(SystemExit) as exc_info:
        cli.main(["--plain", "--debug", "status"])
    assert exc_info.value.code == 130
    assert len(logging.getLogger("discoop").handlers) == 0

