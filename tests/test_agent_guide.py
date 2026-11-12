"""Tests for the discoop agent-guide module."""

import re
from pathlib import Path

import typer

from discoop.agent_guide import build_guide
from discoop.cli import app as cli_app
from discoop.errors import ExitCode

SKILL_FILE = Path(__file__).resolve().parent.parent / ".claude" / "skills" / "discoop" / "SKILL.md"

# The rule for AI agents about logging in (requirement P33, ADR 0022). `discoop agent-guide` and the skill say the same
# thing in their own layout, so every phrase must be in both. Case, line breaks and Markdown backticks do not count.
RULE_PHRASES = (
    "never run discoop login or discoop login --token",
    "discoop login --browser will open a browser window (chrome, edge, chromium or brave)",
    "in which they log in themselves",
    "you never see the password or the token",
    "passkey",
    "explicit consent",
    "discoop --plain login --browser",
    "--format json --progress-json",
    "browser_launch, browser_open, token_captured, logged_in",
    "up to 5 minutes",
    "--timeout seconds, default 300, allowed 30 to 1800",
    "give your shell a timeout longer than that, or run the command in the background and wait until it finishes",
    "never type into it or click in it",
    "never read the token, the cookies or the browser profile",
    "the window was closed or the time ran out",
    "no usable browser",
    "ask the user to run discoop login or discoop login --token in their own terminal",
)

# The rule for AI agents about update notices (requirement P34, ADR 0025).
UPDATE_RULE_PHRASES = (
    "update notice is informational",
    "normally appears only in a terminal",
    "discoop doctor",
    "update row",
    "newer release",
    "tell the user",
    "never run uv tool upgrade or uv tool install",
    "never reinstall discoop yourself",
)


def normalized(text: str) -> str:
    return " ".join(text.replace("`", "").lower().split())


def test_cli_app_commands_and_groups_are_all_present():
    """Every registered, non-hidden command and group in cli.app must appear in the guide."""
    guide = build_guide(cli_app)

    # Check non-hidden commands
    for cmd in cli_app.registered_commands:
        if getattr(cmd, "hidden", False):
            continue
        cmd_name = cmd.name or (cmd.callback.__name__.replace("_", "-") if getattr(cmd, "callback", None) else "")
        assert cmd_name, f"Command {cmd} has no name"
        assert cmd_name in guide, f"Command '{cmd_name}' missing from agent guide"

    # Check non-hidden groups
    for grp in cli_app.registered_groups:
        if getattr(grp, "hidden", False):
            continue
        typer_inst = getattr(grp, "typer_instance", None)
        info = getattr(typer_inst, "info", None) if typer_inst else None
        grp_name = grp.name or (getattr(info, "name", None) if info else "")
        assert grp_name, f"Group {grp} has no name"
        assert grp_name in guide, f"Group '{grp_name}' missing from agent guide"


def test_dynamic_command_addition():
    """Adding a new command to a fresh Typer app must automatically appear in the guide with its help."""
    test_app = typer.Typer()

    @test_app.command()
    def custom_sync():
        """Synchronize repository data with remote archive."""
        pass

    guide = build_guide(test_app)
    assert "custom-sync" in guide
    assert "Synchronize repository data with remote archive." in guide


def test_dynamic_group_addition():
    """Adding a new group to a fresh Typer app must automatically appear in the guide with its help."""
    test_app = typer.Typer()
    sub_app = typer.Typer(help="Manage configuration profiles.")
    test_app.add_typer(sub_app, name="custom-profiles")

    guide = build_guide(test_app)
    assert "custom-profiles" in guide
    assert "Manage configuration profiles." in guide


def test_hidden_commands_and_groups_are_excluded():
    """Commands and groups marked hidden must not appear in the guide."""
    test_app = typer.Typer()

    @test_app.command(hidden=True)
    def secret_cmd():
        """This is secret."""
        pass

    @test_app.command()
    def visible_cmd():
        """This is visible."""
        pass

    hidden_sub = typer.Typer(help="Hidden group help.")
    test_app.add_typer(hidden_sub, name="hidden-grp", hidden=True)

    guide = build_guide(test_app)
    assert "secret-cmd" not in guide
    assert "hidden-grp" not in guide
    assert "visible-cmd" in guide
    assert "This is visible." in guide


