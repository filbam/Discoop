"""Turning fetched messages into output: `text` (plain for agents, styled for humans), `md`, `json` and `jsonl`."""

from dataclasses import dataclass

from discoop.snowflake import Window


@dataclass(frozen=True)
class Query:
    """What was asked for, shown in the output header and kept in an export's manifest."""

    window: Window
    last: int | None = None
    max_messages: int | None = None
    include_system: bool = False
    mode: str = "safe"
