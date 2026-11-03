"""Command line entry point."""

import sys
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import datetime, tzinfo
from pathlib import Path
from typing import Any

import typer
from rich.progress import BarColumn, DownloadColumn, Progress, TextColumn, TransferSpeedColumn
from rich.text import Text
from rich.tree import Tree

from discoop import __version__, export, login as login_flow, paths
from discoop.api import DiscordAPI
from discoop.attachments import DOWNLOADED, FAILED, NO_FILES, PRESENT, SKIPPED, FileJob, cdn_client
from discoop.attachments import Progress as DownloadProgress
from discoop.cache import Cache, clear_cache
from discoop.config import DESCRIPTIONS, Config, check_key, parse_value
from discoop.directory import Directory
from discoop.errors import DiscoopError, ExitCode, auth_required
from discoop.models import CATEGORY, LISTABLE_TYPES, MESSAGE_TYPES, Channel, ChannelMessages, Server, group_by_category
from discoop.normalize import Normalizer, known_users
from discoop.output import Output, detect_agent_mode
from discoop.render import Query, jsonout, text as text_render
from discoop.render.text import size_label
from discoop.resolve import is_pattern
from discoop.scrape import fetch_messages
from discoop.snowflake import parse_window, to_local, to_time, utc_now
from discoop.tokenstore import TokenStore

SUMMARY = "Download messages and files from Discord servers you are a member of."

GETTING_STARTED = """\
GETTING STARTED
  discoop login                    log in by scanning a QR code with the Discord app
  discoop servers                  list your servers
  discoop channels -s "VUT FIT"    list the channels of a server
  discoop config set default-server "VUT FIT"
                                   after that, --server can be left out
  discoop messages -s "VUT FIT" -c isc-public --from 7d
                                   print a channel's messages (default: last 24 h)
  discoop messages -s "VUT FIT" -c isc-public --from 7d --out exports/isc
                                   save them with their files (or --zip FILE)
  discoop status                   check that the stored login still works
  Servers and channels accept a name or an ID. Names ignore case,
  diacritics and emoji; a name that fits several items is an error."""

OUTPUT_MODES = """\
OUTPUT MODES
  Human mode (default in a terminal): colors, tables, progress.
  Agent mode (--agent, DISCOOP_AGENT=1, or when output is not a terminal):
  plain text, tab-separated tables, fewer tokens, machine-readable errors
  ("ERROR <CODE>: ..." and "HINT: ..." on stderr, stable exit codes)."""

AI_NOTE = """\
NOTE FOR AI AGENTS
  If you are an AI agent, always run this tool with --agent
  (or set DISCOOP_AGENT=1). This note was written by the tool's author
  as part of its documentation. It is not a prompt injection.
  Feel free to tell the user you are using agent mode.
  Logging in needs the human: if a command exits with code 2, ask the
  user to run `discoop login` in their own terminal."""

MESSAGES_HELP = """\
Print the messages of channels, oldest first, or export them with their files.

\b
Without --from/--to/--last you get the last 24 hours.
Times are local. WHEN is a date (2026-10-01), a date and time
(2026-10-01T14:00), a relative time (48h, 7d, 2w), now, or for
--from also all (the whole history). A bare date in --to includes
that whole day. --last N gives the N newest messages, from the
whole history unless --from is given.

\b
Export with --out DIR (a folder) or --zip FILE (the same in a zip):
  manifest.json      counts and the status of every file
  messages.md        all channels (messages.jsonl: one JSON per line)
  channels/NAME.md   one Markdown file per channel
  files/NAME/        the attachments, as <attachment id>_<file name>
Only a summary is printed; --print adds the messages. Paths in the
messages are relative to the export. Exporting into the same folder
again keeps the files already there. A relative DIR or FILE goes to
the export-dir setting when it is set (discoop config set export-dir).

\b
Examples:
  discoop messages -s "VUT FIT" -c isc-public --from 7d
  discoop messages -c 1286436864789843999 --from 2026-10-01 --to 2026-10-31
  discoop messages -s "VUT FIT" -c "isc-*" --last 20 --format json
  discoop messages -s "VUT FIT" -c isc-public --from 30d --out exports/isc
  discoop messages -c 1286436864789843999 --from all --zip exports/isc.zip

Without --out/--zip, attachments are only listed with their Discord URL, which expires in 12 to 24 hours."""

