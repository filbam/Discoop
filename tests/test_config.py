import pytest

from discoop.config import Config, parse_delay, parse_mode, parse_value
from discoop.errors import DiscoopError, ExitCode


def test_defaults_and_roundtrip():
    config = Config.default()
    assert config.get("delay") == 1.0
    assert config.get("mode") == "safe"
    assert config.get("default-server") is None
    config.set("default-server", "461541385204400138")
    config.set("delay", 0.5)
    config.set("mode", "fast")
    reloaded = Config.default()
    assert reloaded.get("default-server") == "461541385204400138"
    assert reloaded.get("delay") == 0.5
    assert reloaded.get("mode") == "fast"
    assert reloaded.unset("mode") is True
    assert Config.default().get("mode") == "safe"
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


def test_parse_mode():
    assert parse_mode("safe") == "safe"
    assert parse_mode("FAST") == "fast"
    for bad in ("", "turbo", "slow"):
        with pytest.raises(DiscoopError) as e:
            parse_mode(bad)
        assert e.value.code == ExitCode.BAD_ARGS


def test_export_dir(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert Config.default().get("export-dir") is None
    assert parse_value("export-dir", "exports") == str(tmp_path / "exports")  # stored absolute
    assert parse_value("export-dir", str(tmp_path / "a" / ".." / "b")) == str(tmp_path / "b")
    assert parse_value("delay", "2") == 2.0
    assert parse_value("mode", "fast") == "fast"
    (tmp_path / "file.txt").write_text("x", encoding="utf-8")
    for bad in ("", "  ", "file.txt"):
        with pytest.raises(DiscoopError) as e:
            parse_value("export-dir", bad)
        assert e.value.code == ExitCode.BAD_ARGS
