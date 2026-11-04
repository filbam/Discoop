import sqlite3
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta, timezone

import httpx
import pytest

from discoop.api import BLOCKED_HINT, DiscordAPI
from discoop.cache import Cache, cache_path
from discoop.directory import THREADS_MAX_AGE, Directory
from discoop.errors import DiscoopError, ExitCode
from discoop.models import Channel, ForumTag, Thread, thread_from_api
from discoop.snowflake import Window, to_time
from discoop.threads import (
    MAX_PAGES,
    PAGE_SIZE,
    Stop,
    fetch_all_threads,
    fetch_threads,
    in_window,
    is_thread_container,
)
from fake_messages import FIT, NOW, USER_A
from fake_threads import PARENT, FakeThreadSearch, series, thread

HOUR = timedelta(hours=1)
WEEK = Window(NOW - timedelta(days=7), NOW)
EVERYTHING = Window(None, NOW)
FORUM = Channel(PARENT, FIT, "help-center", 15)


def fetch(search: FakeThreadSearch, window: Window = WEEK, *, archived: bool = True, **kwargs):
    with DiscordAPI("tok", transport=httpx.MockTransport(search.handler())) as api:
        return fetch_threads(api, PARENT, window, archived=archived, **kwargs)


def fetch_all(search: FakeThreadSearch, window: Window = WEEK, **kwargs):
    with DiscordAPI("tok", transport=httpx.MockTransport(search.handler())) as api:
        return fetch_all_threads(api, PARENT, window, **kwargs)


def names(threads) -> list[str]:
    return [t.name for t in threads]


# --- parsing -------------------------------------------------------------------------------------------------------


def test_full_payload_is_parsed():
    data = thread(
        NOW - 2 * HOUR,
        created=NOW - timedelta(days=3),
        seq=7,
        name="Exam question",
        message_count=14,
        applied_tags=["11", "12"],
    )
    data["thread_metadata"]["locked"] = True
    result = thread_from_api(data)
    assert result == Thread(
        id=data["id"],
        parent_id=PARENT,
        name="Exam question",
        type=11,
        created=NOW - timedelta(days=3),
        last_activity=NOW - 2 * HOUR,
        archived=True,
        locked=True,
        message_count=14,
        owner_id=USER_A["id"],
        applied_tags=("11", "12"),
        last_message_id=data["last_message_id"],
    )
    assert result.created.tzinfo is not None and result.last_activity.tzinfo is not None
    assert result.type_name == "thread"


def test_minimal_payload_falls_back_to_the_snowflakes():
    result = thread_from_api({"id": "1521315949171441765"}, parent_id=PARENT)
    created = to_time("1521315949171441765")
    assert result == Thread("1521315949171441765", PARENT, "", 11, created, created)
    assert thread_from_api({"id": "1521315949171441765"}).parent_id == ""


def test_parent_in_the_payload_wins_over_the_argument():
    assert thread_from_api(thread(NOW, parent_id="555"), parent_id=PARENT).parent_id == "555"


def test_null_create_timestamp_uses_the_id():
    data = thread(NOW - HOUR)
    data["thread_metadata"]["create_timestamp"] = None  # threads from before 2022
    assert thread_from_api(data).created == to_time(data["id"])


def test_last_activity_is_never_before_creation():
    data = thread(NOW - timedelta(days=5), created=NOW - HOUR)  # last message older than the thread: a started one
    result = thread_from_api(data)
    assert result.last_activity == result.created == NOW - HOUR


def test_missing_last_message_means_last_activity_is_the_creation():
    result = thread_from_api(thread(NOW, created=NOW - HOUR, last_message_id=None))
    assert result.last_message_id is None and result.last_activity == NOW - HOUR


def test_loose_values_are_tolerated():
    data = {
        "id": "1521315949171441765",
        "type": None,
        "name": None,
        "message_count": "3",
        "applied_tags": None,
        "owner_id": None,
        "last_message_id": None,
        "thread_metadata": {"create_timestamp": "garbage"},
    }
    result = thread_from_api(data, PARENT)
    assert (result.type, result.name, result.message_count, result.applied_tags) == (11, "", None, ())
    assert result.created == to_time(data["id"])
    data["thread_metadata"] = None
    assert thread_from_api(data, PARENT).archived is False
    data["thread_metadata"] = {"create_timestamp": "2026-11-01T10:00:00"}  # no zone: UTC
    assert thread_from_api(data, PARENT).created == datetime(2026, 11, 1, 10, tzinfo=UTC)


