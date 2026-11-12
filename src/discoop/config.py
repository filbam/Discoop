"""User settings in config.toml in the platform config directory."""

import json
import tomllib
from pathlib import Path
from typing import Any

from discoop import paths
from discoop.errors import DiscoopError, ExitCode

MODES = ("safe", "fast")
DEFAULT_MODE = "safe"
UPDATE_CHECK_VALUES = ("on", "off")
DEFAULT_UPDATE_CHECK = "on"

DESCRIPTIONS = {
    "browser-path": "browser program for `login --browser` (default: Chrome, Edge, Chromium or Brave is auto-detected)",
    "default-server": "server ID used when --server is not given",
    "delay": "seconds between Discord API requests",
    "export-dir": "folder for relative --out/--zip paths (default: current folder; TUI: Documents/discoop)",
    "mode": "download mode: safe (human-like scrolling pauses) or fast",
    "update-check": "check GitHub Releases for a newer discoop version: on or off",
}
DEFAULTS: dict[str, Any] = {
    "delay": 1.0,
    "mode": DEFAULT_MODE,
    "update-check": DEFAULT_UPDATE_CHECK,
}


class Config:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.values: dict[str, Any] = {}
        if path.is_file():
            try:
                self.values = tomllib.loads(path.read_text(encoding="utf-8"))
            except (tomllib.TOMLDecodeError, UnicodeDecodeError) as e:
                raise DiscoopError(ExitCode.ERROR, f"Cannot read {path}: {e}", "Fix or delete the file.") from e

    @classmethod
    def default(cls) -> "Config":
        return cls(paths.config_dir() / "config.toml")

    def get(self, key: str) -> Any:
        check_key(key)
        return self.values.get(key, DEFAULTS.get(key))

    def set(self, key: str, value: Any) -> None:
        check_key(key)
        self.values[key] = value
        self._save()

    def unset(self, key: str) -> bool:
        check_key(key)
        removed = self.values.pop(key, None) is not None
        if removed:
            self._save()
        return removed

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # Flat string/number values only; their JSON form is valid TOML.
        lines = [f"{key} = {json.dumps(value, ensure_ascii=False)}" for key, value in sorted(self.values.items())]
        self.path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def check_key(key: str) -> None:
    if key not in DESCRIPTIONS:
        raise DiscoopError(
            ExitCode.BAD_ARGS, f'Unknown setting "{key}".', f"Known settings: {', '.join(DESCRIPTIONS)}."
        )


def parse_delay(raw: str) -> float:
    try:
        value = float(raw)
    except ValueError:
        value = -1.0
    if value < 0:
        raise DiscoopError(ExitCode.BAD_ARGS, f'"{raw}" is not a valid delay.', "Use seconds, e.g. 1 or 0.5.")
    return value


def parse_mode(raw: str) -> str:
    value = raw.strip().lower()
    if value not in MODES:
        raise DiscoopError(
            ExitCode.BAD_ARGS,
            f'Unknown mode "{raw}".',
            f"Known modes: {', '.join(MODES)}.",
        )
    return value


def parse_update_check(raw: str) -> str:
    value = raw.strip().lower()
    if value not in UPDATE_CHECK_VALUES:
        raise DiscoopError(
            ExitCode.BAD_ARGS,
            f'Unknown update-check value "{raw}".',
            f"Use one of: {', '.join(UPDATE_CHECK_VALUES)}.",
        )
    return value


def parse_export_dir(raw: str) -> str:
    """An absolute folder path, so the setting means the same folder whatever the current folder is later."""
    if not raw.strip():
        raise DiscoopError(ExitCode.BAD_ARGS, "export-dir cannot be empty.", "Use `discoop config unset export-dir`.")
    path = Path(raw.strip()).expanduser().resolve()
    if path.exists() and not path.is_dir():
        raise DiscoopError(ExitCode.BAD_ARGS, f"{path} is a file, not a folder.")
    return str(path)


def parse_browser_path(raw: str) -> str:
    """An absolute path to an existing browser program (the file `login --browser` starts)."""
    if not raw.strip():
        raise DiscoopError(
            ExitCode.BAD_ARGS, "browser-path cannot be empty.", "Use `discoop config unset browser-path`."
        )
    path = Path(raw.strip()).expanduser().resolve()
    if path.is_dir():
        raise DiscoopError(
            ExitCode.BAD_ARGS,
            f"{path} is a folder, not a browser program.",
            "Give the program itself. On macOS that is the file inside the app, e.g. "
            "`.../Google Chrome.app/Contents/MacOS/Google Chrome`.",
        )
    if not path.is_file():
        raise DiscoopError(
            ExitCode.BAD_ARGS,
            f"{path} does not exist.",
            "Give the full path of the browser program (chrome.exe, msedge.exe, brave.exe, chromium, ...).",
        )
    return str(path)


def parse_value(key: str, raw: str) -> Any:
    """Check and convert a value for `config set` (default-server is resolved by the CLI instead)."""
    check_key(key)
    if key == "browser-path":
        return parse_browser_path(raw)
    if key == "export-dir":
        return parse_export_dir(raw)
    if key == "mode":
        return parse_mode(raw)
    if key == "update-check":
        return parse_update_check(raw)
    return parse_delay(raw)
