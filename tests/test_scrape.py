from datetime import timedelta

import httpx
import pytest

from discoop.api import DiscordAPI
from discoop.errors import DiscoopError, ExitCode
from discoop.scrape import fetch_messages, is_system
from discoop.snowflake import Window, from_time
from fake_messages import NOW, FakeChannel, message, series

STEP = timedelta(minutes=10)
NEWEST = NOW - timedelta(minutes=5)


def fetch(channel: FakeChannel, window: Window, **kwargs):
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        assert request.url.path == "/api/v9/channels/200/messages"
        return channel.respond(request)

    with DiscordAPI("tok", transport=httpx.MockTransport(handler)) as api:
        return fetch_messages(api, "200", window, label="#test", **kwargs)


def ids(messages):
    return [int(m["id"]) for m in messages]


def test_window_stops_at_its_start():
    channel = FakeChannel(series(250, newest=NEWEST, step=STEP))
    result = fetch(channel, Window(NOW - timedelta(hours=24), NOW))
    # 5 min + 10 min * i < 24 h  ->  i = 0..143
    assert len(result.messages) == 144
    assert result.requests == 2 and not result.hit_limit
    assert ids(result.messages) == sorted(ids(result.messages))  # oldest first
    assert result.messages[-1]["content"] == "message 0"
    first, second = channel.requests
    assert first == {"before": str(from_time(NOW)), "limit": "100"}
    assert second["before"] == channel.messages[99]["id"]  # continues below the oldest message of page 1


def test_whole_history_pages_until_a_short_page():
    channel = FakeChannel(series(250, newest=NEWEST, step=STEP))
    result = fetch(channel, Window(None, NOW))
    assert len(result.messages) == 250
    assert result.requests == 3
    assert all(int(r["limit"]) <= 100 for r in channel.requests)


def test_empty_channel():
    result = fetch(FakeChannel([]), Window(None, NOW))
    assert result.messages == [] and result.requests == 1


def test_custom_page_size():
    channel = FakeChannel(series(60, newest=NEWEST, step=STEP))
    result = fetch(channel, Window(None, NOW), page_size=25)
    assert len(result.messages) == 60
    assert result.requests == 3
    assert [r["limit"] for r in channel.requests] == ["25", "25", "25"]


def test_window_end_excludes_newer_messages():
    channel = FakeChannel(series(10, newest=NEWEST, step=STEP))
    end = NEWEST - 3 * STEP  # message 3 sits exactly at the end and is left out
    result = fetch(channel, Window(end - 4 * STEP, end))
    assert [m["content"] for m in result.messages] == ["message 7", "message 6", "message 5", "message 4"]


def test_last_n_asks_for_one_extra_message():
    channel = FakeChannel(series(250, newest=NEWEST, step=STEP))
    result = fetch(channel, Window(None, NOW), limit=5)
    assert [m["content"] for m in result.messages] == [f"message {i}" for i in (4, 3, 2, 1, 0)]
    assert result.hit_limit and result.requests == 1
    assert channel.requests[0]["limit"] == "6"


def test_limit_across_pages():
    channel = FakeChannel(series(250, newest=NEWEST, step=STEP))
    result = fetch(channel, Window(None, NOW), limit=150)
    assert len(result.messages) == 150 and result.hit_limit
    assert [r["limit"] for r in channel.requests] == ["100", "51"]


def test_limit_larger_than_history_is_not_hit():
    channel = FakeChannel(series(250, newest=NEWEST, step=STEP))
    result = fetch(channel, Window(None, NOW), limit=250)
    assert len(result.messages) == 250 and not result.hit_limit


def test_limit_inside_a_window_that_ends_first():
    channel = FakeChannel(series(250, newest=NEWEST, step=STEP))
    result = fetch(channel, Window(NOW - timedelta(hours=1), NOW), limit=10)
    assert len(result.messages) == 6 and not result.hit_limit


