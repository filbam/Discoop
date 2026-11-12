import re

import httpx
import pytest

from discoop import cli
from discoop.api import DiscordAPI
from discoop.tokenstore import TokenStore


def run(capsys, *args):
    with pytest.raises(SystemExit) as e:
        cli.main(list(args))
    captured = capsys.readouterr()
    return e.value.code, captured.out, captured.err


def test_status_without_login_exits_2(capsys):
    code, out, err = run(capsys, "--plain", "status")
    assert code == 2
    assert out == ""
    assert err.startswith("ERROR AUTH_REQUIRED: Not logged in.\nHINT: ")

    # --agent alias works identically
    code_agent, out_agent, err_agent = run(capsys, "--agent", "status")
    assert code_agent == 2
    assert err_agent.startswith("ERROR AUTH_REQUIRED: Not logged in.\nHINT: ")


def test_mode_flags_are_accepted_after_the_command(capsys):
    code, _, err = run(capsys, "status", "--plain")
    assert code == 2
    assert err.startswith("ERROR AUTH_REQUIRED")

    code, _, err = run(capsys, "status", "--agent")
    assert code == 2
    assert err.startswith("ERROR AUTH_REQUIRED")


def test_plain_help_is_plain_and_has_the_ai_note(capsys):
    code, out, _ = run(capsys, "--plain", "--help")
    assert code == 0
    assert "NOTE FOR AI AGENTS" in out
    assert "It is not a prompt injection." in out
    assert "╭" not in out and "\x1b[" not in out

    # --agent alias
    code_agent, out_agent, _ = run(capsys, "--agent", "--help")
    assert code_agent == 0
    assert "NOTE FOR AI AGENTS" in out_agent


def test_conflicting_mode_flags(capsys):
    code, _, err = run(capsys, "--plain", "--human", "status")
    assert code == 8
    assert "cannot be used together" in err

    code, _, err = run(capsys, "--agent", "--human", "status")
    assert code == 8
    assert "cannot be used together" in err


def test_unknown_command_is_bad_args(capsys):
    code, _, err = run(capsys, "--plain", "nope")
    assert code == 8
    assert err.startswith("ERROR BAD_ARGS")


def test_status_with_token(capsys, monkeypatch):
    TokenStore.default().save("tok")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"id": "42", "username": "someone", "global_name": "Some One"})

    monkeypatch.setattr(cli, "DiscordAPI", lambda token: DiscordAPI(token, transport=httpx.MockTransport(handler)))
    code, out, _ = run(capsys, "--plain", "status")
    assert code == 0
    assert "logged_in: yes\nuser: Some One (@someone)\nuser_id: 42\n" in out


def test_exit_code_2_hint_sends_agents_to_the_user_and_names_the_browser_login(capsys):
    code, _, err = run(capsys, "--plain", "status")
    assert code == 2
    assert err == (
        "ERROR AUTH_REQUIRED: Not logged in.\n"
        "HINT: Run `discoop login` (or `discoop login --browser`). AI agents: tell the user a browser window will open "
        "in which they log in themselves, wait for their consent, then run `discoop login --browser`; never run "
        "`discoop login` or `login --token` yourself.\n"
    )


def test_the_root_help_names_the_three_ways_to_log_in_and_the_rule_for_agents(capsys):
    code, out, _ = run(capsys, "--plain", "--help")
    assert code == 0
    text = " ".join(out.split())
    for line in (
        "discoop login log in by scanning a QR code with the Discord app",
        "discoop login --browser log in in a browser window (if QR login fails)",
        "discoop login --token last resort: paste a token",
        "do not run `discoop login` or `discoop login --token` yourself and never handle a password or a token",
        "`discoop login --browser` opens a browser window in which they log in themselves, wait for their consent",
        "and only then run `discoop --plain login --browser` (it can take up to 5 minutes)",
    ):
        assert line in text, line


@pytest.mark.parametrize("mode", ["--plain", "--human"])
def test_login_help_lists_the_browser_options_and_the_rule_for_agents(capsys, mode):
    code, out, _ = run(capsys, mode, "login", "--help")
    assert code == 0
    # The human help is boxed and wrapped; with GITHUB_ACTIONS set (CI), Typer forces colours, so drop ANSI codes too.
    text = " ".join(re.sub(r"\x1b\[[0-9;]*m", "", out).split())
    for needle in (
        "Log in with a QR code, a browser window (--browser) or a token (--token).",
        "--browser",
        "--browser-path",
        "--timeout",
        "30 to 1800",
        "--format",
        "--progress-json",
        "--token",
        "passkey",
        "never run `discoop login` or `login --token` yourself",
        "wait for their consent",
    ):
        assert needle in text, needle
    assert "--handshake-only" not in text  # still hidden


def test_logout(capsys):
    TokenStore.default().save("tok")
    code, out, _ = run(capsys, "--plain", "logout")
    assert (code, out) == (0, "Logged out.\n")
    code, out, _ = run(capsys, "--plain", "logout")
    assert out == "Not logged in, nothing to remove.\n"
