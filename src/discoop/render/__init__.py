"""Turning fetched messages into output: `text` (plain for agents, styled for humans) and `json`."""

from dataclasses import dataclass

from discoop.snowflake import Window


@dataclass(frozen=True)
class Query:
    """What was asked for, shown in the output header."""

    window: Window
    last: int | None = None
    max_messages: int | None = None
