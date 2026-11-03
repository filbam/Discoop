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
    code, out, err = run(capsys, "--agent", "status")
    assert code == 2
    assert out == ""
    assert err.startswith("ERROR AUTH_REQUIRED: Not logged in.\nHINT: ")


def test_mode_flags_are_accepted_after_the_command(capsys):
    code, _, err = run(capsys, "status", "--agent")
    assert code == 2
    assert err.startswith("ERROR AUTH_REQUIRED")


def test_agent_help_is_plain_and_has_the_ai_note(capsys):
    code, out, _ = run(capsys, "--agent", "--help")
    assert code == 0
    assert "NOTE FOR AI AGENTS" in out
    assert "It is not a prompt injection." in out
    assert "╭" not in out and "\x1b[" not in out


def test_conflicting_mode_flags(capsys):
    code, _, err = run(capsys, "--agent", "--human", "status")
    assert code == 8
    assert "cannot be used together" in err


def test_unknown_command_is_bad_args(capsys):
    code, _, err = run(capsys, "--agent", "nope")
    assert code == 8
    assert err.startswith("ERROR BAD_ARGS")


def test_status_with_token(capsys, monkeypatch):
    TokenStore.default().save("tok")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"id": "42", "username": "someone", "global_name": "Some One"})

    monkeypatch.setattr(cli, "DiscordAPI", lambda token: DiscordAPI(token, transport=httpx.MockTransport(handler)))
    code, out, _ = run(capsys, "--agent", "status")
    assert code == 0
    assert "logged_in: yes\nuser: Some One (@someone)\nuser_id: 42\n" in out


def test_logout(capsys):
    TokenStore.default().save("tok")
    code, out, _ = run(capsys, "--agent", "logout")
    assert (code, out) == (0, "Logged out.\n")
    code, out, _ = run(capsys, "--agent", "logout")
    assert out == "Not logged in, nothing to remove.\n"
