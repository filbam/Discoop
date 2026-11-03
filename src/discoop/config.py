"""User settings in config.toml in the platform config directory."""

import json
import tomllib
from pathlib import Path
from typing import Any

from discoop import paths
from discoop.errors import DiscoopError, ExitCode

DESCRIPTIONS = {
    "default-server": "server ID used when --server is not given",
    "delay": "seconds between Discord API requests",
}
DEFAULTS: dict[str, Any] = {"delay": 1.0}


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
