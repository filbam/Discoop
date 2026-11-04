import json
import warnings
import pytest

from discoop import paths, profiles


def test_missing_file_returns_empty_dict():
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        assert profiles.load() == {}
        assert profiles.names() == []


def test_save_and_load():
    profile = {
        "server": "my-server",
        "channels": ["general", "random"],
        "from": "2026-10-01",
        "to": "2026-10-02",
        "last": 100,
        "mode": "plain",
    }
    profiles.save("dev", profile)

    loaded = profiles.load()
    assert "dev" in loaded
    assert loaded["dev"] == profile
    assert profiles.names() == ["dev"]


def test_filter_disallowed_keys():
    profile = {
        "server": "fit",
        "channels": ["chat"],
        "disallowed_key": "drop_me",
        "token": "secret_token",
        "extra": 12345,
    }
    profiles.save("filtered", profile)

    loaded = profiles.load()
    assert loaded["filtered"] == {
        "server": "fit",
        "channels": ["chat"],
    }


def test_channels_saved_as_list():
    profiles.save("tuple_channels", {"channels": ("a", "b")})
    profiles.save("set_channels", {"channels": {"x"}})
    profiles.save("str_channel", {"channels": "single-ch"})

    loaded = profiles.load()
    assert loaded["tuple_channels"]["channels"] == ["a", "b"]
    assert loaded["set_channels"]["channels"] == ["x"]
    assert loaded["str_channel"]["channels"] == ["single-ch"]


def test_names_sorted():
    profiles.save("gamma", {"server": "g"})
    profiles.save("alpha", {"server": "a"})
    profiles.save("beta", {"server": "b"})

    assert profiles.names() == ["alpha", "beta", "gamma"]


def test_delete():
    profiles.save("to-delete", {"server": "s"})
    assert "to-delete" in profiles.names()

    assert profiles.delete("to-delete") is True
    assert "to-delete" not in profiles.names()
    assert profiles.delete("to-delete") is False
    assert profiles.delete("nonexistent") is False


@pytest.mark.parametrize(
    "bad_name",
    [
        "",
        "   ",
        ".",
        "..",
        "../x",
        "a/b",
        "a\\b",
        "foo..bar",
        "bad name",
        "bad!name",
        "bad?name",
    ],
)
def test_invalid_names_raise_value_error(bad_name):
    with pytest.raises(ValueError):
        profiles.save(bad_name, {"server": "s"})
    with pytest.raises(ValueError):
        profiles.delete(bad_name)


def test_whitespace_stripped_name():
    profiles.save("  clean-name  ", {"server": "s"})
    assert profiles.names() == ["clean-name"]
    assert profiles.delete("  clean-name  ") is True
    assert profiles.names() == []


def test_corrupted_file_warns_and_returns_empty():
    config_file = paths.config_dir() / "profiles.json"
    config_file.parent.mkdir(parents=True, exist_ok=True)
    config_file.write_text("{this is corrupted json", encoding="utf-8")

    with pytest.warns(UserWarning, match="Corrupted profiles file"):
        assert profiles.load() == {}


def test_root_not_dict_warns_and_returns_empty():
    config_file = paths.config_dir() / "profiles.json"
    config_file.parent.mkdir(parents=True, exist_ok=True)
    config_file.write_text(json.dumps(["not", "a", "dict"]), encoding="utf-8")

    with pytest.warns(UserWarning, match="root is not a dict"):
        assert profiles.load() == {}