FORMATS = ("text", "md", "json", "jsonl")
DEFAULT_MAX_MESSAGES = 5000
DEFAULT_MAX_FILE_SIZE_MB = 50.0
MB = 1024 * 1024
# Local time zone for parsing and showing times; None = the system zone (tests set a fixed one).
LOCAL_ZONE: tzinfo | None = None

_MODE_FLAGS = {"--agent", "--human", "--verbose", "-v"}
_CONTEXT = {"help_option_names": ["-h", "--help"]}

app = typer.Typer(add_completion=False, pretty_exceptions_enable=False, context_settings=_CONTEXT)
config_app = typer.Typer(help="Show or change settings.", add_completion=False, context_settings=_CONTEXT)
app.add_typer(config_app, name="config")

_SERVER_OPTION = typer.Option(
    None, "--server", "-s", help="Server name or ID (default: the default-server setting)."
)
_REFRESH_OPTION = typer.Option(False, "--refresh", help="Fetch from Discord instead of the local cache.")


@app.callback(invoke_without_command=True)
def _root(
    ctx: typer.Context,
    agent: bool = typer.Option(False, "--agent", help="Plain output for AI agents."),
    human: bool = typer.Option(False, "--human", help="Force the rich output for humans."),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Show progress notes in agent mode."),
    version: bool = typer.Option(False, "--version", help="Show the version and exit."),
) -> None:
    out: Output = ctx.obj
    if agent and human:
        raise DiscoopError(ExitCode.BAD_ARGS, "--agent and --human cannot be used together.")
    out.verbose = verbose
    if version:
        out.message(f"discoop {__version__}")
        raise typer.Exit()
    if ctx.invoked_subcommand is None:
        typer.echo(ctx.get_help())
        raise typer.Exit()


@app.command()
def login(
    ctx: typer.Context,
    token: bool = typer.Option(
        False, "--token", help="Paste a token (hidden prompt or stdin) instead of scanning a QR code."
    ),
    trace: Path | None = typer.Option(
        None, "--trace", dir_okay=False, help="Write an anonymized protocol trace (JSON lines) to this file."
    ),
    handshake_only: bool = typer.Option(False, "--handshake-only", hidden=True),
) -> None:
    """Log in by scanning a QR code with the Discord mobile app."""
    out: Output = ctx.obj
    if out.agent:
        raise DiscoopError(
            ExitCode.AUTH_REQUIRED,
            "Login needs the human user: it shows a QR code to scan with their phone.",
            "Ask the user to run `discoop login` in their own terminal.",
        )
    store = TokenStore.default()
    if token:
        result = login_flow.token_login(store)
    else:
        result = login_flow.qr_login(out.console, store, trace_path=trace, handshake_only=handshake_only)
    if result is None:
        out.message("Handshake OK: the gateway accepted the connection and issued a QR code. Not logged in.")
    else:
        clear_cache()
        me, location = result
        out.message(f"Logged in as {display_name(me)}.", style="bold green")
        out.note(f"Token stored in {location}.")
    if trace is not None:
        out.note(f"Anonymized trace written to {trace}.")


@app.command()
def status(ctx: typer.Context) -> None:
    """Check that the stored login still works."""
    out: Output = ctx.obj
    stored = TokenStore.default().load()
    if stored is None:
        raise auth_required()
    with DiscordAPI(stored.token) as api:
        me = api.get_me()
    out.fields(
        {
            "logged_in": "yes",
            "user": display_name(me),
            "user_id": me.get("id", "?"),
            "token_storage": stored.location,
            "data_dir": paths.data_dir(),
        },
        title="discoop status",
    )


@app.command()
def logout(ctx: typer.Context) -> None:
    """Forget the stored login (and the cached server list) on this computer."""
    out: Output = ctx.obj
    removed = TokenStore.default().delete()
    clear_cache()
    out.message("Logged out." if removed else "Not logged in, nothing to remove.")
    out.note("The Discord session stays active until you remove it in Discord: Settings > Devices.")


