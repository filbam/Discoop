"""Download progress calculations and ETA formatting."""

from discoop.snowflake import Window, from_time


def fraction_done(start_id: int | None, end_id: int, oldest_id: int) -> float | None:
    """Fraction of the ID window already fetched (0.0 to 1.0).

    Pagination moves backward from newest to oldest message, so the fraction completed
    is (end_id - oldest_id) / (end_id - start_id).
    """
    if start_id is None or end_id <= start_id:
        return None
    fraction = (end_id - oldest_id) / (end_id - start_id)
    return min(1.0, max(0.0, float(fraction)))


def window_start_id(window: Window, channel_id: str | int, last: int | None = None) -> int | None:
    """Oldest message snowflake for progress calculation.

    Returns None when --last is specified (since message count is requested rather than a time window).
    For time windows with a start, returns the synthetic snowflake for window.start.
    For whole-history scraping (start is None), Discord channels begin at channel creation,
    encoded in the channel snowflake itself.
    """
    if last is not None:
        return None
    if window.start is not None:
        return from_time(window.start)
    try:
        return int(channel_id)
    except (ValueError, TypeError):
        return None


def eta_seconds(elapsed: float, fraction: float | None) -> float | None:
    """Estimated remaining time in seconds based on elapsed time and progress fraction."""
    if fraction is None or elapsed <= 0 or fraction < 0.02:
        return None
    if fraction >= 1.0:
        return 0.0
    return max(0.0, elapsed * (1.0 - fraction) / fraction)


def format_eta(seconds: float | None) -> str:
    """Format ETA seconds into human-readable string (e.g. '45 s', '3 min', '1 h 05 min')."""
    if seconds is None:
        return ""
    if seconds <= 0:
        return "0 s"
    if seconds < 60:
        sec = max(1, round(seconds))
        if sec < 60:
            return f"{sec} s"
    total_minutes = round(seconds / 60)
    if total_minutes < 60:
        return f"{total_minutes} min"
    hours = total_minutes // 60
    minutes = total_minutes % 60
    return f"{hours} h {minutes:02d} min"