def test_other_timezones_are_kept_as_the_same_instant():
    data = thread(NOW)
    data["thread_metadata"]["create_timestamp"] = "2026-11-03T09:00:00+02:00"
    assert thread_from_api(data).created == datetime(2026, 11, 3, 7, tzinfo=UTC)


def test_other_thread_types_and_tags_as_numbers():
    result = thread_from_api(thread(NOW, type=12, applied_tags=[11, 12]))
    assert (result.type, result.type_name, result.applied_tags) == (12, "private-thread", ("11", "12"))


def test_a_thread_needs_a_numeric_id():
    with pytest.raises(KeyError):
        thread_from_api({"name": "no id"})
    with pytest.raises(ValueError):
        thread_from_api({"id": "abc"})


def test_thread_as_channel():
    result = thread_from_api(thread(NOW, seq=3, name="Question"))
    channel = result.as_channel(FIT)
    assert channel == Channel(result.id, FIT, "Question", 11, parent_id=PARENT, last_message_id=result.last_message_id)


def test_tag_names_skip_unknown_ids():
    forum = Channel(PARENT, FIT, "help", 15, available_tags=(ForumTag("11", "Exam"), ForumTag("12", "Project")))
    assert forum.tag_names(["12", "99", "11"]) == ("Project", "Exam")
    assert forum.tag_names([]) == ()
    assert Channel(PARENT, FIT, "x", 0).tag_names(["11"]) == ()


@pytest.mark.parametrize(
    "channel_type, expected", [(t, True) for t in (0, 5, 15, 16)] + [(t, False) for t in (2, 4, 10, 11, 12, 13, 14)]
)
def test_thread_containers(channel_type, expected):
    assert is_thread_container(channel_type) is expected


def test_in_window_needs_activity_since_the_start_and_creation_before_the_end():
    window = Window(NOW - 2 * HOUR, NOW - HOUR)

    def make(last, created):
        return thread_from_api(thread(last, created=created))

    assert in_window(make(NOW, NOW - 3 * HOUR), window)  # active later, but alive during the window
    assert not in_window(make(NOW - 3 * HOUR, NOW - 4 * HOUR), window)  # silent before the start
    assert not in_window(make(NOW, NOW - HOUR), window)  # created exactly at the end
    assert in_window(make(NOW - 2 * HOUR, NOW - 3 * HOUR), window)  # active exactly at the start
    assert in_window(make(NOW - 9 * HOUR, NOW - 10 * HOUR), Window(None, NOW))


# --- paging --------------------------------------------------------------------------------------------------------


def test_request_parameters_follow_the_client():
    search = FakeThreadSearch(series(2, newest=NOW - HOUR, step=HOUR))
    fetch(search, EVERYTHING)
    assert search.requests == [
        {"archived": "true", "sort_by": "last_message_time", "sort_order": "desc", "limit": "25", "offset": "0"}
    ]
    search = FakeThreadSearch([])
    fetch(search, EVERYTHING, archived=False)
    assert search.requests[0]["archived"] == "false"


def test_stops_at_the_start_of_the_window():
    # Last activity 1 h, 3 h, 5 h ... back: 84 of them (up to 167 h) lie inside the 7 days; the one at 169 h is on
    # the fourth page, which ends the listing.
    search = FakeThreadSearch(series(120, newest=NOW - HOUR, step=2 * HOUR))
    result = fetch(search, WEEK)
    assert len(result.threads) == 84
    assert names(result.threads) == [f"thread {i}" for i in range(84)]
    assert result.stop is Stop.WINDOW and result.complete and result.problem is None
    assert result.requests == 4
    assert [r["offset"] for r in search.requests] == ["0", "25", "50", "75"]


def test_a_short_window_needs_one_request():
    search = FakeThreadSearch(series(60, newest=NOW - HOUR, step=12 * HOUR))
    result = fetch(search, WEEK)
    assert len(result.threads) == 14 and result.requests == 1 and result.stop is Stop.WINDOW


def test_the_limit_is_always_25():
    search = FakeThreadSearch(series(60, newest=NOW - HOUR, step=HOUR))
    fetch(search, EVERYTHING)
    assert PAGE_SIZE == 25 and {r["limit"] for r in search.requests} == {"25"}


def test_whole_history_pages_until_a_short_page():
    search = FakeThreadSearch(series(60, newest=NOW - HOUR, step=12 * HOUR))
    result = fetch(search, EVERYTHING)
    assert len(result.threads) == 60 and result.requests == 3  # 25, 25, 10
    assert result.stop is Stop.END and result.total_results == 60
    assert [r["offset"] for r in search.requests] == ["0", "25", "50"]


