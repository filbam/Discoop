"""Command line entry point."""

import difflib
import json
import os
import shutil
import sys
import time
import zipfile
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from datetime import datetime, tzinfo
from pathlib import Path
from typing import Any

try:
    import click
except ImportError:
    from typer import _click as click

import httpx
import typer
from rich.progress import BarColumn, DownloadColumn, Progress, TextColumn, TransferSpeedColumn
from rich.text import Text
from rich.tree import Tree
from typer.core import TyperCommand

from discoop import __version__, agent_guide, export, login as login_flow, logs, paths, profiles, tokens, update_check
from discoop.api import DiscordAPI
from discoop.attachments import DOWNLOADED, FAILED, NO_FILES, PRESENT, SKIPPED, FileJob, cdn_client
from discoop.attachments import Progress as DownloadProgress
from discoop.cache import Cache, cache_path, clear_cache
from discoop.config import DESCRIPTIONS, Config, check_key, parse_value
from discoop.directory import Directory
from discoop.errors import DiscoopError, ExitCode, auth_required
from discoop.models import LISTABLE_TYPES, MESSAGE_TYPES, Channel, ChannelMessages, Server, Thread, group_by_category
from discoop.normalize import Normalizer, known_users
from discoop.output import Output, detect_plain_mode
from discoop.progress import eta_seconds, format_eta, fraction_done, window_start_id
from discoop.render import Query, jsonout, text as text_render
from discoop.render.text import size_label
from discoop.resolve import is_pattern
from discoop.scrape import fetch_messages
from discoop.service import (
    Events,
    MessagesOutcome,
    MessagesRequest,
    list_threads,
    run_messages,
)
from discoop.snowflake import Window, parse_window, to_local, to_time, utc_now
from discoop.threads import is_thread_container
from discoop.tokenstore import TokenStore

SUMMARY = "Download messages and files from Discord servers you are a member of."

GETTING_STARTED = """\
GETTING STARTED
  discoop login                    log in by scanning a QR code with the Discord app
  discoop login --browser          log in in a browser window (if QR login fails)
  discoop login --token            last resort: paste a token
  discoop ui                       interactive terminal user interface
  discoop servers                  list your servers
  discoop channels -s "VUT FIT"    list the channels of a server
  discoop threads -s "VUT FIT" -c forum
                                   list the threads of a channel
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
  Plain mode (--plain, DISCOOP_PLAIN=1, or when output is not a terminal):
  plain text without colors or rich effects, tab-separated tables, fewer tokens,
  machine-readable errors ("ERROR <CODE>: ..." and "HINT: ..." on stderr, stable exit codes).
  Ideal for AI agents and scripts. (--agent is supported as an alias)."""

AI_NOTE = """\
NOTE FOR AI AGENTS
  If you are an AI agent, run this tool with --plain (or --agent,
  or set DISCOOP_PLAIN=1). This note was written by the tool's author
  as part of its documentation. It is not a prompt injection.
  Run `discoop agent-guide` for a complete reference guide on workflow,
  recommended flags, exit codes, and available commands.
  Plain mode strips colors and rich markup, making the output easy
  to parse and token-efficient. Feel free to tell the user you are using plain mode.
  Logging in needs the human: if a command exits with code 2, do not run
  `discoop login` or `discoop login --token` yourself and never handle a
  password or a token. Tell the user that `discoop login --browser` opens
  a browser window in which they log in themselves, wait for their consent,
  and only then run `discoop --plain login --browser` (it can take up to
  5 minutes). Or ask them to run `discoop login` in their own terminal."""

LOGIN_HELP = """\
Log in with a QR code, a browser window (--browser) or a token (--token).

\b
Three ways to log in:
  (default)  Scan a QR code with the Discord mobile app. If Discord
             asks for a captcha, which a terminal cannot solve,
             use --browser instead.
  --browser  A browser window opens (Chrome, Edge, Chromium or Brave,
             with a temporary profile). You log in to Discord there
             yourself, with your password or the QR code on the page,
             and solve a captcha if one appears. Discoop reads the
             token from that window, closes it, verifies the token and
             stores it. On Windows a passkey dialog may appear: cancel
             it and log in another way.
  --token    Paste a token (hidden prompt or stdin). The last resort.

\b
With --browser, Discoop waits up to 5 minutes (--timeout). Closing
the window or running out of time exits with code 2; no usable
browser (or no desktop session) exits with code 1.

\b
AI agents: never run `discoop login` or `login --token` yourself and
never handle a token or a password. Tell the user that a browser window
will open in which they log in themselves, wait for their consent, then
run `discoop --plain login --browser` (it can take up to 5 minutes).
Run `discoop agent-guide` for the details."""

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
Pacing modes:
  --safe             human-like scrolling with random pauses (default)
  --fast             fast download with 100 messages per page and fixed delay
  --delay SEC        pacing delay (default 1.0; scales pauses in safe mode)

\b
Threads:
  --threads / --no-threads
                     Download thread messages and forum posts too (default on).
                     Threads add many requests: a large forum with hundreds of
                     posts is slow in safe mode.

\b
Export with --out DIR (a folder) or --zip FILE (the same in a zip):
  manifest.json      counts, settings and the status of every file
  messages.md        all channels (messages.jsonl: one JSON per line)
  channels/NAME.md   one Markdown file per channel
  files/NAME/        the attachments, as <attachment id>_<file name>
  parts/part-NNN.md  only with --max-tokens N: messages.md in parts of at most
                     N estimated tokens (a message is never split)
Only a summary is printed; --print adds the messages. Paths in the
messages are relative to the export. Exporting into the same folder
again keeps the files already there. A relative DIR or FILE goes to
the export-dir setting when it is set (discoop config set export-dir).


An export is written channel by channel into DIR.partial (FILE.partial)
and put in place when it is complete, so an earlier export is never
damaged. If a run is interrupted (Ctrl+C, an error), run the same
command again: the channels already saved are not fetched again.
Exit code 9 means the run finished but a channel was skipped (no
access, not found) or a file could not be downloaded.

\b
Examples:
  discoop messages -s "VUT FIT" -c isc-public --from 7d
  discoop messages -c 1286436864789843999 --from 2026-10-01 --to 2026-10-31
  discoop messages -s "VUT FIT" -c "isc-*" --last 20 --format json
  discoop messages -s "VUT FIT" -c isc-public --from 30d --out exports/isc
  discoop messages -c 1286436864789843999 --from all --zip exports/isc.zip
  discoop messages -s "VUT FIT" -c isc-public --fast

