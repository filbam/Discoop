import json
from datetime import UTC, datetime, timedelta, timezone

import httpx
import pytest

from discoop import cli
from discoop.api import DiscordAPI
from discoop.models import Channel, ChannelMessages, Server
from discoop.output import Output
from discoop.snowflake import Window, from_time
from discoop.tokenstore import TokenStore
from fake_messages import CET, FIT, NOW, FakeChannel, FakeDiscord, message, series


@pytest.fixture
def discord_env(monkeypatch):
    TokenStore.default().save("tok")
    fake_discord = FakeDiscord()
    monkeypatch.setattr(
        cli,
        "DiscordAPI",
        lambda token, **kw: DiscordAPI(
            token, transport=httpx.MockTransport(fake_discord.handle), sleep=lambda s: None, **kw
        ),
    )
    return fake_discord


def run_messages(capsys, *args):
    with pytest.raises(SystemExit) as exc:
        cli.main(["messages", *args])
    captured = capsys.readouterr()
    return exc.value.code, captured.out, captured.err


def test_progress_json_events_and_no_leakage(capsys, discord_env):
    discord_env.channels["200"] = FakeChannel(series(250, newest=NOW - timedelta(minutes=5), step=timedelta(minutes=10)))
    code, out, err = run_messages(capsys, "-s", FIT, "-c", "200", "--from", "all", "--progress-json")
    assert code == 0

    lines = [json.loads(line) for line in err.strip().splitlines()]
    event_names = [e["event"] for e in lines]
    assert event_names[0] == "channel_start"
    assert "page" in event_names
    assert event_names[-1] == "channel_done"

    start = lines[0]
    assert start == {
        "event": "channel_start",
        "index": 1,
        "total": 1,
        "channel_id": "200",
    }

    pages = [e for e in lines if e["event"] == "page"]
    assert len(pages) >= 2
    for p in pages:
        assert p["index"] == 1
        assert p["total"] == 1
        assert p["channel_id"] == "200"
        assert isinstance(p["messages"], int)
        assert isinstance(p["oldest_id"], str)
        assert "fraction" in p
        assert "eta_seconds" in p

    done = lines[-1]
    assert done == {
        "event": "channel_done",
        "index": 1,
        "total": 1,
        "channel_id": "200",
        "messages": 250,
        "files": 0,
        "truncated": False,
    }

    # Strict check: NO channel names, server names, user names, or message texts in stderr!
    assert "2bit-general" not in err
    assert "VUT FIT" not in err
    assert "student_a" not in err
    assert "message 0" not in err
    assert "deadline" not in err


def test_progress_json_skipped_and_warning(capsys, discord_env):
    discord_env.channels["200"] = FakeChannel(series(150, newest=NOW - timedelta(minutes=5), step=timedelta(minutes=10)))
    discord_env.status["202"] = 403  # NO_ACCESS for channel 202

    code, out, err = run_messages(
        capsys,
        "-s", FIT,
        "-c", "200",
        "-c", "202",
        "--from", "all",
        "--max-messages", "100",
        "--progress-json",
    )
    assert code == 0

    lines = [json.loads(line) for line in err.strip().splitlines()]

    # Warning event for max-messages truncation
    warnings = [e for e in lines if e["event"] == "warning"]
    assert len(warnings) == 1
    assert warnings[0] == {
        "event": "warning",
        "index": 1,
        "total": 2,
        "channel_id": "200",
    }

    # Skipped event for channel 202
    skipped = [e for e in lines if e["event"] == "skipped"]
    assert len(skipped) == 1
    assert skipped[0] == {
        "event": "skipped",
        "index": 2,
        "total": 2,
        "channel_id": "202",
        "code": "NO_ACCESS",
    }

    # Check that channel and server names are not in stderr
    assert "2bit-general" not in err
    assert "2bit-terminy" not in err
    assert "VUT FIT" not in err


def test_progress_json_pause_event(capsys, discord_env):
    discord_env.channels["200"] = FakeChannel(series(10, newest=NOW - timedelta(minutes=5), step=timedelta(minutes=10)))
    discord_env.channels["202"] = FakeChannel(series(10, newest=NOW - timedelta(minutes=5), step=timedelta(minutes=10)))

    # In safe mode between channels, a pause is emitted
    code, out, err = run_messages(
        capsys,
        "-s", FIT,
        "-c", "200",
        "-c", "202",
        "--safe",
        "--progress-json",
    )
    assert code == 0

    lines = [json.loads(line) for line in err.strip().splitlines()]
    pauses = [e for e in lines if e["event"] == "pause"]
    assert len(pauses) >= 1
    p = pauses[0]
    assert p["event"] == "pause"
    assert "seconds" in p and isinstance(p["seconds"], float)
    assert "reason" in p and isinstance(p["reason"], str)
    assert "channel_id" in p


def test_cli_events_percentage_and_eta_plain_verbose(capsys):
    out = Output(plain=True, verbose=True)
    t = [100.0]

    start_time = datetime(2026, 11, 1, 0, 0, tzinfo=UTC)
    end_time = datetime(2026, 11, 2, 0, 0, tzinfo=UTC)
    start_id = from_time(start_time)
    end_id = from_time(end_time)
    window = Window(start=start_time, end=end_time)

    events = cli._CliEvents(out, tz=CET, window=window, clock=lambda: t[0])
    server = Server(FIT, "VUT FIT")
    channel = Channel("200", FIT, "2bit-general", 0)

    events.channel_start(1, 1, server, channel)
    captured = capsys.readouterr()
    assert "Fetching #2bit-general (200) in VUT FIT" in captured.err

    # 42% progress
    oldest_id = end_id - int((end_id - start_id) * 0.42)
    # Elapsed time giving ~180s ETA: 130.34 * 0.58 / 0.42 ~= 180s (3 min)
    t[0] = 100.0 + 130.34
    events.page(100, oldest_id)
    captured = capsys.readouterr()
    assert ", ~42%, about 3 min left" in captured.err

    # Same progress with elapsed <= 0 gives percentage without ETA string
    t[0] = 100.0
    events.page(100, oldest_id)
    captured = capsys.readouterr()
    assert ", ~42%" in captured.err
    assert "about" not in captured.err

    # Very small progress (< 1%) gives no percentage or ETA
    almost_newest_id = end_id - int((end_id - start_id) * 0.005)
    t[0] = 100.0 + 5.0
    events.page(10, almost_newest_id)
    captured = capsys.readouterr()
    assert "~" not in captured.err
    assert "about" not in captured.err


def test_cli_events_percentage_and_eta_human_spinner():
    out = Output(plain=False)
    t = [100.0]

    start_time = datetime(2026, 11, 1, 0, 0, tzinfo=UTC)
    end_time = datetime(2026, 11, 2, 0, 0, tzinfo=UTC)
    start_id = from_time(start_time)
    end_id = from_time(end_time)
    window = Window(start=start_time, end=end_time)

    events = cli._CliEvents(out, tz=CET, window=window, clock=lambda: t[0])
    server = Server(FIT, "VUT FIT")
    channel = Channel("200", FIT, "2bit-general", 0)

    events.channel_start(1, 1, server, channel)

    # 42% progress with 3 min ETA
    oldest_id = end_id - int((end_id - start_id) * 0.42)
    t[0] = 100.0 + 130.34

    # Intercept status updates
    updates = []
    events._status.update = lambda msg: updates.append(msg)

    events.page(100, oldest_id)
    assert len(updates) == 1
    assert ", ~42%, about 3 min left" in updates[0]
    events.close()