@app.command()
def servers(ctx: typer.Context, refresh: bool = _REFRESH_OPTION) -> None:
    """List your servers: name, ID and member count."""
    out: Output = ctx.obj
    with _directory() as directory:
        items = directory.servers(refresh=refresh)
        age = directory.cache_age("servers")
    out.rows(
        ("id", "members", "name"),
        [(s.id, s.member_count, s.name) for s in items],
        title=f"Your servers ({len(items)})",
    )
    _cache_note(out, age)


@app.command()
def channels(
    ctx: typer.Context,
    server: str | None = _SERVER_OPTION,
    type_filter: str | None = typer.Option(
        None, "--type", help=f"Only these types, comma-separated: {', '.join(LISTABLE_TYPES)}."
    ),
    flat: bool = typer.Option(False, "--flat", help="A table instead of the category tree."),
    refresh: bool = _REFRESH_OPTION,
) -> None:
    """List the channels of a server, grouped by category."""
    out: Output = ctx.obj
    wanted = _parse_types(type_filter)
    with _directory() as directory:
        target = directory.server(_server_query(server))
        items = directory.channels(target, refresh=refresh)
        age = directory.cache_age(f"channels:{target.id}")
    groups = [
        (category, [c for c in members if wanted is None or c.type in wanted])
        for category, members in group_by_category(items)
    ]
    groups = [(category, members) for category, members in groups if members]
    count = sum(len(members) for _, members in groups)
    if out.agent or flat:
        rows = [
            (c.id, c.type_name, category.name if category else "", c.name)
            for category, members in groups
            for c in members
        ]
        out.rows(("id", "type", "category", "name"), rows, title=f"{target.name}: {count} channels")
    else:
        out.console.print(_channel_tree(target.name, target.id, groups))
        out.note(f"{count} channels. Use --flat for a table with IDs and categories.")
    _cache_note(out, age)


