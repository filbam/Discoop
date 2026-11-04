"""State management, selection models, and export job planning for the discoop TUI.

Pure Python, decoupled from Textual widgets for fast startup and testability.
"""

import glob
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from discoop.attachments import safe_name
from discoop.models import CATEGORY, MESSAGE_TYPES, Channel, Server
from discoop.resolve import normalize
from discoop.service import MessagesRequest

WINDOW_PRESETS = ("24h", "7d", "30d", "all")
EXPORT_FOLDER = "exports"  # where exports go without an export-dir in the config
CUSTOM_WINDOW = "custom"


def window_preset(from_: str | None, to: str | None, last: object) -> str:
    """What a Window row shows for these field values: their preset, or "custom"."""
    return from_ if from_ in WINDOW_PRESETS and not to and not last else CUSTOM_WINDOW


@dataclass(frozen=True)
class WindowSpec:
    """Time and count boundaries for downloading channel messages."""

    from_: str | None = "7d"
    to: str | None = None
    last: int | None = None
    max_messages: int = 5000

    def _open_end(self) -> bool:
        """True if the window ends now (no --to, or --to now)."""
        return self.to is None or self.to == "now"

    def _start(self) -> str:
        """Start as the service reads it: without --from the window is 24h, or the whole history with --last."""
        if self.from_ is not None:
            return self.from_
        return "all" if self.last is not None else "24h"

    def slug(self) -> str:
        """Filesystem-safe short slug describing the window."""
        if self.last is not None and self.from_ is None and self._open_end():
            raw = f"last-{self.last}"
        else:
            parts = [self._start()]
            if not self._open_end() and self.to is not None:
                parts.append(self.to)
            if self.last is not None:
                parts.append(f"last-{self.last}")
            raw = "_".join(parts)
        return safe_name(raw, "window", max_chars=40, max_bytes=80)

    def label(self) -> str:
        """Human-readable summary of the window."""
        if self.last is not None and self.from_ is None and self._open_end():
            return f"last {self.last}"
        base = f"{self._start()} → {self.to or 'now'}"
        if self.last is not None:
            return f"{base} (last {self.last})"
        return base


@dataclass
class ExportSettings:
    """Configurable settings for export target, attachments, and speed."""

    mode: str = "safe"
    delay: float | None = None
    files: bool = True
    max_file_size: float | None = 50.0
    include_system: bool = False
    target: str = "folder"
    path: str = ""  # the Name row: empty = date and time, a bare name = inside the exports folder, else a path
    export_dir: str | None = None  # export-dir from the config
    preview_format: str = "text"


@dataclass
class SelectionState:
    """Selected channels across servers, per-channel time windows, and access tracking."""

    selected: dict[str, tuple[Server, Channel]] = field(default_factory=dict)
    custom_windows: dict[str, WindowSpec] = field(default_factory=dict)
    global_window: WindowSpec = field(default_factory=WindowSpec)
    no_access_channels: set[str] = field(default_factory=set)

    @staticmethod
    def is_selectable(channel: Channel) -> bool:
        """True if the channel type can contain messages."""
        return channel.type in MESSAGE_TYPES

    def is_selected(self, channel_id: str) -> bool:
        """True if the channel is currently selected for export."""
        return channel_id in self.selected

    def toggle(self, server: Server, channel: Channel) -> bool:
        """Toggle channel selection. Returns True if selected, False if deselected or unselectable."""
        if not self.is_selectable(channel):
            return False
        if channel.id in self.selected:
            del self.selected[channel.id]
            self.custom_windows.pop(channel.id, None)
            return False
        self.selected[channel.id] = (server, channel)
        return True

    def select_many(self, server: Server, channels: Iterable[Channel]) -> int:
        """Select all selectable channels in the iterable. Returns count of newly added channels."""
        added = 0
        for channel in channels:
            if self.is_selectable(channel) and channel.id not in self.selected:
                self.selected[channel.id] = (server, channel)
                added += 1
        return added

    def deselect_many(self, channel_ids: Iterable[str]) -> None:
        """Deselect channels by their IDs and clear their custom windows."""
        for ch_id in channel_ids:
            self.selected.pop(ch_id, None)
            self.custom_windows.pop(ch_id, None)

    def clear_server(self, server_id: str) -> None:
        """Remove all selected channels belonging to a specific server."""
        to_remove = [ch_id for ch_id, (srv, _) in self.selected.items() if srv.id == server_id]
        for ch_id in to_remove:
            del self.selected[ch_id]
            self.custom_windows.pop(ch_id, None)

    def clear_all(self) -> None:
        """Clear all selected channels and custom windows."""
        self.selected.clear()
        self.custom_windows.clear()

    def window_for(self, channel_id: str) -> WindowSpec:
        """Return the effective window for a channel (custom if set, else global)."""
        return self.custom_windows.get(channel_id, self.global_window)

    def has_custom_window(self, channel_id: str) -> bool:
        """True if the channel has a custom window overriding the global window."""
        return channel_id in self.custom_windows

    def set_custom_window(self, channel_id: str, window: WindowSpec | None) -> None:
        """Set or remove a custom window for a channel."""
        if window is None or window == self.global_window:
            self.custom_windows.pop(channel_id, None)
        else:
            self.custom_windows[channel_id] = window


