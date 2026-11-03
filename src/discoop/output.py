"""Output modes: rich output for humans, plain text for AI agents and scripts.

Data goes to stdout, everything else (notes, errors) to stderr, in both modes.
"""

import os
import sys
from collections.abc import Iterable, Mapping, Sequence
from typing import TextIO

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from discoop.errors import DiscoopError

PLAIN_ENV = "DISCOOP_PLAIN"
AGENT_ENV = "DISCOOP_AGENT"
_TRUTHY = {"1", "true", "yes", "on"}


def detect_plain_mode(
    plain_flag: bool = False,
    human_flag: bool = False,
    *,
    agent_flag: bool = False,
    env: Mapping[str, str] = os.environ,
    stdout: TextIO | None = None,
) -> bool:
    """--human wins, then --plain / --agent, then DISCOOP_PLAIN / DISCOOP_AGENT, then "stdout is not a terminal"."""
    if human_flag:
        return False
    if plain_flag or agent_flag:
        return True
    if env.get(PLAIN_ENV, "").strip().lower() in _TRUTHY:
        return True
    if env.get(AGENT_ENV, "").strip().lower() in _TRUTHY:
        return True
    stream = stdout if stdout is not None else sys.stdout
    return not stream.isatty()


# Alias for backward compatibility
detect_agent_mode = detect_plain_mode


class Output:
    def __init__(self, plain: bool | None = None, agent: bool | None = None, verbose: bool = False) -> None:
        if plain is not None:
            self._plain = bool(plain)
        elif agent is not None:
            self._plain = bool(agent)
        else:
            self._plain = False
        self.verbose = verbose
        self.console = Console(highlight=False)
        self.err_console = Console(stderr=True, highlight=False)

    @property
    def plain(self) -> bool:
        return self._plain

    @plain.setter
    def plain(self, value: bool) -> None:
        self._plain = bool(value)

    @property
    def agent(self) -> bool:
        """Alias for backward compatibility."""
        return self._plain

    @agent.setter
    def agent(self, value: bool) -> None:
        self._plain = bool(value)

    def fields(self, values: Mapping[str, object], title: str | None = None) -> None:
        """Key/value result: `key: value` lines for plain mode, a small table for humans."""
        if self._plain:
            for key, value in values.items():
                print(f"{key}: {value}")
            return
        table = Table.grid(padding=(0, 2))
        table.add_column(style="bold cyan")
        table.add_column()
        for key, value in values.items():
            table.add_row(key.replace("_", " "), Text(str(value)))
        self.console.print(Panel(table, title=title, expand=False) if title else table)

    def rows(self, columns: Sequence[str], rows: Iterable[Sequence[object]], title: str | None = None) -> None:
        """Tabular result: a header plus tab-separated lines for plain mode, a table for humans."""
        if self._plain:
            print("\t".join(columns))
            for row in rows:
                print("\t".join("" if value is None else str(value).replace("\t", " ") for value in row))
            return
        table = Table(title=title, title_justify="left", header_style="bold")
        for column in columns:
            table.add_column("ID" if column == "id" else column.replace("_", " ").capitalize())
        for row in rows:
            table.add_row(*(Text("" if value is None else str(value)) for value in row))
        self.console.print(table)

    def message(self, text: str, style: str | None = None) -> None:
        """A one-line result (stdout)."""
        if self._plain:
            print(text)
        else:
            self.console.print(Text(text, style=style or ""))

    def note(self, text: str) -> None:
        """Progress or advice (stderr). Plain mode only sees it with --verbose."""
        if self._plain:
            if self.verbose:
                print(text, file=sys.stderr)
        else:
            self.err_console.print(Text(text, style="dim"))

    def warning(self, text: str) -> None:
        """Something about the result that must not go unnoticed (stderr, also without --verbose)."""
        if self._plain:
            print(f"WARNING: {text}", file=sys.stderr)
        else:
            self.err_console.print(Text("Warning: ", style="bold yellow") + Text(text))

    def error(self, err: DiscoopError) -> None:
        if self._plain:
            print(f"ERROR {err.name}: {err.message}", file=sys.stderr)
            if err.hint:
                print(f"HINT: {err.hint}", file=sys.stderr)
            return
        line = Text("Error: ", style="bold red") + Text(err.message)
        self.err_console.print(line)
        if err.hint:
            self.err_console.print(Text("Hint: ", style="bold") + Text(err.hint))
