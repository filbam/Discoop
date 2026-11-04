"""Tests for incremental scraping (--since-last) and disk space check (R4-D package).

Covers:
- MessagesRequest since_last field and to_argv
- Mutual exclusion of --since-last with --from, --to, --last (ExitCode.BAD_ARGS, code 8)
- First run without state = default 24h window + note + state saved
- Second run with state = exclusive min_id (saved_id + 1), no duplicates
- Zero new messages preserves last_message_id and advances updated time
- Empty channel stores synthetic snowflake for current_now
- State not updated after error / interruption
- State not updated for channel with truncated=True
- State not updated for skipped channel
- State not updated if thread list had a problem or thread failed
- State not updated if an attachment failed
- Skipping inactive channels (last_message_id <= saved_id) for --no-threads / non-containers (0 requests)
- A text channel with threads and nothing newer in it: its own messages are not fetched, its threads are
- Never skipping forum and media channels
- Threads with --since-last (thread with state vs new thread from parent updated)
- Disk space check before download (< needed + 50 MB -> error, 0 CDN requests)
- Disk space check passes with --no-files, present files, or files > max-file-size
"""

import json
import shutil
from collections import Counter
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import httpx
import pytest
from typer.testing import CliRunner

from discoop import cli, paths, service
from discoop.api import DiscordAPI
from discoop.cache import Cache
from discoop.directory import Directory
from discoop.errors import DiscoopError, ExitCode
from discoop.models import Attachment
from discoop.service import Cancelled, Events, MessagesOutcome, MessagesRequest, run_messages
from discoop.snowflake import Window, from_time, to_time
from discoop.syncstate import (
    ChannelSync,
    load_account_channels,
    sync_state_path,
    update_account_channels,
)
from discoop.tokenstore import TokenStore
from fake_messages import FIT, USER_A, FakeCDN, FakeChannel, signed_url
from fake_threads import PARENT, FakeThreadSearch, thread as make_thread

NOW = datetime(2026, 11, 4, 12, 0, tzinfo=UTC)
CET = timezone(timedelta(hours=1))
runner = CliRunner()


def make_msg(msg_id: str, content: str, channel_id: str, when: datetime, attachments: list[dict] | None = None) -> dict:
    return {
        "id": msg_id,
        "type": 0,
        "channel_id": channel_id,
        "content": content,
        "author": USER_A,
        "timestamp": when.isoformat(),
        "edited_timestamp": None,
        "attachments": attachments or [],
        "embeds": [],
        "mentions": [],
        "mention_roles": [],
        "pinned": False,
        "flags": 0,
        "components": [],
    }