def test_a_list_that_fills_its_last_page_ends_on_the_empty_one_after_it():
    search = FakeThreadSearch(series(50, newest=NOW - HOUR, step=HOUR))
    result = fetch(search, EVERYTHING)
    assert len(result.threads) == 50 and result.requests == 3
    assert result.stop is Stop.END and result.complete


def test_has_more_true_after_the_last_page_changes_nothing():
    search = FakeThreadSearch(series(60, newest=NOW - HOUR, step=HOUR))
    search.always_has_more = True  # seen at the end of a real list
    result = fetch(search, EVERYTHING)
    assert len(result.threads) == 60 and result.requests == 3 and result.stop is Stop.END


def test_has_more_false_does_not_end_a_listing_with_full_pages():
    search = FakeThreadSearch(series(60, newest=NOW - HOUR, step=HOUR))
    search.never_has_more = True
    result = fetch(search, EVERYTHING)
    assert len(result.threads) == 60 and result.requests == 3 and result.stop is Stop.END


def test_a_missing_has_more_changes_nothing():
    search = FakeThreadSearch(series(60, newest=NOW - HOUR, step=HOUR))
    search.omit_has_more = True
    result = fetch(search, EVERYTHING)
    assert len(result.threads) == 60 and result.requests == 3 and result.stop is Stop.END


def test_total_results_is_only_passed_on():
    search = FakeThreadSearch(series(12, newest=NOW - HOUR, step=HOUR, archived=False))
    search.total_results = 14  # seen: 12 threads, total_results 14
    result = fetch(search, EVERYTHING, archived=False)
    assert len(result.threads) == 12 and result.requests == 1 and result.complete
    assert result.total_results == 14
    search.total_results = 1000
    assert len(fetch(search, EVERYTHING, archived=False).threads) == 12


def test_a_channel_without_threads():
    result = fetch(FakeThreadSearch([]), EVERYTHING)
    assert (result.threads, result.requests, result.stop) == ([], 1, Stop.END)


def test_a_server_that_ignores_the_offset_does_not_loop():
    search = FakeThreadSearch(series(60, newest=NOW - HOUR, step=HOUR))
    search.ignore_offset = True
    result = fetch(search, EVERYTHING)
    assert result.stop is Stop.NO_PROGRESS and not result.complete and result.problem
    assert result.requests == 2 and len(result.threads) == 25


def test_the_page_cap_ends_the_listing():
    search = FakeThreadSearch(series(100, newest=NOW - HOUR, step=HOUR))
    result = fetch(search, EVERYTHING, max_pages=3)
    assert result.stop is Stop.PAGE_CAP and not result.complete and "page limit" in result.problem
    assert result.requests == 3 and len(result.threads) == 75
    assert MAX_PAGES >= 100  # the default cap is a safety net, not a limit in daily use


def test_the_page_cap_is_not_hit_when_the_list_ends_on_its_last_page():
    search = FakeThreadSearch(series(40, newest=NOW - HOUR, step=HOUR))
    result = fetch(search, EVERYTHING, max_pages=2)  # 25, then a short page of 15
    assert result.stop is Stop.END and result.complete and len(result.threads) == 40


def test_overlapping_pages_are_deduplicated():
    search = FakeThreadSearch(series(60, newest=NOW - HOUR, step=HOUR))
    search.overlap = 1  # new activity shifts the list by one between two requests
    result = fetch(search, EVERYTHING)
    assert len(result.threads) == 60 and len({t.id for t in result.threads}) == 60
    assert result.requests == 3 and result.stop is Stop.END


def test_threads_come_out_newest_activity_first_whatever_the_order_of_the_answer():
    threads = series(5, newest=NOW - HOUR, step=HOUR)
    result = fetch(FakeThreadSearch(threads[::-1]), EVERYTHING)
    assert names(result.threads) == [f"thread {i}" for i in range(5)]


def test_threads_created_after_the_window_end_are_skipped_but_paging_goes_on():
    new = series(30, newest=NOW - HOUR, step=HOUR)  # last activity and creation after the end: a whole page of them
    old = series(10, newest=NOW - timedelta(days=4), step=6 * HOUR, first_seq=100)
    window = Window(NOW - timedelta(days=10), NOW - timedelta(days=3))
    search = FakeThreadSearch(new + old)
    result = fetch(search, window)
    assert names(result.threads) == [f"thread {i}" for i in range(100, 110)]
    assert result.requests == 2 and result.stop is Stop.END


