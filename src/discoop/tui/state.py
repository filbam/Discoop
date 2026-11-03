"""State management, selection models, and export job planning for the discoop TUI.

Pure Python, decoupled from Textual widgets for fast startup and testability.
"""

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
import shlex
from typing import Any

from discoop.attachments import safe_name
from discoop.models import CATEGORY, Channel, MESSAGE_TYPES, Server
from discoop.resolve import normalize

try:
    from discoop.service import MessagesRequest  # type: ignore[import-untyped,import-not-found]
except (ImportError, AttributeError):

    @dataclass
    class MessagesRequest:  # type: ignore[no-redef]
        """Parameters for running the messages export command/service."""

        channels: tuple[str, ...]
        server: str | None = None
        from_: str | None = None
        to: str | None = None
        last: int | None = None
        max_messages: int = 5000
        include_system: bool = False
        mode: str = "safe"
        delay: float | None = None
        out_dir: str | None = None
        zip_file: str | None = None
        print_messages: bool = False
        no_files: bool = False
        max_file_size: float | None = None
        output_format: str = "text"

        def to_argv(self) -> list[str]:
            argv = ["discoop", "messages"]
            for ch in self.channels:
                argv.extend(["-c", ch])
            if self.server:
                argv.extend(["-s", self.server])
            if self.from_ is not None:
                argv.extend(["--from", self.from_])
            if self.to is not None:
                argv.extend(["--to", self.to])
            if self.last is not None:
                argv.extend(["--last", str(self.last)])
            if self.output_format and self.output_format != "text":
                argv.extend(["--format", self.output_format])
            if self.include_system:
                argv.append("--include-system")
            if self.max_messages != 5000:
                argv.extend(["--max-messages", str(self.max_messages)])
            if self.mode == "fast":
                argv.append("--fast")
            elif self.mode == "safe":
                argv.append("--safe")
            if self.delay is not None:
                argv.extend(["--delay", str(self.delay)])
            if self.out_dir is not None:
                argv.extend(["--out", self.out_dir])
            if self.zip_file is not None:
                argv.extend(["--zip", self.zip_file])
            if self.print_messages:
                argv.append("--print")
            if self.no_files:
                argv.append("--no-files")
            if self.max_file_size is not None:
                argv.extend(["--max-file-size", str(self.max_file_size)])
            return argv

        def to_command_str(self) -> str:
            return shlex.join(self.to_argv())


@dataclass(frozen=True)
class WindowSpec:
    """Time and count boundaries for downloading channel messages."""

    from_: str | None = "7d"
    to: str | None = None
    last: int | None = None
    max_messages: int = 5000

    def slug(self) -> str:
        """Filesystem-safe short slug describing the window."""
        if self.last is not None and self.from_ is None and self.to is None:
            raw = f"last-{self.last}"
            return safe_name(raw, raw or "window", max_chars=40, max_bytes=80)
        parts = [self.from_ or "24h"]
        if self.to is not None and self.to != "now":
            parts.append(self.to)
        if self.last is not None:
            parts.append(f"last-{self.last}")
        raw = "_".join(parts)
        return safe_name(raw, raw or "window", max_chars=40, max_bytes=80)

    def label(self) -> str:
        """Human-readable summary of the window."""
        if self.last is not None and self.from_ is None and self.to is None:
            return f"last {self.last}"
        start = self.from_ or "24h"
        end = self.to or "now"
        base = f"{start} → {end}"
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
    path: str = "exports/discoop-export"
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


def plan_jobs(selection: SelectionState, settings: ExportSettings) -> list[PlannedJob]:
    """Group selected channels by identical WindowSpec and construct PlannedJobs."""
    if not selection.selected:
        return []

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
            base = settings.path.strip() or "exports/discoop-export"
            if total == 1:
                out_dir = base
            else:
                out_dir = f"{base.rstrip('/\\')}/{idx:02d}-{window.slug()}"
        elif settings.target == "zip":
            base = settings.path.strip() or "exports/discoop-export.zip"
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
            print_messages=is_preview,
            no_files=True if is_preview else (not settings.files),
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

    Matches non-category channels by normalized name, lowercase substring, or ID.
    Includes parent categories of matched channels, and if a category itself matches,
    includes all channels belonging to that category.
    """
    raw_query = query.strip()
    if not raw_query:
        return list(channels)

    q = normalize(raw_query)
    q_lower = raw_query.lower()

    def _matches(name: str, item_id: str) -> bool:
        if raw_query in item_id:
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
