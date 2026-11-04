from datetime import UTC, datetime

from discoop.progress import eta_seconds, format_eta, fraction_done, window_start_id
from discoop.snowflake import Window, from_time


def test_fraction_done_bounds_and_clamping():
    # Regular midpoint
    assert fraction_done(1000, 2000, 1500) == 0.5

    # At the start of pagination (oldest_id == end_id)
    assert fraction_done(1000, 2000, 2000) == 0.0

    # At the end of pagination (oldest_id == start_id)
    assert fraction_done(1000, 2000, 1000) == 1.0

    # Clamping outside [0.0, 1.0]
    assert fraction_done(1000, 2000, 500) == 1.0
    assert fraction_done(1000, 2000, 2500) == 0.0

    # Invalid / undefined window
    assert fraction_done(None, 2000, 1500) is None
    assert fraction_done(2000, 2000, 1500) is None
    assert fraction_done(3000, 2000, 1500) is None


def test_window_start_id():
    now = datetime(2026, 11, 4, 12, 0, tzinfo=UTC)
    start = datetime(2026, 11, 3, 12, 0, tzinfo=UTC)
    window_timed = Window(start=start, end=now)
    window_all = Window(start=None, end=now)

    # When --last is specified, window_start_id is None
    assert window_start_id(window_timed, "123456", last=50) is None
    assert window_start_id(window_all, "123456", last=10) is None

    # Timed window returns from_time(window.start)
    assert window_start_id(window_timed, "123456") == from_time(start)

    # Whole history returns channel ID as integer
    assert window_start_id(window_all, "123456789") == 123456789
    assert window_start_id(window_all, 123456789) == 123456789

    # Invalid channel ID with start=None returns None safely
    assert window_start_id(window_all, "invalid-id") is None


def test_eta_seconds():
    # None or invalid fraction / elapsed
    assert eta_seconds(10.0, None) is None
    assert eta_seconds(0.0, 0.5) is None
    assert eta_seconds(-5.0, 0.5) is None
    assert eta_seconds(10.0, 0.019) is None

    # Threshold fraction 0.02
    assert eta_seconds(10.0, 0.02) == 10.0 * 0.98 / 0.02

    # Normal case: half done after 30s -> 30s remaining
    assert eta_seconds(30.0, 0.5) == 30.0

    # Finished
    assert eta_seconds(30.0, 1.0) == 0.0
    assert eta_seconds(30.0, 1.2) == 0.0


def test_format_eta():
    assert format_eta(None) == ""
    assert format_eta(0) == "0 s"
    assert format_eta(-5) == "0 s"
    assert format_eta(0.2) == "1 s"
    assert format_eta(45) == "45 s"
    assert format_eta(59.4) == "59 s"
    assert format_eta(59.6) == "1 min"
    assert format_eta(60) == "1 min"
    assert format_eta(180) == "3 min"
    assert format_eta(3570) == "1 h 00 min"
    assert format_eta(3600) == "1 h 00 min"
    assert format_eta(3900) == "1 h 05 min"
    assert format_eta(7320) == "2 h 02 min"
