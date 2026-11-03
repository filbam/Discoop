"""Turning what the user typed (ID, name, pattern) into servers and channels.

Rules (docs/navrh-nastroja.md, section 5): exact ID, then exact name, then normalized name
(case, diacritics and emoji ignored, so "aeu-private" finds "aeu-private🔒"), and glob
patterns where several results are fine. Several equally good matches are an error, never a guess.
"""

import fnmatch
import unicodedata
from collections.abc import Callable, Sequence
from typing import Protocol, TypeVar

from discoop.errors import DiscoopError, ExitCode

_GLOB_CHARS = "*?[]"
_MAX_CANDIDATES_SHOWN = 10


class Named(Protocol):
    id: str
    name: str


T = TypeVar("T", bound=Named)


class NotFoundError(DiscoopError):
    def __init__(self, kind: str, query: str, hint: str | None = None) -> None:
        super().__init__(ExitCode.NOT_FOUND, f'No {kind} matches "{query}".', hint)


def normalize(name: str, keep: str = "") -> str:
    """Lowercase, no diacritics, no emoji or symbols, single spaces."""
    chars = []
    for ch in unicodedata.normalize("NFKD", name):
        if unicodedata.combining(ch):
            continue
        if ch.isalnum() or ch in "-_." or ch in keep:
            chars.append(ch)
        elif ch.isspace():
            chars.append(" ")
    return " ".join("".join(chars).casefold().split())


def is_pattern(query: str) -> bool:
    return any(ch in query for ch in _GLOB_CHARS)


def resolve_one(query: str, items: Sequence[T], kind: str, describe: Callable[[T], str]) -> T:
    query = query.strip()
    if query.isdigit():
        for item in items:
            if item.id == query:
                return item
        raise NotFoundError(kind, query)
    exact = [item for item in items if item.name == query]
    if len(exact) == 1:
        return exact[0]
    if not exact:
        wanted = normalize(query)
        exact = [item for item in items if normalize(item.name) == wanted]
        if len(exact) == 1:
            return exact[0]
    if exact:
        raise ambiguous(kind, query, exact, describe)
    raise NotFoundError(kind, query)


def resolve_many(query: str, items: Sequence[T], kind: str, describe: Callable[[T], str]) -> list[T]:
    """Like resolve_one, but a glob pattern (`isc-*`) may match several items."""
    if not is_pattern(query):
        return [resolve_one(query, items, kind, describe)]
    pattern = normalize(query, keep=_GLOB_CHARS)
    matches = [item for item in items if fnmatch.fnmatchcase(normalize(item.name), pattern)]
    if not matches:
        raise NotFoundError(kind, query)
    return matches


def ambiguous(kind: str, query: str, candidates: Sequence[T], describe: Callable[[T], str]) -> DiscoopError:
    lines = [f"  {describe(c)}" for c in candidates[:_MAX_CANDIDATES_SHOWN]]
    if len(candidates) > _MAX_CANDIDATES_SHOWN:
        lines.append(f"  ... and {len(candidates) - _MAX_CANDIDATES_SHOWN} more")
    return DiscoopError(
        ExitCode.AMBIGUOUS,
        f'"{query}" matches {len(candidates)} {kind}s:\n' + "\n".join(lines),
        "Use the ID instead, or narrow it down with --server.",
    )
