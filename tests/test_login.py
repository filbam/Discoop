import base64
import io
import json

import httpx
import pytest
from fake_gateway import TICKET, FakeGateway, gateway_in_thread
from rich.console import Console

from discoop import cli, login
from discoop.api import DiscordAPI
from discoop.errors import DiscoopError, ExitCode
from discoop.remote_auth.crypto import OAEP_SHA256
from discoop.tokenstore import TokenStore

TOKEN = "tok.en.value"
ME = {"id": "42", "username": "some_user", "global_name": "Some User"}


def discord_api(gateway: FakeGateway, *, captcha: bool = False):
    """Fake REST side: the ticket exchange and /users/@me."""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/users/@me/remote-auth/login"):
            if captcha:
                return httpx.Response(
                    400, json={"captcha_key": ["captcha-required"], "captcha_service": "hcaptcha"}
                )
            assert json.loads(request.content) == {"ticket": TICKET}
            encrypted = gateway.public_keys[-1].encrypt(TOKEN.encode(), OAEP_SHA256)
            return httpx.Response(200, json={"encrypted_token": base64.b64encode(encrypted).decode()})
        if request.url.path.endswith("/users/@me"):
            assert request.headers["Authorization"] == TOKEN
            return httpx.Response(200, json=ME)
        return httpx.Response(404)

    return lambda token: DiscordAPI(token, transport=httpx.MockTransport(handler))


def quiet_console() -> Console:
    return Console(file=io.StringIO())


def test_qr_login_stores_the_decrypted_token(tmp_path):
    gateway = FakeGateway("complete")
    store = TokenStore.default()
    trace_path = tmp_path / "trace.jsonl"
    with gateway_in_thread(gateway) as url:
        me, location = login.qr_login(
            quiet_console(), store, trace_path=trace_path, api_factory=discord_api(gateway), url=url
        )
    assert me["username"] == "some_user"
    assert location.startswith("keyring")
    assert store.load().token == TOKEN
    text = trace_path.read_text(encoding="utf-8")
    assert TOKEN not in text and TICKET not in text
    http = [r for r in map(json.loads, text.splitlines()) if r["kind"] == "http"]
    assert http == [
        {
            "t_ms": http[0]["t_ms"],
            "kind": "http",
            "method": "POST",
            "path": "/users/@me/remote-auth/login",
            "status": 200,
            "body": {"encrypted_token": {"type": "str", "len": 344}},
        }
    ]


def test_captcha_is_reported_with_the_browser_hint(tmp_path):
    gateway = FakeGateway("complete")
    trace_path = tmp_path / "trace.jsonl"
    with gateway_in_thread(gateway) as url, pytest.raises(login.CaptchaRequired) as e:
        login.qr_login(
            quiet_console(),
            TokenStore.default(),
            trace_path=trace_path,
            api_factory=discord_api(gateway, captcha=True),
            url=url,
        )
    assert isinstance(e.value, DiscoopError)  # every handler of DiscoopError still catches it
    assert e.value.code == ExitCode.ERROR
    assert e.value.message == "Discord asked for a captcha, which cannot be solved in a terminal."
    assert e.value.hint == login.BROWSER_HINT
    assert "`discoop login --browser`" in e.value.hint and "`discoop login --token`" in e.value.hint
    assert e.value.hint.index("--browser") < e.value.hint.index("--token")  # the browser first, the token last
    assert TokenStore.default().load() is None
    assert '"captcha_service": "hcaptcha"' in trace_path.read_text(encoding="utf-8")


def test_handshake_only_does_not_log_in():
    gateway = FakeGateway("qr_only")
    with gateway_in_thread(gateway) as url:
        assert login.qr_login(quiet_console(), TokenStore.default(), handshake_only=True, url=url) is None
    assert TokenStore.default().load() is None


def test_token_login_reads_stdin(monkeypatch):
    monkeypatch.setattr("sys.stdin", io.StringIO(f"  {TOKEN}\n"))
    me, _ = login.token_login(TokenStore.default(), api_factory=discord_api(FakeGateway()))
    assert me["id"] == "42"
    assert TokenStore.default().load().token == TOKEN


def test_login_is_refused_in_agent_mode(capsys):
    with pytest.raises(SystemExit) as e:
        cli.main(["--agent", "login", "--token"])
    assert e.value.code == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == (
        "ERROR AUTH_REQUIRED: Login needs the human user: QR login shows a code to scan with their phone, "
        "and a token must not pass through an AI.\n"
        "HINT: Tell the user that a browser window will open in which they log in themselves; after they agree, "
        "run `discoop login --browser`. Or ask them to run `discoop login` in their own terminal.\n"
    )


def test_login_command_reports_the_user(capsys, monkeypatch):
    monkeypatch.setattr(cli.login_flow, "token_login", lambda store: (ME, "keyring (test)"))
    with pytest.raises(SystemExit) as e:
        cli.main(["--human", "login", "--token"])
    assert e.value.code == 0
    assert "Logged in as Some User (@some_user)." in capsys.readouterr().out