class MockSinceLastDiscord:
    """Mock Discord API with support for /users/@me, guilds, channels, threads, messages."""

    def __init__(
        self,
        channels: list[dict] | None = None,
        messages: dict[str, list[dict]] | None = None,
        threads: dict[str, list[dict]] | None = None,
        user_id: str = "123456789",
    ):
        self.user_id = user_id
        self.channels_list = channels or [
            {"id": "100", "type": 4, "name": "general-cat", "position": 0},
            {"id": "200", "type": 0, "name": "2bit-general", "parent_id": "100", "position": 1, "last_message_id": None},
            {"id": "201", "type": 2, "name": "voice-room", "parent_id": "100", "position": 2, "last_message_id": None},
            {"id": "204", "type": 15, "name": "help-center", "position": 3, "last_message_id": None, "available_tags": []},
        ]
        self.messages = messages or {}
        self.threads = threads or {}
        self.calls: Counter = Counter()
        self.channel_status: dict[str, int] = {}
        self.thread_search_status: dict[str, int] = {}

    def handle(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path.removeprefix("/api/v9")
        self.calls[path] += 1

        if path == "/users/@me":
            return httpx.Response(200, json={"id": self.user_id, "username": "testuser"})
        if path == "/users/@me/guilds":
            return httpx.Response(200, json=[{"id": FIT, "name": "VUT FIT", "approximate_member_count": 5000}])
        if path == f"/guilds/{FIT}/channels":
            return httpx.Response(200, json=self.channels_list)
        if path == "/attachments/refresh-urls" and request.method == "POST":
            return httpx.Response(200, json={"refreshed_urls": []})

        parts = path.strip("/").split("/")
        if parts[0] == "channels":
            channel_id = parts[1]
            if len(parts) == 2:
                known = next((c for c in self.channels_list if c["id"] == channel_id), None)
                if known:
                    return httpx.Response(200, json={**known, "guild_id": FIT})
                for t_list in self.threads.values():
                    for t in t_list:
                        if t["id"] == channel_id:
                            return httpx.Response(200, json={**t, "guild_id": FIT})
                return httpx.Response(404, json={"message": "Unknown Channel", "code": 10003})

            if len(parts) >= 4 and parts[2] == "threads" and parts[3] == "search":
                if channel_id in self.thread_search_status:
                    code = self.thread_search_status[channel_id]
                    return httpx.Response(code, json={"message": "forced", "code": 50001 if code == 403 else 10003})
                t_list = self.threads.get(channel_id, [])
                searcher = FakeThreadSearch(t_list)
                return searcher.respond(request)

            if len(parts) == 3 and parts[2] == "messages":
                if channel_id in self.channel_status:
                    code = self.channel_status[channel_id]
                    return httpx.Response(code, json={"message": "forced", "code": 50001 if code == 403 else 10003})
                msgs = self.messages.get(channel_id, [])
                fc = FakeChannel(msgs)
                return fc.respond(request)

        return httpx.Response(404, json={"message": "Unknown Endpoint", "code": 10003})


class NoteCollectorEvents(Events):
    def __init__(self):
        super().__init__()
        self.notes: list[str] = []
        self.warnings: list[str] = []

    def note(self, text: str) -> None:
        self.notes.append(text)

    def warning(self, text: str) -> None:
        self.warnings.append(text)


@pytest.fixture
def lab_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(paths, "data_dir", lambda: tmp_path)
    monkeypatch.setattr(paths, "config_dir", lambda: tmp_path)
    TokenStore.default().save("fake_token")
    monkeypatch.setattr(cli, "utc_now", lambda: NOW)
    monkeypatch.setattr(cli, "LOCAL_ZONE", CET)
    return tmp_path


def test_messages_request_since_last_argv():
    req_default = MessagesRequest(channels=("c1",))
    assert req_default.since_last is False
    assert "--since-last" not in req_default.to_argv()

    req_since = MessagesRequest(channels=("c1",), since_last=True)
    assert req_since.since_last is True
    assert "--since-last" in req_since.to_argv()
    assert req_since.to_command_str() == "discoop messages -c c1 --safe --since-last"


def test_bad_args_combination_before_api_calls(lab_env: Path):
    mock = MockSinceLastDiscord()
    transport = httpx.MockTransport(mock.handle)
    api = DiscordAPI("token", transport=transport, delay=0.0, mode="safe")

    with Cache(lab_env / "cache.db") as cache, Directory(cache, lambda: api) as directory:
        # 1. Combined with from_
        req1 = MessagesRequest(channels=("200",), since_last=True, from_="24h")
        with pytest.raises(DiscoopError) as exc1:
            run_messages(req1, directory=directory, now=NOW, tz=CET)
        assert exc1.value.code == ExitCode.BAD_ARGS
        assert "--since-last cannot be combined" in exc1.value.message
        assert mock.calls["/users/@me"] == 0

        # 2. Combined with to
        req2 = MessagesRequest(channels=("200",), since_last=True, to="now")
        with pytest.raises(DiscoopError) as exc2:
            run_messages(req2, directory=directory, now=NOW, tz=CET)
        assert exc2.value.code == ExitCode.BAD_ARGS
        assert "--since-last cannot be combined" in exc2.value.message
        assert mock.calls["/users/@me"] == 0

        # 3. Combined with last
        req3 = MessagesRequest(channels=("200",), since_last=True, last=10)
        with pytest.raises(DiscoopError) as exc3:
            run_messages(req3, directory=directory, now=NOW, tz=CET)
        assert exc3.value.code == ExitCode.BAD_ARGS
        assert "--since-last cannot be combined" in exc3.value.message
        assert mock.calls["/users/@me"] == 0


def test_cli_bad_args_combination(lab_env: Path, capsys: pytest.CaptureFixture):
    with pytest.raises(SystemExit) as e:
        cli.main(["--agent", "messages", "-s", "VUT FIT", "-c", "2bit-general", "--since-last", "--from", "24h"])
    assert e.value.code == int(ExitCode.BAD_ARGS)
    captured = capsys.readouterr()
    assert "--since-last cannot be combined" in captured.err or "--since-last cannot be combined" in captured.out


def test_first_run_without_state(lab_env: Path):
    # Messages within the 24h window
    m1_time = NOW - timedelta(hours=5)
    m2_time = NOW - timedelta(hours=2)
    m1_id = str(from_time(m1_time))
    m2_id = str(from_time(m2_time))

    mock = MockSinceLastDiscord(
        messages={"200": [make_msg(m1_id, "Msg 1", "200", m1_time), make_msg(m2_id, "Msg 2", "200", m2_time)]}
    )
    transport = httpx.MockTransport(mock.handle)
    api = DiscordAPI("token", transport=transport, delay=0.0, mode="safe")

    events = NoteCollectorEvents()
    with Cache(lab_env / "cache.db") as cache, Directory(cache, lambda: api) as directory:
        req = MessagesRequest(channels=("200",), since_last=True, threads=False)
        outcome = run_messages(req, directory=directory, now=NOW, tz=CET, events=events)

    assert len(outcome.results) == 1
    assert len(outcome.results[0].messages) == 2
    # Verify note was emitted
    assert any("No previous sync state for #2bit-general: fetching the last 24 hours." in n for n in events.notes)

    # Verify state was saved
    channels = load_account_channels(mock.user_id)
    assert "200" in channels
    assert channels["200"].last_message_id == m2_id
    assert channels["200"].updated == NOW.isoformat()


def test_second_run_incremental_exclusive_boundary(lab_env: Path):
    # Setup initial state with saved_id
    t_saved = NOW - timedelta(hours=10)
    saved_id = str(from_time(t_saved))
    update_account_channels(
        "123456789",
        {"200": ChannelSync(last_message_id=saved_id, updated=t_saved.isoformat())},
    )

    # Messages: one older than saved_id, one exactly saved_id, two newer than saved_id
    t_older = t_saved - timedelta(hours=1)
    t_new1 = t_saved + timedelta(hours=1)
    t_new2 = t_saved + timedelta(hours=2)

    older_id = str(from_time(t_older))
    new1_id = str(from_time(t_new1))
    new2_id = str(from_time(t_new2))

    mock = MockSinceLastDiscord(
        messages={
            "200": [
                make_msg(older_id, "Older msg", "200", t_older),
                make_msg(saved_id, "Saved msg", "200", t_saved),
                make_msg(new1_id, "New 1", "200", t_new1),
                make_msg(new2_id, "New 2", "200", t_new2),
            ]
        }
    )
    transport = httpx.MockTransport(mock.handle)
    api = DiscordAPI("token", transport=transport, delay=0.0, mode="safe")

    events = NoteCollectorEvents()
    with Cache(lab_env / "cache.db") as cache, Directory(cache, lambda: api) as directory:
        req = MessagesRequest(channels=("200",), since_last=True, threads=False)
        outcome = run_messages(req, directory=directory, now=NOW, tz=CET, events=events)

    # Exclusive boundary: saved_id must NOT be in results!
    assert len(outcome.results) == 1
    msg_ids = [m.id for m in outcome.results[0].messages]
    assert msg_ids == [new1_id, new2_id]
    assert saved_id not in msg_ids
    assert older_id not in msg_ids

    # State updated to newest message
    channels = load_account_channels(mock.user_id)
    assert channels["200"].last_message_id == new2_id
    assert channels["200"].updated == NOW.isoformat()


def test_zero_new_messages_preserves_id_and_advances_time(lab_env: Path):
    t_saved = NOW - timedelta(hours=2)
    saved_id = str(from_time(t_saved))
    update_account_channels(
        "123456789",
        {"200": ChannelSync(last_message_id=saved_id, updated=t_saved.isoformat())},
    )

    # No newer messages
    mock = MockSinceLastDiscord(
        messages={"200": [make_msg(saved_id, "Saved msg", "200", t_saved)]}
    )
    transport = httpx.MockTransport(mock.handle)
    api = DiscordAPI("token", transport=transport, delay=0.0, mode="safe")

    with Cache(lab_env / "cache.db") as cache, Directory(cache, lambda: api) as directory:
        req = MessagesRequest(channels=("200",), since_last=True, threads=False)
        outcome = run_messages(req, directory=directory, now=NOW, tz=CET)

    assert len(outcome.results) == 1
    assert len(outcome.results[0].messages) == 0

    # last_message_id preserved, updated updated to NOW
    channels = load_account_channels(mock.user_id)
    assert channels["200"].last_message_id == saved_id
    assert channels["200"].updated == NOW.isoformat()


def test_empty_channel_without_messages_stores_synthetic_snowflake(lab_env: Path):
    mock = MockSinceLastDiscord(messages={"200": []})
    transport = httpx.MockTransport(mock.handle)
    api = DiscordAPI("token", transport=transport, delay=0.0, mode="safe")

    with Cache(lab_env / "cache.db") as cache, Directory(cache, lambda: api) as directory:
        req = MessagesRequest(channels=("200",), since_last=True, threads=False)
        outcome = run_messages(req, directory=directory, now=NOW, tz=CET)

    assert len(outcome.results) == 1
    assert len(outcome.results[0].messages) == 0

    channels = load_account_channels(mock.user_id)
    assert "200" in channels
    expected_synthetic = str(from_time(NOW))
    assert channels["200"].last_message_id == expected_synthetic
    assert channels["200"].updated == NOW.isoformat()


def test_state_not_updated_on_error(lab_env: Path):
    mock = MockSinceLastDiscord()
    mock.channel_status["200"] = 500  # Server error on messages
    transport = httpx.MockTransport(mock.handle)
    api = DiscordAPI("token", transport=transport, delay=0.0, mode="safe", max_retries=0)

    with Cache(lab_env / "cache.db") as cache, Directory(cache, lambda: api) as directory:
        req = MessagesRequest(channels=("200",), since_last=True, threads=False)
        with pytest.raises(DiscoopError):
            run_messages(req, directory=directory, now=NOW, tz=CET)

    # State file was never created/updated
    assert not sync_state_path().is_file()


def test_state_not_updated_on_truncated(lab_env: Path):
    # Channel has 5 messages, but max_messages is 2
    times = [NOW - timedelta(hours=i) for i in range(1, 6)]
    ids = [str(from_time(t)) for t in times]
    msgs = [make_msg(mid, f"Msg {i}", "200", t) for i, (mid, t) in enumerate(zip(ids, times))]

    mock = MockSinceLastDiscord(messages={"200": msgs})
    transport = httpx.MockTransport(mock.handle)
    api = DiscordAPI("token", transport=transport, delay=0.0, mode="safe")

    with Cache(lab_env / "cache.db") as cache, Directory(cache, lambda: api) as directory:
        req = MessagesRequest(channels=("200",), since_last=True, threads=False, max_messages=2)
        outcome = run_messages(req, directory=directory, now=NOW, tz=CET)

    assert len(outcome.results) == 1
    assert outcome.results[0].truncated is True

    # Truncated channel must NOT update sync state
    channels = load_account_channels(mock.user_id)
    assert "200" not in channels


def test_state_not_updated_on_skipped_channel(lab_env: Path):
    # 2 channels: 200 has no access (403), 201 is voice room
    mock = MockSinceLastDiscord()
    mock.channel_status["200"] = 403
    transport = httpx.MockTransport(mock.handle)
    api = DiscordAPI("token", transport=transport, delay=0.0, mode="safe")

    with Cache(lab_env / "cache.db") as cache, Directory(cache, lambda: api) as directory:
        req = MessagesRequest(channels=("200", "201"), since_last=True, threads=False)
        outcome = run_messages(req, directory=directory, now=NOW, tz=CET)

    assert len(outcome.skipped) == 1
    channels = load_account_channels(mock.user_id)
    assert "200" not in channels  # skipped channel has no state saved


def test_skip_inactive_voice_channel_even_with_threads(lab_env: Path):
    t_saved = NOW - timedelta(hours=5)
    saved_id = str(from_time(t_saved))
    update_account_channels("123456789", {"201": ChannelSync(saved_id, t_saved.isoformat())})

    # Voice channel (type 2) is not a thread container
    mock = MockSinceLastDiscord(
        channels=[
            {"id": "100", "type": 4, "name": "general-cat", "position": 0},
            {"id": "201", "type": 2, "name": "voice-room", "parent_id": "100", "position": 2, "last_message_id": saved_id},
        ]
    )
    transport = httpx.MockTransport(mock.handle)
    api = DiscordAPI("token", transport=transport, delay=0.0, mode="safe")

    events = NoteCollectorEvents()
    with Cache(lab_env / "cache.db") as cache, Directory(cache, lambda: api) as directory:
        # threads=True is passed, but voice channel is not a container, so it can be skipped!
        req = MessagesRequest(channels=("201",), since_last=True, threads=True)
        outcome = run_messages(req, directory=directory, now=NOW, tz=CET, events=events)

    assert outcome.unchanged == 1
    assert len(outcome.results) == 0
    assert mock.calls["/channels/201/messages"] == 0
    assert any("voice-room is unchanged since last sync: skipping." in n for n in events.notes)


def test_state_not_updated_on_thread_problem(lab_env: Path):
    # Channel 200 has a thread search 403 error
    mock = MockSinceLastDiscord(
        channels=[
            {"id": "200", "type": 0, "name": "2bit-general", "parent_id": "100", "position": 1, "last_message_id": None},
        ],
        messages={"200": [make_msg(str(from_time(NOW - timedelta(hours=1))), "Msg", "200", NOW - timedelta(hours=1))]},
    )
    mock.thread_search_status["200"] = 403
    transport = httpx.MockTransport(mock.handle)
    api = DiscordAPI("token", transport=transport, delay=0.0, mode="safe")

    events = NoteCollectorEvents()
    with Cache(lab_env / "cache.db") as cache, Directory(cache, lambda: api) as directory:
        req = MessagesRequest(channels=("200",), since_last=True, threads=True)
        outcome = run_messages(req, directory=directory, now=NOW, tz=CET, events=events)

    assert outcome.thread_problems == 1
    # Channel had a thread problem -> its state must NOT be saved!
    channels = load_account_channels(mock.user_id)
    assert "200" not in channels


def test_state_not_updated_on_failed_attachment(lab_env: Path):
    att_size = 100
    att_url = signed_url("200", "887766", "file.pdf", expires=NOW + timedelta(hours=12))
    att_dict = {
        "id": "887766",
        "filename": "file.pdf",
        "size": att_size,
        "url": att_url,
        "proxy_url": att_url,
    }

    t_msg = NOW - timedelta(hours=1)
    msg_id = str(from_time(t_msg))
    mock = MockSinceLastDiscord(
        messages={"200": [make_msg(msg_id, "Msg with file", "200", t_msg, attachments=[att_dict])]}
    )
    transport = httpx.MockTransport(mock.handle)
    api = DiscordAPI("token", transport=transport, delay=0.0, mode="safe")

    # CDN will answer 404 for this file
    fake_cdn = FakeCDN()
    fake_cdn.missing.add(httpx.URL(att_url).path)

    export_path = lab_env / "export_dir"
    with Cache(lab_env / "cache.db") as cache, Directory(cache, lambda: api) as directory:
        req = MessagesRequest(channels=("200",), out_dir=str(export_path), since_last=True, threads=False)
        outcome = run_messages(
            req,
            directory=directory,
            cdn=lambda: httpx.Client(transport=httpx.MockTransport(fake_cdn.handle)),
            now=NOW,
            tz=CET,
        )

    assert outcome.partial is True
    # Channel had a failed attachment -> its state must NOT be saved!
    channels = load_account_channels(mock.user_id)
    assert "200" not in channels


def test_skip_inactive_channel_no_threads(lab_env: Path):
    t_saved = NOW - timedelta(hours=5)
    saved_id = str(from_time(t_saved))
    update_account_channels("123456789", {"200": ChannelSync(saved_id, t_saved.isoformat())})

    # Channel has last_message_id equal to saved_id in Discord's channel list
    mock = MockSinceLastDiscord(
        channels=[
            {"id": "100", "type": 4, "name": "general-cat", "position": 0},
            {"id": "200", "type": 0, "name": "2bit-general", "parent_id": "100", "position": 1, "last_message_id": saved_id},
        ]
    )
    transport = httpx.MockTransport(mock.handle)
    api = DiscordAPI("token", transport=transport, delay=0.0, mode="safe")

    events = NoteCollectorEvents()
    with Cache(lab_env / "cache.db") as cache, Directory(cache, lambda: api) as directory:
        req = MessagesRequest(channels=("200",), since_last=True, threads=False)
        outcome = run_messages(req, directory=directory, now=NOW, tz=CET, events=events)

    assert outcome.unchanged == 1
    assert len(outcome.results) == 0
    # ZERO requests to messages endpoint!
    assert mock.calls["/channels/200/messages"] == 0
    assert any("2bit-general is unchanged since last sync: skipping." in n for n in events.notes)


def test_text_channel_with_threads_is_not_skipped_even_if_last_message_id_le_saved(lab_env: Path):
    t_saved = NOW - timedelta(hours=5)
    saved_id = str(from_time(t_saved))
    update_account_channels("123456789", {"200": ChannelSync(saved_id, t_saved.isoformat())})

    # With threads=True the channel is not skipped altogether: its threads are listed. Its own messages are not
    # fetched when last_message_id <= saved_id (see test_unchanged_text_channel_still_fetches_its_threads).
    mock = MockSinceLastDiscord(
        channels=[
            {"id": "100", "type": 4, "name": "general-cat", "position": 0},
            {"id": "200", "type": 0, "name": "2bit-general", "parent_id": "100", "position": 1, "last_message_id": saved_id},
        ],
        messages={"200": []},
        threads={"200": []},
    )
    transport = httpx.MockTransport(mock.handle)
    api = DiscordAPI("token", transport=transport, delay=0.0, mode="safe")

    with Cache(lab_env / "cache.db") as cache, Directory(cache, lambda: api) as directory:
        req = MessagesRequest(channels=("200",), since_last=True, threads=True)
        outcome = run_messages(req, directory=directory, now=NOW, tz=CET)

    assert outcome.unchanged == 0
    assert len(outcome.results) == 1
    # Its own messages were not queried (nothing newer in it), but its threads were listed
    assert mock.calls["/channels/200/messages"] == 0
    assert mock.calls["/channels/200/threads/search"] >= 1


def test_forum_channel_never_skipped(lab_env: Path):
    t_saved = NOW - timedelta(hours=5)
    saved_id = str(from_time(t_saved))
    update_account_channels("123456789", {"204": ChannelSync(saved_id, t_saved.isoformat())})

    # Forum channel with last_message_id <= saved_id
    mock = MockSinceLastDiscord(
        channels=[
            {"id": "204", "type": 15, "name": "help-center", "position": 1, "last_message_id": saved_id, "available_tags": []},
        ],
        threads={"204": []},
    )
    transport = httpx.MockTransport(mock.handle)
    api = DiscordAPI("token", transport=transport, delay=0.0, mode="safe")

    with Cache(lab_env / "cache.db") as cache, Directory(cache, lambda: api) as directory:
        req = MessagesRequest(channels=("204",), since_last=True, threads=True)
        outcome = run_messages(req, directory=directory, now=NOW, tz=CET)

    assert outcome.unchanged == 0
    assert len(outcome.results) == 1
    assert mock.calls["/channels/204/threads/search"] >= 1


def test_threads_with_since_last(lab_env: Path):
    # Parent channel 200 has state from 4h ago
    t_parent_sync = NOW - timedelta(hours=4)
    parent_saved_id = str(from_time(t_parent_sync))

    # Thread 1 has its own state from 2h ago
    t_th1_sync = NOW - timedelta(hours=2)
    th1_saved_id = str(from_time(t_th1_sync))
    th1_id = "301"

    # Thread 2 has NO saved state (new thread)
    th2_id = "302"

    update_account_channels(
        "123456789",
        {
            "200": ChannelSync(parent_saved_id, t_parent_sync.isoformat()),
            th1_id: ChannelSync(th1_saved_id, t_th1_sync.isoformat()),
        },
    )

    # Thread 1 messages: older than th1_saved_id, exactly th1_saved_id, newer
    t_th1_msg_new = NOW - timedelta(hours=1)
    th1_new_id = str(from_time(t_th1_msg_new))

    # Thread 2 messages: between parent_sync and now
    t_th2_msg = NOW - timedelta(hours=3)
    th2_msg_id = str(from_time(t_th2_msg))

    mock = MockSinceLastDiscord(
        channels=[
            {"id": "200", "type": 0, "name": "2bit-general", "parent_id": "100", "position": 1, "last_message_id": None},
        ],
        messages={
            "200": [],
            th1_id: [
                make_msg(th1_saved_id, "Old th1 msg", th1_id, t_th1_sync),
                make_msg(th1_new_id, "New th1 msg", th1_id, t_th1_msg_new),
            ],
            th2_id: [
                make_msg(th2_msg_id, "Th2 msg", th2_id, t_th2_msg),
            ],
        },
        threads={
            "200": [
                make_thread(t_th1_msg_new, seq=1, parent_id="200", id=th1_id, name="thread 1"),
                make_thread(t_th2_msg, seq=2, parent_id="200", id=th2_id, name="thread 2"),
            ]
        },
    )
    transport = httpx.MockTransport(mock.handle)
    api = DiscordAPI("token", transport=transport, delay=0.0, mode="safe")

    with Cache(lab_env / "cache.db") as cache, Directory(cache, lambda: api) as directory:
        req = MessagesRequest(channels=("200",), since_last=True, threads=True)
        outcome = run_messages(req, directory=directory, now=NOW, tz=CET)

    assert len(outcome.results) == 1
    threads_results = outcome.results[0].threads
    assert len(threads_results) == 2

    th1_res = next(t for t in threads_results if t.channel.id == th1_id)
    th2_res = next(t for t in threads_results if t.channel.id == th2_id)

    # Thread 1 exclusively filtered out th1_saved_id
    assert [m.id for m in th1_res.messages] == [th1_new_id]

    # Thread 2 got messages since parent_sync
    assert [m.id for m in th2_res.messages] == [th2_msg_id]

    # Both threads have their state updated
    channels = load_account_channels(mock.user_id)
    assert channels[th1_id].last_message_id == th1_new_id
    assert channels[th2_id].last_message_id == th2_msg_id


def test_disk_space_check_fails_before_download(lab_env: Path, monkeypatch: pytest.MonkeyPatch):
    # Setup export with attachment of 10 MB
    att_size = 10 * 1024 * 1024  # 10 MB
    att_url = signed_url("200", "att1", "file.pdf", expires=NOW + timedelta(hours=12))
    att_dict = {
        "id": "att1",
        "filename": "file.pdf",
        "size": att_size,
        "url": att_url,
        "proxy_url": att_url,
    }

    t_msg = NOW - timedelta(hours=1)
    msg_id = str(from_time(t_msg))
    mock = MockSinceLastDiscord(
        messages={"200": [make_msg(msg_id, "Msg with file", "200", t_msg, attachments=[att_dict])]}
    )
    transport = httpx.MockTransport(mock.handle)
    api = DiscordAPI("token", transport=transport, delay=0.0, mode="safe")

    fake_cdn = FakeCDN()
    fake_cdn.add(att_url, b"x" * 100)

    # Simulate free space: 55 MB free, need 10 MB -> free - need = 45 MB < 50 MB margin!
    fake_usage = MagicMock()
    fake_usage.free = 55 * 1024 * 1024
    monkeypatch.setattr(shutil, "disk_usage", lambda _: fake_usage)

    export_path = lab_env / "export_dir"

    with Cache(lab_env / "cache.db") as cache, Directory(cache, lambda: api) as directory:
        req = MessagesRequest(channels=("200",), out_dir=str(export_path), threads=False)
        with pytest.raises(DiscoopError) as exc:
            run_messages(req, directory=directory, cdn=lambda: httpx.Client(transport=httpx.MockTransport(fake_cdn.handle)), now=NOW, tz=CET)

        assert exc.value.code == ExitCode.ERROR
        assert "Not enough free space: need about 10 MB, 55 MB free." in exc.value.message
        assert "Free up disk space, use --no-files, or lower --max-file-size." in exc.value.hint
        # ZERO CDN requests made!
        assert len(fake_cdn.requests) == 0


def test_disk_space_check_passes_with_no_files(lab_env: Path, monkeypatch: pytest.MonkeyPatch):
    # 0 bytes free on disk!
    fake_usage = MagicMock()
    fake_usage.free = 0
    monkeypatch.setattr(shutil, "disk_usage", lambda _: fake_usage)

    att_size = 10 * 1024 * 1024
    att_url = signed_url("200", "att1", "file.pdf", expires=NOW + timedelta(hours=12))
    att_dict = {
        "id": "att1",
        "filename": "file.pdf",
        "size": att_size,
        "url": att_url,
        "proxy_url": att_url,
    }

    t_msg = NOW - timedelta(hours=1)
    msg_id = str(from_time(t_msg))
    mock = MockSinceLastDiscord(
        messages={"200": [make_msg(msg_id, "Msg with file", "200", t_msg, attachments=[att_dict])]}
    )
    transport = httpx.MockTransport(mock.handle)
    api = DiscordAPI("token", transport=transport, delay=0.0, mode="safe")

    export_path = lab_env / "export_dir"

    with Cache(lab_env / "cache.db") as cache, Directory(cache, lambda: api) as directory:
        # no_files=True: should pass without checking or requiring space
        req = MessagesRequest(channels=("200",), out_dir=str(export_path), threads=False, no_files=True)
        outcome = run_messages(req, directory=directory, now=NOW, tz=CET)

    assert len(outcome.results) == 1
    assert outcome.exported is not None


def test_disk_space_check_passes_when_files_larger_than_max_file_size(lab_env: Path, monkeypatch: pytest.MonkeyPatch):
    fake_usage = MagicMock()
    fake_usage.free = 0
    monkeypatch.setattr(shutil, "disk_usage", lambda _: fake_usage)

    att_size = 20 * 1024 * 1024  # 20 MB
    att_url = signed_url("200", "att1", "file.pdf", expires=NOW + timedelta(hours=12))
    att_dict = {
        "id": "att1",
        "filename": "file.pdf",
        "size": att_size,
        "url": att_url,
        "proxy_url": att_url,
    }

    t_msg = NOW - timedelta(hours=1)
    msg_id = str(from_time(t_msg))
    mock = MockSinceLastDiscord(
        messages={"200": [make_msg(msg_id, "Msg with file", "200", t_msg, attachments=[att_dict])]}
    )
    transport = httpx.MockTransport(mock.handle)
    api = DiscordAPI("token", transport=transport, delay=0.0, mode="safe")

    export_path = lab_env / "export_dir"

    with Cache(lab_env / "cache.db") as cache, Directory(cache, lambda: api) as directory:
        # max_file_size is 5 MB -> 20 MB file is skipped -> needed_bytes is 0 -> check passes
        req = MessagesRequest(channels=("200",), out_dir=str(export_path), threads=False, max_file_size=5.0)
        outcome = run_messages(req, directory=directory, now=NOW, tz=CET)

    assert len(outcome.results) == 1
    assert outcome.exported is not None


def test_disk_space_check_passes_when_files_already_present(lab_env: Path, monkeypatch: pytest.MonkeyPatch):
    fake_usage = MagicMock()
    fake_usage.free = 0
    monkeypatch.setattr(shutil, "disk_usage", lambda _: fake_usage)

    att_size = 100
    att_url = signed_url("200", "998877", "file.pdf", expires=NOW + timedelta(hours=12))
    att_dict = {
        "id": "998877",
        "filename": "file.pdf",
        "size": att_size,
        "url": att_url,
        "proxy_url": att_url,
    }

    t_msg = NOW - timedelta(hours=1)
    msg_id = str(from_time(t_msg))
    mock = MockSinceLastDiscord(
        messages={"200": [make_msg(msg_id, "Msg with file", "200", t_msg, attachments=[att_dict])]}
    )
    transport = httpx.MockTransport(mock.handle)
    api = DiscordAPI("token", transport=transport, delay=0.0, mode="safe")

    export_path = lab_env / "export_dir"
    export_path.mkdir(parents=True, exist_ok=True)
    (export_path / "manifest.json").write_text(json.dumps({"tool": "discoop"}), encoding="utf-8")
    # Pre-create the file in the staging/target location
    files_dir = export_path / "files" / "2bit-general"
    files_dir.mkdir(parents=True, exist_ok=True)
    existing_file = files_dir / "998877_file.pdf"
    existing_file.write_bytes(b"x" * att_size)

    with Cache(lab_env / "cache.db") as cache, Directory(cache, lambda: api) as directory:
        req = MessagesRequest(channels=("200",), out_dir=str(export_path), threads=False)
        outcome = run_messages(req, directory=directory, now=NOW, tz=CET)

    assert len(outcome.results) == 1
    assert outcome.exported is not None


def sync_channel(channel_id: str, channel_type: int, newest_id: str | None, **fields: Any) -> dict:
    """A channel of the server list; `last_message_id` is what Discord says is the newest message in it."""
    return {
        "id": channel_id,
        "type": channel_type,
        "name": f"channel-{channel_id}",
        "parent_id": "100",
        "position": 1,
        "last_message_id": newest_id,
        **fields,
    }


def new_api(mock: MockSinceLastDiscord) -> DiscordAPI:
    return DiscordAPI("token", transport=httpx.MockTransport(mock.handle), delay=0.0, mode="safe")


@pytest.mark.parametrize("channel_type", [0, 5], ids=["text", "announcement"])
def test_unchanged_text_channel_still_fetches_its_threads(lab_env: Path, channel_type: int):
    t_saved = NOW - timedelta(hours=5)
    saved_id = str(from_time(t_saved))
    update_account_channels("123456789", {"200": ChannelSync(saved_id, t_saved.isoformat())})

    t_new = NOW - timedelta(hours=1)
    new_id = str(from_time(t_new))
    mock = MockSinceLastDiscord(
        channels=[sync_channel("200", channel_type, saved_id)],
        messages={
            "200": [make_msg(new_id, "must not be fetched", "200", t_new)],
            "301": [make_msg(new_id, "New in the thread", "301", t_new)],
        },
        threads={"200": [make_thread(t_new, seq=1, parent_id="200", id="301", name="a thread")]},
    )
    events = NoteCollectorEvents()
    with Cache(lab_env / "cache.db") as cache, Directory(cache, lambda: new_api(mock)) as directory:
        req = MessagesRequest(channels=("200",), since_last=True, threads=True)
        outcome = run_messages(req, directory=directory, now=NOW, tz=CET, events=events)

    assert mock.calls["/channels/200/messages"] == 0  # no request for the messages of the channel itself
    assert mock.calls["/channels/200/threads/search"] >= 1
    assert mock.calls["/channels/301/messages"] >= 1
    assert outcome.unchanged == 0 and len(outcome.results) == 1
    result = outcome.results[0]
    assert result.messages == ()
    assert [m.id for m in result.threads[0].messages] == [new_id]
    assert any("#channel-200: its own messages are unchanged since last sync" in note for note in events.notes)
    assert not any("is unchanged since last sync: skipping" in note for note in events.notes)

    channels = load_account_channels(mock.user_id)
    assert channels["200"].last_message_id == saved_id  # the state does not go backwards (or forwards)
    assert channels["200"].updated == NOW.isoformat()
    assert channels["301"].last_message_id == new_id


def test_unchanged_text_channel_with_an_export_writes_the_threads_only(lab_env: Path):
    t_saved = NOW - timedelta(hours=5)
    saved_id = str(from_time(t_saved))
    update_account_channels("123456789", {"200": ChannelSync(saved_id, t_saved.isoformat())})
    t_new = NOW - timedelta(hours=1)
    new_id = str(from_time(t_new))
    mock = MockSinceLastDiscord(
        channels=[sync_channel("200", 0, saved_id)],
        messages={"301": [make_msg(new_id, "New in the thread", "301", t_new)]},
        threads={"200": [make_thread(t_new, seq=1, parent_id="200", id="301", name="a thread")]},
    )
    target = lab_env / "export_dir"
    with Cache(lab_env / "cache.db") as cache, Directory(cache, lambda: new_api(mock)) as directory:
        req = MessagesRequest(channels=("200",), since_last=True, out_dir=str(target))
        outcome = run_messages(req, directory=directory, now=NOW, tz=CET)

    assert mock.calls["/channels/200/messages"] == 0
    assert outcome.exported is not None and outcome.exported.complete
    manifest = json.loads((target / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["counts"]["messages"] == 0 and manifest["counts"]["thread_messages"] == 1
    assert "New in the thread" in (target / "messages.md").read_text(encoding="utf-8")


def test_text_channel_with_newer_messages_is_fetched_even_with_threads(lab_env: Path):
    t_saved = NOW - timedelta(hours=5)
    update_account_channels("123456789", {"200": ChannelSync(str(from_time(t_saved)), t_saved.isoformat())})
    t_new = NOW - timedelta(hours=1)
    new_id = str(from_time(t_new))
    mock = MockSinceLastDiscord(
        channels=[sync_channel("200", 0, new_id)],  # Discord says there is something newer than the saved state
        messages={"200": [make_msg(new_id, "New message", "200", t_new)]},
        threads={"200": []},
    )
    with Cache(lab_env / "cache.db") as cache, Directory(cache, lambda: new_api(mock)) as directory:
        req = MessagesRequest(channels=("200",), since_last=True, threads=True)
        outcome = run_messages(req, directory=directory, now=NOW, tz=CET)

    assert mock.calls["/channels/200/messages"] == 1
    assert [m.id for m in outcome.results[0].messages] == [new_id]
    assert load_account_channels(mock.user_id)["200"].last_message_id == new_id


def test_text_channel_without_a_last_message_id_is_fetched_even_with_threads(lab_env: Path):
    t_saved = NOW - timedelta(hours=5)
    update_account_channels("123456789", {"200": ChannelSync(str(from_time(t_saved)), t_saved.isoformat())})
    mock = MockSinceLastDiscord(channels=[sync_channel("200", 0, None)], messages={"200": []}, threads={"200": []})
    with Cache(lab_env / "cache.db") as cache, Directory(cache, lambda: new_api(mock)) as directory:
        run_messages(MessagesRequest(channels=("200",), since_last=True), directory=directory, now=NOW, tz=CET)
    assert mock.calls["/channels/200/messages"] == 1


@pytest.mark.parametrize("forum_type", [15, 16], ids=["forum", "media"])
def test_forum_and_media_channels_are_never_skipped_whole_or_in_part(lab_env: Path, forum_type: int):
    t_saved = NOW - timedelta(hours=5)
    saved_id = str(from_time(t_saved))
    update_account_channels("123456789", {"204": ChannelSync(saved_id, t_saved.isoformat())})
    mock = MockSinceLastDiscord(
        channels=[sync_channel("204", forum_type, saved_id, available_tags=[])], threads={"204": []}
    )
    events = NoteCollectorEvents()
    with Cache(lab_env / "cache.db") as cache, Directory(cache, lambda: new_api(mock)) as directory:
        outcome = run_messages(
            MessagesRequest(channels=("204",), since_last=True), directory=directory, now=NOW, tz=CET, events=events
        )
    assert outcome.unchanged == 0 and len(outcome.results) == 1
    assert mock.calls["/channels/204/threads/search"] >= 1
    assert mock.calls["/channels/204/messages"] == 0  # a forum has no messages of its own, whatever its state
    assert not any("unchanged" in note for note in events.notes)


def test_no_threads_still_skips_an_unchanged_text_channel_whole(lab_env: Path):
    t_saved = NOW - timedelta(hours=5)
    saved_id = str(from_time(t_saved))
    update_account_channels("123456789", {"200": ChannelSync(saved_id, t_saved.isoformat())})
    mock = MockSinceLastDiscord(channels=[sync_channel("200", 0, saved_id)])
    events = NoteCollectorEvents()
    with Cache(lab_env / "cache.db") as cache, Directory(cache, lambda: new_api(mock)) as directory:
        outcome = run_messages(
            MessagesRequest(channels=("200",), since_last=True, threads=False),
            directory=directory,
            now=NOW,
            tz=CET,
            events=events,
        )
    assert outcome.unchanged == 1 and outcome.results == []
    assert mock.calls["/channels/200/messages"] == 0
    assert mock.calls["/channels/200/threads/search"] == 0
    assert any("is unchanged since last sync: skipping." in note for note in events.notes)


# --- an interrupted export: who may continue it, and what happens to the sync state ------------------------


class StopAfter(NoteCollectorEvents):
    """Stops the run (`Cancelled`) after `after` finished channels; records `resumed`."""

    def __init__(self, after: int | None = None) -> None:
        super().__init__()
        self.after = after
        self.finished = 0
        self.resumed_calls: list[tuple[int, int]] = []

    def channel_done(self, result) -> None:
        self.finished += 1
        if self.after is not None and self.finished >= self.after:
            raise Cancelled()

    def resumed(self, done: int, total: int) -> None:
        self.resumed_calls.append((done, total))


def two_channel_mock() -> MockSinceLastDiscord:
    when = {"200": NOW - timedelta(hours=3), "202": NOW - timedelta(hours=2)}
    return MockSinceLastDiscord(
        channels=[sync_channel("200", 0, None), sync_channel("202", 0, None)],
        messages={cid: [make_msg(str(from_time(t)), f"Msg {cid}", cid, t)] for cid, t in when.items()},
    )


@pytest.mark.parametrize(
    ("first", "second", "resumes"),
    [(True, False, False), (False, True, False), (True, True, True), (False, False, True)],
    ids=["since-last then normal", "normal then since-last", "both since-last", "both normal"],
)
def test_since_last_and_normal_runs_do_not_continue_each_other(lab_env: Path, first: bool, second: bool, resumes: bool):
    mock = two_channel_mock()
    target = lab_env / "export_dir"

    def request(since_last: bool) -> MessagesRequest:
        return MessagesRequest(channels=("200", "202"), out_dir=str(target), threads=False, since_last=since_last)

    with Cache(lab_env / "cache.db") as cache, Directory(cache, lambda: new_api(mock)) as directory:
        with pytest.raises(Cancelled):
            run_messages(request(first), directory=directory, now=NOW, tz=CET, events=StopAfter(after=1))
        events = StopAfter()
        outcome = run_messages(request(second), directory=directory, now=NOW, tz=CET, events=events)

    assert outcome.resumed == (1 if resumes else 0)
    assert events.resumed_calls == ([(1, 2)] if resumes else [])
    assert [result.channel.id for result in outcome.results] == (["202"] if resumes else ["200", "202"])
    manifest = json.loads((target / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["complete"] is True and manifest["request"]["since_last"] is second
    assert manifest["counts"]["channels"] == 2


def test_continued_since_last_run_says_the_saved_channels_keep_their_old_state(lab_env: Path):
    mock = two_channel_mock()
    target = lab_env / "export_dir"
    req = MessagesRequest(channels=("200", "202"), out_dir=str(target), threads=False, since_last=True)
    with Cache(lab_env / "cache.db") as cache, Directory(cache, lambda: new_api(mock)) as directory:
        with pytest.raises(Cancelled):
            run_messages(req, directory=directory, now=NOW, tz=CET, events=StopAfter(after=1))
        assert not sync_state_path().is_file()  # an interrupted run does not move the state
        events = StopAfter()
        outcome = run_messages(req, directory=directory, now=NOW, tz=CET, events=events)

    assert outcome.resumed == 1
    notes = [note for note in events.notes if "keep their old sync state" in note]
    assert notes == [
        "The channels saved by the interrupted run keep their old sync state, so the next --since-last fetches"
        " them again (duplicates, but nothing is lost)."
    ]
    # The known limitation: only the channel this run fetched is advanced
    channels = load_account_channels(mock.user_id)
    assert set(channels) == {"202"}


def test_continued_normal_run_has_no_sync_state_note(lab_env: Path):
    mock = two_channel_mock()
    req = MessagesRequest(channels=("200", "202"), out_dir=str(lab_env / "export_dir"), threads=False)
    with Cache(lab_env / "cache.db") as cache, Directory(cache, lambda: new_api(mock)) as directory:
        with pytest.raises(Cancelled):
            run_messages(req, directory=directory, now=NOW, tz=CET, events=StopAfter(after=1))
        events = StopAfter()
        run_messages(req, directory=directory, now=NOW, tz=CET, events=events)
    assert events.resumed_calls == [(1, 2)]
    assert not any("sync state" in note for note in events.notes)
