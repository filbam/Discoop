"""Time and Discord snowflakes: parsing --from/--to and turning the window into message IDs.

A snowflake carries its creation time in the top bits: `ms = (id >> 22) + DISCORD_EPOCH_MS`
(docs/analyses/discord-analysis.md, section 11). A time becomes a synthetic snowflake with the
lower 22 bits set to zero, which is what `before=` needs.

Times without a zone are local time. `tz=None` means the system zone with the right DST offset
for each date; tests pass a fixed zone instead.
"""

import re
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta, tzinfo

from discoop.errors import DiscoopError, ExitCode

DISCORD_EPOCH_MS = 1420070400000
_EPOCH = datetime.fromtimestamp(DISCORD_EPOCH_MS / 1000, tz=UTC)
_RELATIVE = re.compile(r"^(\d+)\s*([a-z]+)$")
_UNITS = {"h": "hours", "d": "days", "w": "weeks"}
DEFAULT_SPAN = timedelta(hours=24)  # ADR 0011
WHEN_FORMATS = "a date (2026-10-01), a date and time (2026-10-01T14:00), 48h, 7d, 2w"


@dataclass(frozen=True)
class Window:
    """Messages with start <= time < end; start None means the whole history."""

    start: datetime | None
    end: datetime
    min_id: int | None = None

    @property
    def after_id(self) -> int | None:
        """Lowest message ID inside the window (inclusive)."""
        if self.min_id is not None:
            return self.min_id
        return None if self.start is None else from_time(self.start)

    @property
    def before_id(self) -> int:
        """IDs below this are older than `end`."""
        return from_time(self.end)


def utc_now() -> datetime:
    return datetime.now(UTC)


def from_time(when: datetime) -> int:
    """Synthetic snowflake for a time (lower 22 bits zero). Times before 2015 give 0."""
    ms = (when - _EPOCH) // timedelta(milliseconds=1)
    return max(ms, 0) << 22


def to_time(snowflake: int | str) -> datetime:
    """Creation time (UTC) stored in a snowflake."""
    ms = (int(snowflake) >> 22) + DISCORD_EPOCH_MS
    return datetime.fromtimestamp(ms / 1000, tz=UTC)


def localize(naive: datetime, tz: tzinfo | None = None) -> datetime:
    """Attach a zone to a wall-clock time typed by the user."""
    return naive.astimezone() if tz is None else naive.replace(tzinfo=tz)


def to_local(when: datetime, tz: tzinfo | None = None) -> datetime:
    return when.astimezone(tz)


def parse_when(raw: str, option: str, *, now: datetime, tz: tzinfo | None = None, end: bool = False) -> datetime:
    """One --from/--to value. With end=True a bare date means the end of that day (the next midnight)."""
    text = raw.strip().lower()
    if text == "now":
        return now
    relative = _RELATIVE.match(text)
    if relative:
        amount, unit = relative.groups()
        if unit not in _UNITS:
            raise _bad_when(raw, option, f'Unknown unit "{unit}": use h (hours), d (days) or w (weeks).')
        return now - timedelta(**{_UNITS[unit]: int(amount)})
    try:
        day = date.fromisoformat(text)
    except ValueError:
        pass
    else:
        midnight = datetime(day.year, day.month, day.day) + (timedelta(days=1) if end else timedelta())
        return localize(midnight, tz)
    try:
        moment = datetime.fromisoformat(raw.strip())
    except ValueError:
        raise _bad_when(raw, option) from None
    return localize(moment, tz) if moment.tzinfo is None else moment


def parse_window(
    from_raw: str | None, to_raw: str | None, *, now: datetime, tz: tzinfo | None = None, whole_history: bool = False
) -> Window:
    """--from/--to into a window. Without --from: the 24 h before the end, or the whole history if whole_history."""
    if to_raw is not None and to_raw.strip().lower() == "all":
        raise DiscoopError(ExitCode.BAD_ARGS, '"all" only works with --from.', "Leave --to out to end now.")
    end = now if to_raw is None else parse_when(to_raw, "--to", now=now, tz=tz, end=True)
    if from_raw is None:
        start = None if whole_history else end - DEFAULT_SPAN
    elif from_raw.strip().lower() == "all":
        start = None
    else:
        start = parse_when(from_raw, "--from", now=now, tz=tz)
    if start is not None and start >= end:
        raise DiscoopError(
            ExitCode.BAD_ARGS,
            f"--from ({_show(start, tz)}) must be before --to ({_show(end, tz)}).",
            "A bare date in --to includes that whole day.",
        )
    return Window(start, end)


def _show(when: datetime, tz: tzinfo | None) -> str:
    return to_local(when, tz).strftime("%Y-%m-%d %H:%M")


def _bad_when(raw: str, option: str, detail: str | None = None) -> DiscoopError:
    message = f'Cannot read {option} "{raw}".' + (f" {detail}" if detail else "")
    hint = f"Use {WHEN_FORMATS}, now" + (" or all." if option == "--from" else ".")
    return DiscoopError(ExitCode.BAD_ARGS, message, hint)
