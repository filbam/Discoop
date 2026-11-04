from collections import namedtuple
import os
import shutil
from pathlib import Path

import httpx
import pytest

from discoop import __version__, cli
from discoop.api import DiscordAPI
from discoop.cache import Cache, cache_path
from discoop.config import Config
from discoop.models import Server
from discoop.tokenstore import TokenStore

MB = 1024 * 1024


def run_cli(capsys, *args):
    with pytest.raises(SystemExit) as exc:
        cli.main(list(args))
    captured = capsys.readouterr()
    return exc.value.code, captured.out, captured.err


def test_doctor_all_ok_plain(capsys, monkeypatch):
    TokenStore.default().save("tok")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"id": "42", "username": "alice", "global_name": "Alice"})

    transport = httpx.MockTransport(handler)
    monkeypatch.setattr(cli, "DiscordAPI", lambda token, **kw: DiscordAPI(token, transport=transport))

    code, out, err = run_cli(capsys, "--plain", "doctor")
    assert code == 0
    assert err == ""

    lines = dict(line.split("\t", 2)[:2] for line in out.strip().splitlines())
    assert lines == {
        "login": "OK",
        "network": "OK",
        "export_dir": "OK",
        "disk_space": "OK",
        "cache": "OK",
        "version": "OK",
    }
    assert "Alice (@alice) (42)" in out
    assert "Discord API reachable" in out
    assert __version__ in out


def test_doctor_all_ok_human(capsys, monkeypatch):
    TokenStore.default().save("tok")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"id": "42", "username": "alice", "global_name": "Alice"})

    transport = httpx.MockTransport(handler)
    monkeypatch.setattr(cli, "DiscordAPI", lambda token, **kw: DiscordAPI(token, transport=transport))

    code, out, err = run_cli(capsys, "--human", "doctor")
    assert code == 0
    assert "discoop doctor" in out
    assert "login" in out
    assert "network" in out
    assert "OK" in out


def test_doctor_not_logged_in(capsys):
    TokenStore.default().delete()

    code, out, _ = run_cli(capsys, "--plain", "doctor")
    assert code == 2  # ExitCode.AUTH_REQUIRED

    rows = [line.split("\t") for line in out.strip().splitlines()]
    checks = {r[0]: (r[1], r[2]) for r in rows}

    assert checks["login"][0] == "FAIL"
    assert "not logged in" in checks["login"][1]

    assert checks["network"][0] == "OK"
    assert "skipped (not logged in)" in checks["network"][1]

    # Other checks still ran
    assert checks["export_dir"][0] == "OK"
    assert checks["disk_space"][0] == "OK"
    assert checks["cache"][0] == "OK"
    assert checks["version"][0] == "OK"


def test_doctor_invalid_token_401(capsys, monkeypatch):
    TokenStore.default().save("bad-token")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"message": "401: Unauthorized", "code": 0})

    transport = httpx.MockTransport(handler)
    monkeypatch.setattr(cli, "DiscordAPI", lambda token, **kw: DiscordAPI(token, transport=transport))

    code, out, _ = run_cli(capsys, "--plain", "doctor")
    assert code == 2  # ExitCode.AUTH_REQUIRED

    rows = [line.split("\t") for line in out.strip().splitlines()]
    checks = {r[0]: (r[1], r[2]) for r in rows}

    assert checks["login"][0] == "FAIL"
    assert checks["network"][0] == "OK"
    assert checks["network"][1] == "Discord API reachable"


def test_doctor_network_error(capsys, monkeypatch):
    TokenStore.default().save("tok")

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    transport = httpx.MockTransport(handler)
    # Use max_retries=1 to avoid retry loop delay
    monkeypatch.setattr(
        cli, "DiscordAPI", lambda token, **kw: DiscordAPI(token, transport=transport, max_retries=1, sleep=lambda s: None)
    )

    code, out, _ = run_cli(capsys, "--plain", "doctor")
    assert code == 7  # ExitCode.NETWORK

    rows = [line.split("\t") for line in out.strip().splitlines()]
    checks = {r[0]: (r[1], r[2]) for r in rows}

    assert checks["login"][0] == "OK"
    assert "unverified" in checks["login"][1]

    assert checks["network"][0] == "FAIL"
    assert "Network error" in checks["network"][1]


