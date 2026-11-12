from collections import namedtuple
import json
import os
import shutil
import sys
import time
from pathlib import Path

import httpx
import pytest

from discoop import __version__, cli, paths, update_check
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


@pytest.fixture
def update_env(monkeypatch):
    monkeypatch.delenv("DISCOOP_NO_UPDATE_NOTIFIER", raising=False)
    monkeypatch.delenv("CI", raising=False)


def _mock_discord_ok(monkeypatch):
    TokenStore.default().save("tok")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"id": "42", "username": "alice", "global_name": "Alice"})

    transport = httpx.MockTransport(handler)
    monkeypatch.setattr(cli, "DiscordAPI", lambda token, **kw: DiscordAPI(token, transport=transport))


def _mock_github(monkeypatch, status_code: int | Exception, payload: dict | None = None):
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if isinstance(status_code, Exception):
            raise status_code
        if payload is None:
            return httpx.Response(status_code)
        return httpx.Response(status_code, json=payload)

    transport = httpx.MockTransport(handler)
    monkeypatch.setattr(cli, "_update_transport", lambda: transport)
    return calls


def _newer_version() -> str:
    parsed = update_check.parse_version(__version__, allow_v=False)
    if parsed is None:
        return "99.0.0"
    return f"{parsed[0] + 1}.0.0"


def test_doctor_all_ok_plain(capsys, monkeypatch):
    TokenStore.default().save("tok")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"id": "42", "username": "alice", "global_name": "Alice"})

    transport = httpx.MockTransport(handler)
    monkeypatch.setattr(cli, "DiscordAPI", lambda token, **kw: DiscordAPI(token, transport=transport))

    code, out, err = run_cli(capsys, "--plain", "doctor")
    assert code == 0
    assert err == ""

    rows = [line.split("\t", 2) for line in out.strip().splitlines()]
    assert [row[0] for row in rows] == [
        "login",
        "network",
        "export_dir",
        "disk_space",
        "cache",
        "version",
        "update",
    ]
    lines = {row[0]: row[1] for row in rows}
    assert lines == {
        "login": "OK",
        "network": "OK",
        "export_dir": "OK",
        "disk_space": "OK",
        "cache": "OK",
        "version": "OK",
        "update": "OK",
    }
    assert "Alice (@alice) (42)" in out
    assert "Discord API reachable" in out
    assert __version__ in out
    assert "skipped (update-check is off)" in out


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
    assert "update" in out
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
    assert checks["update"][0] == "OK"


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


def test_doctor_update_up_to_date(capsys, monkeypatch, update_env):
    _mock_discord_ok(monkeypatch)
    calls = _mock_github(monkeypatch, 200, {"tag_name": f"v{__version__}"})

    code, out, err = run_cli(capsys, "--plain", "doctor")
    assert code == 0
    assert err == ""
    assert len(calls) == 1

    rows = {r[0]: (r[1], r[2]) for r in (line.split("\t") for line in out.strip().splitlines())}
    assert rows["update"] == ("OK", f"up to date (latest {__version__})")
    cache = json.loads((paths.data_dir() / "update-check.json").read_text(encoding="utf-8"))
    assert cache["latest_version"] == __version__


def test_doctor_update_available_keeps_exit_0(capsys, monkeypatch, update_env):
    _mock_discord_ok(monkeypatch)
    newer = _newer_version()
    calls = _mock_github(
        monkeypatch,
        200,
        {"tag_name": f"v{newer}", "html_url": f"https://github.com/filbam/Discoop/releases/tag/v{newer}"},
    )

    code, out, err = run_cli(capsys, "--plain", "doctor")
    assert code == 0
    assert err == ""
    assert len(calls) == 1

    rows = {r[0]: (r[1], r[2]) for r in (line.split("\t") for line in out.strip().splitlines())}
    assert rows["update"] == ("OK", f"{newer} available: uv tool upgrade discoop")


def test_doctor_update_no_release_404(capsys, monkeypatch, update_env):
    _mock_discord_ok(monkeypatch)
    calls = _mock_github(monkeypatch, 404)

    code, out, _ = run_cli(capsys, "--plain", "doctor")
    assert code == 0
    assert len(calls) == 1

    rows = {r[0]: (r[1], r[2]) for r in (line.split("\t") for line in out.strip().splitlines())}
    assert rows["update"] == ("OK", "no release published yet")


def test_doctor_update_disabled_by_config(capsys, monkeypatch, update_env):
    _mock_discord_ok(monkeypatch)
    calls = _mock_github(monkeypatch, 200, {"tag_name": f"v{_newer_version()}"})
    Config.default().set("update-check", "off")

    code, out, _ = run_cli(capsys, "--plain", "doctor")
    assert code == 0
    assert calls == []

    rows = {r[0]: (r[1], r[2]) for r in (line.split("\t") for line in out.strip().splitlines())}
    assert rows["update"] == ("OK", "skipped (update-check is off)")


