"""Service layer: core orchestration logic for CLI and TUI."""

from __future__ import annotations

import contextlib
import shlex
import shutil
import zipfile
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, tzinfo
from pathlib import Path

import httpx

from discoop import export, syncstate, tokens
from discoop.api import DiscordAPI
from discoop.attachments import FAILED, Progress as DownloadProgress, cdn_client
from discoop.config import Config
from discoop.directory import Directory
from discoop.errors import DiscoopError, ExitCode
from discoop.models import CATEGORY, FORUM_TYPES, MESSAGE_TYPES, Channel, ChannelMessages, Message, Server, Thread
from discoop.normalize import Normalizer, known_users
from discoop.render import Query
from discoop.resolve import is_pattern
from discoop.scrape import fetch_messages
from discoop.snowflake import DEFAULT_SPAN, Window, from_time, parse_window, to_local, to_time, utc_now
from discoop.threads import FetchedThreads, is_thread_container

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
    threads: bool = True
    since_last: bool = False
    max_tokens: int | None = None

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
        if not self.threads:
            argv.append("--no-threads")
        if self.since_last:
            argv.append("--since-last")
        if self.max_tokens is not None:
            argv.extend(["--max-tokens", str(self.max_tokens)])
        return argv

    def to_command_str(self) -> str:
        """Return human-readable `discoop messages ...` command string with proper quoting."""
        return shlex.join(["discoop", *self.to_argv()])


class Events:
    def __init__(self, downloads: DownloadProgress | None = None) -> None:
        self.downloads: DownloadProgress = downloads or DownloadProgress()

    def channel_start(self, index: int, total: int, server: Server, channel: Channel) -> None:
        pass

    def thread(self, index: int, total: int, channel: Channel, thread: Thread) -> None:
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

    def resumed(self, done: int, total: int) -> None:
        """An unfinished export of the same request is continued: `done` of `total` channels are saved already."""

    def interrupted(self, saved: int, total: int, path: Path) -> None:
        """The run ended early (cancelled, Ctrl+C, an error). `saved` of `total` channels wait in `path` (the
        staging folder `<target>.partial`); the same request, run again, continues there. Called just before the
        exception goes on, and only if something worth continuing from was saved."""


@dataclass
class MessagesOutcome:
    """What `run_messages` did. `results` are the channels fetched by THIS run; for an export that continued an
    earlier run, `exported.manifest` has the totals of the whole export (see the `*_count` properties)."""

    results: list[ChannelMessages]
    skipped: list[DiscoopError]
    exported: export.Exported | None
    query: Query
    resumed: int = 0  # channels taken over from an unfinished export of the same request (not fetched again)
    total: int = 0  # channels the request asked for
    skipped_channels: list[Channel] = field(default_factory=list)  # the channels of `skipped`, in the same order
    thread_problems: int = 0
    unchanged: int = 0
    tokens_estimate: int | None = None

    @property
    def partial(self) -> bool:
        """True if something asked for is missing: a channel was skipped (no access, not found) or a file failed.
        Files left out on purpose (`--max-file-size`, `--no-files`) do not count. The CLI exits with `ExitCode.PARTIAL`."""
        return bool(self.skipped) or bool(self.thread_problems) or (self.exported is not None and self.exported.partial)

    @property
    def channel_count(self) -> int:
        counts = self._counts()
        return int(counts["channels"]) if counts else len(self.results)

    @property
    def message_count(self) -> int:
        counts = self._counts()
        if counts:
            return int(counts["messages"]) + int(counts.get("thread_messages", 0))
        return sum(result.total_messages for result in self.results)

    @property
    def truncated_count(self) -> int:
        """Channels cut short by --max-messages."""
        if self.exported is not None and "channels" in self.exported.manifest:
            return sum(1 for item in self.exported.manifest["channels"] if item.get("truncated"))
        return sum(1 for result in self.results if result.truncated)

    def _counts(self) -> dict[str, int]:
        if self.exported is None:
            return {}
        counts = self.exported.manifest.get("counts")
        return dict(counts) if counts and "channels" in counts and "messages" in counts else {}


