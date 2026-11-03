"""Command line entry point."""

import sys
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import typer
from rich.text import Text
from rich.tree import Tree

from discoop import __version__, login as login_flow, paths
from discoop.api import DiscordAPI
from discoop.cache import Cache, clear_cache
from discoop.config import DESCRIPTIONS, Config, check_key, parse_delay
from discoop.directory import Directory
from discoop.errors import DiscoopError, ExitCode, auth_required
from discoop.models import LISTABLE_TYPES, Channel, group_by_category
from discoop.output import Output, detect_agent_mode
from discoop.tokenstore import TokenStore

SUMMARY = "Download messages and files from Discord servers you are a member of."

GETTING_STARTED = """\
GETTING STARTED
  discoop login                    log in by scanning a QR code with the Discord app
  discoop servers                  list your servers
  discoop channels -s "VUT FIT"    list the channels of a server
  discoop config set default-server "VUT FIT"
                                   after that, --server can be left out
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
    """Change a setting. default-server is resolved and stored as the server ID."""
    out: Output = ctx.obj
    config = Config.default()
    check_key(key)
    if key == "default-server":
        with _directory() as directory:
            target = directory.server(value)
        config.set(key, target.id)
        out.message(f"default-server = {target.id} ({target.name})")
    else:
        config.set(key, parse_delay(value))
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
