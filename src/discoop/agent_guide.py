"""Reference guide for AI agents interacting with discoop."""

from typing import Any
import typer

from discoop.errors import ExitCode

# Stable descriptions for ExitCode enum members.
# Any newly added code to ExitCode will still be included automatically.
_EXIT_CODE_DESCRIPTIONS: dict[ExitCode, str] = {
    ExitCode.OK: "Success (everything requested was completed).",
    ExitCode.ERROR: "Unexpected runtime error (`login --browser`: no usable browser or no desktop session).",
    ExitCode.AUTH_REQUIRED: (
        "Not logged in (see LOGGING IN, never log in yourself). `login --browser`: window closed or time ran out."
    ),
    ExitCode.AMBIGUOUS: "Ambiguous server or channel name (multiple matches).",
    ExitCode.NOT_FOUND: "Server or channel not found.",
    ExitCode.NO_ACCESS: "No access to channel (HTTP 403 / missing permissions).",
    ExitCode.RATE_LIMITED: "Rate limited or aborted due to rate limits (retry or increase delay).",
    ExitCode.NETWORK: "Network error or connection failure.",
    ExitCode.BAD_ARGS: "Invalid command line arguments or options.",
    ExitCode.PARTIAL: "Partial success: finished, but some channels were skipped or files failed.",
}


def _extract_doc(val: Any) -> str:
    """Extract the first non-empty line of text from a help string or docstring."""
    if isinstance(val, str) and val.strip():
        for line in val.strip().splitlines():
            cleaned = line.strip().rstrip("\b").strip()
            if cleaned:
                return cleaned
    return ""


def _format_commands(app: typer.Typer) -> list[str]:
    """Dynamically list all registered non-hidden commands and groups from a Typer app."""
    items: list[tuple[str, str]] = []

    for cmd in getattr(app, "registered_commands", []):
        if getattr(cmd, "hidden", False):
            continue
        name = cmd.name or (cmd.callback.__name__.replace("_", "-") if getattr(cmd, "callback", None) else "")
        if not name:
            continue
        desc = (
            _extract_doc(getattr(cmd, "short_help", None))
            or _extract_doc(getattr(cmd, "help", None))
            or (_extract_doc(cmd.callback.__doc__) if getattr(cmd, "callback", None) else "")
        )
        items.append((name, desc))

    for grp in getattr(app, "registered_groups", []):
        if getattr(grp, "hidden", False):
            continue
        typer_inst = getattr(grp, "typer_instance", None)
        info = getattr(typer_inst, "info", None) if typer_inst else None
        name = grp.name or (getattr(info, "name", None) if info else "")
        if not name:
            continue
        desc = (
            _extract_doc(getattr(grp, "short_help", None))
            or _extract_doc(getattr(grp, "help", None))
            or (_extract_doc(getattr(info, "short_help", None)) if info else "")
            or (_extract_doc(getattr(info, "help", None)) if info else "")
            or (_extract_doc(grp.callback.__doc__) if getattr(grp, "callback", None) else "")
        )
        items.append((name, desc))

    if not items:
        return ["  (no commands registered)"]

    max_len = max(len(name) for name, _ in items)
    max_len = max(max_len, 12)

    lines: list[str] = []
    for name, desc in items:
        if desc:
            lines.append(f"  discoop {name:<{max_len}}  {desc}")
        else:
            lines.append(f"  discoop {name}")
    return lines


def _format_exit_codes() -> list[str]:
    """Dynamically build an exit code table from the ExitCode enum."""
    lines: list[str] = [
        f"  {'Code':<6} {'Name':<15} Description",
        f"  {'-' * 4:<6} {'-' * 13:<15} {'-' * 40}",
    ]
    for code in ExitCode:
        desc = _EXIT_CODE_DESCRIPTIONS.get(code, code.name.replace("_", " ").capitalize() + ".")
        lines.append(f"  {int(code):<6} {code.name:<15} {desc}")
    lines.append(f"  {'130':<6} {'CANCELLED':<15} Interrupted by user (Ctrl+C).")
    return lines