def list_servers(directory: Directory, refresh: bool = False) -> list[Server]:
    return directory.servers(refresh=refresh)


def list_channels(directory: Directory, server: Server, refresh: bool = False) -> list[Channel]:
    return directory.channels(server, refresh=refresh)


def list_threads(
    directory: Directory,
    channel: Channel,
    window: Window,
    refresh: bool = False,
) -> FetchedThreads:
    if not is_thread_container(channel.type):
        raise DiscoopError(
            ExitCode.BAD_ARGS,
            f"#{channel.name} is a {channel.type_name} channel: it cannot have threads.",
            "Only text, announcement, forum and media channels can have threads.",
        )
    return directory.threads(channel, window, refresh=refresh)


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
        f"#{channel.name} is a {channel.type_name} channel: discoop cannot read its messages.",
        "Check the channel type or list channels with `discoop channels`.",
    )


def resolve_targets(
    directory: Directory,
    server: str | None,
    queries: Sequence[str],
    default_server: str | None = None,
    refresh: bool = False,
) -> list[tuple[Server, Channel]]:
    targets: dict[str, tuple[Server, Channel]] = {}
    refreshed_servers: set[str] = set()
    for raw in queries:
        query = raw.strip()
        if query.isdigit() and server is None:
            found = directory.channel_by_id(query)
            where = directory.server(found.server_id)
            if refresh and where.id not in refreshed_servers:
                directory.channels(where, refresh=True)
                refreshed_servers.add(where.id)
                found = directory.channel_by_id(query)
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
            if refresh and where.id not in refreshed_servers:
                directory.channels(where, refresh=True)
                refreshed_servers.add(where.id)
            matches = directory.find_channels(where, query)
        readable = [c for c in matches if c.type in MESSAGE_TYPES or c.type in FORUM_TYPES]
        if not is_pattern(query) and not readable:
            raise _unreadable(matches[0])
        if not readable:
            shown = ", ".join("#" + c.name for c in matches[:5])
            raise DiscoopError(
                ExitCode.NOT_FOUND,
                f'"{query}" matches no channel with messages, only: {shown}.',
                "Check the name or list channels with `discoop channels`.",
            )
        for found_channel in readable:
            targets.setdefault(found_channel.id, (where, found_channel))
    return list(targets.values())


def _no_newer_message(target: Channel, channel_sync: syncstate.ChannelSync | None) -> bool:
    """True if Discord's `last_message_id` of the channel is not newer than the saved one (so nothing was posted in the
    channel itself since the last sync). False if there is no state or the channel has no `last_message_id`."""
    if channel_sync is None or not target.last_message_id:
        return False
    return int(target.last_message_id) <= int(channel_sync.last_message_id)


def _is_channel_unchanged(
    target: Channel,
    channel_sync: syncstate.ChannelSync | None,
    threads_enabled: bool,
) -> bool:
    """True if `--since-last` leaves the channel out altogether (no request): nothing new in it, and it has no
    threads to look at (a channel that cannot have threads, or `--no-threads`). A forum is never left out."""
    if target.type in FORUM_TYPES:
        return False
    if is_thread_container(target.type) and threads_enabled:
        return False
    return _no_newer_message(target, channel_sync)


def _is_own_unchanged(
    target: Channel,
    channel_sync: syncstate.ChannelSync | None,
    threads_enabled: bool,
) -> bool:
    """True if `--since-last` skips the messages of the channel itself but still lists its threads: a text or
    announcement channel with threads on and nothing newer in it. A forum has no messages of its own and its
    `last_message_id` points at its newest post, so it never qualifies. [PREDPOKLAD] `last_message_id` of a text channel
    is reliable (docs/decisions/0020-since-last.md)."""
    if target.type in FORUM_TYPES or not threads_enabled or not is_thread_container(target.type):
        return False
    return _no_newer_message(target, channel_sync)