def test_all_exit_codes_present():
    """Every member of ExitCode enum must have its integer value and name in the guide."""
    guide = build_guide(cli_app)

    for code in ExitCode:
        assert str(int(code)) in guide, f"Exit code {int(code)} missing from guide"
        assert code.name in guide, f"Exit code name {code.name} missing from guide"

    # Specifically check PARTIAL / 9 and cancellation 130
    assert "PARTIAL" in guide
    assert "9" in guide
    assert "130" in guide


def test_workflow_steps_and_flags():
    """The guide must contain the fixed workflow sequence and required flags."""
    guide = build_guide(cli_app)

    # Fixed workflow progression
    for step in ("status", "servers", "channels", "messages"):
        assert step in guide

    # Progression order
    status_pos = guide.find("status")
    servers_pos = guide.find("servers", status_pos)
    channels_pos = guide.find("channels", servers_pos)
    messages_pos = guide.find("messages", channels_pos)
    assert -1 not in (status_pos, servers_pos, channels_pos, messages_pos)

    # Required flags and concepts
    assert "--plain" in guide
    assert "--format json" in guide
    assert "--progress-json" in guide
    assert "--out" in guide
    assert "--since-last" in guide
    assert "--max-tokens" in guide
    assert "threads" in guide


def test_agent_rules():
    """The guide must state rules on login, token secrecy, safe mode, and partial export resumes."""
    guide = build_guide(cli_app)

    assert "discoop login" in guide
    assert "--safe" in guide
    assert ".partial" in guide
    # Rule regarding not asking for or sending tokens
    assert "token" in guide.lower()


def test_the_guide_tells_agents_how_to_log_in_with_the_users_consent():
    """Login needs the human: the guide names the browser login, the consent, the window rules and the timeout."""
    guide = build_guide(cli_app)
    text = normalized(guide)

    for phrase in RULE_PHRASES:
        assert phrase in text, f"the guide lacks: {phrase}"

    # the order of the steps: tell the user, wait for the consent, only then run the command
    tell = text.index("tell the user, in plain words, that discoop login --browser will open a browser window")
    wait = text.index("wait for the user's explicit consent in the chat")
    run_it = text.index("run: discoop --plain login --browser")
    assert tell < wait < run_it
    assert "do not run the command before they agree" in text

    # the section sits between the rules and the command list, and the exit codes point to it
    heading = guide.index("LOGGING IN (needs the human)\n---")
    assert guide.index("RULES FOR AI AGENTS") < heading < guide.index("COMMANDS\n--------")
    exit_codes = guide[guide.index("EXIT CODES\n---"):]
    assert "see LOGGING IN" in exit_codes and "`login --browser`" in exit_codes

    # the old advice to run `discoop login` is gone from the workflow: the agent follows LOGGING IN instead
    workflow = guide[: guide.index("RULES FOR AI AGENTS")]
    assert "follow LOGGING IN below" in workflow
    assert "ask the user to run `discoop login` in their terminal" not in guide


def test_the_login_command_is_listed_with_the_browser_option():
    login_line = next(line for line in build_guide(cli_app).splitlines() if line.startswith("  discoop login "))
    assert "--browser" in login_line and "--token" in login_line


def test_the_skill_carries_the_same_login_rule_as_the_guide():
    """No test read the skill before, and the two had drifted apart once: they must keep the same login rule."""
    assert SKILL_FILE.is_file(), f"the skill is missing: {SKILL_FILE}"
    skill = SKILL_FILE.read_text(encoding="utf-8")
    assert skill.startswith("---\nname: discoop\n")  # the front matter is intact
    text = normalized(skill)
    for phrase in RULE_PHRASES:
        assert phrase in text, f"the skill lacks: {phrase}"
    # and it does not say any more that login is the user's QR code alone
    assert "never log in for the user" not in text
    assert "do not run `login`" not in skill


