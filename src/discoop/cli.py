"""Command line entry point."""

import sys
from pathlib import Path
from typing import Any

import typer

from discoop import __version__, login as login_flow, paths
from discoop.api import DiscordAPI
from discoop.errors import DiscoopError, ExitCode, auth_required
from discoop.output import Output, detect_agent_mode
from discoop.tokenstore import TokenStore

SUMMARY = "Download messages and files from Discord servers you are a member of."

GETTING_STARTED = """\
GETTING STARTED
  discoop login     log in by scanning a QR code with the Discord mobile app
  discoop status    check that the stored login still works
  discoop logout    forget the stored login on this computer"""

OUTPUT_MODES = """\
OUTPUT MODES
  Human mode (default in a terminal): colors, tables, progress.
  Agent mode (--agent, DISCOOP_AGENT=1, or when output is not a terminal):
  plain text, no formatting, fewer tokens, machine-readable errors
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

app = typer.Typer(
    add_completion=False,
    pretty_exceptions_enable=False,
    context_settings={"help_option_names": ["-h", "--help"]},
)


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
    """Forget the stored login on this computer."""
    out: Output = ctx.obj
    removed = TokenStore.default().delete()
    out.message("Logged out." if removed else "Not logged in, nothing to remove.")
    out.note("The Discord session stays active until you remove it in Discord: Settings > Devices.")


def display_name(user: dict[str, Any]) -> str:
    username = user.get("username", "?")
    global_name = user.get("global_name")
    return f"{global_name} (@{username})" if global_name else f"@{username}"


def main(argv: list[str] | None = None) -> None:
    args = _hoist_mode_flags(list(sys.argv[1:] if argv is None else argv))
    agent = detect_agent_mode("--agent" in args, "--human" in args)
    if agent:
        _use_utf8_streams()
    out = Output(agent=agent)
    app.rich_markup_mode = None if agent else "rich"
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