def test_system_messages_are_skipped_unless_asked():
    messages = [
        message(NEWEST, "hello"),
        message(NEWEST - STEP, "", type=7),  # member joined
        message(NEWEST - 2 * STEP, "answer", type=19),
        message(NEWEST - 3 * STEP, "bot answer", type=20),
    ]
    assert [is_system(m) for m in messages] == [False, True, False, False]
    result = fetch(FakeChannel(messages), Window(None, NOW))
    assert [m["content"] for m in result.messages] == ["bot answer", "answer", "hello"]
    result = fetch(FakeChannel(messages), Window(None, NOW), include_system=True)
    assert len(result.messages) == 4


def test_skipped_system_messages_do_not_count_for_the_limit():
    messages = [message(NEWEST - i * STEP, f"m{i}", type=7 if i % 2 else 0) for i in range(10)]
    result = fetch(FakeChannel(messages), Window(None, NOW), limit=3)
    assert [m["content"] for m in result.messages] == ["m4", "m2", "m0"]


def test_progress_is_reported_between_pages():
    seen = []
    fetch(FakeChannel(series(250, newest=NEWEST, step=STEP)), Window(None, NOW), on_page=lambda n, i: seen.append(n))
    assert seen == [100, 200]


@pytest.mark.parametrize(
    ("status", "body", "code"),
    [
        (403, {"message": "Missing Access", "code": 50001}, ExitCode.NO_ACCESS),
        (403, {"message": "Missing Permissions", "code": 50013}, ExitCode.NO_ACCESS),
        (404, {"message": "Unknown Channel", "code": 10003}, ExitCode.NOT_FOUND),
        (400, {"message": "Invalid Form Body", "code": 50035}, ExitCode.ERROR),
    ],
)
def test_errors(status, body, code):
    transport = httpx.MockTransport(lambda r: httpx.Response(status, json=body))
    with DiscordAPI("tok", transport=transport) as api, pytest.raises(DiscoopError) as e:
        fetch_messages(api, "200", Window(None, NOW), label="#secret (200) in VUT FIT")
    assert e.value.code == code
    if status != 400:
        assert "#secret (200) in VUT FIT" in e.value.message
    else:
        assert e.value.message.endswith(": Invalid Form Body (code 50035)")


@pytest.mark.parametrize(
    ("response", "reason"),
    [
        (httpx.Response(403, json={"message": "Unknown Message", "code": 10008}), "(403, code 10008): Unknown Message."),
        (httpx.Response(403, json={"message": "Blocked", "code": 40333}), "(403, code 40333): Blocked."),
        (httpx.Response(403, text="<html>Access denied</html>"), "(403, no error code): no message."),
    ],
)
def test_other_403_codes_are_blocks_not_missing_access(response, reason):
    with DiscordAPI("tok", transport=httpx.MockTransport(lambda r: response)) as api, pytest.raises(DiscoopError) as e:
        fetch_messages(api, "200", Window(None, NOW), label="#x")
    assert e.value.code == ExitCode.ERROR
    assert e.value.message == f"Discord refused to read #x {reason}"
    assert "not a missing permission" in e.value.hint


def test_empty_first_page_is_reported():
    result = fetch(FakeChannel([]), Window(None, NOW))
    assert result.nothing_before_end
    channel = FakeChannel(series(3, newest=NOW - timedelta(days=3), step=STEP))
    result = fetch(channel, Window(NOW - timedelta(hours=24), NOW))  # history exists, just not in the window
    assert result.messages == [] and not result.nothing_before_end


def test_401_needs_login():
    transport = httpx.MockTransport(lambda r: httpx.Response(401, json={"message": "401: Unauthorized"}))
    with DiscordAPI("tok", transport=transport) as api, pytest.raises(DiscoopError) as e:
        fetch_messages(api, "200", Window(None, NOW), label="#x")
    assert e.value.code == ExitCode.AUTH_REQUIRED
