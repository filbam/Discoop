"""Profiles management for saving and loading scraping configuration sets."""

import json
import os
import re
import warnings
from pathlib import Path
from typing import Any

from discoop import paths

ALLOWED_KEYS = {"server", "channels", "from", "to", "last", "mode"}


def _profiles_file() -> Path:
    return paths.config_dir() / "profiles.json"


def validate_name(name: str) -> str:
    """Return the profile name without surrounding spaces, or raise ValueError if it is not allowed.

    Letters, digits, dash, underscore and dot are allowed; `..` and an empty name are not.
    """
    clean = name.strip()
    if not clean or clean in (".", "..") or ".." in clean:
        raise ValueError(f"Invalid profile name: {name!r}")
    if not re.fullmatch(r"[a-zA-Z0-9_.-]+", clean):
        raise ValueError(f"Invalid profile name: {name!r}")
    return clean


_validate_name = validate_name  # the old private name, kept for existing imports


def _write_profiles(data: dict[str, dict[str, Any]]) -> None:
    target_path = _profiles_file()
    target_dir = target_path.parent
    target_dir.mkdir(parents=True, exist_ok=True)
    temp_path = target_dir / f"profiles.{os.getpid()}.tmp"
    serialized = json.dumps(data, indent=2, ensure_ascii=False)
    try:
        temp_path.write_text(serialized, encoding="utf-8")
        os.replace(temp_path, target_path)
    finally:
        if temp_path.exists():
            try:
                temp_path.unlink()
            except OSError:
                pass


def load() -> dict[str, dict[str, Any]]:
    """Load all saved profiles from config_dir/profiles.json.

    Returns an empty dict if the file is missing.
    Issues a warning and returns an empty dict if the file is corrupted or root is not a dict.
    Never raises an exception.
    """
    path = _profiles_file()
    if not path.is_file():
        return {}
    try:
        text = path.read_text(encoding="utf-8")
        data = json.loads(text)
        if not isinstance(data, dict):
            warnings.warn(f"Corrupted profiles file (root is not a dict): {path}", UserWarning, stacklevel=2)
            return {}
        return data
    except Exception as err:
        warnings.warn(f"Corrupted profiles file ({err}): {path}", UserWarning, stacklevel=2)
        return {}


def save(name: str, profile: dict[str, Any]) -> None:
    """Save or update a profile by name.

    Only allowed keys (server, channels, from, to, last, mode) are preserved.
    Channels, if present, are stored as a list.
    """
    clean_name = validate_name(name)
    cleaned: dict[str, Any] = {k: v for k, v in profile.items() if k in ALLOWED_KEYS}
    if "channels" in cleaned and cleaned["channels"] is not None:
        ch = cleaned["channels"]
        if isinstance(ch, (list, tuple, set)):
            cleaned["channels"] = list(ch)
        elif isinstance(ch, str):
            cleaned["channels"] = [ch]
        else:
            cleaned["channels"] = list(ch)
    data = load()
    data[clean_name] = cleaned
    _write_profiles(data)


def delete(name: str) -> bool:
    """Delete a profile by name. Returns True if found and deleted, False otherwise."""
    clean_name = validate_name(name)
    data = load()
    if clean_name not in data:
        return False
    del data[clean_name]
    _write_profiles(data)
    return True


def names() -> list[str]:
    """Return sorted list of saved profile names."""
    return sorted(load().keys())