def _existing_ancestor(path: Path) -> Path:
    check_dir = path.resolve()
    while not check_dir.exists():
        parent = check_dir.parent
        if parent == check_dir:
            break
        check_dir = parent
    return check_dir


def _check_disk_space(writer: export.ExportWriter, result: ChannelMessages, target_path: Path) -> None:
    """Refuse to download the files of `result` if less than 50 MB would be left on the disk afterwards."""
    needed_bytes = writer.bytes_to_download(result)
    if needed_bytes == 0:
        return

    usage = shutil.disk_usage(_existing_ancestor(target_path))
    free_bytes = usage.free
    margin = 50 * 1024 * 1024
    if free_bytes - needed_bytes < margin:
        need_mb = max(1, round(needed_bytes / (1024 * 1024)))
        free_mb = round(free_bytes / (1024 * 1024))
        raise DiscoopError(
            ExitCode.ERROR,
            f"Not enough free space: need about {need_mb} MB, {free_mb} MB free.",
            "Free up disk space, use --no-files, or lower --max-file-size.",
        )


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


def _query_for(request: MessagesRequest, now: datetime, tz: tzinfo | None) -> tuple[Window, int, Query]:
    """The window, the number of messages to fetch per channel and the query of a request, with `now` as "now"."""
    window = parse_window(request.from_, request.to, now=now, tz=tz, whole_history=request.last is not None)
    limit = request.max_messages if request.last is None else min(request.last, request.max_messages)
    query = Query(window, request.last, request.max_messages, request.include_system, mode=request.mode)
    return window, limit, query


def _export_options(request: MessagesRequest) -> export.Options:
    limit_mb = DEFAULT_MAX_FILE_SIZE_MB if request.max_file_size is None else request.max_file_size
    return export.Options(
        files=not request.no_files,
        max_file_size=int(limit_mb * MB) if limit_mb > 0 else None,
        threads=request.threads,
        since_last=request.since_last,
    )


def _find_resume(
    path: Path,
    channels: Sequence[Channel],
    request: MessagesRequest,
    options: export.Options,
    now: datetime,
    tz: tzinfo | None,
) -> tuple[export.Resume, datetime, tuple[Window, int, Query]] | None:
    """The unfinished export in `path` that this request continues, with the "now" its window was made with.

    A relative window (`--from 1d`) ends at "now", so it only matches the unfinished export if it is resolved with the
    "now" of the run that began it (`Resume.created`). If that does not match either, the export is of another request.
    """
    unfinished = export.find_unfinished(path)
    if unfinished is None:
        return None
    for at in dict.fromkeys((unfinished.created, now)):
        try:
            planned = _query_for(request, at, tz)
        except DiscoopError:
            continue
        resume = export.find_unfinished(path, export.request_fingerprint(channels, planned[2], options, tz))
        if resume is not None:
            return resume, at, planned
    return None


_UNREADABLE = (ExitCode.NO_ACCESS, ExitCode.NOT_FOUND)  # a channel or thread the account cannot read, or that is gone


def _check_request(request: MessagesRequest) -> None:
    """Refuse a request that cannot be run, before anything is asked of Discord."""
    output_format = request.output_format.strip().lower()
    if output_format not in FORMATS:
        raise DiscoopError(ExitCode.BAD_ARGS, f'Unknown format "{request.output_format}".', f"Use one of: {', '.join(FORMATS)}.")
    if request.delay is not None and request.delay < 0:
        raise DiscoopError(ExitCode.BAD_ARGS, "--delay cannot be negative.", "Use seconds, e.g. 1 or 0.5.")
    if request.last is not None and request.last < 1:
        raise DiscoopError(ExitCode.BAD_ARGS, "--last must be at least 1.")
    if request.max_messages < 1:
        raise DiscoopError(ExitCode.BAD_ARGS, "--max-messages must be at least 1.")
    if request.since_last and (request.from_ is not None or request.to is not None or request.last is not None):
        raise DiscoopError(
            ExitCode.BAD_ARGS,
            "--since-last cannot be combined with --from, --to or --last.",
            "Drop --since-last to use a time window, or remove the time options.",
        )
    if request.max_tokens is not None:
        if request.max_tokens < 1:
            raise DiscoopError(ExitCode.BAD_ARGS, "--max-tokens must be at least 1.")
        if request.out_dir is None and request.zip_file is None:
            raise DiscoopError(
                ExitCode.BAD_ARGS,
                "--max-tokens only works with --out or --zip.",
                "Export with --out DIR or --zip FILE, which gets the parts/ too.",
            )


