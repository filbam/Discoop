"""Service layer: core orchestration logic for CLI and TUI."""

from __future__ import annotations

import shlex
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime, tzinfo
from pathlib import Path

import httpx

from discoop import export
from discoop.attachments import Progress as DownloadProgress, cdn_client
from discoop.config import Config
from discoop.directory import Directory
from discoop.errors import DiscoopError, ExitCode
from discoop.models import CATEGORY, MESSAGE_TYPES, Channel, ChannelMessages, Server
from discoop.normalize import Normalizer, known_users
from discoop.render import Query
from discoop.resolve import is_pattern
from discoop.scrape import fetch_messages
from discoop.snowflake import parse_window, to_local, to_time, utc_now

DEFAULT_MAX_MESSAGES = 5000
DEFAULT_MAX_FILE_SIZE_MB = 50.0
MB = 1024 * 1024
FORMATS = ("text", "md", "json", "jsonl")


class Cancelled(Exception):
    """Raised when the user cancels a running operation in TUI."""


@dataclass(frozen=True)
class MessagesRequest:
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
        """Return equivalent CLI arguments starting with 'messages'."""
        argv = ["messages"]
        if self.server:
            argv.extend(["-s", self.server])
        for ch in self.channels:
            argv.extend(["-c", ch])
        if self.from_ is not None:
            argv.extend(["--from", self.from_])
        if self.to is not None:
            argv.extend(["--to", self.to])
        if self.last is not None:
            argv.extend(["--last", str(self.last)])
        if self.max_messages != 5000:
            argv.extend(["--max-messages", str(self.max_messages)])
        if self.include_system:
            argv.append("--include-system")
        if self.mode == "safe":
            argv.append("--safe")
        elif self.mode == "fast":
            argv.append("--fast")
        if self.delay is not None:
            argv.extend(["--delay", f"{self.delay:g}"])
        if self.out_dir is not None:
            argv.extend(["--out", self.out_dir])
        if self.zip_file is not None:
            argv.extend(["--zip", self.zip_file])
        if self.print_messages:
            argv.append("--print")
        if self.no_files:
            argv.append("--no-files")
        if self.max_file_size is not None:
            argv.extend(["--max-file-size", f"{self.max_file_size:g}"])
        if self.output_format != "text":
            argv.extend(["--format", self.output_format])
        return argv

    def to_command_str(self) -> str:
        """Return human-readable `discoop messages ...` command string with proper quoting."""
        return shlex.join(["discoop", *self.to_argv()])


class Events:
    def __init__(self, downloads: DownloadProgress | None = None) -> None:
        self.downloads: DownloadProgress = downloads or DownloadProgress()

    def channel_start(self, index: int, total: int, server: Server, channel: Channel) -> None:
        pass

    def page(self, kept: int, oldest_id: int) -> None:
        pass

    def pause(self, seconds: float, reason: str) -> None:
        pass

    def channel_done(self, result: ChannelMessages) -> None:
        pass

    def skipped(self, error: DiscoopError) -> None:
        pass

    def warning(self, text: str) -> None:
        pass

    def note(self, text: str) -> None:
        pass


@dataclass
class MessagesOutcome:
    results: list[ChannelMessages]
    skipped: list[DiscoopError]
    exported: export.Exported | None
    query: Query


def list_servers(directory: Directory, refresh: bool = False) -> list[Server]:
    return directory.servers(refresh=refresh)


def list_channels(directory: Directory, server: Server, refresh: bool = False) -> list[Channel]:
    return directory.channels(server, refresh=refresh)


def load_all(
    directory: Directory,
    on_server: Callable[[int, int, Server], None] | None = None,
) -> list[tuple[Server, list[Channel]]]:
    servers = directory.servers(refresh=True)
    result: list[tuple[Server, list[Channel]]] = []
    total = len(servers)
    for i, srv in enumerate(servers):
        if i > 0:
            directory.api().between_channels()
        if on_server is not None:
            on_server(i + 1, total, srv)
        try:
            channels = directory.channels(srv, refresh=True)
        except DiscoopError as e:
            if e.code == ExitCode.NO_ACCESS:
                channels = []
            else:
                raise
        result.append((srv, channels))
    return result


