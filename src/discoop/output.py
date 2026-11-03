"""Output modes: rich output for humans, plain text for AI agents.

Data goes to stdout, everything else (notes, errors) to stderr, in both modes.
"""

import os
import sys
from collections.abc import Mapping
from typing import TextIO

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from discoop.errors import DiscoopError

AGENT_ENV = "DISCOOP_AGENT"
_TRUTHY = {"1", "true", "yes", "on"}


def detect_agent_mode(
    agent_flag: bool,
    human_flag: bool,
    *,
    env: Mapping[str, str] = os.environ,
    stdout: TextIO | None = None,
) -> bool:
    """--human wins, then --agent, then DISCOOP_AGENT, then "stdout is not a terminal"."""
    if human_flag:
        return False
    if agent_flag:
        return True
    if env.get(AGENT_ENV, "").strip().lower() in _TRUTHY:
        return True
    stream = stdout if stdout is not None else sys.stdout
    return not stream.isatty()


class Output:
    def __init__(self, agent: bool, verbose: bool = False) -> None:
        self.agent = agent
        self.verbose = verbose
        self.console = Console(highlight=False)
        self.err_console = Console(stderr=True, highlight=False)

    def fields(self, values: Mapping[str, object], title: str | None = None) -> None:
        """Key/value result: `key: value` lines for agents, a small table for humans."""
        if self.agent:
            for key, value in values.items():
                print(f"{key}: {value}")
            return
        table = Table.grid(padding=(0, 2))
        table.add_column(style="bold cyan")
        table.add_column()
        for key, value in values.items():
            table.add_row(key.replace("_", " "), Text(str(value)))
        self.console.print(Panel(table, title=title, expand=False) if title else table)

    def message(self, text: str, style: str | None = None) -> None:
        """A one-line result (stdout)."""
        if self.agent:
            print(text)
        else:
            self.console.print(Text(text, style=style or ""))

    def note(self, text: str) -> None:
        """Progress or advice (stderr). Agents only see it with --verbose."""
        if self.agent:
            if self.verbose:
                print(text, file=sys.stderr)
        else:
            self.err_console.print(Text(text, style="dim"))

    def error(self, err: DiscoopError) -> None:
        if self.agent:
            print(f"ERROR {err.name}: {err.message}", file=sys.stderr)
            if err.hint:
                print(f"HINT: {err.hint}", file=sys.stderr)
            return
        line = Text("Error: ", style="bold red") + Text(err.message)
        self.err_console.print(line)
        if err.hint:
            self.err_console.print(Text("Hint: ", style="bold") + Text(err.hint))