def _refuse_forum_without_threads(request: MessagesRequest, targets: Sequence[tuple[Server, Channel]]) -> None:
    if request.threads:
        return
    for _, target in targets:
        if target.type in FORUM_TYPES:
            raise DiscoopError(
                ExitCode.BAD_ARGS,
                f"#{target.name} is a {target.type_name} channel: it only has threads.",
                "A forum only has threads: drop --no-threads.",
            )


def _refuse_print_on_resume(saved: int, total: int, resume: export.Resume) -> None:
    raise DiscoopError(
        ExitCode.BAD_ARGS,
        f"--print cannot be used while continuing an unfinished export: {saved} of {total} channels were saved"
        " by the run that was interrupted, so their messages are not in memory.",
        f"Run again without --print to finish the export, or delete {resume.staging} to start over.",
    )


def _state_id(messages: Sequence[Message], saved_id: str | None, last_id: str | None, now: datetime) -> str:
    """The message ID `--since-last` saves for a channel or thread that was fetched whole.

    The newest fetched message, unless the saved ID is newer (the state never goes back). Without messages: the newest
    of the saved ID and the `last_message_id` Discord gives, else a snowflake of "now" (an empty channel).
    """
    if messages:
        newest = str(max(int(m.id) for m in messages))
        return saved_id if saved_id is not None and int(saved_id) > int(newest) else newest
    known = [int(known_id) for known_id in (saved_id, last_id) if known_id]
    return str(max(known)) if known else str(from_time(now))


def _estimate_tokens(exported: export.Exported | None) -> int | None:
    """The estimated tokens of messages.md in a finished export (folder or zip); None if there is none to read."""
    if exported is None:
        return None
    try:
        if exported.path.is_dir():
            return tokens.estimate_tokens((exported.path / "messages.md").read_text(encoding="utf-8"))
        with zipfile.ZipFile(exported.path) as archive:
            return tokens.estimate_tokens(archive.read("messages.md").decode("utf-8"))
    except (OSError, KeyError, ValueError, zipfile.BadZipFile):
        return None


@dataclass
class _Threads:
    """The threads of one channel as fetched, and whether something about them is missing."""

    results: list[ChannelMessages] = field(default_factory=list)
    problem: bool = False  # the list or a thread could not be read, or the list may be incomplete


