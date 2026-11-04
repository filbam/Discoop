"""Unit tests for discoop.syncstate."""

import json
import subprocess
import sys
import warnings
from pathlib import Path

import pytest

from discoop import paths
from discoop.cache import Cache, cache_path, clear_cache
from discoop.syncstate import (
    ChannelSync,
    load_account_channels,
    load_sync_data,
    save_sync_data,
    sync_state_path,
    update_account_channels,
)


def test_sync_state_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(paths, "data_dir", lambda: tmp_path)
    assert sync_state_path() == tmp_path / "sync-state.json"


def test_save_and_load_sync_data(tmp_path: Path):
    path = tmp_path / "sync-state.json"
    # Initially missing
    empty = load_sync_data(path)
    assert empty == {"version": 1, "accounts": {}}

    # Update account channels
    update_account_channels(
        "12345",
        {
            "c1": ChannelSync(last_message_id="1001", updated="2026-11-04T12:00:00+00:00"),
            "c2": ChannelSync(last_message_id="1002", updated="2026-11-04T12:01:00+00:00"),
        },
        path=path,
    )

    data = load_sync_data(path)
    assert data["version"] == 1
    assert "12345" in data["accounts"]
    assert data["accounts"]["12345"]["channels"]["c1"] == {
        "last_message_id": "1001",
        "updated": "2026-11-04T12:00:00+00:00",
    }
    assert data["accounts"]["12345"]["channels"]["c2"] == {
        "last_message_id": "1002",
        "updated": "2026-11-04T12:01:00+00:00",
    }

    # Load account channels
    channels = load_account_channels("12345", path=path)
    assert len(channels) == 2
    assert channels["c1"].last_message_id == "1001"
    assert channels["c1"].updated == "2026-11-04T12:00:00+00:00"
    assert channels["c2"].last_message_id == "1002"

    # Non-existent account returns empty dict
    assert load_account_channels("99999", path=path) == {}


def test_multiple_accounts_isolated(tmp_path: Path):
    path = tmp_path / "sync-state.json"
    update_account_channels("user_a", {"c1": ChannelSync("500", "2026-11-04T10:00:00+00:00")}, path=path)
    update_account_channels("user_b", {"c2": ChannelSync("600", "2026-11-04T11:00:00+00:00")}, path=path)

    channels_a = load_account_channels("user_a", path=path)
    channels_b = load_account_channels("user_b", path=path)

    assert "c1" in channels_a and "c2" not in channels_a
    assert "c2" in channels_b and "c1" not in channels_b


def test_update_merges_existing_channels(tmp_path: Path):
    path = tmp_path / "sync-state.json"
    update_account_channels(
        "user_a",
        {
            "c1": ChannelSync("100", "2026-11-04T10:00:00+00:00"),
            "c2": ChannelSync("200", "2026-11-04T10:00:00+00:00"),
        },
        path=path,
    )
    # Update c1 and add c3
    update_account_channels(
        "user_a",
        {
            "c1": ChannelSync("150", "2026-11-04T11:00:00+00:00"),
            "c3": ChannelSync("300", "2026-11-04T11:00:00+00:00"),
        },
        path=path,
    )

    channels = load_account_channels("user_a", path=path)
    assert channels["c1"].last_message_id == "150"
    assert channels["c1"].updated == "2026-11-04T11:00:00+00:00"
    assert channels["c2"].last_message_id == "200"  # preserved
    assert channels["c3"].last_message_id == "300"  # added


def test_corrupted_file_handling(tmp_path: Path):
    path = tmp_path / "sync-state.json"
    warnings_list: list[str] = []

    def on_warning(msg: str) -> None:
        warnings_list.append(msg)

    # 1. Invalid JSON
    path.write_text("{invalid json", encoding="utf-8")
    with warnings.catch_warnings(record=True) as recorded:
        res = load_sync_data(path, on_warning=on_warning)
        assert res == {"version": 1, "accounts": {}}
        assert len(warnings_list) == 1
        assert "Corrupted sync state file" in warnings_list[-1]
        assert recorded == []  # no Python `UserWarning`: the callback and the log carry the problem

    # 2. Root is not a dict (e.g. list)
    warnings_list.clear()
    path.write_text("[]", encoding="utf-8")
    with warnings.catch_warnings(record=True):
        res = load_sync_data(path, on_warning=on_warning)
        assert res == {"version": 1, "accounts": {}}
        assert len(warnings_list) == 1
        assert "root is not a dict" in warnings_list[-1]

    # 3. Bad version
    warnings_list.clear()
    path.write_text(json.dumps({"version": 99, "accounts": {}}), encoding="utf-8")
    with warnings.catch_warnings(record=True):
        res = load_sync_data(path, on_warning=on_warning)
        assert res == {"version": 1, "accounts": {}}
        assert len(warnings_list) == 1
        assert "Unsupported sync state version" in warnings_list[-1]

    # 4. Accounts is not a dict
    warnings_list.clear()
    path.write_text(json.dumps({"version": 1, "accounts": "bad"}), encoding="utf-8")
    with warnings.catch_warnings(record=True):
        res = load_sync_data(path, on_warning=on_warning)
        assert res == {"version": 1, "accounts": {}}
        assert len(warnings_list) == 1
        assert "accounts is not a dict" in warnings_list[-1]


def test_sync_state_survives_clear_cache(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(paths, "data_dir", lambda: tmp_path)

    # Initialize a cache db
    cache = Cache.default()
    cache.close()
    assert cache_path().is_file()

    # Create sync state
    update_account_channels("123", {"c1": ChannelSync("999", "2026-11-04T12:00:00+00:00")})
    assert sync_state_path().is_file()

    # Clear cache
    clear_cache()
    assert not cache_path().exists(), "cache.db should have been deleted"
    assert sync_state_path().is_file(), "sync-state.json must survive clear_cache()"

    channels = load_account_channels("123")
    assert channels["c1"].last_message_id == "999"


def test_corrupted_file_is_logged_and_prints_nothing_to_stderr_by_itself(tmp_path: Path, caplog: pytest.LogCaptureFixture):
    path = tmp_path / "sync-state.json"
    path.write_text("{invalid json", encoding="utf-8")
    with caplog.at_level("WARNING", logger="discoop.syncstate"), warnings.catch_warnings():
        warnings.simplefilter("error")  # a Python warning would raise here
        assert load_sync_data(path) == {"version": 1, "accounts": {}}
    messages = [r.getMessage() for r in caplog.records if r.name == "discoop.syncstate"]
    assert len(messages) == 1
    assert messages[0].startswith("Corrupted sync state file (") and messages[0].endswith(f"): {path}")

    code = (
        "import sys\n"
        "from pathlib import Path\n"
        "from discoop.syncstate import load_sync_data\n"
        "print(load_sync_data(Path(sys.argv[1])))\n"
    )
    done = subprocess.run(
        [sys.executable, "-c", code, str(path)], capture_output=True, text=True, cwd=tmp_path, check=True
    )
    assert done.stdout.strip() == "{'version': 1, 'accounts': {}}"
    assert done.stderr == ""
