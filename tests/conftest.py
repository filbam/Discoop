import keyring
import pytest
from keyring.backend import KeyringBackend
from keyring.errors import PasswordDeleteError


class MemoryKeyring(KeyringBackend):
    priority = 1

    def __init__(self) -> None:
        super().__init__()
        self.store: dict[tuple[str, str], str] = {}

    def get_password(self, service: str, username: str) -> str | None:
        return self.store.get((service, username))

    def set_password(self, service: str, username: str, password: str) -> None:
        self.store[(service, username)] = password

    def delete_password(self, service: str, username: str) -> None:
        if self.store.pop((service, username), None) is None:
            raise PasswordDeleteError("not found")


@pytest.fixture(autouse=True)
def isolated_env(tmp_path, monkeypatch):
    """Never touch the real keyring, data dir, Documents folder or environment of the machine running the tests."""
    previous = keyring.get_keyring()
    memory = MemoryKeyring()
    keyring.set_keyring(memory)
    monkeypatch.setattr("discoop.paths.data_dir", lambda: tmp_path / "data")
    monkeypatch.setattr("discoop.paths.config_dir", lambda: tmp_path / "config")
    monkeypatch.setattr("discoop.paths.documents_dir", lambda: tmp_path / "documents")
    monkeypatch.delenv("DISCOOP_AGENT", raising=False)
    monkeypatch.setenv("DISCOOP_NO_UPDATE_NOTIFIER", "1")
    yield memory
    keyring.set_keyring(previous)
