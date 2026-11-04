import json
from datetime import UTC, datetime
import pytest
import httpx

from discoop import cli, profiles
from discoop.api import DiscordAPI
from discoop.tokenstore import TokenStore
from fake_messages import CET, FIT, NOW, FakeChannel, FakeDiscord, message


def at(hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 11, 3, hour, minute, tzinfo=CET).astimezone(UTC)


def run_cli(capsys, *args):
    with pytest.raises(SystemExit) as e:
        cli.main(["--agent", *args])
    captured = capsys.readouterr()
    return e.value.code, captured.out, captured.err


@pytest.fixture
def offline_discord(monkeypatch):
    TokenStore.default().save("tok")
    monkeypatch.setattr(cli, "utc_now", lambda: NOW)
    monkeypatch.setattr(cli, "LOCAL_ZONE", CET)
    msg1 = message(at(10), "First message")
    msg2 = message(at(11), "Second message in 202")
    fake = FakeDiscord({"200": FakeChannel([msg1]), "202": FakeChannel([msg2])})

    def handle(request: httpx.Request) -> httpx.Response:
        if "/threads/search" in request.url.path:
            return httpx.Response(200, json={"threads": [], "has_more": False, "total_results": 0})
        return fake.handle(request)

    transport = httpx.MockTransport(handle)
    monkeypatch.setattr(cli, "DiscordAPI", lambda token, **kw: DiscordAPI(token, transport=transport))
    return fake


def test_save_profile_saves_before_fetching(capsys, offline_discord, monkeypatch):
    code, out, err = run_cli(
        capsys,
        "messages",
        "-s",
        FIT,
        "-c",
        "200",
        "--from",
        "7d",
        "--to",
        "now",
        "--last",
        "10",
        "--fast",
        "--save-profile",
        "dev_profile",
    )
    assert code == 0
    saved = profiles.load()
    assert "dev_profile" in saved
    assert saved["dev_profile"] == {
        "server": FIT,
        "channels": ["200"],
        "from": "7d",
        "to": "now",
        "last": 10,
        "mode": "fast",
    }

    # Test that invalid profile name fails with BAD_ARGS before API call
    def boom(*args, **kwargs):
        raise AssertionError("Discord API must not be called!")

    monkeypatch.setattr(cli, "DiscordAPI", boom)

    code, _, err = run_cli(
        capsys, "messages", "-s", FIT, "-c", "200", "--save-profile", "invalid/name"
    )
    assert code == 8
    assert "Invalid profile name" in err


def test_profile_loads_options(capsys, offline_discord):
    profiles.save(
        "my_test_prof",
        {
            "server": FIT,
            "channels": ["200"],
            "from": "7d",
            "last": 5,
            "mode": "fast",
        },
    )

    # Invoking with only --profile (no -s, no -c)
    code, out, err = run_cli(capsys, "messages", "--profile", "my_test_prof")
    assert code == 0
    assert "=== VUT FIT / #2bit-general ===" in out


def test_explicit_cli_options_override_profile(capsys, offline_discord):
    profiles.save(
        "override_base",
        {
            "server": FIT,
            "channels": ["200"],
            "from": "7d",
            "mode": "safe",
        },
    )

    # -c 202 overrides channels, --fast overrides mode
    code, out, err = run_cli(capsys, "messages", "--profile", "override_base", "-c", "202", "--fast")
    assert code == 0
    assert "=== VUT FIT / #2bit-terminy ===" in out
    assert "#2bit-general" not in out


def test_unknown_profile_error_and_hint(capsys, monkeypatch):
    def boom(*args, **kwargs):
        raise AssertionError("Discord API must not be called!")

    monkeypatch.setattr(cli, "DiscordAPI", boom)

    # Case 1: no profiles saved yet
    code, _, err = run_cli(capsys, "messages", "--profile", "dev-team")
    assert code == 8
    assert 'Unknown profile "dev-team".' in err
    assert "No profiles saved yet." in err

    # Case 2: profiles exist, close match
    profiles.save("dev-team", {"server": "s"})
    profiles.save("production", {"server": "s"})

    code, _, err = run_cli(capsys, "messages", "--profile", "dev-tame")
    assert code == 8
    assert 'Unknown profile "dev-tame".' in err
    assert "Did you mean: dev-team?" in err
    assert "Available profiles: dev-team, production." in err


def test_profiles_list_and_delete(capsys):
    # Empty listing
    code, out, _ = run_cli(capsys, "profiles")
    assert code == 0 and out.strip() == ""

    code, out, _ = run_cli(capsys, "profiles", "--format", "json")
    assert code == 0
    assert json.loads(out) == []

    # Human empty listing
    with pytest.raises(SystemExit) as e:
        cli.main(["--human", "profiles"])
    captured = capsys.readouterr()
    assert e.value.code == 0
    assert "No profiles saved yet." in captured.err

    # Create profiles
    profiles.save("alpha", {"server": "s1"})
    profiles.save("beta", {"server": "s2"})

    code, out, _ = run_cli(capsys, "profiles")
    assert code == 0
    assert out.splitlines() == ["alpha", "beta"]

    code, out, _ = run_cli(capsys, "profiles", "list")
    assert code == 0
    assert out.splitlines() == ["alpha", "beta"]

    code, out, _ = run_cli(capsys, "profiles", "--format", "json")
    assert code == 0
    assert json.loads(out) == ["alpha", "beta"]

    # Delete alpha
    code, out, _ = run_cli(capsys, "profiles", "delete", "alpha")
    assert code == 0
    assert 'Profile "alpha" deleted.' in out
    assert profiles.names() == ["beta"]

    # Delete nonexistent profile -> NOT_FOUND (code 4)
    code, _, err = run_cli(capsys, "profiles", "delete", "nonexistent")
    assert code == 4
    assert 'Profile "nonexistent" does not exist.' in err

    # Delete with invalid profile name -> BAD_ARGS (code 8)
    code, _, err = run_cli(capsys, "profiles", "delete", "../invalid")
    assert code == 8
    assert "Invalid profile name" in err