@dataclass
class _Run:
    """One `run_messages` call: the settings its steps share, and what they tally up for the outcome."""

    request: MessagesRequest
    directory: Directory
    events: Events
    tz: tzinfo | None
    now: datetime
    window: Window  # the window of the request (`--since-last` makes one per channel and thread)
    limit: int  # messages to fetch per channel and per thread
    query: Query
    options: export.Options
    created: datetime  # the "now" of the window; a continued export keeps the one of its first run
    total: int  # channels the request asked for
    account_sync: dict[str, syncstate.ChannelSync]
    export_to: tuple[Path, bool] | None  # the target and whether it is a zip; None: no export
    resume: export.Resume | None  # the unfinished export that is continued
    saved: set[str]  # IDs of the channels it has finished
    writer: export.ExportWriter | None = None
    results: list[ChannelMessages] = field(default_factory=list)
    skipped: list[DiscoopError] = field(default_factory=list)
    skipped_channels: list[Channel] = field(default_factory=list)
    thread_problems: int = 0
    unchanged: int = 0
    new_sync_updates: dict[str, syncstate.ChannelSync] = field(default_factory=dict)

    @property
    def api(self) -> DiscordAPI:
        return self.directory.api()

    # -- the export

    def open_export(
        self, stack: contextlib.ExitStack, cdn: Callable[[], httpx.Client], channels: Sequence[Channel]
    ) -> None:
        """Open the writer of the export of `channels`, and tell that an unfinished one is continued. The writer is in
        `stack`: leaving it by an exception keeps the staging folder for the next run."""
        assert self.export_to is not None
        path, as_zip = self.export_to
        events, request = self.events, self.request
        client = stack.enter_context(cdn())
        writer = self.writer = export.ExportWriter(
            path,
            as_zip,
            query=self.query,
            options=self.options,
            api=self.api,
            cdn=client,
            created=self.created,
            tz=self.tz,
            now=lambda: self.now.timestamp(),
            progress=events.downloads,
            max_tokens=request.max_tokens,
            on_warning=events.warning,
        )
        stack.enter_context(writer)
        writer.open(channels, self.resume)
        if self.saved:
            events.resumed(len(self.saved), self.total)
            if request.since_last:
                events.note(
                    "The channels saved by the interrupted run keep their old sync state, so the next"
                    " --since-last fetches them again (duplicates, but nothing is lost)."
                )

    # -- the channels

    def fetch_channels(self, targets: Sequence[tuple[Server, Channel]]) -> None:
        """Fetch every target that is not in `saved` (taken over from an unfinished export)."""
        since_last = self.request.since_last
        fetching = False
        for index, (server, target) in enumerate(targets, 1):
            if target.id in self.saved:
                continue
            channel_sync = self.account_sync.get(target.id) if since_last else None
            if since_last and _is_channel_unchanged(target, channel_sync, self.request.threads):
                self.events.note(f"#{target.name} is unchanged since last sync: skipping.")
                self.unchanged += 1
                continue
            if fetching:
                self.api.between_channels()
            fetching = True
            self.events.channel_start(index, self.total, server, target)
            self.fetch_channel(server, target, channel_sync)

    def fetch_channel(self, server: Server, target: Channel, channel_sync: syncstate.ChannelSync | None) -> None:
        """Fetch a channel and its threads and hand them on as one unit: to the writer (an export), the results."""
        label = f"#{target.name} ({target.id}) in {server.name}"
        names = {c.id: c.name for c in self.directory.channels(server)}
        window, parent_updated = self._channel_window(target, channel_sync)
        own = self._fetch_own(target, channel_sync, window, label, names)
        if own is None:
            return  # skipped (no access, not found)
        items, truncated = own
        threads = self._fetch_threads(server, target, names, window, parent_updated)
        if threads is None:
            return  # a forum whose threads cannot be read: skipped
        result = ChannelMessages(server, target, items, truncated, threads=tuple(threads.results))
        if self.writer is not None and self.export_to is not None:
            _check_disk_space(self.writer, result, self.export_to[0])
            self.writer.add_channel(result)  # downloads its files and saves it: a crash keeps it
        self.events.channel_done(result)
        self.results.append(result)
        if self.request.since_last:
            self._advance_sync_state(target, channel_sync, result, threads.problem)

    def _fetch_own(
        self,
        target: Channel,
        channel_sync: syncstate.ChannelSync | None,
        window: Window,
        label: str,
        names: dict[str, str],
    ) -> tuple[tuple[Message, ...], bool] | None:
        """The messages posted in the channel itself and whether they were cut short; None if the channel is skipped.

        A forum has none, and neither does a channel `--since-last` sees nothing new in (its threads are still read).
        """
        if target.type in FORUM_TYPES:
            return (), False
        if self.request.since_last and _is_own_unchanged(target, channel_sync, self.request.threads):
            self.events.note(
                f"#{target.name}: its own messages are unchanged since last sync, fetching only its threads."
            )
            return (), False
        try:
            return self._read(target.id, window, label, names)
        except DiscoopError as e:
            if self.total == 1 or e.code not in _UNREADABLE:
                raise
            self._skip(e, target)
            return None

    def _skip(self, error: DiscoopError, channel: Channel) -> None:
        self.events.skipped(error)
        self.skipped.append(error)
        self.skipped_channels.append(channel)

    def _read(
        self,
        channel_id: str,
        window: Window,
        label: str,
        names: dict[str, str],
        *,
        quiet_when_empty: bool = False,
    ) -> tuple[tuple[Message, ...], bool]:
        """Fetch and normalize the messages of a channel or thread; tells about a cut-short window.

        Returns the messages and whether `--max-messages` stopped the fetching. `quiet_when_empty`: a place without
        messages in the window is left out without a word (a thread).
        """
        request, events = self.request, self.events
        fetched = fetch_messages(
            self.api,
            channel_id,
            window,
            label=label,
            limit=self.limit,
            include_system=request.include_system,
            on_page=lambda count, oldest_id: events.page(count, oldest_id),
        )
        if quiet_when_empty and not fetched.messages:
            return (), False
        truncated = fetched.hit_limit and (request.last is None or request.max_messages < request.last)
        if truncated:
            events.warning(
                f"Stopped at --max-messages {request.max_messages} in {label}: older messages in the window"
                " were not fetched. Raise --max-messages or use a later --from."
            )
        if fetched.nothing_before_end:
            time_label = to_local(window.end, self.tz).strftime("%Y-%m-%d %H:%M")
            events.note(
                f"Discord returned no messages for {label} before {time_label}. Either there are"
                " none, or you lack the Read Message History permission there."
            )
        normalizer = Normalizer(names, known_users(fetched.messages), self.tz)
        return tuple(normalizer.message(m) for m in fetched.messages), truncated

    # -- the windows

    def _channel_window(
        self, target: Channel, channel_sync: syncstate.ChannelSync | None
    ) -> tuple[Window, datetime | None]:
        """The window of a channel, and when its sync state was updated (None without one, or without `--since-last`).

        `--since-last`: the messages with an ID above the saved one (the boundary is exclusive), up to now; a channel
        without state gets the default window.
        """
        if not self.request.since_last:
            return self.window, None
        if channel_sync is not None:
            saved_id = int(channel_sync.last_message_id)
            window = Window(to_time(saved_id), self.now, min_id=saved_id + 1)
            return window, datetime.fromisoformat(channel_sync.updated)
        self.events.note(f"No previous sync state for #{target.name}: fetching the last 24 hours.")
        return Window(self.now - DEFAULT_SPAN, self.now), None

    def _search_window(self, channel_window: Window, parent_updated: datetime | None) -> Window:
        """The window in which the threads of a channel are looked for: active in it (`--since-last`: since the
        channel's sync state was updated)."""
        if not self.request.since_last:
            return channel_window
        return Window(parent_updated if parent_updated is not None else channel_window.start, self.now)

    def _thread_window(self, thread: Thread, channel_window: Window, parent_updated: datetime | None) -> Window:
        """The window of a thread's messages: that of the channel; `--since-last`: after the thread's own saved ID,
        else since the channel's sync state was updated, else the default window."""
        if not self.request.since_last:
            return channel_window
        thread_sync = self.account_sync.get(thread.id)
        if thread_sync is not None:
            saved_id = int(thread_sync.last_message_id)
            return Window(to_time(saved_id), self.now, min_id=saved_id + 1)
        if parent_updated is not None:
            return Window(parent_updated, self.now)
        return Window(self.now - DEFAULT_SPAN, self.now)

    # -- the threads

    def _fetch_threads(
        self,
        server: Server,
        target: Channel,
        names: dict[str, str],
        channel_window: Window,
        parent_updated: datetime | None,
    ) -> _Threads | None:
        """The threads of a channel that has some, oldest first; None if the channel (a forum) is skipped.

        A list that cannot be read, a thread that cannot be read and a list that may be incomplete are warned about,
        counted as problems and make the outcome partial; the channel's own messages are kept.
        """
        if not (self.request.threads and is_thread_container(target.type)):
            return _Threads()
        try:
            listed = self.directory.threads(
                target, self._search_window(channel_window, parent_updated), refresh=True
            )
        except DiscoopError as e:
            if target.type in FORUM_TYPES:
                if self.total == 1 or e.code not in _UNREADABLE:
                    raise
                self._skip(e, target)
                return None
            if e.code not in _UNREADABLE:
                raise
            self.events.warning(f"Could not list threads of #{target.name}: {e.message}")
            self.thread_problems += 1
            return _Threads(problem=True)

        found = _Threads()
        if listed.problem:
            found.problem = True
            self.events.warning(f"Thread list of #{target.name} may be incomplete: {listed.problem}.")
            self.thread_problems += 1
        ordered = sorted(listed.threads, key=lambda t: (t.created, int(t.id) if t.id.isdigit() else 0))
        for number, thread in enumerate(ordered, 1):
            self.events.thread(number, len(ordered), target, thread)
            label = f'thread "{thread.name}" ({thread.id}) in #{target.name}'
            window = self._thread_window(thread, channel_window, parent_updated)
            try:
                items, truncated = self._read(thread.id, window, label, names, quiet_when_empty=True)
            except DiscoopError as e:
                found.problem = True
                if e.code not in _UNREADABLE:
                    raise
                self.events.warning(f"Could not read {label}: {e.message}")
                self.thread_problems += 1
                continue
            if items:  # a thread without messages in the window is left out
                found.results.append(
                    ChannelMessages(server, thread.as_channel(server.id), items, truncated, thread=thread)
                )
        return found

    # -- the end

    def finish(self, user_id: str | None) -> export.Exported | None:
        """Publish the export (if there is one) and save the sync state: the run went through without an error.

        A run in which nothing could be read fails (channels taken over from an unfinished export count as read). The
        skipped channels are recorded only now, so a run that read nothing leaves no staging folder behind and a
        channel skipped before a crash is simply tried again by the next run.
        """
        if not self.results and not self.saved and not self.unchanged and self.skipped:
            raise DiscoopError(self.skipped[0].code, "None of the channels could be read.", self.skipped[0].hint)
        exported = None
        if self.writer is not None:
            for channel, error in zip(self.skipped_channels, self.skipped):
                self.writer.add_skipped(channel, export.skip_reason(error.code))
            exported = self.writer.close(complete=True)
        if self.request.since_last and self.new_sync_updates and user_id is not None:
            syncstate.update_account_channels(user_id, self.new_sync_updates)
        return exported

    # -- the sync state

    def _advance_sync_state(
        self,
        target: Channel,
        channel_sync: syncstate.ChannelSync | None,
        result: ChannelMessages,
        thread_problem: bool,
    ) -> None:
        """Collect the new sync state of a finished channel and its threads (saved when the whole run is done).

        Only a channel that was fetched whole counts: not cut short, no thread problem, no failed file. A thread that
        was cut short stays as it was.
        """
        if result.truncated or thread_problem or self._attachment_failed(target):
            return
        iso_now = (self.now if self.now.tzinfo else self.now.replace(tzinfo=UTC)).astimezone(UTC).isoformat()
        saved_id = channel_sync.last_message_id if channel_sync is not None else None
        new_id = _state_id(result.messages, saved_id, target.last_message_id, self.now)
        self.new_sync_updates[target.id] = syncstate.ChannelSync(new_id, iso_now)
        for nested in result.threads:
            if nested.truncated:
                continue
            thread_sync = self.account_sync.get(nested.channel.id)
            last_id = nested.thread.last_message_id if nested.thread else None
            thread_id = _state_id(
                nested.messages, thread_sync.last_message_id if thread_sync is not None else None, last_id, self.now
            )
            self.new_sync_updates[nested.channel.id] = syncstate.ChannelSync(thread_id, iso_now)

    def _attachment_failed(self, target: Channel) -> bool:
        return self.writer is not None and any(
            job.status == FAILED for job in self.writer.jobs if job.channel_id == target.id
        )


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
    """Fetch the messages of the requested channels and print them or export them (`out_dir` / `zip_file`).

    An export is written channel by channel (`export.ExportWriter`): nothing is put into the target before the last
    channel is done, and a run that is interrupted (`Cancelled`, Ctrl+C, an error) keeps the finished channels in
    `<target>.partial`. The same request, run again, continues there: `events.resumed` tells how many channels are
    taken over, and those are neither fetched nor downloaded again. The exception of an interrupted run goes on
    after `events.interrupted`.

    A channel that cannot be read (no access, not found) is skipped unless it is the only one; that makes the outcome
    `partial`, as does a file that could not be downloaded.
    """
    events = events or Events()
    _check_request(request)
    export_to = validate_export_target(
        request.out_dir,
        request.zip_file,
        request.print_messages,
        request.no_files,
        request.max_file_size,
        export_dir=export_dir,
    )

    current_now = now if now is not None else utc_now()
    window, limit, query = _query_for(request, current_now, tz)

    user_id: str | None = None
    account_sync: dict[str, syncstate.ChannelSync] = {}
    if request.since_last:
        me = directory.api().get_me()
        user_id = str(me["id"])
        account_sync = syncstate.load_account_channels(user_id, on_warning=events.warning)

    targets = resolve_targets(
        directory,
        request.server,
        request.channels,
        default_server=default_server,
        refresh=request.since_last,
    )
    _refuse_forum_without_threads(request, targets)
    channels = [
        channel
        for _, channel in targets
        if not (request.since_last and _is_channel_unchanged(channel, account_sync.get(channel.id), request.threads))
    ]
    total = len(targets)

    options = _export_options(request)
    created = current_now  # the "now" of the window; a continued export keeps the one of its first run
    resume: export.Resume | None = None
    if export_to is not None:
        found = _find_resume(export_to[0], channels, request, options, current_now, tz)
        if found is not None:
            resume, created, (window, limit, query) = found
    saved = {channel.id for channel in channels if resume is not None and channel.id in resume.done}
    if saved and request.print_messages:
        assert resume is not None
        _refuse_print_on_resume(len(saved), total, resume)

    run = _Run(
        request,
        directory,
        events,
        tz,
        current_now,
        window,
        limit,
        query,
        options,
        created,
        total,
        account_sync,
        export_to,
        resume,
        saved,
    )
    exported: export.Exported | None = None
    try:
        with contextlib.ExitStack() as stack:
            if export_to is not None:
                run.open_export(stack, cdn, channels)
            api = directory.api()
            old_on_pause = getattr(api, "on_pause", None)
            api.on_pause = lambda s, reason: events.pause(s, reason)
            try:
                run.fetch_channels(targets)
            finally:
                api.on_pause = old_on_pause
            exported = run.finish(user_id)
    except BaseException:
        if run.writer is not None:
            _announce_interruption(events, run.writer, total)
        raise

    return MessagesOutcome(
        results=run.results,
        skipped=run.skipped,
        exported=exported,
        query=query,
        resumed=len(saved),
        total=total,
        skipped_channels=run.skipped_channels,
        thread_problems=run.thread_problems,
        unchanged=run.unchanged,
        tokens_estimate=_estimate_tokens(exported),
    )


def _announce_interruption(events: Events, writer: export.ExportWriter, total: int) -> None:
    """Tell where the channels that were saved wait, if there are any. Never raises: the original exception goes on."""
    with contextlib.suppress(Exception):
        kept = writer.close(complete=False)  # the `with` has closed it already: this is its first result
        if not kept.complete and kept.path != writer.target:
            events.interrupted(len(writer.done), total, kept.path)
