from datetime import UTC, datetime, timedelta, timezone

import pytest

from discoop.errors import DiscoopError, ExitCode
from discoop.snowflake import Window, from_time, parse_when, parse_window, to_time

CET = timezone(timedelta(hours=1))
NOW = datetime(2026, 11, 3, 11, 0, tzinfo=UTC)  # 12:00 CET


def test_snowflake_time_matches_the_analysis():
    # docs/analyzy/discord-analyza.md, section 11
    assert to_time("1566570336659439696") == datetime(2026, 11, 1, 21, 51, 13, 729000, tzinfo=UTC)
    assert from_time(datetime(2026, 10, 1, 22, 0, tzinfo=UTC)) == 1555338520166400000


def test_snowflake_round_trip_and_ordering():
    when = datetime(2026, 10, 12, 14, 3, 7, 250000, tzinfo=UTC)
    assert to_time(from_time(when)) == when
    # A real message ID in the same millisecond has lower bits set, so it is >= the synthetic one.
    assert from_time(when) | 12345 >= from_time(when)
    assert from_time(when + timedelta(milliseconds=1)) > from_time(when) | ((1 << 22) - 1)


def test_times_before_discord_existed_give_zero():
    assert from_time(datetime(2010, 1, 1, tzinfo=UTC)) == 0


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("48h", NOW - timedelta(hours=48)),
        ("7d", NOW - timedelta(days=7)),
        ("2w", NOW - timedelta(weeks=2)),
        ("7 D", NOW - timedelta(days=7)),
        ("now", NOW),
        ("2026-10-01", datetime(2026, 10, 1, tzinfo=CET)),
        ("2026-10-01T14:00", datetime(2026, 10, 1, 14, 0, tzinfo=CET)),
        ("2026-10-01 14:00", datetime(2026, 10, 1, 14, 0, tzinfo=CET)),
        ("2026-10-01T14:00:30", datetime(2026, 10, 1, 14, 0, 30, tzinfo=CET)),
        ("2026-10-01T14:00Z", datetime(2026, 10, 1, 14, 0, tzinfo=UTC)),
        ("2026-10-01T14:00+02:00", datetime(2026, 10, 1, 12, 0, tzinfo=UTC)),
    ],
)
def test_parse_when(raw, expected):
    assert parse_when(raw, "--from", now=NOW, tz=CET) == expected


def test_bare_date_as_end_includes_the_whole_day():
    assert parse_when("2026-10-31", "--to", now=NOW, tz=CET, end=True) == datetime(2026, 11, 1, tzinfo=CET)
    assert parse_when("2026-10-31T18:00", "--to", now=NOW, tz=CET, end=True) == datetime(2026, 10, 31, 18, tzinfo=CET)


def test_system_zone_is_used_without_tz():
    parsed = parse_when("2026-10-01T14:00", "--from", now=NOW)
    assert parsed.tzinfo is not None
    assert parsed.replace(tzinfo=None) == datetime(2026, 10, 1, 14, 0)


@pytest.mark.parametrize("raw", ["yesterday", "1m", "10min", "2026-13-01", "7", "", "d7"])
def test_bad_when(raw):
    with pytest.raises(DiscoopError) as e:
        parse_when(raw, "--from", now=NOW, tz=CET)
    assert e.value.code == ExitCode.BAD_ARGS
    assert "48h" in e.value.hint


def test_default_window_is_24_hours():
    window = parse_window(None, None, now=NOW, tz=CET)
    assert window == Window(NOW - timedelta(hours=24), NOW)
    assert window.after_id == from_time(NOW - timedelta(hours=24))
    assert window.before_id == from_time(NOW)


def test_default_window_ends_at_to():
    window = parse_window(None, "2026-10-31", now=NOW, tz=CET)
    assert window == Window(datetime(2026, 10, 31, tzinfo=CET), datetime(2026, 11, 1, tzinfo=CET))


def test_whole_history():
    assert parse_window("all", None, now=NOW, tz=CET) == Window(None, NOW)
    assert parse_window("ALL", "2026-10-31", now=NOW, tz=CET) == Window(None, datetime(2026, 11, 1, tzinfo=CET))
    assert parse_window(None, None, now=NOW, tz=CET, whole_history=True).start is None
    assert Window(None, NOW).after_id is None


def test_absolute_window():
    window = parse_window("2026-10-01", "2026-10-31", now=NOW, tz=CET)
    assert window == Window(datetime(2026, 10, 1, tzinfo=CET), datetime(2026, 11, 1, tzinfo=CET))


@pytest.mark.parametrize(
    ("from_raw", "to_raw", "text"),
    [
        (None, "all", '"all" only works with --from'),
        ("2026-10-31", "2026-10-01", "must be before --to"),
        ("now", None, "must be before --to"),
        ("2026-11-03T12:00", "2026-11-03T12:00", "must be before --to"),
    ],
)
def test_bad_windows(from_raw, to_raw, text):
    with pytest.raises(DiscoopError) as e:
        parse_window(from_raw, to_raw, now=NOW, tz=CET)
    assert e.value.code == ExitCode.BAD_ARGS
    assert text in e.value.message