def test_doctor_low_disk_space(capsys, monkeypatch):
    TokenStore.default().save("tok")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"id": "42", "username": "alice", "global_name": "Alice"})

    transport = httpx.MockTransport(handler)
    monkeypatch.setattr(cli, "DiscordAPI", lambda token, **kw: DiscordAPI(token, transport=transport))

    Usage = namedtuple("Usage", ["total", "used", "free"])
    monkeypatch.setattr(shutil, "disk_usage", lambda path: Usage(1000 * MB, 960 * MB, 40 * MB))

    code, out, _ = run_cli(capsys, "--plain", "doctor")
    assert code == 1  # ExitCode.ERROR
    assert "disk_space\tFAIL\t40 MB free (< 100 MB)" in out


def test_doctor_unwritable_export_dir_and_no_dir_created(capsys, monkeypatch, tmp_path):
    TokenStore.default().save("tok")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"id": "42", "username": "alice", "global_name": "Alice"})

    transport = httpx.MockTransport(handler)
    monkeypatch.setattr(cli, "DiscordAPI", lambda token, **kw: DiscordAPI(token, transport=transport))

    non_existent = tmp_path / "deep" / "nonexistent" / "exports"
    Config.default().set("export-dir", str(non_existent))

    # Make os.access return False
    monkeypatch.setattr(os, "access", lambda path, mode: False)

    code, out, _ = run_cli(capsys, "--plain", "doctor")
    assert code == 1  # ExitCode.ERROR
    assert "export_dir\tFAIL\t" in out
    assert f"{non_existent} is not writable" in out
    # Verify non_existent directory was NOT created
    assert not non_existent.exists()


def test_doctor_export_dir_is_file(capsys, monkeypatch, tmp_path):
    TokenStore.default().save("tok")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"id": "42", "username": "alice", "global_name": "Alice"})

    transport = httpx.MockTransport(handler)
    monkeypatch.setattr(cli, "DiscordAPI", lambda token, **kw: DiscordAPI(token, transport=transport))

    target_file = tmp_path / "some_file.txt"
    target_file.write_text("not a directory")
    Config.default().set("export-dir", str(target_file))

    code, out, _ = run_cli(capsys, "--plain", "doctor")
    assert code == 1  # ExitCode.ERROR
    assert "export_dir\tFAIL\t" in out
    assert "is not a directory" in out


def test_doctor_cache_status(capsys, monkeypatch):
    TokenStore.default().save("tok")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"id": "42", "username": "alice", "global_name": "Alice"})

    transport = httpx.MockTransport(handler)
    monkeypatch.setattr(cli, "DiscordAPI", lambda token, **kw: DiscordAPI(token, transport=transport))

    if cache_path().exists():
        cache_path().unlink()
    code, out, _ = run_cli(capsys, "--plain", "doctor")
    assert code == 0
    assert "cache\tOK\tno cache file" in out

    with Cache.default() as cache:
        cache.replace_servers([Server("1", "Test")])
    code, out, _ = run_cli(capsys, "--plain", "doctor")
    assert code == 0
    assert "cache\tOK\tless than a minute ago" in out


def test_doctor_cache_empty(capsys, monkeypatch):
    TokenStore.default().save("tok")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"id": "42", "username": "alice", "global_name": "Alice"})

    transport = httpx.MockTransport(handler)
    monkeypatch.setattr(cli, "DiscordAPI", lambda token, **kw: DiscordAPI(token, transport=transport))

    # Re-create empty cache database without fetched servers
    if cache_path().exists():
        cache_path().unlink()
    with Cache.default() as cache:
        pass
    code, out, _ = run_cli(capsys, "--plain", "doctor")
    assert code == 0
    assert "cache\tOK\tempty" in out
