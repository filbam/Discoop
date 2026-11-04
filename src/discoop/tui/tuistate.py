"""Persistent TUI state management (tui-state.json in paths.config_dir()).

Saves and restores channel selection, custom time windows, global time windows,
export settings, and channel export timestamps per Discord account (user_id).
"""

from __future__ import annotations

from datetime import datetime, timezone, tzinfo
import json
import logging
import os
from pathlib import Path
from typing import Any

from discoop import paths
from discoop.models import Channel, Server
from discoop.snowflake import to_time
from discoop.tui.state import ExportSettings, SelectionState, WindowSpec

logger = logging.getLogger("discoop.tui.tuistate")


def _state_file() -> Path:
    return paths.config_dir() / "tui-state.json"


def load_raw_state() -> dict[str, Any]:
    """Load raw root JSON object from tui-state.json.

    Returns empty dict if missing or corrupted. Never raises. A corrupted file is reported with `logger.warning`,
    not with `warnings.warn`: inside a running Textual app a Python warning would be painted into the terminal.
    """
    path = _state_file()
    if not path.is_file():
        return {}
    try:
        text = path.read_text(encoding="utf-8")
        data = json.loads(text)
        if not isinstance(data, dict):
            logger.warning("Corrupted tui-state file (root is not a dict): %s", path)
            return {}
        return data
    except Exception as err:
        logger.warning("Corrupted tui-state file (%s): %s", err, path)
        return {}


def save_raw_state(data: dict[str, Any]) -> None:
    """Save root JSON object to tui-state.json atomically."""
    target_path = _state_file()
    target_dir = target_path.parent
    target_dir.mkdir(parents=True, exist_ok=True)
    temp_path = target_dir / f"tui-state.{os.getpid()}.tmp"
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


def load_user_state(user_id: str | None) -> dict[str, Any]:
    """Load the state dict for a specific user ID."""
    if not user_id:
        return {}
    raw = load_raw_state()
    accounts = raw.get("accounts")
    if not isinstance(accounts, dict):
        return {}
    user_data = accounts.get(str(user_id))
    return user_data if isinstance(user_data, dict) else {}


def save_user_state(user_id: str | None, user_state: dict[str, Any]) -> None:
    """Save the state dict for a specific user ID atomically."""
    if not user_id:
        return
    raw = load_raw_state()
    accounts = raw.setdefault("accounts", {})
    if not isinstance(accounts, dict):
        accounts = {}
        raw["accounts"] = accounts
    accounts[str(user_id)] = user_state
    save_raw_state(raw)


def serialize_window(window: WindowSpec) -> dict[str, Any]:
    """Convert WindowSpec to JSON-serializable dict."""
    return {
        "from": window.from_,
        "to": window.to,
        "last": window.last,
        "max_messages": window.max_messages,
    }


def deserialize_window(data: Any, default: WindowSpec | None = None) -> WindowSpec:
    """Convert dict to WindowSpec, falling back to default."""
    if not isinstance(data, dict):
        return default or WindowSpec()
    return WindowSpec(
        from_=data.get("from", "7d"),
        to=data.get("to"),
        last=data.get("last"),
        max_messages=data.get("max_messages", 5000),
    )