def _unreadable(channel: Channel) -> DiscoopError:
    if channel.type == CATEGORY:
        return DiscoopError(
            ExitCode.BAD_ARGS,
            f"#{channel.name} is a category, not a channel.",
            'List its channels with `discoop channels`, or use a pattern such as -c "isc-*".',
        )
    return DiscoopError(
        ExitCode.BAD_ARGS,
        f"#{channel.name} is a {channel.type_name} channel: discoop cannot read its messages yet.",
        "Forum posts are threads; threads come in a later version.",
    )


def resolve_targets(
    directory: Directory,
    server: str | None,
    queries: Sequence[str],
    default_server: str | None = None,
) -> list[tuple[Server, Channel]]:
    targets: dict[str, tuple[Server, Channel]] = {}
    for raw in queries:
        query = raw.strip()
        if query.isdigit() and server is None:
            found = directory.channel_by_id(query)
            where = directory.server(found.server_id)
            matches = [found]
        else:
            server_name = server or default_server or Config.default().get("default-server")
            if not server_name:
                raise DiscoopError(
                    ExitCode.BAD_ARGS,
                    "No server given.",
                    'Use --server NAME, or set a default: discoop config set default-server "NAME".',
                )
            where = directory.server(server_name)
            matches = directory.find_channels(where, query)
        readable = [c for c in matches if c.type in MESSAGE_TYPES]
        if not is_pattern(query) and not readable:
            raise _unreadable(matches[0])
        if not readable:
            shown = ", ".join("#" + c.name for c in matches[:5])
            raise DiscoopError(
                ExitCode.NOT_FOUND,
                f'"{query}" matches no channel with messages, only: {shown}.',
                "Forums and their posts (threads) come in a later version.",
            )
        for found_channel in readable:
            targets.setdefault(found_channel.id, (where, found_channel))
    return list(targets.values())


def validate_export_target(
    out_dir: str | None,
    zip_file: str | None,
    print_messages: bool,
    no_files: bool,
    max_file_size: float | None,
    export_dir: str | None = None,
) -> tuple[Path, bool] | None:
    if out_dir is not None and zip_file is not None:
        raise DiscoopError(ExitCode.BAD_ARGS, "--out and --zip cannot be used together.", "Choose one of them.")
    raw = out_dir if out_dir is not None else zip_file
    if raw is None:
        given = (("--print", print_messages), ("--no-files", no_files), ("--max-file-size", max_file_size is not None))
        flags = [flag for flag, used in given if used]
        if flags:
            raise DiscoopError(
                ExitCode.BAD_ARGS,
                f"{', '.join(flags)} only work{'s' if len(flags) == 1 else ''} with --out or --zip.",
                "Without them the messages are printed and no files are downloaded.",
            )
        return None
    if max_file_size is not None and max_file_size < 0:
        raise DiscoopError(ExitCode.BAD_ARGS, "--max-file-size cannot be negative.", "Use 0 for no limit.")
    path = Path(raw).expanduser()
    base = export_dir if export_dir is not None else Config.default().get("export-dir")
    if not path.is_absolute() and base:
        path = Path(base) / path
    path = path.resolve()
    as_zip = zip_file is not None
    export.check_target(path, as_zip)
    return path, as_zip