def test_private_and_announcement_threads_are_kept():
    threads = [thread(NOW - HOUR, seq=1, type=12), thread(NOW - 2 * HOUR, seq=2, type=10)]
    result = fetch(FakeThreadSearch(threads), EVERYTHING)
    assert [t.type for t in result.threads] == [12, 10]


def test_a_thread_without_a_last_message_does_not_stop_the_listing():
    threads = series(30, newest=NOW - HOUR, step=HOUR)
    unsure = thread(NOW - timedelta(days=20), created=NOW - timedelta(days=30), seq=99, last_message_id=None)
    threads.insert(1, unsure)  # on the first page: its guessed time is before the window, but that proves nothing
    result = fetch(FakeThreadSearch(threads), WEEK)
    assert names(result.threads) == [f"thread {i}" for i in range(30)]  # the unsure one is outside the window
    assert result.requests == 2 and result.stop is Stop.END


def test_malformed_entries_are_skipped():
    good = thread(NOW - HOUR, seq=1)
    search = FakeThreadSearch([])
    search.body = {"threads": ["text", 3, None, {}, {"id": "abc"}, {"id": None}, good], "has_more": False}
    result = fetch(search, EVERYTHING)
    assert names(result.threads) == ["thread 1"] and result.stop is Stop.END


def test_a_page_of_nothing_but_junk_does_not_loop():
    search = FakeThreadSearch([])
    search.body = {"threads": [{}, "x"], "has_more": True}
    result = fetch(search, EVERYTHING)
    assert result.threads == [] and result.requests == 1 and result.stop is Stop.NO_PROGRESS


def test_progress_is_reported_between_pages():
    seen = []
    search = FakeThreadSearch(series(80, newest=NOW - HOUR, step=HOUR))
    fetch(search, EVERYTHING, on_page=lambda kept, requests: seen.append((kept, requests)))
    assert seen == [(25, 1), (50, 2), (75, 3)]  # the fourth page, a short one, ends the listing


# --- HTTP 202, wrong shapes and errors -----------------------------------------------------------------------------


def test_http_202_stops_with_a_clear_result():
    search = FakeThreadSearch(series(5, newest=NOW - HOUR, step=HOUR))
    search.status = 202
    result = fetch(search, EVERYTHING)
    assert result.threads == [] and result.requests == 1
    assert result.stop is Stop.NOT_INDEXED and not result.complete and "202" in result.problem


def test_http_202_after_some_pages_keeps_what_was_found():
    search = FakeThreadSearch(series(60, newest=NOW - HOUR, step=HOUR))
    search.status_at = {2: 202}
    result = fetch(search, EVERYTHING)
    assert len(result.threads) == 25 and result.requests == 2 and result.stop is Stop.NOT_INDEXED


@pytest.mark.parametrize(
    "body", [{"message": "nope"}, [], {"threads": None}, {"threads": {"a": 1}}, "text", 7, {"has_more": True}]
)
def test_an_answer_without_a_threads_list_stops(body):
    search = FakeThreadSearch([])
    search.body = body
    result = fetch(search, EVERYTHING)
    assert result.threads == [] and result.requests == 1
    assert result.stop is Stop.UNEXPECTED and not result.complete and result.problem


def test_an_answer_that_is_not_json_stops():
    search = FakeThreadSearch([])
    search.raw = b"<html>maintenance</html>"
    result = fetch(search, EVERYTHING)
    assert result.requests == 1 and result.stop is Stop.UNEXPECTED


def test_missing_access_is_no_access():
    search = FakeThreadSearch([])
    search.status = 403  # JSON code 50001
    with pytest.raises(DiscoopError) as error:
        fetch(search, label="#help-center")
    assert error.value.code == ExitCode.NO_ACCESS
    assert error.value.message == "No access to the threads of #help-center."


def test_the_default_label_names_the_channel_id():
    search = FakeThreadSearch([])
    search.status = 403
    with pytest.raises(DiscoopError) as error:
        fetch(search)
    assert PARENT in error.value.message


def test_another_403_is_a_block_not_missing_access():
    search = FakeThreadSearch([])
    search.status = (403, 40333)
    with pytest.raises(DiscoopError) as error:
        fetch(search, label="#help-center")
    assert error.value.code == ExitCode.ERROR and error.value.hint == BLOCKED_HINT
    assert "403, code 40333" in error.value.message