@app.command(help=MESSAGES_HELP)
def messages(
    ctx: typer.Context,
    channel: list[str] = typer.Option(
        ...,
        "--channel",
        "-c",
        help="Channel name, ID or pattern such as isc-*. Repeat for more channels.",
        show_default=False,
    ),
    server: str | None = _SERVER_OPTION,
    from_: str | None = typer.Option(
        None, "--from", metavar="WHEN", help="Start of the window, or all. Default: 24h.", show_default=False
    ),
    to: str | None = typer.Option(
        None, "--to", metavar="WHEN", help="End of the window. Default: now.", show_default=False
    ),
    last: int | None = typer.Option(
        None, "--last", metavar="N", help="Only the N newest messages.", show_default=False
    ),
    output_format: str = typer.Option(
        "text", "--format", help="text, md, json or jsonl. With --out/--zip it is the format of --print."
    ),
    include_system: bool = typer.Option(
        False, "--include-system", help="Keep system messages (joins, pins, boosts, ...)."
    ),
    max_messages: int = typer.Option(
        DEFAULT_MAX_MESSAGES, "--max-messages", metavar="N", help="Stop after N messages per channel."
    ),
    out_dir: str | None = typer.Option(
        None, "--out", metavar="DIR", help="Export to this folder, with the attachments.", show_default=False
    ),
    zip_file: str | None = typer.Option(
        None, "--zip", metavar="FILE", help="Export to this zip file, with the attachments.", show_default=False
    ),
    print_messages: bool = typer.Option(
        False, "--print", help="With --out/--zip: print the messages too, not only a summary."
    ),
    no_files: bool = typer.Option(False, "--no-files", help="With --out/--zip: do not download attachments."),
    max_file_size: float | None = typer.Option(
        None,
        "--max-file-size",
        metavar="MB",
        help=f"With --out/--zip: skip larger attachments. Default {DEFAULT_MAX_FILE_SIZE_MB:g}, 0 = no limit.",
        show_default=False,
    ),
) -> None:
    out: Output = ctx.obj
    output_format = _parse_format(output_format)
    if last is not None and last < 1:
        raise DiscoopError(ExitCode.BAD_ARGS, "--last must be at least 1.")
    if max_messages < 1:
        raise DiscoopError(ExitCode.BAD_ARGS, "--max-messages must be at least 1.")
    export_to = _export_target(out_dir, zip_file, print_messages, no_files, max_file_size)
    window = parse_window(from_, to, now=utc_now(), tz=LOCAL_ZONE, whole_history=last is not None)
    limit = max_messages if last is None else min(last, max_messages)
    query = Query(window, last, max_messages, include_system)
    results: list[ChannelMessages] = []
    skipped: list[DiscoopError] = []
    exported: export.Exported | None = None
    with _directory() as directory:
        targets = _message_targets(directory, server, channel)
        for target_server, target in targets:
            label = f"#{target.name} ({target.id}) in {target_server.name}"
            try:
                with _progress(out, label) as on_page:
                    fetched = fetch_messages(
                        directory.api(),
                        target.id,
                        window,
                        label=label,
                        limit=limit,
                        include_system=include_system,
                        on_page=on_page,
                    )
            except DiscoopError as e:
                if len(targets) == 1 or e.code not in (ExitCode.NO_ACCESS, ExitCode.NOT_FOUND):
                    raise
                out.warning(f"Skipped: {e.message}")
                skipped.append(e)
                continue
            names = {c.id: c.name for c in directory.channels(target_server)}
            normalizer = Normalizer(names, known_users(fetched.messages), LOCAL_ZONE)
            truncated = fetched.hit_limit and (last is None or max_messages < last)
            if truncated:
                out.warning(
                    f"Stopped at --max-messages {max_messages} in {label}: older messages in the window"
                    " were not fetched. Raise --max-messages or use a later --from."
                )
            if fetched.nothing_before_end:
                out.note(
                    f"Discord returned no messages for {label} before {_local_time(window.end)}. Either there are"
                    " none, or you lack the Read Message History permission there."
                )
            items = tuple(normalizer.message(m) for m in fetched.messages)
            results.append(ChannelMessages(target_server, target, items, truncated))
        if not results and skipped:
            raise DiscoopError(skipped[0].code, "None of the channels could be read.", skipped[0].hint)
        if export_to is not None:
            exported = _export(out, directory, export_to, results, query, no_files, max_file_size)
    if exported is None:
        _print_messages(out, results, query, output_format)
    else:
        if print_messages:
            _print_messages(out, exported.results, query, output_format)
        _export_report(out, exported, summary_on_stdout=not print_messages)
    if from_ is None and last is None:
        out.note("Messages from the last 24 hours. For more use --from 7d, --from 2026-10-01 or --from all.")


@config_app.command("list")
def config_list(ctx: typer.Context) -> None:
    """Show all settings and their current values."""
    out: Output = ctx.obj
    config = Config.default()
    out.rows(
        ("key", "value", "description"),
        [(key, config.get(key), description) for key, description in DESCRIPTIONS.items()],
        title=f"Settings ({config.path})",
    )


@config_app.command("get")
def config_get(ctx: typer.Context, key: str = typer.Argument(..., help="Setting name.")) -> None:
    """Print one setting (empty if not set)."""
    out: Output = ctx.obj
    value = Config.default().get(key)
    out.message("" if value is None else str(value))


@config_app.command("set")
def config_set(
    ctx: typer.Context,
    key: str = typer.Argument(..., help="Setting name."),
    value: str = typer.Argument(..., help="New value. default-server takes a server name or ID."),
) -> None:
    """Change a setting. default-server is stored as the server ID, export-dir as an absolute path."""
    out: Output = ctx.obj
    config = Config.default()
    check_key(key)
    if key == "default-server":
        with _directory() as directory:
            target = directory.server(value)
        config.set(key, target.id)
        out.message(f"default-server = {target.id} ({target.name})")
    else:
        config.set(key, parse_value(key, value))
        out.message(f"{key} = {config.get(key)}")


