import os
import stat
import sys

import keyring
import pytest
from keyring.backends import fail

from discoop.tokenstore import ACCOUNT, SERVICE, TokenStore


@pytest.fixture
def store(tmp_path):
    return TokenStore(tmp_path / "data" / "token")


def test_keyring_roundtrip(store, isolated_env):
    location = store.save("secret-token")
    assert location.startswith("keyring")
    assert isolated_env.store[(SERVICE, ACCOUNT)] == "secret-token"
    loaded = store.load()
    assert loaded is not None and loaded.token == "secret-token"
    assert not store.file_path.exists()


def test_falls_back_to_private_file_without_keyring(store):
    keyring.set_keyring(fail.Keyring())
    location = store.save("secret-token")
    assert location.startswith("file")
    assert store.file_path.read_text(encoding="utf-8") == "secret-token"
    if sys.platform != "win32":
        assert stat.S_IMODE(os.stat(store.file_path).st_mode) == 0o600
    loaded = store.load()
    assert loaded is not None and loaded.token == "secret-token"


def test_delete_removes_everything(store, isolated_env):
    store.save("secret-token")
    store.file_path.parent.mkdir(parents=True, exist_ok=True)
    store.file_path.write_text("old", encoding="utf-8")
    assert store.delete() is True
    assert store.load() is None
    assert store.delete() is False