def test_unknown_channel_is_not_found():
    search = FakeThreadSearch([])
    search.status = 404
    with pytest.raises(DiscoopError) as error:
        fetch(search, label="#gone")
    assert error.value.code == ExitCode.NOT_FOUND and error.value.message == "Discord does not know #gone."


def test_other_errors_are_api_errors():
    search = FakeThreadSearch([])
    search.status = 400
    with pytest.raises(DiscoopError) as error:
        fetch(search)
    assert error.value.code == ExitCode.ERROR and "400" in error.value.message


# --- active and archived together ----------------------------------------------------------------------------------


def both_kinds() -> FakeThreadSearch:
    active = series(3, newest=NOW - HOUR, step=HOUR, archived=False)  # thread 0 .. 2
    archived = series(4, newest=NOW - 150 * timedelta(minutes=1), step=HOUR, first_seq=10)  # thread 10 .. 13
    changed = {**active[0], "thread_metadata": {**active[0]["thread_metadata"], "archived": True}}
    return FakeThreadSearch([*active, changed, *archived])  # thread 0 turned up in both lists


def test_active_and_archived_threads_are_merged():
    search = both_kinds()
    result = fetch_all(search, EVERYTHING)
    assert names(result.threads) == [f"thread {i}" for i in (0, 1, 10, 2, 11, 12, 13)]
    assert result.threads[0].archived is False  # the active record wins
    assert result.requests == 2 and result.stop is Stop.END and result.complete
    assert [r["archived"] for r in search.requests] == ["false", "true"]
    assert result.total_results == 3 + 5


def test_a_listing_that_fails_to_complete_makes_the_merged_one_incomplete():
    search = both_kinds()
    search.status_at = {2: 202}  # the archived listing
    result = fetch_all(search, EVERYTHING)
    assert names(result.threads) == ["thread 0", "thread 1", "thread 2"]
    assert result.stop is Stop.NOT_INDEXED and not result.complete


def test_progress_runs_over_both_listings():
    seen = []
    active = series(30, newest=NOW - HOUR, step=HOUR, archived=False)  # pages of 25 and 5
    archived = series(60, newest=NOW - 100 * HOUR, step=HOUR, first_seq=100)  # pages of 25, 25 and 10
    search = FakeThreadSearch(active + archived)
    result = fetch_all(search, EVERYTHING, on_page=lambda kept, requests: seen.append((kept, requests)))
    assert len(result.threads) == 90 and result.requests == 5
    # One report between the pages of the active listing, then two of the archived one: 30 and 2 requests come first.
    assert seen == [(25, 1), (30 + 25, 2 + 1), (30 + 50, 2 + 2)]


def test_errors_of_the_merged_listing_are_raised():
    search = FakeThreadSearch([])
    search.status = 403
    with pytest.raises(DiscoopError) as error:
        fetch_all(search, label="#help-center")
    assert error.value.code == ExitCode.NO_ACCESS


# --- Directory.threads ---------------------------------------------------------------------------------------------


@contextmanager
def run_with(search: FakeThreadSearch):
    """A Directory like the one of a new `discoop` run: the cache file is shared, the rest is new."""
    cache = Cache.default()
    directory = Directory(cache, lambda: DiscordAPI("tok", transport=httpx.MockTransport(search.handler())))
    try:
        with directory:
            yield directory
    finally:
        cache.close()


def test_threads_are_fetched_once_then_served_from_the_cache():
    search = FakeThreadSearch(series(3, newest=NOW - HOUR, step=HOUR))
    with run_with(search) as directory:
        first = directory.threads(FORUM, WEEK)
        assert len(first.threads) == 3 and first.requests == 2  # active, archived
        assert directory.cache_age(f"threads:{PARENT}") is None  # fetched by this run
        again = directory.threads(FORUM, WEEK)
        assert again.threads == first.threads and again.requests == 0 and again.complete
    with run_with(search) as directory:  # the next run
        assert directory.cache_age(f"threads:{PARENT}") >= 0
        assert directory.threads(FORUM, WEEK).threads == first.threads
    assert len(search.requests) == 2


def test_refresh_asks_discord_again():
    search = FakeThreadSearch(series(3, newest=NOW - HOUR, step=HOUR))
    with run_with(search) as directory:
        directory.threads(FORUM, WEEK)
    with run_with(search) as directory:
        result = directory.threads(FORUM, WEEK, refresh=True)
        assert result.requests == 2 and directory.cache_age(f"threads:{PARENT}") is None
    assert len(search.requests) == 4