@dataclass(frozen=True)
class PlannedJob:
    """A planned batch download job sharing a common WindowSpec."""

    number: int
    total: int
    window: WindowSpec
    targets: tuple[tuple[Server, Channel], ...]
    request: MessagesRequest


def export_stamp(now: datetime | None = None) -> str:
    """The automatic export name: local date and time, e.g. 2026-1104-0108."""
    return (now or datetime.now()).strftime("%Y-%m%d-%H%M")


def _export_base(settings: ExportSettings, now: datetime | None) -> str:
    """Where the export goes, without the .zip suffix or the numbering of several jobs.

    An empty name is the date and time, a bare name goes into the exports folder, a name with a separator is a path.
    """
    name = settings.path.strip()
    folder = (settings.export_dir or EXPORT_FOLDER).rstrip("/\\") or EXPORT_FOLDER
    if not name:
        stamp = export_stamp(now)
        unique, number = stamp, 1
        while any(Path(folder).glob(f"{glob.escape(unique)}*")):  # the same minute: do not mix two exports
            number += 1
            unique = f"{stamp}-{number}"
        return f"{folder}/{unique}"
    if "/" in name or "\\" in name or Path(name).is_absolute():
        return name
    return f"{folder}/{safe_name(name, 'export')}"


def plan_jobs(selection: SelectionState, settings: ExportSettings, now: datetime | None = None) -> list[PlannedJob]:
    """Group selected channels by identical WindowSpec and construct PlannedJobs.

    `now` is the local time the automatic name comes from.
    """
    if not selection.selected:
        return []
    base_path = _export_base(settings, now) if settings.target != "preview" else ""

    groups: dict[WindowSpec, list[tuple[Server, Channel]]] = {}
    for ch_id, target in selection.selected.items():
        w = selection.window_for(ch_id)
        if w not in groups:
            groups[w] = []
        groups[w].append(target)

    total = len(groups)
    jobs: list[PlannedJob] = []

    for idx, (window, targets) in enumerate(groups.items(), start=1):
        server_ids = {srv.id for srv, _ in targets}
        if len(server_ids) == 1:
            server_arg: str | None = targets[0][0].id
        else:
            server_arg = None
        channel_args = tuple(ch.id for _, ch in targets)

        out_dir: str | None = None
        zip_file: str | None = None

        if settings.target == "preview":
            out_dir = None
            zip_file = None
        elif settings.target == "folder":
            base = base_path
            if total == 1:
                out_dir = base
            else:
                out_dir = f"{base.rstrip('/\\')}/{idx:02d}-{window.slug()}"
        elif settings.target == "zip":
            base = base_path
            if base.endswith(("/", "\\")):
                base += "discoop-export.zip"
            if not base.lower().endswith(".zip"):
                base += ".zip"
            if total == 1:
                zip_file = base
            else:
                stem = base[:-4]
                zip_file = f"{stem}-{idx:02d}-{window.slug()}.zip"

        is_preview = settings.target == "preview"
        req = MessagesRequest(
            channels=channel_args,
            server=server_arg,
            from_=window.from_,
            to=window.to,
            last=window.last,
            max_messages=window.max_messages,
            include_system=settings.include_system,
            mode=settings.mode,
            delay=settings.delay,
            out_dir=out_dir,
            zip_file=zip_file,
            # Preview = console output of the CLI: --print, --no-files, --max-file-size only work with --out/--zip.
            no_files=not is_preview and not settings.files,
            max_file_size=None if (is_preview or not settings.files) else settings.max_file_size,
            output_format=settings.preview_format if is_preview else "text",
        )
        jobs.append(
            PlannedJob(
                number=idx,
                total=total,
                window=window,
                targets=tuple(targets),
                request=req,
            )
        )

    return jobs


def filter_channels(channels: Sequence[Channel], query: str) -> list[Channel]:
    """Filter channels by search query, supporting fuzzy/diacritic matching and category expansion.

    Matches non-category channels by normalized name, lowercase substring, or their whole ID.
    Includes parent categories of matched channels, and if a category itself matches,
    includes all channels belonging to that category.
    """
    raw_query = query.strip()
    if not raw_query:
        return list(channels)

    q = normalize(raw_query)
    q_lower = raw_query.lower()

    def _matches(name: str, item_id: str) -> bool:
        if raw_query == item_id:
            return True
        if q_lower in name.lower():
            return True
        if q and q in normalize(name):
            return True
        return False

    matching_category_ids = {
        c.id for c in channels if c.type == CATEGORY and _matches(c.name, c.id)
    }

    matched_channel_ids = {
        c.id
        for c in channels
        if c.type != CATEGORY
        and (c.parent_id in matching_category_ids or _matches(c.name, c.id))
    }

    needed_category_ids = matching_category_ids | {
        c.parent_id
        for c in channels
        if c.id in matched_channel_ids and c.parent_id is not None
    }

    return [
        c
        for c in channels
        if (c.id in needed_category_ids if c.type == CATEGORY else c.id in matched_channel_ids)
    ]