def run_messages(
    request: MessagesRequest,
    *,
    directory: Directory,
    cdn: Callable[[], httpx.Client] = cdn_client,
    now: datetime | None = None,
    tz: tzinfo | None = None,
    events: Events | None = None,
    export_dir: str | None = None,
    default_server: str | None = None,
) -> MessagesOutcome:
    events = events or Events()
    output_format = request.output_format.strip().lower()
    if output_format not in FORMATS:
        raise DiscoopError(ExitCode.BAD_ARGS, f'Unknown format "{request.output_format}".', f"Use one of: {', '.join(FORMATS)}.")
    if request.delay is not None and request.delay < 0:
        raise DiscoopError(ExitCode.BAD_ARGS, "--delay cannot be negative.", "Use seconds, e.g. 1 or 0.5.")
    if request.last is not None and request.last < 1:
        raise DiscoopError(ExitCode.BAD_ARGS, "--last must be at least 1.")
    if request.max_messages < 1:
        raise DiscoopError(ExitCode.BAD_ARGS, "--max-messages must be at least 1.")

    export_to = validate_export_target(
        request.out_dir,
        request.zip_file,
        request.print_messages,
        request.no_files,
        request.max_file_size,
        export_dir=export_dir,
    )

    current_now = now if now is not None else utc_now()
    window = parse_window(request.from_, request.to, now=current_now, tz=tz, whole_history=request.last is not None)
    limit = request.max_messages if request.last is None else min(request.last, request.max_messages)
    query = Query(window, request.last, request.max_messages, request.include_system, mode=request.mode)

    targets = resolve_targets(directory, request.server, request.channels, default_server=default_server)

    results: list[ChannelMessages] = []
    skipped: list[DiscoopError] = []
    total = len(targets)
    old_on_pause = getattr(directory.api(), "on_pause", None)
    directory.api().on_pause = lambda s, reason: events.pause(s, reason)
    try:
        for i, (target_server, target) in enumerate(targets, 1):
            if i > 1:
                directory.api().between_channels()
            events.channel_start(i, total, target_server, target)
            label = f"#{target.name} ({target.id}) in {target_server.name}"
            try:
                fetched = fetch_messages(
                    directory.api(),
                    target.id,
                    window,
                    label=label,
                    limit=limit,
                    include_system=request.include_system,
                    on_page=lambda count, oldest_id: events.page(count, oldest_id),
                )
            except DiscoopError as e:
                if total == 1 or e.code not in (ExitCode.NO_ACCESS, ExitCode.NOT_FOUND):
                    raise
                events.skipped(e)
                skipped.append(e)
                continue

            names = {c.id: c.name for c in directory.channels(target_server)}
            normalizer = Normalizer(names, known_users(fetched.messages), tz)
            truncated = fetched.hit_limit and (request.last is None or request.max_messages < request.last)
            if truncated:
                events.warning(
                    f"Stopped at --max-messages {request.max_messages} in {label}: older messages in the window"
                    " were not fetched. Raise --max-messages or use a later --from."
                )
            if fetched.nothing_before_end:
                time_label = to_local(window.end, tz).strftime("%Y-%m-%d %H:%M")
                events.note(
                    f"Discord returned no messages for {label} before {time_label}. Either there are"
                    " none, or you lack the Read Message History permission there."
                )
            items = tuple(normalizer.message(m) for m in fetched.messages)
            channel_result = ChannelMessages(target_server, target, items, truncated)
            events.channel_done(channel_result)
            results.append(channel_result)
    finally:
        directory.api().on_pause = old_on_pause

    if not results and skipped:
        raise DiscoopError(skipped[0].code, "None of the channels could be read.", skipped[0].hint)

    exported: export.Exported | None = None
    if export_to is not None:
        limit_mb = DEFAULT_MAX_FILE_SIZE_MB if request.max_file_size is None else request.max_file_size
        options = export.Options(
            files=not request.no_files,
            max_file_size=int(limit_mb * MB) if limit_mb > 0 else None,
        )
        path, as_zip = export_to
        with cdn() as cdn_client_inst:
            exported = export.export(
                path,
                as_zip,
                results,
                query,
                api=directory.api(),
                cdn=cdn_client_inst,
                options=options,
                created=current_now,
                tz=tz,
                now=lambda: current_now.timestamp(),
                progress=events.downloads,
            )

    return MessagesOutcome(results=results, skipped=skipped, exported=exported, query=query)
