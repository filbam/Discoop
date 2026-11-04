"""Sync state management for incremental scraping (--since-last)."""

import json
import logging
import os
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from discoop import paths

logger = logging.getLogger("discoop.syncstate")
logger.addHandler(logging.NullHandler())  # no handler of ours: do not let `lastResort` print it to stderr


def sync_state_path() -> Path:
    """Location of sync-state.json in data_dir, separate from cache.db."""
    return paths.data_dir() / "sync-state.json"


@dataclass(frozen=True)
class ChannelSync:
    """Sync state for a single channel or thread."""

    last_message_id: str
    updated: str  # ISO 8601 UTC timestamp


def _warn(msg: str, on_warning: Callable[[str], None] | None = None) -> None:
    """Log the problem and tell `on_warning` (the CLI prints it): no Python `warnings`, they add noise in a terminal."""
    logger.warning(msg)
    if on_warning is not None:
        on_warning(msg)


def load_sync_data(
    path: Path | None = None,
    on_warning: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    """Load the full sync state document from sync-state.json.

    Returns `{"version": 1, "accounts": {}}` if missing or corrupted.
    Never raises an exception on corrupted files.
    """
    file_path = path or sync_state_path()
    if not file_path.is_file():
        return {"version": 1, "accounts": {}}
    try:
        text = file_path.read_text(encoding="utf-8")
        data = json.loads(text)
        if not isinstance(data, dict):
            _warn(f"Corrupted sync state file (root is not a dict): {file_path}", on_warning)
            return {"version": 1, "accounts": {}}
        if data.get("version") != 1:
            _warn(f"Unsupported sync state version ({data.get('version')}): {file_path}", on_warning)
            return {"version": 1, "accounts": {}}
        if not isinstance(data.get("accounts"), dict):
            _warn(f"Corrupted sync state file (accounts is not a dict): {file_path}", on_warning)
            return {"version": 1, "accounts": {}}
        return data
    except Exception as err:
        _warn(f"Corrupted sync state file ({err}): {file_path}", on_warning)
        return {"version": 1, "accounts": {}}


def load_account_channels(
    user_id: str,
    path: Path | None = None,
    on_warning: Callable[[str], None] | None = None,
) -> dict[str, ChannelSync]:
    """Load the mapping of channel_id -> ChannelSync for a given user ID."""
    data = load_sync_data(path=path, on_warning=on_warning)
    accounts = data.get("accounts", {})
    account = accounts.get(str(user_id), {})
    if not isinstance(account, dict):
        return {}
    channels_data = account.get("channels", {})
    if not isinstance(channels_data, dict):
        return {}
    result: dict[str, ChannelSync] = {}
    for cid, val in channels_data.items():
        if isinstance(val, dict) and "last_message_id" in val and "updated" in val:
            result[str(cid)] = ChannelSync(
                last_message_id=str(val["last_message_id"]),
                updated=str(val["updated"]),
            )
    return result


def save_sync_data(data: dict[str, Any], path: Path | None = None) -> None:
    """Atomically write the full sync state document to sync-state.json."""
    target_path = path or sync_state_path()
    target_dir = target_path.parent
    target_dir.mkdir(parents=True, exist_ok=True)
    temp_path = target_dir / f"sync-state.{os.getpid()}.tmp"
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


def update_account_channels(
    user_id: str,
    updates: dict[str, ChannelSync],
    path: Path | None = None,
) -> None:
    """Update or insert channel sync states for a specific user ID."""
    data = load_sync_data(path=path)
    accounts = data.setdefault("accounts", {})
    account = accounts.setdefault(str(user_id), {"channels": {}})
    channels = account.setdefault("channels", {})
    for cid, sync in updates.items():
        channels[str(cid)] = {
            "last_message_id": sync.last_message_id,
            "updated": sync.updated,
        }
    save_sync_data(data, path=path)