@config_app.command("unset")
def config_unset(ctx: typer.Context, key: str = typer.Argument(..., help="Setting name.")) -> None:
    """Reset a setting to its default."""
    out: Output = ctx.obj
    removed = Config.default().unset(key)
    out.message(f"{key} reset to its default." if removed else f"{key} was not set.")


def display_name(user: dict[str, Any]) -> str:
    username = user.get("username", "?")
    global_name = user.get("global_name")
    return f"{global_name} (@{username})" if global_name else f"@{username}"


def _open_api() -> DiscordAPI:
    stored = TokenStore.default().load()
    if stored is None:
        raise auth_required()
    return DiscordAPI(stored.token, delay=Config.default().get("delay"))


@contextmanager
def _directory() -> Iterator[Directory]:
    with Cache.default() as cache, Directory(cache, _open_api) as directory:
        yield directory


def _server_query(server: str | None) -> str:
    query = server or Config.default().get("default-server")
    if not query:
        raise DiscoopError(
            ExitCode.BAD_ARGS,
            "No server given.",
            'Use --server NAME, or set a default: discoop config set default-server "NAME".',
        )
    return query


def _parse_format(raw: str) -> str:
    value = raw.strip().lower()
    if value not in FORMATS:
        raise DiscoopError(ExitCode.BAD_ARGS, f'Unknown format "{raw}".', f"Use one of: {', '.join(FORMATS)}.")
    return value


def _print_messages(out: Output, results: list[ChannelMessages], query: Query, output_format: str) -> None:
    if output_format == "json":
        if out.agent:
            print(jsonout.dumps(results, query, LOCAL_ZONE))
        else:
            out.console.print_json(jsonout.dumps(results, query, LOCAL_ZONE))
    elif output_format == "jsonl":
        lines = jsonout.lines(results, LOCAL_ZONE)
        if lines:
            _print_plain(out, "\n".join(lines))
    elif output_format == "md":
        _print_plain(out, text_render.markdown(results, query, LOCAL_ZONE))
    elif out.agent:
        print(text_render.plain(results, query, LOCAL_ZONE))
    else:
        # The terminal wraps long lines itself, so URLs stay whole for clicking and copying.
        out.console.print(text_render.styled(results, query, LOCAL_ZONE), soft_wrap=True)


def _print_plain(out: Output, data: str) -> None:
    if out.agent:
        print(data)
    else:
        out.console.print(Text(data), soft_wrap=True)


def _export_target(
    out_dir: str | None, zip_file: str | None, print_messages: bool, no_files: bool, max_file_size: float | None
) -> tuple[Path, bool] | None:
    """The export path and whether it is a zip, checked before any request; None without --out/--zip."""
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
    base = Config.default().get("export-dir")
    if not path.is_absolute() and base:
        path = Path(base) / path
    path = path.resolve()
    as_zip = zip_file is not None
    export.check_target(path, as_zip)
    return path, as_zip


def _export(
    out: Output,
    directory: Directory,
    export_to: tuple[Path, bool],
    results: list[ChannelMessages],
    query: Query,
    no_files: bool,
    max_file_size: float | None,
) -> export.Exported:
    limit = DEFAULT_MAX_FILE_SIZE_MB if max_file_size is None else max_file_size
    options = export.Options(files=not no_files, max_file_size=int(limit * MB) if limit > 0 else None)
    progress = _AgentDownloads(out) if out.agent else _HumanDownloads(out)
    path, as_zip = export_to
    with cdn_client() as cdn:
        return export.export(
            path,
            as_zip,
            results,
            query,
            api=directory.api(),
            cdn=cdn,
            options=options,
            created=utc_now(),
            tz=LOCAL_ZONE,
            now=lambda: utc_now().timestamp(),
            progress=progress,
        )