def test_the_guide_and_skill_carry_the_same_update_rule():
    """Both `discoop agent-guide` and `.claude/skills/discoop/SKILL.md` state the update-notice rule."""
    guide_text = normalized(build_guide(cli_app))
    skill = SKILL_FILE.read_text(encoding="utf-8")
    skill_text = normalized(skill)

    for phrase in UPDATE_RULE_PHRASES:
        assert phrase in guide_text, f"the guide lacks: {phrase}"
        assert phrase in skill_text, f"the skill lacks: {phrase}"

    assert "cache, version, update" in skill


def test_the_other_texts_for_agents_say_the_same_in_short():
    """The help note, the login help and the hint of exit code 2 point agents to the browser login and the consent."""
    from discoop import cli, errors

    for name, text in (("AI_NOTE", cli.AI_NOTE), ("LOGIN_HELP", cli.LOGIN_HELP), ("AUTH_HINT", errors.AUTH_HINT)):
        flat = normalized(text)
        assert "login --browser" in flat, name
        assert "consent" in flat, name
        assert "login --token" in flat, name
    assert "discoop --plain login --browser" in normalized(cli.AI_NOTE)
    assert "up to 5 minutes" in normalized(cli.AI_NOTE)


def test_no_ansi_escape_sequences():
    """Output must be plain text without any ANSI escape sequences or color codes."""
    guide = build_guide(cli_app)

    # No ANSI escape character \x1b
    assert "\x1b" not in guide
    # No ANSI CSI sequences \x1b[
    assert not re.search(r"\x1b\[[0-9;]*[a-zA-Z]", guide)


def test_agent_guide_does_not_import_cli():
    """src/discoop/agent_guide.py must not import cli.py at top-level."""
    import inspect
    from discoop import agent_guide

    source = inspect.getsource(agent_guide)
    # Ensure cli is not imported
    assert "import cli" not in source
    assert "from discoop import cli" not in source
    assert "from . import cli" not in source
    assert "from .. import cli" not in source


def test_agent_guide_cli_agent_and_human(capsys):
    """discoop agent-guide via CLI exits 0 and outputs clean text without ANSI in both modes."""
    import pytest
    from discoop import cli

    # 1. Running with --agent
    with pytest.raises(SystemExit) as exc_agent:
        cli.main(["--agent", "agent-guide"])
    assert exc_agent.value.code == 0
    captured_agent = capsys.readouterr()
    assert "DISCOOP AI AGENT GUIDE" in captured_agent.out
    assert "WORKFLOW" in captured_agent.out
    assert "EXIT CODES" in captured_agent.out
    assert "discoop agent-guide" in captured_agent.out
    assert "\x1b" not in captured_agent.out
    assert captured_agent.err == ""

    # 2. Running with --human
    with pytest.raises(SystemExit) as exc_human:
        cli.main(["--human", "agent-guide"])
    assert exc_human.value.code == 0
    captured_human = capsys.readouterr()
    assert "DISCOOP AI AGENT GUIDE" in captured_human.out
    assert "WORKFLOW" in captured_human.out
    assert "EXIT CODES" in captured_human.out
    assert "discoop agent-guide" in captured_human.out
    assert "\x1b" not in captured_human.out
    assert captured_human.err == ""


def test_help_contains_reference_to_agent_guide(capsys):
    """discoop --help contains a reference to agent-guide in both default and plain modes."""
    import pytest
    from discoop import cli

    # Default / human help
    with pytest.raises(SystemExit) as exc_human:
        cli.main(["--help"])
    assert exc_human.value.code == 0
    captured_human = capsys.readouterr()
    assert "agent-guide" in captured_human.out

    # Plain help
    with pytest.raises(SystemExit) as exc_plain:
        cli.main(["--plain", "--help"])
    assert exc_plain.value.code == 0
    captured_plain = capsys.readouterr()
    assert "agent-guide" in captured_plain.out
    assert "discoop agent-guide" in captured_plain.out
    assert "NOTE FOR AI AGENTS" in captured_plain.out