Without --out/--zip, attachments are only listed with their Discord URL, which expires in 12 to 24 hours."""

FORMATS = ("text", "md", "json", "jsonl")
DEFAULT_MAX_MESSAGES = 5000
DEFAULT_MAX_FILE_SIZE_MB = 50.0
MB = 1024 * 1024
# Local time zone for parsing and showing times; None = the system zone (tests set a fixed one).
LOCAL_ZONE: tzinfo | None = None

_TRUTHY = {"1", "true", "yes", "on"}


def _env_truthy(key: str) -> bool:
    return os.environ.get(key, "").strip().lower() in _TRUTHY


_MODE_FLAGS = {"--plain", "--agent", "--human", "--verbose", "-v", "--debug"}
_CONTEXT = {"help_option_names": ["-h", "--help"]}
CLI_NOTICE_WAIT_TIMEOUT = 1.0


class _CliCommand(TyperCommand):
    """TyperCommand that kicks off an eligible CLI background update check before running."""

    def invoke(self, ctx: click.Context) -> Any:
        _maybe_start_update_check(ctx)
        return super().invoke(ctx)


class _CliTyper(typer.Typer):
    """Typer app whose leaf commands use `_CliCommand` by default."""

    def command(
        self,
        name: str | None = None,
        *,
        cls: type[TyperCommand] | None = None,
        **kwargs: Any,
    ) -> Callable[[Any], Any]:
        return super().command(name, cls=cls or _CliCommand, **kwargs)


app = _CliTyper(add_completion=False, pretty_exceptions_enable=False, context_settings=_CONTEXT)
config_app = _CliTyper(help="Show or change settings.", add_completion=False, context_settings=_CONTEXT)
app.add_typer(config_app, name="config")
profiles_app = _CliTyper(help="List or delete saved profiles.", add_completion=False, context_settings=_CONTEXT)
app.add_typer(profiles_app, name="profiles")

_SERVER_OPTION = typer.Option(
    None, "--server", "-s", help="Server name or ID (default: the default-server setting)."
)
_REFRESH_OPTION = typer.Option(False, "--refresh", help="Fetch from Discord instead of the local cache.")


@app.callback(invoke_without_command=True)
def _root(
    ctx: typer.Context,
    plain: bool = typer.Option(False, "--plain", help="Plain output without colors or rich effects (ideal for AI agents and scripts)."),
    agent: bool = typer.Option(False, "--agent", hidden=True, help="Alias for --plain."),
    human: bool = typer.Option(False, "--human", help="Force the rich output for humans."),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Show progress notes in plain mode."),
    debug: bool = typer.Option(False, "--debug", help="Write diagnostic logs to stderr."),
    log_file: Path | None = typer.Option(None, "--log", metavar="FILE", dir_okay=False, help="Append diagnostic logs to this file."),
    version: bool = typer.Option(False, "--version", help="Show the version and exit."),
    ui_flag: bool = typer.Option(False, "--ui", help="Start the interactive terminal UI."),
) -> None:
    out: Output = ctx.obj
    if (plain or agent) and human:
        raise DiscoopError(ExitCode.BAD_ARGS, "--plain and --human cannot be used together.")
    out.verbose = verbose
    if version:
        out.message(f"discoop {__version__}")
        raise typer.Exit()
    if not ui_flag and ctx.invoked_subcommand is None:
        typer.echo(ctx.get_help())
        raise typer.Exit()

    effective_debug = debug or _env_truthy("DISCOOP_DEBUG")
    if log_file is not None:
        effective_log: Path | None = log_file
    else:
        env_log = os.environ.get("DISCOOP_LOG", "").strip()
        effective_log = Path(env_log) if env_log else None

    if effective_log is not None and effective_log.is_dir():
        raise DiscoopError(ExitCode.BAD_ARGS, f'Log path "{effective_log}" is a directory, not a file.')

    is_ui = ui_flag or ctx.invoked_subcommand == "ui"
    if is_ui and effective_debug:
        raise DiscoopError(
            ExitCode.BAD_ARGS,
            "discoop ui cannot be used with --debug.",
            "Use --log FILE: the terminal UI owns the screen.",
        )

    out.debug = effective_debug
    logs.setup_logging(effective_debug, effective_log)

    if ui_flag:
        ui(ctx)
        raise typer.Exit()


@app.command()
def ui(ctx: typer.Context) -> None:
    """Start the interactive terminal user interface."""
    out: Output = ctx.obj
    if getattr(out, "debug", False):
        raise DiscoopError(
            ExitCode.BAD_ARGS,
            "discoop ui cannot be used with --debug.",
            "Use --log FILE: the terminal UI owns the screen.",
        )
    if out.plain:
        raise DiscoopError(
            ExitCode.BAD_ARGS,
            "discoop ui requires an interactive terminal.",
            "Use commands such as `discoop messages` in scripts or with --plain.",
        )
    from discoop.tui.app import run_app

    run_app()


@app.command(help=LOGIN_HELP)
def login(
    ctx: typer.Context,
    token: bool = typer.Option(
        False,
        "--token",
        help="Paste a token (hidden prompt or stdin) instead of scanning a QR code. The last resort.",
    ),
    browser: bool = typer.Option(
        False,
        "--browser",
        help="Log in in a browser window (Chrome, Edge, Chromium or Brave) instead of scanning a QR code. "
        "Use it when QR login fails because of a captcha.",
    ),
    browser_path: str | None = typer.Option(
        None,
        "--browser-path",
        metavar="PATH",
        help="With --browser: the browser program to start. Default: the browser-path setting, else "
        "Chrome, Edge, Chromium or Brave is found automatically.",
        show_default=False,
    ),
    timeout: float | None = typer.Option(
        None,
        "--timeout",
        metavar="SECONDS",
        help=f"With --browser: how long to wait for the login, {login_flow.MIN_BROWSER_TIMEOUT:g} to "
        f"{login_flow.MAX_BROWSER_TIMEOUT:g} seconds. Default {login_flow.BROWSER_TIMEOUT:g}.",
        show_default=False,
    ),
    output_format: str = typer.Option(
        "text", "--format", help="With --browser: print the result as text or json (one JSON object)."
    ),
    progress_json: bool = typer.Option(
        False, "--progress-json", help="With --browser: write machine-readable progress events (JSON lines) to stderr."
    ),
    trace: Path | None = typer.Option(
        None, "--trace", dir_okay=False, help="Write an anonymized protocol trace (JSON lines) to this file."
    ),
    handshake_only: bool = typer.Option(False, "--handshake-only", hidden=True),
) -> None:
    out: Output = ctx.obj
    fmt = _parse_list_format(output_format)
    _check_login_options(
        token=token,
        browser=browser,
        browser_path=browser_path,
        timeout=timeout,
        fmt=fmt,
        progress_json=progress_json,
        trace=trace,
        handshake_only=handshake_only,
    )
    if out.plain and not browser:
        raise DiscoopError(
            ExitCode.AUTH_REQUIRED,
            "Login needs the human user: QR login shows a code to scan with their phone, "
            "and a token must not pass through an AI.",
            "Tell the user that a browser window will open in which they log in themselves; after they agree, "
            "run `discoop login --browser`. Or ask them to run `discoop login` in their own terminal.",
        )
    store = TokenStore.default()
    if browser:
        explicit_browser_path = Path(browser_path.strip()) if (browser_path is not None and browser_path.strip()) else None
        _login_with_browser(
            out,
            store,
            browser_path=explicit_browser_path,
            timeout=timeout if timeout is not None else login_flow.BROWSER_TIMEOUT,
            fmt=fmt,
            progress_json=progress_json,
        )
        return
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


def _check_login_options(
    *,
    token: bool,
    browser: bool,
    browser_path: str | None,
    timeout: float | None,
    fmt: str,
    progress_json: bool,
    trace: Path | None,
    handshake_only: bool,
) -> None:
    """The options of `login` that only make sense with --browser, and the ones that cannot go with it."""
    if browser:
        clashes = (
            (token, "--token", "Choose one way to log in: the QR code (no option), --browser or --token."),
            (trace is not None, "--trace", "--trace records the QR login protocol. Drop one of the two options."),
            (
                handshake_only,
                "--handshake-only",
                "--handshake-only only tests the connection to the QR login gateway. Drop one of the two options.",
            ),
        )
        for given, name, hint in clashes:
            if given:
                raise DiscoopError(ExitCode.BAD_ARGS, f"--browser cannot be used with {name}.", hint)
        if browser_path is not None and browser_path.strip():
            candidate = Path(browser_path.strip()).expanduser()
            if candidate.is_dir():
                raise DiscoopError(
                    ExitCode.BAD_ARGS,
                    f"{candidate} is a folder, not a browser program.",
                    "Give the program itself. On macOS that is the file inside the app, e.g. "
                    "`.../Google Chrome.app/Contents/MacOS/Google Chrome`.",
                )
    else:
        needs_browser = (
            (browser_path is not None, "--browser-path"),
            (timeout is not None, "--timeout"),
            (progress_json, "--progress-json"),
            (fmt == "json", "--format json"),
        )
        for given, name in needs_browser:
            if given:
                raise DiscoopError(
                    ExitCode.BAD_ARGS,
                    f"{name} only works with --browser.",
                    f"Add --browser to log in through a browser window, or drop {name}.",
                )
    low, high = login_flow.MIN_BROWSER_TIMEOUT, login_flow.MAX_BROWSER_TIMEOUT
    if timeout is not None and not low <= timeout <= high:  # written so that NaN fails too
        raise DiscoopError(
            ExitCode.BAD_ARGS,
            f"--timeout must be between {low:g} and {high:g} seconds.",
            f"Use for example --timeout {login_flow.BROWSER_TIMEOUT:g} (5 minutes).",
        )


def _login_with_browser(
    out: Output,
    store: TokenStore,
    *,
    browser_path: Path | None,
    timeout: float,
    fmt: str,
    progress_json: bool,
) -> None:
    """`login --browser`: notices (or progress events) while the human logs in, then the result."""
    progress = login_flow.BrowserProgressJson(timeout) if progress_json else None
    listener = progress if progress is not None else login_flow.BrowserScreen(out)
    me, location, browser = login_flow.browser_login(listener, store, browser_path=browser_path, timeout=timeout)
    clear_cache()
    if progress is not None:
        progress.logged_in(me.get("id", "?"))
    if fmt == "json":
        out.json({
            "logged_in": "yes",
            "user": display_name(me),
            "user_id": me.get("id", "?"),
            "token_storage": location,
            "browser": browser.name.lower(),
        })
        return
    out.message(f"Logged in as {display_name(me)}.", style="bold green")
    if progress is None:
        out.note(f"Token stored in {location}.")


def _parse_list_format(raw: str) -> str:
    value = raw.strip().lower()
    if value not in ("text", "json"):
        raise DiscoopError(ExitCode.BAD_ARGS, f'Unknown format "{raw}".', "Use one of: text, json.")
    return value


@app.command()
def status(
    ctx: typer.Context,
    output_format: str = typer.Option("text", "--format", help="Output format: text or json."),
) -> None:
    """Check that the stored login still works."""
    out: Output = ctx.obj
    fmt = _parse_list_format(output_format)
    stored = TokenStore.default().load()
    if stored is None:
        raise auth_required()
    with DiscordAPI(stored.token) as api:
        me = api.get_me()
    if fmt == "json":
        out.json({
            "logged_in": "yes",
            "user": display_name(me),
            "user_id": me.get("id", "?"),
            "token_storage": stored.location,
            "data_dir": str(paths.data_dir()),
        })
    else:
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
def doctor(ctx: typer.Context) -> None:
    """Check authentication, network connectivity, and system requirements."""
    out: Output = ctx.obj

    stored = TokenStore.default().load()
    if stored is None:
        login_ok = False
        login_detail = "not logged in (run discoop login)"
        login_code = ExitCode.AUTH_REQUIRED
        network_ok = True
        network_detail = "skipped (not logged in)"
        network_code = 0
    else:
        try:
            with DiscordAPI(stored.token) as api:
                me = api.get_me()
            login_ok = True
            login_detail = f"{display_name(me)} ({me.get('id', '?')})"
            login_code = 0
            network_ok = True
            network_detail = "Discord API reachable"
            network_code = 0
        except DiscoopError as e:
            if e.code == ExitCode.AUTH_REQUIRED:
                login_ok = False
                login_detail = e.message
                login_code = ExitCode.AUTH_REQUIRED
                network_ok = True
                network_detail = "Discord API reachable"
                network_code = 0
            elif e.code == ExitCode.NETWORK:
                login_ok = True
                login_detail = f"token stored in {stored.location} (unverified)"
                login_code = 0
                network_ok = False
                network_detail = e.message
                network_code = ExitCode.NETWORK
            else:
                login_ok = False
                login_detail = e.message
                login_code = ExitCode.ERROR
                network_ok = False
                network_detail = e.message
                network_code = ExitCode.ERROR
        except Exception as e:
            login_ok = False
            login_detail = str(e)
            login_code = ExitCode.ERROR
            network_ok = False
            network_detail = str(e)
            network_code = ExitCode.ERROR

    raw_export_dir = Config.default().get("export-dir")
    target_dir = Path(raw_export_dir).expanduser().resolve() if raw_export_dir else Path.cwd().resolve()
    probe_dir = target_dir
    while not probe_dir.exists() and probe_dir.parent != probe_dir:
        probe_dir = probe_dir.parent

    if target_dir.exists() and not target_dir.is_dir():
        export_ok = False
        export_detail = f"{target_dir} is not a directory"
        export_code = ExitCode.ERROR
    elif probe_dir.is_dir() and os.access(probe_dir, os.W_OK):
        export_ok = True
        export_detail = str(target_dir)
        export_code = 0
    else:
        export_ok = False
        export_detail = f"{target_dir} is not writable"
        export_code = ExitCode.ERROR

    try:
        usage = shutil.disk_usage(probe_dir)
        if usage.free < 100 * MB:
            disk_ok = False
            disk_detail = f"{usage.free // MB} MB free (< 100 MB)"
            disk_code = ExitCode.ERROR
        else:
            disk_ok = True
            disk_detail = f"{usage.free // MB} MB free"
            disk_code = 0
    except OSError as e:
        disk_ok = False
        disk_detail = f"cannot check disk space: {e}"
        disk_code = ExitCode.ERROR

    if cache_path().exists():
        with Cache.default() as cache:
            fetched = cache.fetched_at("servers")
        age = (time.time() - fetched) if fetched is not None else None
        cache_detail = _ago(age) if age is not None else "empty"
    else:
        cache_detail = "no cache file"
    cache_ok = True
    cache_code = 0

    version_ok = True
    version_detail = __version__
    version_code = 0

    update_result = _doctor_update_check()
    update_ok = True
    update_detail = update_check.format_doctor_detail(update_result)
    update_code = 0
    _attach_doctor_update_handle(out, update_result)

    checks = [
        ("login", login_ok, login_detail, login_code),
        ("network", network_ok, network_detail, network_code),
        ("export_dir", export_ok, export_detail, export_code),
        ("disk_space", disk_ok, disk_detail, disk_code),
        ("cache", cache_ok, cache_detail, cache_code),
        ("version", version_ok, version_detail, version_code),
        ("update", update_ok, update_detail, update_code),
    ]

    if out.plain:
        for name, ok, detail, _ in checks:
            print(f"{name}\t{'OK' if ok else 'FAIL'}\t{detail}")
    else:
        out.rows(
            ("check", "status", "detail"),
            [(name, "OK" if ok else "FAIL", detail) for name, ok, detail, _ in checks],
            title="discoop doctor",
        )

    first_failed = next((code for _, ok, _, code in checks if not ok), 0)
    raise typer.Exit(code=int(first_failed))


@app.command("agent-guide")
def agent_guide_cmd(ctx: typer.Context) -> None:
    """Print reference guide and instructions for AI agents."""
    sys.stdout.write(agent_guide.build_guide(app))
    sys.stdout.flush()


@app.command()
def servers(
    ctx: typer.Context,
    refresh: bool = _REFRESH_OPTION,
    output_format: str = typer.Option("text", "--format", help="Output format: text or json."),
) -> None:
    """List your servers: name, ID and member count."""
    out: Output = ctx.obj
    fmt = _parse_list_format(output_format)
    with _directory() as directory:
        items = directory.servers(refresh=refresh)
        age = directory.cache_age("servers")
    if fmt == "json":
        out.json([{"id": s.id, "name": s.name, "member_count": s.member_count} for s in items])
    else:
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
    output_format: str = typer.Option("text", "--format", help="Output format: text or json."),
) -> None:
    """List the channels of a server, grouped by category."""
    out: Output = ctx.obj
    fmt = _parse_list_format(output_format)
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
    if fmt == "json":
        out.json([
            {
                "id": c.id,
                "name": c.name,
                "type": c.type,
                "type_name": c.type_name,
                "category": category.name if category else None,
                "position": c.position,
            }
            for category, members in groups
            for c in members
        ])
    elif out.agent or flat:
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


@app.command()
def threads(
    ctx: typer.Context,
    channel: str = typer.Option(..., "--channel", "-c", help="Channel name or ID.", show_default=False),
    server: str | None = _SERVER_OPTION,
    from_: str | None = typer.Option(
        None, "--from", metavar="WHEN", help="Start of the window, or all. Default: 30d.", show_default=False
    ),
    to: str | None = typer.Option(
        None, "--to", metavar="WHEN", help="End of the window. Default: now.", show_default=False
    ),
    refresh: bool = _REFRESH_OPTION,
    output_format: str = typer.Option("text", "--format", help="Output format: text or json."),
) -> None:
    """List the threads and forum posts of a channel."""
    out: Output = ctx.obj
    fmt = _parse_list_format(output_format)
    effective_from = from_ if from_ is not None else "30d"
    window = parse_window(effective_from, to, now=utc_now(), tz=LOCAL_ZONE)

    with _directory() as directory:
        channel_query = channel.strip()
        if channel_query.isdigit() and server is None:
            target_channel = directory.channel_by_id(channel_query)
        else:
            target_server = directory.server(_server_query(server))
            matches = directory.find_channels(target_server, channel_query)
            if len(matches) > 1:
                raise DiscoopError(
                    ExitCode.BAD_ARGS,
                    f'"{channel}" matches {len(matches)} channels: {", ".join("#" + c.name for c in matches[:5])}.',
                    "Specify a single channel.",
                )
            target_channel = matches[0]

        if not is_thread_container(target_channel.type):
            raise DiscoopError(
                ExitCode.BAD_ARGS,
                f"#{target_channel.name} is a {target_channel.type_name} channel: it cannot have threads.",
                "Only text, announcement, forum and media channels can have threads.",
            )

        fetched = directory.threads(target_channel, window, refresh=refresh)
        age = directory.cache_age(f"threads:{target_channel.id}")

    if fetched.problem:
        out.warning(f"Threads in #{target_channel.name}: {fetched.problem}.")

    items = fetched.threads
    if fmt == "json":
        out.json([
            {
                "id": t.id,
                "name": t.name,
                "parent_id": t.parent_id,
                "type": t.type,
                "archived": t.archived,
                "locked": t.locked,
                "message_count": t.message_count,
                "created": t.created.isoformat(),
                "last_activity": t.last_activity.isoformat(),
                "tags": list(target_channel.tag_names(t.applied_tags)),
            }
            for t in items
        ])
    else:
        rows = [
            (
                t.id,
                "yes" if t.archived else "no",
                t.message_count if t.message_count is not None else "",
                to_local(t.last_activity, LOCAL_ZONE).strftime("%Y-%m-%d %H:%M"),
                ", ".join(target_channel.tag_names(t.applied_tags)),
                t.name,
            )
            for t in items
        ]
        out.rows(
            ("id", "archived", "messages", "last_activity", "tags", "name"),
            rows,
            title=f"Threads in #{target_channel.name} ({len(items)})",
        )
        _cache_note(out, age)


@app.command(help=MESSAGES_HELP)
def messages(
    ctx: typer.Context,
    channel: list[str] | None = typer.Option(
        None,
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
    threads: bool = typer.Option(
        True,
        "--threads/--no-threads",
        help="Download thread messages and forum posts too (default). Threads add many requests: a large forum is slow in safe mode.",
    ),
    since_last: bool = typer.Option(
        False,
        "--since-last",
        help="Fetch messages newer than the last successful sync.",
    ),
    max_tokens: int | None = typer.Option(
        None,
        "--max-tokens",
        metavar="N",
        help="With --out/--zip: also write parts/part-NNN.md, messages.md split into parts of at most N estimated tokens.",
        show_default=False,
    ),
    profile: str | None = typer.Option(
        None,
        "--profile",
        metavar="NAME",
        help="Load options (server, channels, time window, mode) from a saved profile.",
        show_default=False,
    ),
    save_profile: str | None = typer.Option(
        None,
        "--save-profile",
        metavar="NAME",
        help="Save options (server, channels, time window, mode) as a profile.",
        show_default=False,
    ),
    safe: bool = typer.Option(False, "--safe", help="Human-like slow download with random pauses (default)."),
    fast: bool = typer.Option(False, "--fast", help="Fast download with 100 messages per request and fixed delay."),
    delay: float | None = typer.Option(
        None,
        "--delay",
        metavar="SEC",
        help="Pacing delay (seconds). Default 1.0; scales pauses in safe mode.",
        show_default=False,
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
    progress_json: bool = typer.Option(
        False, "--progress-json", help="Write machine-readable progress events (JSON lines) to stderr."
    ),
) -> None:
    out: Output = ctx.obj
    output_format = _parse_format(output_format)
    if profile is not None:
        saved_profiles = profiles.load()
        if profile not in saved_profiles:
            available = profiles.names()
            matches = difflib.get_close_matches(profile, available, n=3, cutoff=0.6)
            hint_parts = []
            if matches:
                hint_parts.append(f"Did you mean: {', '.join(matches)}?")
            if available:
                hint_parts.append(f"Available profiles: {', '.join(available)}.")
            else:
                hint_parts.append("No profiles saved yet.")
            hint = " ".join(hint_parts)
            raise DiscoopError(ExitCode.BAD_ARGS, f'Unknown profile "{profile}".', hint)
        prof = saved_profiles[profile]
        if not server and "server" in prof:
            server = prof["server"]
        if not channel and "channels" in prof and prof["channels"]:
            channel = list(prof["channels"])
        if from_ is None and "from" in prof:
            from_ = prof["from"]
        if to is None and "to" in prof:
            to = prof["to"]
        if last is None and "last" in prof:
            last = prof["last"]
        if not safe and not fast and "mode" in prof and prof["mode"] in ("safe", "fast"):
            selected_mode = prof["mode"]
        else:
            selected_mode = "safe" if safe else ("fast" if fast else (Config.default().get("mode") or "safe"))
    else:
        selected_mode = "safe" if safe else ("fast" if fast else (Config.default().get("mode") or "safe"))

    if not channel:
        raise DiscoopError(
            ExitCode.BAD_ARGS,
            "Missing option '--channel' / '-c'.",
            "Specify --channel / -c CHANNEL, or use --profile NAME.",
        )

    if max_tokens is not None:
        if max_tokens < 1:
            raise DiscoopError(ExitCode.BAD_ARGS, "--max-tokens must be at least 1.")
        if out_dir is None and zip_file is None:
            raise DiscoopError(
                ExitCode.BAD_ARGS,
                "--max-tokens only works with --out or --zip.",
                "Export with --out DIR or --zip FILE, which gets the parts/ too.",
            )

    if since_last and (from_ is not None or to is not None or last is not None):
        raise DiscoopError(
            ExitCode.BAD_ARGS,
            "--since-last cannot be combined with --from, --to or --last.",
            "Drop --since-last to use a time window, or remove the time options.",
        )
    if safe and fast:
        raise DiscoopError(ExitCode.BAD_ARGS, "--safe and --fast cannot be used together.", "Choose one of them.")

    effective_delay = delay if delay is not None else Config.default().get("delay")

    if save_profile is not None:
        profile_data: dict[str, Any] = {
            "server": server,
            "channels": list(channel),
            "from": from_,
            "to": to,
            "last": last,
            "mode": selected_mode,
        }
        to_save = {k: v for k, v in profile_data.items() if v is not None}
        try:
            profiles.save(save_profile, to_save)
        except ValueError as e:
            raise DiscoopError(ExitCode.BAD_ARGS, str(e))

    request = MessagesRequest(
        channels=tuple(channel),
        server=server,
        from_=from_,
        to=to,
        last=last,
        max_messages=max_messages,
        include_system=include_system,
        mode=selected_mode,
        delay=effective_delay,
        out_dir=out_dir,
        zip_file=zip_file,
        print_messages=print_messages,
        no_files=no_files,
        max_file_size=max_file_size,
        output_format=output_format,
        threads=threads,
        since_last=since_last,
        max_tokens=max_tokens,
    )
    try:
        window = parse_window(from_, to, now=utc_now(), tz=LOCAL_ZONE, whole_history=last is not None)
    except DiscoopError:
        window = None

    events = _CliEvents(out, tz=LOCAL_ZONE, window=window, last=last, progress_json=progress_json)
    try:
        with _directory(delay=effective_delay, mode=selected_mode) as directory:
            outcome = run_messages(
                request,
                directory=directory,
                cdn=cdn_client,
                now=utc_now(),
                tz=LOCAL_ZONE,
                events=events,
                export_dir=Config.default().get("export-dir"),
                default_server=Config.default().get("default-server"),
            )
    finally:
        events.close()
    if outcome.exported is None:
        _print_messages(out, outcome.results, outcome.query, output_format)
    else:
        if print_messages:
            _print_messages(out, outcome.exported.results, outcome.query, output_format)
        _export_report(out, outcome.exported, summary_on_stdout=not print_messages)
    if from_ is None and last is None and not since_last and not progress_json:
        out.note("Messages from the last 24 hours. For more use --from 7d, --from 2026-10-01 or --from all.")
    if outcome.partial:
        if not progress_json:
            out.note(_partial_advice(outcome))
        raise typer.Exit(code=int(ExitCode.PARTIAL))


@config_app.command("list")
def config_list(
    ctx: typer.Context,
    output_format: str = typer.Option("text", "--format", help="Output format: text or json."),
) -> None:
    """Show all settings and their current values."""
    out: Output = ctx.obj
    fmt = _parse_list_format(output_format)
    config = Config.default()
    if fmt == "json":
        out.json({key: config.get(key) for key in DESCRIPTIONS})
    else:
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
    """Change a setting. default-server is stored as the server ID, export-dir and browser-path as absolute paths."""
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


@profiles_app.callback(invoke_without_command=True)
def profiles_root(
    ctx: typer.Context,
    output_format: str = typer.Option("text", "--format", help="Output format: text or json."),
) -> None:
    """List or delete saved profiles."""
    if ctx.invoked_subcommand is None:
        _maybe_start_update_check(ctx, command_name="profiles")
        _list_profiles(ctx, output_format)


@profiles_app.command("list")
def profiles_list(
    ctx: typer.Context,
    output_format: str = typer.Option("text", "--format", help="Output format: text or json."),
) -> None:
    """List saved profile names."""
    _list_profiles(ctx, output_format)


@profiles_app.command("delete")
def profiles_delete(
    ctx: typer.Context,
    name: str = typer.Argument(..., help="Profile name to delete."),
) -> None:
    """Delete a saved profile."""
    out: Output = ctx.obj
    try:
        deleted = profiles.delete(name)
    except ValueError as e:
        raise DiscoopError(ExitCode.BAD_ARGS, str(e))
    if not deleted:
        raise DiscoopError(ExitCode.NOT_FOUND, f'Profile "{name}" does not exist.')
    out.message(f'Profile "{name}" deleted.')


def _list_profiles(ctx: typer.Context, output_format: str) -> None:
    out: Output = ctx.obj
    fmt = _parse_list_format(output_format)
    names = profiles.names()
    if fmt == "json":
        out.json(names)
    else:
        if out.plain:
            for name in names:
                print(name)
        else:
            if names:
                out.rows(("name",), [(name,) for name in names], title=f"Saved profiles ({len(names)})")
            else:
                out.note("No profiles saved yet.")


def display_name(user: dict[str, Any]) -> str:
    username = user.get("username", "?")
    global_name = user.get("global_name")
    return f"{global_name} (@{username})" if global_name else f"@{username}"


def _open_api(delay: float | None = None, mode: str | None = None) -> DiscordAPI:
    stored = TokenStore.default().load()
    if stored is None:
        raise auth_required()
    config = Config.default()
    actual_delay = delay if delay is not None else config.get("delay")
    actual_mode = mode if mode is not None else config.get("mode")
    return DiscordAPI(stored.token, delay=actual_delay, mode=actual_mode)


@contextmanager
def _directory(delay: float | None = None, mode: str | None = None) -> Iterator[Directory]:
    with Cache.default() as cache, Directory(cache, lambda: _open_api(delay=delay, mode=mode)) as directory:
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


def _read_messages_md(exported: export.Exported) -> str:
    if exported.path.is_dir():
        md_file = exported.path / "messages.md"
        if md_file.is_file():
            try:
                return md_file.read_text(encoding="utf-8")
            except OSError:
                pass
    elif exported.path.is_file() and zipfile.is_zipfile(exported.path):
        try:
            with zipfile.ZipFile(exported.path) as zf:
                if "messages.md" in zf.namelist():
                    return zf.read("messages.md").decode("utf-8")
        except Exception:
            pass
    try:
        from discoop.render import Query
        from discoop.snowflake import Window
        return text_render.markdown(exported.results, Query(Window(None, None)))
    except Exception:
        return ""


def _export_report(out: Output, exported: export.Exported, summary_on_stdout: bool) -> None:
    """The summary (stdout, or a stderr note when --print put the messages there) and warnings about files.

    The totals are those of the whole export (its manifest): after a resumed run `exported.results` only has the
    channels fetched by that run.
    """
    jobs = exported.jobs
    counts = {status: exported.count(status) for status in (DOWNLOADED, PRESENT, FAILED, SKIPPED)}
    totals = exported.manifest.get("counts", {})
    channels = totals.get("channels", len(exported.results))
    messages = totals.get("messages", sum(len(r.messages) for r in exported.results)) + totals.get("thread_messages", 0)
    truncated = exported.manifest.get("truncated", any(r.truncated for r in exported.results))
    channels_skipped = len(exported.skipped)
    md_text = _read_messages_md(exported)
    est = tokens.estimate_tokens(md_text)
    if summary_on_stdout:
        summary = {
            "export": exported.path,
            "channels": channels,
            "messages": messages,
            "tokens": f"~{tokens.format_tokens(est)} (estimate, about 4 characters per token)",
            "files": len(jobs),
            "downloaded": counts[DOWNLOADED],
            "already_present": counts[PRESENT],
            "failed": counts[FAILED],
            "skipped": counts[SKIPPED],
            "truncated": "yes" if truncated else "no",
        }
        if channels_skipped:  # "skipped" above counts files
            summary["channels_skipped"] = channels_skipped
        out.fields(summary, title="Export")
    else:
        skipped_text = f", {channels_skipped} channels skipped" if channels_skipped else ""
        out.note(
            f"Exported to {exported.path}: {channels} channels, {messages} messages, {len(jobs)} files"
            f" ({counts[DOWNLOADED]} downloaded, {counts[PRESENT]} already present, {counts[FAILED]} failed,"
            f" {counts[SKIPPED]} skipped), tokens: ~{tokens.format_tokens(est)}{skipped_text}."
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


def _partial_advice(outcome: MessagesOutcome) -> str:
    """Why the exit code is 9 and what to do. Saved files are kept, so a second run only does the missing part."""
    parts = []
    if outcome.skipped:
        parts.append(f"{len(outcome.skipped)} {'channel' if len(outcome.skipped) == 1 else 'channels'} skipped")
    if outcome.thread_problems:
        parts.append(
            f"{outcome.thread_problems} {'thread problem' if outcome.thread_problems == 1 else 'thread problems'}"
        )
    failed = outcome.exported.count(FAILED) if outcome.exported is not None else 0
    if failed:
        parts.append(f"{failed} {'file' if failed == 1 else 'files'} not downloaded")
    advice = "Run the same command again to try them again"
    advice += "; files already saved are not downloaded again." if outcome.exported is not None else "."
    return f"Partial result (exit code {int(ExitCode.PARTIAL)}): {', '.join(parts)}. {advice}"


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


class _CliEvents(Events):
    """Event handler for the CLI: progress indicators, notes, warnings."""

    def __init__(
        self,
        out: Output,
        tz: tzinfo | None = None,
        window: Window | None = None,
        last: int | None = None,
        progress_json: bool = False,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        plain_progress = out.agent or getattr(out, "debug", False)
        if progress_json:
            downloads = DownloadProgress()
        elif plain_progress:
            downloads = _AgentDownloads(out)
        else:
            downloads = _HumanDownloads(out)
        super().__init__(downloads=downloads)
        self.out = out
        self.tz = tz
        self.window = window
        self.last = last
        self.progress_json = progress_json
        self._clock = clock
        self._status = None
        self._label = ""
        self._channel_id: str | None = None
        self._index: int = 0
        self._total: int = 0
        self._started_at: float | None = None
        self._start_id: int | None = None
        self._end_id: int | None = None

    def _emit_json(self, data: dict[str, Any]) -> None:
        print(json.dumps(data, ensure_ascii=False), file=sys.stderr)

    def channel_start(self, index: int, total: int, server: Server, channel: Channel) -> None:
        self._index = index
        self._total = total
        self._channel_id = channel.id
        self._started_at = self._clock()
        self._start_id = window_start_id(self.window, channel.id, last=self.last) if self.window is not None else None
        self._end_id = self.window.before_id if self.window is not None else None
        self._label = f"#{channel.name} ({channel.id}) in {server.name}"

        if self.progress_json:
            self._emit_json({
                "event": "channel_start",
                "index": index,
                "total": total,
                "channel_id": channel.id,
            })
            return

        if self.out.agent or getattr(self.out, "debug", False):
            self.out.note(f"Fetching {self._label}")
        else:
            if self._status is not None:
                self._status.stop()
            self._status = self.out.err_console.status(f"Fetching {self._label}")
            self._status.start()

    def thread(self, index: int, total: int, channel: Channel, thread: Thread) -> None:
        if self.progress_json:
            self._emit_json({
                "event": "thread",
                "index": index,
                "total": total,
                "channel_id": channel.id,
                "thread_id": thread.id,
            })
            return

        msg = f"Fetching #{channel.name} — thread {index} of {total}: {thread.name}"
        if self._status is not None:
            self._status.update(f"{msg}...")
        if self.out.verbose or self.out.agent or getattr(self.out, "debug", False):
            self.out.note(msg)

    def page(self, kept: int, oldest_id: int) -> None:
        frac = (
            fraction_done(self._start_id, self._end_id, oldest_id)
            if (self._start_id is not None and self._end_id is not None)
            else None
        )
        elapsed = (self._clock() - self._started_at) if self._started_at is not None else 0.0
        eta = eta_seconds(elapsed, frac)

        if self.progress_json:
            self._emit_json({
                "event": "page",
                "index": self._index,
                "total": self._total,
                "channel_id": self._channel_id,
                "messages": kept,
                "oldest_id": str(oldest_id),
                "fraction": frac,
                "eta_seconds": eta,
            })
            return

        time_str = to_local(to_time(oldest_id), self.tz).strftime("%Y-%m-%d %H:%M")
        extra = ""
        if frac is not None and round(frac * 100) >= 1:
            pct = round(frac * 100)
            eta_str = format_eta(eta) if (eta is not None and eta > 0) else ""
            if eta_str:
                extra = f", ~{pct}%, about {eta_str} left"
            else:
                extra = f", ~{pct}%"

        msg = f"Fetching {self._label}: {kept} messages, back to {time_str}{extra}"
        if self.out.agent or getattr(self.out, "debug", False):
            self.out.note(msg)
        elif self._status is not None:
            self._status.update(msg)

    def pause(self, seconds: float, reason: str) -> None:
        if self.progress_json:
            self._emit_json({
                "event": "pause",
                "index": self._index,
                "total": self._total,
                "channel_id": self._channel_id,
                "seconds": round(seconds, 3),
                "reason": reason,
            })
            return

        if self.out.agent or getattr(self.out, "debug", False):
            self.out.note(f"Pausing {seconds:.1f}s ({reason})")
        elif self._status is not None:
            prefix = f"Fetching {self._label}: " if self._label else ""
            self._status.update(f"{prefix}pausing {seconds:.1f}s ({reason})")

    def channel_done(self, result: ChannelMessages) -> None:
        if self._status is not None:
            self._status.stop()
            self._status = None

        if self.progress_json:
            self._emit_json({
                "event": "channel_done",
                "index": self._index,
                "total": self._total,
                "channel_id": result.channel.id,
                "messages": len(result.messages),
                "files": sum(len(m.attachments) for m in result.messages),
                "truncated": result.truncated,
            })

    def skipped(self, error: DiscoopError) -> None:
        if self._status is not None:
            self._status.stop()
            self._status = None

        if self.progress_json:
            self._emit_json({
                "event": "skipped",
                "index": self._index,
                "total": self._total,
                "channel_id": self._channel_id,
                "code": error.name,
            })
            return

        self.out.warning(f"Skipped: {error.message}")

    def warning(self, text: str) -> None:
        if self.progress_json:
            self._emit_json({
                "event": "warning",
                "index": self._index,
                "total": self._total,
                "channel_id": self._channel_id,
            })
            return

        self.out.warning(text)

    def note(self, text: str) -> None:
        if self.progress_json:
            return
        self.out.note(text)

    def resumed(self, done: int, total: int) -> None:
        if self.progress_json:
            self._emit_json({"event": "resumed", "done": done, "total": total})
            return
        self.out.note(f"Continuing an unfinished export: {done} of {total} channels are already saved.")

    def interrupted(self, saved: int, total: int, path: Path) -> None:
        if self._status is not None:
            self._status.stop()
            self._status = None

        if self.progress_json:
            self._emit_json({"event": "interrupted", "saved": saved, "total": total})
            return

        self.out.warning(f"Saved {saved} of {total} channels in {path}. Run the same command again to continue.")

    def close(self) -> None:
        if self._status is not None:
            self._status.stop()
            self._status = None


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


def _update_transport() -> httpx.BaseTransport | None:
    """Return an optional httpx transport override for update checks (test seam)."""
    return None


def _stderr_is_tty() -> bool:
    stream = sys.stderr
    if stream is None:
        return False
    isatty = getattr(stream, "isatty", None)
    if not callable(isatty):
        return False
    try:
        return bool(isatty())
    except Exception:
        return False


def _is_machine_output_ctx(ctx: click.Context) -> bool:
    cur: click.Context | None = ctx
    while cur is not None:
        if bool(cur.params.get("progress_json")):
            return True
        fmt = cur.params.get("output_format")
        if fmt is None:
            fmt = cur.params.get("format")
        if isinstance(fmt, str) and fmt.strip().lower() in ("json", "jsonl"):
            return True
        cur = cur.parent
    return False


def _start_cli_update_check() -> update_check.BackgroundUpdateCheck:
    return update_check.start_background_check(transport=_update_transport())


# Top-level commands that never start the CLI background check (and so never print the notice): `ui` runs its own
# check, `doctor` checks fresh in its `update` row, and `config` only manages settings (so `config set update-check
# off` never makes the request it is turning off).
_NO_BACKGROUND_CHECK = frozenset({"ui", "doctor", "config"})


def _top_level_command_name(ctx: click.Context) -> str | None:
    """Name of the subcommand directly under `discoop` that `ctx` belongs to (`config` for `discoop config set`)."""
    cur = ctx
    while cur.parent is not None and cur.parent.parent is not None:
        cur = cur.parent
    if cur.parent is None:
        return None
    return cur.command.name or cur.info_name


def _maybe_start_update_check(ctx: click.Context, *, command_name: str | None = None) -> None:
    out = ctx.find_object(Output)
    if out is None or getattr(out, "_update_handle", None) is not None:
        return
    name = command_name if command_name is not None else (ctx.command.name or ctx.info_name)
    if name in _NO_BACKGROUND_CHECK or _top_level_command_name(ctx) in _NO_BACKGROUND_CHECK:
        return
    if not _stderr_is_tty() or _is_machine_output_ctx(ctx):
        return
    try:
        if update_check.is_cli_disabled():
            return
        out._update_handle = _start_cli_update_check()  # type: ignore[attr-defined]
    except Exception as exc:
        update_check.logger.debug("Could not start update check: %s", exc)


def _doctor_update_check() -> update_check.CheckResult:
    try:
        return update_check.check_for_update(
            force=True,
            include_ci=False,
            transport=_update_transport(),
        )
    except Exception as exc:
        update_check.logger.debug("Doctor update check failed unexpectedly: %s", exc)
        return update_check.CheckResult(status=update_check.STATUS_ERROR, error=str(exc) or "unexpected error")


def _attach_doctor_update_handle(out: Output, result: update_check.CheckResult) -> None:
    if result.update is None:
        return
    if not _stderr_is_tty():
        return
    try:
        if update_check.is_cli_disabled():
            return
        cache = update_check.load_cache()
        out._update_handle = update_check.BackgroundUpdateCheck(  # type: ignore[attr-defined]
            cache_path=update_check.update_cache_path(),
            now=None,
            check_now=time.time(),
            result=result,
            notified_at=cache.notified_at,
        )
    except Exception as exc:
        update_check.logger.debug("Could not attach doctor update handle: %s", exc)


def _finish_cli_update_check(out: Output) -> None:
    handle: update_check.BackgroundUpdateCheck | None = getattr(out, "_update_handle", None)
    if handle is None:
        return
    try:
        info = handle.wait(timeout=CLI_NOTICE_WAIT_TIMEOUT)
        if info is None:
            return
        out.update_notice(update_check.format_cli_notice_lines(info))
        handle.mark_notified()
    except Exception as exc:
        update_check.logger.debug("CLI update notice failed: %s", exc)


def main(argv: list[str] | None = None) -> None:
    args = _hoist_mode_flags(list(sys.argv[1:] if argv is None else argv))
    plain = detect_plain_mode("--plain" in args, "--human" in args, agent_flag="--agent" in args)
    if plain:
        _use_utf8_streams()
    out = Output(plain=plain)
    out.debug = False
    out._update_handle = None  # type: ignore[attr-defined]
    for typer_app in (app, config_app, profiles_app):
        typer_app.rich_markup_mode = None if plain else "rich"
    app.info.help = _help_text(plain)
    exit_code = 0
    show_notice = True
    try:
        try:
            code = app(args=args, prog_name="discoop", standalone_mode=False, obj=out)
            exit_code = code if isinstance(code, int) else 0
        except DiscoopError as e:
            out.error(e)
            exit_code = int(e.code)
        except typer.TyperException as e:
            show_notice = False
            # Typer's usage errors (unknown command, bad option) carry exit_code 2.
            if getattr(e, "exit_code", 1) == 2:
                out.error(DiscoopError(ExitCode.BAD_ARGS, e.format_message(), "Run `discoop --help`."))
                exit_code = int(ExitCode.BAD_ARGS)
            else:
                out.error(DiscoopError(ExitCode.ERROR, e.format_message()))
                exit_code = int(ExitCode.ERROR)
        except (typer.Abort, KeyboardInterrupt):
            show_notice = False
            out.error(DiscoopError(ExitCode.ERROR, "Interrupted."))
            exit_code = 130
        if show_notice and exit_code != 130:
            _finish_cli_update_check(out)
        sys.exit(exit_code)
    finally:
        logs.teardown_logging()


def _hoist_mode_flags(args: list[str]) -> list[str]:
    """Accept global flags anywhere (`discoop status --agent`), as agents often put them last."""
    end = args.index("--") if "--" in args else len(args)
    flags: list[str] = []
    rest: list[str] = []
    i = 0
    while i < end:
        a = args[i]
        if a in _MODE_FLAGS:
            flags.append(a)
            i += 1
        elif a == "--log":
            flags.append(a)
            if i + 1 < end:
                flags.append(args[i + 1])
                i += 2
            else:
                i += 1
        elif a.startswith("--log="):
            flags.append(a)
            i += 1
        else:
            rest.append(a)
            i += 1
    return flags + rest + args[end:]


def _help_text(plain: bool) -> str:
    sections = [GETTING_STARTED, OUTPUT_MODES, AI_NOTE]
    if plain:
        # Click rewraps paragraphs unless they start with \b; Rich keeps line breaks on its own.
        sections = ["\b\n" + s for s in sections]
    return "\n\n".join([SUMMARY, *sections])


def _use_utf8_streams() -> None:
    for stream in (sys.stdout, sys.stderr):
        if not stream.isatty() and hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")


def command_help(path: Sequence[str] = ()) -> str:
    """Return plain-text help string for the command or root if path is empty."""
    old_help = app.info.help
    old_app_mode = app.rich_markup_mode
    old_config_mode = config_app.rich_markup_mode
    old_profiles_mode = profiles_app.rich_markup_mode
    try:
        app.rich_markup_mode = None
        config_app.rich_markup_mode = None
        profiles_app.rich_markup_mode = None
        app.info.help = _help_text(True)
        cmd = typer.main.get_command(app)
        ctx = click.Context(cmd, info_name="discoop")
        for name in path:
            sub = cmd.get_command(ctx, name)
            if sub is None:
                raise DiscoopError(ExitCode.BAD_ARGS, f"Unknown command: {name}")
            ctx = click.Context(sub, info_name=name, parent=ctx)
            cmd = sub
        return cmd.get_help(ctx)
    finally:
        app.info.help = old_help
        app.rich_markup_mode = old_app_mode
        config_app.rich_markup_mode = old_config_mode
        profiles_app.rich_markup_mode = old_profiles_mode