def extract_app_state(
    selection: SelectionState,
    settings: ExportSettings,
    last_exported: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Create a JSON-serializable state dict from current selection and settings."""
    selected_dict: dict[str, dict[str, Any]] = {}
    for ch_id, (server, channel) in selection.selected.items():
        custom_w = selection.custom_windows.get(ch_id)
        selected_dict[ch_id] = {
            "server_id": server.id,
            "custom_window": serialize_window(custom_w) if custom_w is not None else None,
        }

    return {
        "selection": selected_dict,
        "global_window": serialize_window(selection.global_window),
        "settings": {
            "mode": settings.mode,
            "folder": settings.folder,
            "name": settings.name,
            "threads": settings.threads,
        },
        "last_exported": dict(last_exported or {}),
    }


def restore_app_state(
    state: dict[str, Any],
    servers: list[Server],
    channels_by_server: dict[str, list[Channel]],
    selection: SelectionState,
    settings: ExportSettings,
) -> tuple[int, dict[str, str]]:
    """Restore selection, windows, and settings from state.

    Discards server and channel IDs that no longer exist.
    Returns (number_of_restored_channels, last_exported_dict).
    """
    if not isinstance(state, dict):
        return 0, {}

    # Restore settings
    settings_data = state.get("settings")
    if isinstance(settings_data, dict):
        if "mode" in settings_data and settings_data["mode"] in ("safe", "fast"):
            settings.mode = settings_data["mode"]
        if "folder" in settings_data and isinstance(settings_data["folder"], str):
            settings.folder = settings_data["folder"]
        if "name" in settings_data and isinstance(settings_data["name"], str):
            settings.name = settings_data["name"]
        if "threads" in settings_data and isinstance(settings_data["threads"], bool):
            settings.threads = settings_data["threads"]

    # Restore global window
    if "global_window" in state:
        selection.global_window = deserialize_window(state["global_window"], selection.global_window)

    # Fast lookup for known servers and channels
    server_lookup = {s.id: s for s in servers}
    channel_lookup: dict[str, tuple[Server, Channel]] = {}
    for s_id, ch_list in channels_by_server.items():
        if s_id in server_lookup:
            srv = server_lookup[s_id]
            for ch in ch_list:
                channel_lookup[ch.id] = (srv, ch)

    # Restore selection and custom windows
    selection.selected.clear()
    selection.custom_windows.clear()
    restored_count = 0

    selection_data = state.get("selection")
    if isinstance(selection_data, dict):
        for ch_id, ch_info in selection_data.items():
            if ch_id in channel_lookup:
                srv, ch = channel_lookup[ch_id]
                if selection.is_selectable(ch):
                    selection.selected[ch_id] = (srv, ch)
                    restored_count += 1
                    if isinstance(ch_info, dict) and ch_info.get("custom_window"):
                        selection.custom_windows[ch_id] = deserialize_window(
                            ch_info["custom_window"], selection.global_window
                        )

    raw_last_exported = state.get("last_exported")
    last_exported: dict[str, str] = {}
    if isinstance(raw_last_exported, dict):
        last_exported = {
            str(k): str(v)
            for k, v in raw_last_exported.items()
            if isinstance(k, str) and isinstance(v, str)
        }

    return restored_count, last_exported


def format_activity(
    last_message_id: int | str | None, now: datetime | None = None, *, short: bool = False
) -> str:
    """Format relative activity time from snowflake last_message_id.

    `2d ago` by default; `short=True` drops the word for a tight tree row: `now`, `5m`, `3h`, `2d`, `4mo`, `1y`.
    Returns "" for a missing or invalid ID.
    """
    if last_message_id is None:
        return ""
    try:
        msg_id_int = int(last_message_id)
        if msg_id_int <= 0:
            return ""
        msg_time = to_time(msg_id_int)
    except (ValueError, TypeError, OverflowError, OSError):
        return ""

    ref_now = now or datetime.now(timezone.utc)
    delta = ref_now - msg_time
    total_seconds = max(0.0, delta.total_seconds())
    ago = "" if short else " ago"

    if total_seconds < 60:
        return "now" if short else "just now"
    minutes = int(total_seconds // 60)
    if minutes < 60:
        return f"{minutes}m{ago}"
    hours = int(total_seconds // 3600)
    if hours < 24:
        return f"{hours}h{ago}"
    days = int(total_seconds // 86400)
    if days < 30:
        return f"{days}d{ago}"
    if days < 365:
        return f"{min(days // 30, 11)}mo{ago}"
    return f"{days // 365}y{ago}"


def format_last_exported(
    iso_str: str | None, now: datetime | None = None, *, short: bool = False, tz: tzinfo | None = None
) -> str:
    """Format last exported timestamp relative to now (e.g. 'exported 1h ago').

    `short=True` gives the date of the last export, in zone `tz` (None: the system zone): `exp 11-03`, with the
    year (`exp 2025-11-03`) when it is not the current one. Returns "" for a missing or invalid timestamp.
    """
    if not iso_str:
        return ""
    try:
        dt = datetime.fromisoformat(iso_str)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return ""

    ref_now = now or datetime.now(timezone.utc)
    if short:
        try:
            local = dt.astimezone(tz)
            same_year = local.year == ref_now.astimezone(tz).year
        except (ValueError, OverflowError, OSError):
            return ""
        return f"exp {local:%m-%d}" if same_year else f"exp {local:%Y-%m-%d}"

    delta = ref_now - dt
    total_seconds = max(0.0, delta.total_seconds())

    if total_seconds < 60:
        return "exported just now"
    minutes = int(total_seconds // 60)
    if minutes < 60:
        return f"exported {minutes}m ago"
    hours = int(total_seconds // 3600)
    if hours < 24:
        return f"exported {hours}h ago"
    days = int(total_seconds // 86400)
    return f"exported {days}d ago"