def test_doctor_update_runs_even_in_ci(capsys, monkeypatch, update_env):
    _mock_discord_ok(monkeypatch)
    newer = _newer_version()
    calls = _mock_github(monkeypatch, 200, {"tag_name": f"v{newer}"})
    monkeypatch.setenv("CI", "1")
    monkeypatch.setattr(sys.stderr, "isatty", lambda: True)

    code, out, err = run_cli(capsys, "--plain", "doctor")
    assert code == 0
    assert len(calls) == 1
    assert err == ""  # CI still suppresses CLI stderr notice

    rows = {r[0]: (r[1], r[2]) for r in (line.split("\t") for line in out.strip().splitlines())}
    assert rows["update"] == ("OK", f"{newer} available: uv tool upgrade discoop")


@pytest.mark.parametrize(
    ("outcome", "expected_prefix"),
    [
        (502, "could not check: HTTP 502"),
        (httpx.ConnectError("boom"), "could not check: network error"),
    ],
)
def test_doctor_update_error_keeps_ok_and_exit_0(capsys, monkeypatch, update_env, outcome, expected_prefix):
    _mock_discord_ok(monkeypatch)
    calls = _mock_github(monkeypatch, outcome)

    code, out, _ = run_cli(capsys, "--plain", "doctor")
    assert code == 0
    assert len(calls) == 1

    rows = {r[0]: (r[1], r[2]) for r in (line.split("\t") for line in out.strip().splitlines())}
    assert rows["update"] == ("OK", expected_prefix)


def test_doctor_forces_fresh_check_and_preserves_notified_at(capsys, monkeypatch, update_env):
    _mock_discord_ok(monkeypatch)
    newer = _newer_version()
    calls = _mock_github(monkeypatch, 200, {"tag_name": f"v{newer}"})

    cache_file = update_check.update_cache_path()
    cache_file.parent.mkdir(parents=True, exist_ok=True)
    cache_file.write_text(
        json.dumps({
            "checked_at": time.time(),
            "latest_version": __version__,
            "latest_url": f"https://github.com/filbam/Discoop/releases/tag/v{__version__}",
            "failed_at": None,
            "notified_at": 12345.0,
        }),
        encoding="utf-8",
    )

    code, out, _ = run_cli(capsys, "--plain", "doctor")
    assert code == 0
    assert len(calls) == 1

    rows = {r[0]: (r[1], r[2]) for r in (line.split("\t") for line in out.strip().splitlines())}
    assert rows["update"] == ("OK", f"{newer} available: uv tool upgrade discoop")

    updated = json.loads(cache_file.read_text(encoding="utf-8"))
    assert updated["latest_version"] == newer
    assert updated["notified_at"] == 12345.0


def test_doctor_failure_exit_code_unchanged_by_update_row(capsys, monkeypatch, update_env):
    TokenStore.default().delete()
    calls = _mock_github(monkeypatch, 500)

    code, out, _ = run_cli(capsys, "--plain", "doctor")
    assert code == 2
    assert len(calls) == 1

    rows = {r[0]: (r[1], r[2]) for r in (line.split("\t") for line in out.strip().splitlines())}
    assert rows["login"][0] == "FAIL"
    assert rows["update"] == ("OK", "could not check: HTTP 500")


def test_doctor_tty_makes_single_http_call_and_shows_notice_once(capsys, monkeypatch, update_env):
    _mock_discord_ok(monkeypatch)
    newer = _newer_version()
    calls = _mock_github(
        monkeypatch,
        200,
        {"tag_name": f"v{newer}", "html_url": f"https://github.com/filbam/Discoop/releases/tag/v{newer}"},
    )
    monkeypatch.setattr(sys.stderr, "isatty", lambda: True)

    code, out, err = run_cli(capsys, "--plain", "doctor")
    assert code == 0
    assert len(calls) == 1
    assert f"{newer} available: uv tool upgrade discoop" in out
    assert f"A new release of discoop is available: {__version__} -> {newer}" in err
    assert f"https://github.com/filbam/Discoop/releases/tag/v{newer}" in err

    # Second run within 24h refreshes doctor row (1 more HTTP call) without repeating stderr notice.
    code2, out2, err2 = run_cli(capsys, "--plain", "doctor")
    assert code2 == 0
    assert len(calls) == 2
    assert f"{newer} available: uv tool upgrade discoop" in out2
    assert err2 == ""


def test_doctor_human_tty_prints_yellow_notice_and_table(capsys, monkeypatch, update_env):
    _mock_discord_ok(monkeypatch)
    newer = _newer_version()
    calls = _mock_github(
        monkeypatch,
        200,
        {"tag_name": f"v{newer}", "html_url": f"https://github.com/filbam/Discoop/releases/tag/v{newer}"},
    )
    monkeypatch.setattr(sys.stderr, "isatty", lambda: True)

    code, out, err = run_cli(capsys, "--human", "doctor")
    assert code == 0
    assert len(calls) == 1
    assert "discoop doctor" in out
    assert "\x1b[33m" in err
    assert f"A new release of discoop is available: {__version__} -> {newer}" in err
    assert f"https://github.com/filbam/Discoop/releases/tag/v{newer}" in err
