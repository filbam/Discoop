import pytest

from discoop.config import Config, parse_delay
from discoop.errors import DiscoopError, ExitCode


def test_defaults_and_roundtrip():
    config = Config.default()
    assert config.get("delay") == 1.0
    assert config.get("default-server") is None
    config.set("default-server", "461541385204400138")
    config.set("delay", 0.5)
    reloaded = Config.default()
    assert reloaded.get("default-server") == "461541385204400138"
    assert reloaded.get("delay") == 0.5
    assert reloaded.unset("delay") is True
    assert Config.default().get("delay") == 1.0
    assert Config.default().unset("delay") is False


def test_unknown_key():
    with pytest.raises(DiscoopError) as e:
        Config.default().get("colour")
    assert e.value.code == ExitCode.BAD_ARGS


def test_unusual_strings_survive():
    Config.default().set("default-server", 'He said "hi" \\ ✓')
    assert Config.default().get("default-server") == 'He said "hi" \\ ✓'


def test_broken_file_is_reported():
    config = Config.default()
    config.path.parent.mkdir(parents=True, exist_ok=True)
    config.path.write_text("delay = = 1", encoding="utf-8")
    with pytest.raises(DiscoopError) as e:
        Config.default()
    assert "Fix or delete" in e.value.hint


def test_parse_delay():
    assert parse_delay("0.5") == 0.5
    for bad in ("-1", "fast"):
        with pytest.raises(DiscoopError):
            parse_delay(bad)