def test_a_wider_window_than_the_cached_one_is_fetched():
    search = FakeThreadSearch(series(60, newest=NOW - HOUR, step=12 * HOUR))
    with run_with(search) as directory:
        assert len(directory.threads(FORUM, WEEK).threads) == 14
    requests = len(search.requests)
    with run_with(search) as directory:
        assert len(directory.threads(FORUM, WEEK).threads) == 14  # as cached
        assert len(search.requests) == requests
        everything = directory.threads(FORUM, EVERYTHING)
        assert len(everything.threads) == 60 and everything.requests > 0
    with Cache.default() as cache:
        assert len(cache.threads(PARENT)) == 60  # the wider list replaced the cached one


def test_a_narrower_window_is_answered_from_a_wider_cached_list():
    search = FakeThreadSearch(series(3, newest=NOW - HOUR, step=HOUR))  # last activity 1 h, 2 h, 3 h ago
    with run_with(search) as directory:
        directory.threads(FORUM, EVERYTHING)
    requests = len(search.requests)
    with run_with(search) as directory:
        result = directory.threads(FORUM, Window(NOW - 150 * timedelta(minutes=1), NOW))
        assert names(result.threads) == ["thread 0", "thread 1"] and result.requests == 0
        assert result.stop is Stop.END
    assert len(search.requests) == requests


def test_an_old_cached_list_is_fetched_again():
    search = FakeThreadSearch(series(3, newest=NOW - HOUR, step=HOUR))
    with run_with(search) as directory:
        directory.threads(FORUM, WEEK)
    with run_with(search) as directory:
        assert directory.threads(FORUM, WEEK, max_age=0).requests == 2
    db = sqlite3.connect(cache_path())
    db.execute("UPDATE fetched SET at = at - ? WHERE what = ?", (THREADS_MAX_AGE + 60, f"threads:{PARENT}"))
    db.commit()
    db.close()
    with run_with(search) as directory:
        assert directory.threads(FORUM, WEEK, max_age=None).requests == 0  # any age will do
        assert directory.threads(FORUM, WEEK).requests == 2  # older than the default
        assert directory.threads(FORUM, WEEK).requests == 0  # and fresh again, fetched by this run


def test_channels_without_threads_ask_nothing():
    search = FakeThreadSearch([])
    with run_with(search) as directory:
        for channel_type in (2, 4, 11, 13):
            result = directory.threads(Channel("400", FIT, "x", channel_type), WEEK)
            assert (result.threads, result.requests, result.complete) == ([], 0, True)
    assert search.requests == []


def test_a_channel_with_no_threads_is_cached_too():
    search = FakeThreadSearch([])
    with run_with(search) as directory:
        assert directory.threads(FORUM, WEEK).threads == []
    with run_with(search) as directory:
        assert directory.threads(FORUM, WEEK).requests == 0
    assert len(search.requests) == 2


def test_an_incomplete_list_is_returned_but_not_cached():
    search = FakeThreadSearch(series(3, newest=NOW - HOUR, step=HOUR))
    search.status_at = {2: 202}
    with run_with(search) as directory:
        result = directory.threads(FORUM, WEEK)
        assert not result.complete and result.stop is Stop.NOT_INDEXED
        assert directory.cache.cached_threads(PARENT) is None
        assert directory.threads(FORUM, WEEK).requests == 2  # asks again


def test_errors_reach_the_caller_with_the_channel_named():
    search = FakeThreadSearch([])
    search.status = 403
    with run_with(search) as directory:
        with pytest.raises(DiscoopError) as error:
            directory.threads(FORUM, WEEK)
        assert error.value.code == ExitCode.NO_ACCESS and "#help-center (300, forum)" in error.value.message
        assert directory.cache.cached_threads(PARENT) is None


def test_progress_reaches_the_fetch():
    seen = []
    search = FakeThreadSearch(series(60, newest=NOW - HOUR, step=12 * HOUR))
    with run_with(search) as directory:
        directory.threads(FORUM, EVERYTHING, on_page=lambda kept, requests: seen.append(kept))
    assert seen == [25, 50]


def test_zone_of_the_window_does_not_matter():
    cet = timezone(timedelta(hours=1))
    window = Window((NOW - timedelta(days=7)).astimezone(cet), NOW.astimezone(cet))
    search = FakeThreadSearch(series(60, newest=NOW - HOUR, step=12 * HOUR))
    with run_with(search) as directory:
        assert len(directory.threads(FORUM, window).threads) == 14