def build_guide(app: typer.Typer) -> str:
    """Build a compact, color-free reference guide for AI agents."""
    commands_block = "\n".join(_format_commands(app))
    exit_codes_block = "\n".join(_format_exit_codes())

    return f"""DISCOOP AI AGENT GUIDE
=======================

Quick reference and execution guidelines for AI coding agents using discoop.

WORKFLOW
--------
Always follow this sequence: status -> servers -> channels -> messages (or threads)

1. Verify authentication status:
     discoop status --plain --format json
   If exit code is 2 (AUTH_REQUIRED), you are not logged in: follow LOGGING IN below.
   Do not run `discoop login` or `discoop login --token` yourself.

2. List available servers:
     discoop servers --plain --format json
   Pick the server by name (e.g. "VUT FIT") or numeric ID.

3. List channels on the target server:
     discoop channels -s "SERVER" --plain --format json

4. (Optional) List threads or forum posts within a channel:
     discoop threads -s "SERVER" -c "CHANNEL" --plain --format json

5. Inspect or export messages:
   - Quick console preview (last 24h by default):
       discoop messages -s "SERVER" -c "CHANNEL" --plain
   - Structured JSON messages (e.g. newest 20 messages):
       discoop messages -s "SERVER" -c "CHANNEL" --last 20 --format json --plain
   - Export messages and attachments with live JSON progress on stderr:
       discoop messages -s "SERVER" -c "CHANNEL" --from 7d --out exports/dir --progress-json --plain
   - Incremental update (download only messages newer than previous export):
       discoop messages -s "SERVER" -c "CHANNEL" --since-last --out exports/dir --plain
   - Export partitioned by token count for LLM context limits:
       discoop messages -s "SERVER" -c "CHANNEL" --from 30d --out exports/dir --max-tokens 50000 --plain

RULES FOR AI AGENTS
-------------------
- Always use --plain (or set DISCOOP_PLAIN=1) for clean, token-efficient text without ANSI escape sequences.
- For listing commands (servers, channels, threads, config list), always specify --format json for structured output.
- Authentication is strictly user-driven: the user logs in, never you. Never run `discoop login` or
  `discoop login --token`, and never prompt for, read, handle, or transmit a password, a token, or a cookie.
  The one login you may run is `discoop --plain login --browser`, and only after the user's explicit consent
  (see LOGGING IN).
- Always run large downloads in the default safe mode (--safe) to emulate human pacing and protect the account from bans.
- If interrupted (Ctrl+C, network error) or if the command exits with code 9 (PARTIAL), re-run the exact same command.
  discoop will automatically resume from `<target>.partial` without re-downloading already completed channels.

LOGGING IN (needs the human)
----------------------------
If a command exits with code 2 you are not logged in, and only the user can fix that.

A. Browser window (needs the user's explicit consent first):
   1. Tell the user, in plain words, that `discoop login --browser` will open a browser window (Chrome, Edge,
      Chromium or Brave) in which THEY log in themselves, with their password or the QR code shown on the web
      page, and solve a captcha if Discord shows one. You never see the password or the token. On Windows a
      passkey (Windows Security) dialog may appear; they can cancel it and log in another way.
   2. Wait for the user's explicit consent in the chat. Do not run the command before they agree.
   3. Run:  discoop --plain login --browser    (optionally with --format json --progress-json)
      A human is logging in, so it can take up to 5 minutes (--timeout SECONDS, default 300, allowed 30 to 1800).
      Give your shell a timeout longer than that, or run the command in the background and wait until it finishes.
      --progress-json prints one JSON event per line on stderr: browser_launch, browser_open, token_captured, logged_in.
   4. While the window is open, never type into it or click in it, and never read the token, the cookies or the
      browser profile. Discoop reads the token itself, verifies it, stores it and closes the window.
   5. Result:
        exit code 0  logged in. Check with `discoop --plain status`.
        exit code 2  the window was closed or the time ran out. Tell the user and ask whether to try again.
        exit code 1  no usable browser (or no desktop session). Ask the user to run `discoop login` or
                     `discoop login --token` in their own terminal.
B. Ask the user to run `discoop login` (QR code) in their own terminal.

COMMANDS
--------
{commands_block}

Run `discoop <command> --help` for detailed command options.

EXIT CODES
----------
{exit_codes_block}
"""