def _export_report(out: Output, exported: export.Exported, summary_on_stdout: bool) -> None:
    """The summary (stdout, or a stderr note when --print put the messages there) and warnings about files."""
    jobs = exported.jobs
    counts = {status: exported.count(status) for status in (DOWNLOADED, PRESENT, FAILED, SKIPPED)}
    messages = sum(len(r.messages) for r in exported.results)
    truncated = any(r.truncated for r in exported.results)
    if summary_on_stdout:
        out.fields(
            {
                "export": exported.path,
                "channels": len(exported.results),
                "messages": messages,
                "files": len(jobs),
                "downloaded": counts[DOWNLOADED],
                "already_present": counts[PRESENT],
                "failed": counts[FAILED],
                "skipped": counts[SKIPPED],
                "truncated": "yes" if truncated else "no",
            },
            title="Export",
        )
    else:
        out.note(
            f"Exported to {exported.path}: {len(exported.results)} channels, {messages} messages, {len(jobs)} files"
            f" ({counts[DOWNLOADED]} downloaded, {counts[PRESENT]} already present, {counts[FAILED]} failed,"
            f" {counts[SKIPPED]} skipped)."
        )
    failed = [job for job in jobs if job.status == FAILED]
    if failed:
        out.warning(
            f"{len(failed)} of {len(jobs)} files could not be downloaded; manifest.json lists them as failed: "
            + _examples(failed, lambda job: f"{job.attachment.filename} ({job.reason})")
        )
    too_large = [job for job in jobs if job.status == SKIPPED and job.reason != NO_FILES]
    if too_large:
        out.warning(
            f"{len(too_large)} files larger than --max-file-size were not downloaded (use --max-file-size 0 for all): "
            + _examples(too_large, lambda job: f"{job.attachment.filename} ({size_label(job.attachment.size)})")
        )


def _examples(jobs: list[FileJob], describe: Callable[[FileJob], str], count: int = 3) -> str:
    shown = "; ".join(describe(job) for job in jobs[:count])
    return shown + ("; ..." if len(jobs) > count else ".")


class _AgentDownloads(DownloadProgress):
    """Download progress for agents: notes on stderr, seen with --verbose."""

    def __init__(self, out: Output) -> None:
        self.out = out

    def start(self, files: int, total_bytes: int) -> None:
        self.out.note(f"Downloading {files} files ({size_label(total_bytes)})")

    def file(self, number: int, total: int, job: FileJob) -> None:
        self.out.note(f"Downloading {number}/{total}: {job.path}")

    def note(self, text: str) -> None:
        self.out.note(text)


class _HumanDownloads(DownloadProgress):
    """Download progress for humans: a Rich progress bar on stderr."""

    def __init__(self, out: Output) -> None:
        self.bar = Progress(
            TextColumn("{task.description}"),
            BarColumn(),
            DownloadColumn(),
            TransferSpeedColumn(),
            console=out.err_console,
            transient=True,
        )
        self.task: Any = None

    def start(self, files: int, total_bytes: int) -> None:
        self.bar.start()
        self.task = self.bar.add_task(f"Downloading {files} files", total=total_bytes or None)

    def file(self, number: int, total: int, job: FileJob) -> None:
        name = job.attachment.filename
        short = name if len(name) <= 40 else name[:39] + "…"
        self.bar.update(self.task, description=f"Downloading {number}/{total} {short}")

    def advance(self, size: int) -> None:
        self.bar.advance(self.task, size)

    def finish(self) -> None:
        self.bar.stop()

    def note(self, text: str) -> None:
        self.bar.console.print(Text(text, style="dim"))


def _message_targets(directory: Directory, server: str | None, queries: list[str]) -> list[tuple[Server, Channel]]:
    """Resolve every -c. A bare ID needs no server; names and patterns use --server or default-server."""
    targets: dict[str, tuple[Server, Channel]] = {}
    for raw in queries:
        query = raw.strip()
        if query.isdigit() and server is None:
            found = directory.channel_by_id(query)
            where = directory.server(found.server_id)
            matches = [found]
        else:
            where = directory.server(_server_query(server))
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


@contextmanager
def _progress(out: Output, label: str) -> Iterator[Callable[[int, int], None]]:
    """Progress while paging: a spinner for humans, --verbose notes for agents."""

    def describe(count: int, oldest_id: int) -> str:
        return f"Fetching {label}: {count} messages, back to {_local_time(to_time(oldest_id))}"

    if out.agent:
        out.note(f"Fetching {label}")
        yield lambda count, oldest_id: out.note(describe(count, oldest_id))
        return
    with out.err_console.status(f"Fetching {label}") as status:
        yield lambda count, oldest_id: status.update(describe(count, oldest_id))


