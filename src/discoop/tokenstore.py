"""Where the Discord token lives.

The OS keyring (Windows Credential Manager, macOS Keychain, Linux Secret Service) is preferred.
When no keyring backend works, e.g. a headless Linux box, the token goes to a 0600 file.
"""

import os
from dataclasses import dataclass
from pathlib import Path

import keyring
from keyring.errors import KeyringError, PasswordDeleteError

from discoop import paths

SERVICE = "discoop"
ACCOUNT = "token"


@dataclass(frozen=True)
class StoredToken:
    token: str
    location: str


class TokenStore:
    def __init__(self, file_path: Path) -> None:
        self.file_path = file_path

    @classmethod
    def default(cls) -> "TokenStore":
        return cls(paths.data_dir() / "token")

    def keyring_name(self) -> str:
        backend = keyring.get_keyring()
        return f"keyring ({type(backend).__module__}.{type(backend).__name__})"

    def load(self) -> StoredToken | None:
        try:
            token = keyring.get_password(SERVICE, ACCOUNT)
        except KeyringError:
            token = None
        if token:
            return StoredToken(token, self.keyring_name())
        if self.file_path.is_file():
            token = self.file_path.read_text(encoding="utf-8").strip()
            if token:
                return StoredToken(token, f"file ({self.file_path})")
        return None

    def save(self, token: str) -> str:
        """Store the token and return where it went."""
        try:
            keyring.set_password(SERVICE, ACCOUNT, token)
        except KeyringError:
            self._write_file(token)
            return f"file ({self.file_path})"
        self.file_path.unlink(missing_ok=True)
        return self.keyring_name()

    def delete(self) -> bool:
        """Remove the token from every place it could be. Returns True if anything was removed."""
        removed = False
        try:
            keyring.delete_password(SERVICE, ACCOUNT)
            removed = True
        except (PasswordDeleteError, KeyringError):
            pass
        if self.file_path.is_file():
            self.file_path.unlink()
            removed = True
        return removed

    def _write_file(self, token: str) -> None:
        self.file_path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(self.file_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(token)
        os.chmod(self.file_path, 0o600)