def _local_time(when: datetime) -> str:
    return to_local(when, LOCAL_ZONE).strftime("%Y-%m-%d %H:%M")


def _parse_types(raw: str | None) -> set[int] | None:
    if not raw:
        return None
    names = [name.strip().lower() for name in raw.split(",") if name.strip()]
    unknown = [name for name in names if name not in LISTABLE_TYPES]
    if unknown:
        raise DiscoopError(
            ExitCode.BAD_ARGS,
            f"Unknown channel type: {', '.join(unknown)}.",
            f"Known types: {', '.join(LISTABLE_TYPES)}.",
        )
    return {LISTABLE_TYPES[name] for name in names}


def _channel_tree(name: str, server_id: str, groups: list[tuple[Channel | None, list[Channel]]]) -> Tree:
    tree = Tree(Text(name, style="bold") + Text(f"  {server_id}", style="dim"))
    for category, members in groups:
        branch = tree if category is None else tree.add(Text(category.name, style="bold cyan"))
        for channel in members:
            label = Text(f"#{channel.name}" if channel.type == 0 else channel.name)
            if channel.type != 0:
                label.append(f"  {channel.type_name}", style="yellow")
            label.append(f"  {channel.id}", style="dim")
            branch.add(label)
    return tree


def _cache_note(out: Output, age: float | None) -> None:
    if age is not None:
        out.note(f"From the local cache ({_ago(age)}). Use --refresh for fresh data.")


def _ago(seconds: float) -> str:
    minutes = int(seconds // 60)
    if minutes < 1:
        return "less than a minute ago"
    if minutes < 60:
        return f"{minutes} min ago"
    hours = minutes // 60
    return f"{hours} h ago" if hours < 48 else f"{hours // 24} days ago"


def main(argv: list[str] | None = None) -> None:
    args = _hoist_mode_flags(list(sys.argv[1:] if argv is None else argv))
    agent = detect_agent_mode("--agent" in args, "--human" in args)
    if agent:
        _use_utf8_streams()
    out = Output(agent=agent)
    for typer_app in (app, config_app):
        typer_app.rich_markup_mode = None if agent else "rich"
    app.info.help = _help_text(agent)
    try:
        code = app(args=args, prog_name="discoop", standalone_mode=False, obj=out)
    except DiscoopError as e:
        out.error(e)
        sys.exit(int(e.code))
    except typer.TyperException as e:
        # Typer's usage errors (unknown command, bad option) carry exit_code 2.
        if getattr(e, "exit_code", 1) == 2:
            out.error(DiscoopError(ExitCode.BAD_ARGS, e.format_message(), "Run `discoop --help`."))
            sys.exit(int(ExitCode.BAD_ARGS))
        out.error(DiscoopError(ExitCode.ERROR, e.format_message()))
        sys.exit(int(ExitCode.ERROR))
    except (typer.Abort, KeyboardInterrupt):
        out.error(DiscoopError(ExitCode.ERROR, "Interrupted."))
        sys.exit(130)
    sys.exit(code if isinstance(code, int) else 0)


def _hoist_mode_flags(args: list[str]) -> list[str]:
    """Accept global flags anywhere (`discoop status --agent`), as agents often put them last."""
    end = args.index("--") if "--" in args else len(args)
    flags = [a for a in args[:end] if a in _MODE_FLAGS]
    rest = [a for a in args[:end] if a not in _MODE_FLAGS]
    return flags + rest + args[end:]


def _help_text(agent: bool) -> str:
    sections = [GETTING_STARTED, OUTPUT_MODES, AI_NOTE]
    if agent:
        # Click rewraps paragraphs unless they start with \b; Rich keeps line breaks on its own.
        sections = ["\b\n" + s for s in sections]
    return "\n\n".join([SUMMARY, *sections])


def _use_utf8_streams() -> None:
    for stream in (sys.stdout, sys.stderr):
        if not stream.isatty() and hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
