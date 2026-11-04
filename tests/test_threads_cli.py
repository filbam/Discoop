"""Tests for threads in CLI and service (R3 package).

Tests `discoop threads` command, forum end-to-end in `discoop messages`,
threads under text channels, --no-threads flag, 403 error handling (PARTIAL code 9),
--progress-json events, and export resumption with threads.
"""

import json
from collections import Counter
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

import httpx
import pytest

from discoop import cli
from discoop.api import DiscordAPI
from discoop.cache import Cache
from discoop.directory import Directory
from discoop.errors import ExitCode
from discoop.service import Cancelled, Events, MessagesRequest, run_messages
from discoop.snowflake import from_time
from discoop.tokenstore import TokenStore
from fake_messages import BOT, FIT, NOW, USER_A, USER_B, FakeChannel, message as make_message
from fake_threads import PARENT, FakeThreadSearch, series as thread_series, thread as make_thread

CET = timezone(timedelta(hours=1))

CHANNELS_DATA = [
    {"id": "100", "type": 4, "name": "general-cat", "position": 0},
    {"id": "101", "type": 2, "name": "voice-study", "position": 1},
    {"id": "200", "type": 0, "name": "2bit-general", "parent_id": "100", "position": 2},
    {
        "id": "204",
        "type": 15,
        "name": "help-center",
        "position": 3,
        "available_tags": [{"id": "901", "name": "bug"}, {"id": "902", "name": "feature"}],
    },
    {"id": "205", "type": 16, "name": "memes-media", "position": 4, "available_tags": []},
]


def at(hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 11, 3, hour, minute, tzinfo=CET).astimezone(UTC)


class MockThreadDiscord:
    """Mock Discord API supporting servers, channels, messages and threads/search."""

    def __init__(
        self,
        channels: list[dict] | None = None,
        messages: dict[str, list[dict]] | None = None,
        threads: dict[str, list[dict]] | None = None,
    ):
        self.channels_list = channels or list(CHANNELS_DATA)
        self.messages = messages or {}
        self.threads = threads or {}
        self.channel_status: dict[str, int] = {}
        self.thread_search_status: dict[str, int] = {}
        self.thread_message_status: dict[str, int] = {}
        self.thread_search_202: set[str] = set()
        self.calls: Counter = Counter()

    def handle(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path.removeprefix("/api/v9")
        self.calls[path] += 1
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
                    err_code = {403: 50001, 404: 10003}.get(code, 0)
                    return httpx.Response(code, json={"message": "forced", "code": err_code})
                if channel_id in self.thread_search_202:
                    return httpx.Response(202, json={"message": "Not Indexed"})
                t_list = self.threads.get(channel_id, [])
                searcher = FakeThreadSearch(t_list)
                return searcher.respond(request)

            if len(parts) == 3 and parts[2] == "messages":
                if channel_id in self.channel_status:
                    code = self.channel_status[channel_id]
                    err_code = {403: 50001, 404: 10003}.get(code, 0)
                    return httpx.Response(code, json={"message": "forced", "code": err_code})
                if channel_id in self.thread_message_status:
                    code = self.thread_message_status[channel_id]
                    err_code = {403: 50001, 404: 10003}.get(code, 0)
                    return httpx.Response(code, json={"message": "forced", "code": err_code})
                msgs = self.messages.get(channel_id, [])
                fc = FakeChannel(msgs)
                return fc.respond(request)

        return httpx.Response(404, json={"message": "Unknown Endpoint", "code": 10003})


@pytest.fixture
def thread_lab(monkeypatch):
    TokenStore.default().save("tok")
    monkeypatch.setattr(cli, "utc_now", lambda: NOW)
    monkeypatch.setattr(cli, "LOCAL_ZONE", CET)

    t1_created = at(9, 0)
    t1_last = at(10, 0)
    t2_created = at(10, 30)
    t2_last = at(11, 0)

    # Old thread (45 days ago)
    t_old_time = NOW - timedelta(days=45)

    thread_1 = make_thread(
        t1_last,
        created=t1_created,
        seq=1,
        parent_id="204",
        name="cannot login",
        applied_tags=["901"],
        message_count=2,
    )
    thread_2 = make_thread(
        t2_last,
        created=t2_created,
        seq=2,
        parent_id="204",
        name="dark mode",
        applied_tags=["902"],
        message_count=1,
    )
    thread_old = make_thread(
        t_old_time,
        created=t_old_time - timedelta(hours=1),
        seq=99,
        parent_id="204",
        name="ancient post",
        applied_tags=[],
        message_count=1,
    )

    t1_id = thread_1["id"]
    t2_id = thread_2["id"]
    t_old_id = thread_old["id"]

    msg_t1 = [
        make_message(at(9, 0), "I cannot login to the system", author=USER_A),
        make_message(at(10, 0), "Use password reset", author=USER_B),
    ]
    msg_t2 = [
        make_message(at(10, 30), "Please add dark mode", author=USER_A),
    ]
    msg_old = [
        make_message(t_old_time, "Ancient thread message", author=USER_A),
    ]
    msg_200 = [
        make_message(at(8, 0), "Hello text channel", author=USER_A),
    ]

    # A thread under 200 text channel
    t_text_channel = make_thread(
        at(10, 15),
        created=at(10, 0),
        seq=5,
        parent_id="200",
        name="project discussion",
        applied_tags=[],
        message_count=1,
    )
    t_text_id = t_text_channel["id"]
    msg_text_thread = [
        make_message(at(10, 15), "Discussion message", author=USER_B),
    ]

    mock = MockThreadDiscord(
        threads={"204": [thread_2, thread_1, thread_old], "200": [t_text_channel]},
        messages={
            "200": msg_200,
            t1_id: msg_t1,
            t2_id: msg_t2,
            t_old_id: msg_old,
            t_text_id: msg_text_thread,
        },
    )

    transport = httpx.MockTransport(mock.handle)
    monkeypatch.setattr(cli, "DiscordAPI", lambda token, **kw: DiscordAPI(token, transport=transport))
    return mock


def run(capsys, *args):
    with pytest.raises(SystemExit) as e:
        cli.main(["--agent", *args])
    captured = capsys.readouterr()
    return e.value.code, captured.out, captured.err


# --- discoop threads command tests -----------------------------------------------------------------


def test_threads_plain_tsv(capsys, thread_lab):
    code, out, err = run(capsys, "threads", "-s", FIT, "-c", "help-center", "--plain")
    assert code == 0
    lines = out.strip().splitlines()
    assert lines[0] == "id\tarchived\tmessages\tlast_activity\ttags\tname"
    # Newest activity first: dark mode (t2), then cannot login (t1)
    # The ancient thread (45 days ago) is omitted by default 30d window
    assert len(lines) == 3
    assert "dark mode" in lines[1]
    assert "feature" in lines[1]
    assert "cannot login" in lines[2]
    assert "bug" in lines[2]


def test_threads_from_all_includes_older_threads(capsys, thread_lab):
    code, out, _ = run(capsys, "threads", "-s", FIT, "-c", "help-center", "--from", "all", "--plain")
    assert code == 0
    lines = out.strip().splitlines()
    assert len(lines) == 4  # header + 3 threads
    assert any("ancient post" in l for l in lines)


def test_threads_human_table(capsys, thread_lab):
    with pytest.raises(SystemExit) as e:
        cli.main(["--human", "threads", "-s", FIT, "-c", "help-center"])
    captured = capsys.readouterr()
    assert e.value.code == 0
    assert "Threads in #help-center (2)" in captured.out
    assert "cannot login" in captured.out
    assert "dark mode" in captured.out


def test_threads_format_json(capsys, thread_lab):
    code, out, _ = run(capsys, "threads", "-s", FIT, "-c", "help-center", "--format", "json")
    assert code == 0
    data = json.loads(out)
    assert isinstance(data, list)
    assert len(data) == 2
    item = data[0]
    expected_keys = {
        "id",
        "name",
        "parent_id",
        "type",
        "archived",
        "locked",
        "message_count",
        "created",
        "last_activity",
        "tags",
    }
    assert set(item.keys()) == expected_keys
    assert item["name"] in ("dark mode", "cannot login")
    assert isinstance(item["tags"], list)


def test_threads_on_category_rejected(capsys, thread_lab):
    code, _, err = run(capsys, "threads", "-s", FIT, "-c", "100")
    assert code == int(ExitCode.BAD_ARGS)
    assert "cannot have threads" in err


def test_threads_on_voice_channel_rejected(capsys, thread_lab):
    code, _, err = run(capsys, "threads", "-s", FIT, "-c", "101")
    assert code == int(ExitCode.BAD_ARGS)
    assert "cannot have threads" in err


# --- discoop messages with threads -----------------------------------------------------------------


def test_messages_forum_end_to_end(capsys, thread_lab):
    code, out, _ = run(capsys, "messages", "-s", FIT, "-c", "help-center")
    assert code == 0
    assert "=== VUT FIT / #help-center ===" in out
    assert "threads: 2 (3 messages)" in out
    # Forum itself has 0 messages
    assert "messages: 0" in out
    # Check threads rendered oldest first: cannot login (at 9:00), dark mode (at 10:30)
    assert 'thread "cannot login"' in out
    assert 'thread "dark mode"' in out
    assert out.index('thread "cannot login"') < out.index('thread "dark mode"')
    assert "I cannot login to the system" in out
    assert "Please add dark mode" in out


def test_messages_text_channel_with_threads(capsys, thread_lab):
    code, out, _ = run(capsys, "messages", "-s", FIT, "-c", "2bit-general")
    assert code == 0
    assert "=== VUT FIT / #2bit-general ===" in out
    assert "Hello text channel" in out
    assert 'thread "project discussion"' in out
    assert "Discussion message" in out


def test_messages_no_threads_skips_threads(capsys, thread_lab):
    code, out, _ = run(capsys, "messages", "-s", FIT, "-c", "2bit-general", "--no-threads")
    assert code == 0
    assert "Hello text channel" in out
    assert "project discussion" not in out
    assert "Discussion message" not in out


def test_messages_forum_with_no_threads_rejected(capsys, thread_lab):
    code, _, err = run(capsys, "messages", "-s", FIT, "-c", "help-center", "--no-threads")
    assert code == int(ExitCode.BAD_ARGS)
    assert "A forum only has threads: drop --no-threads" in err


def test_messages_glob_with_forum_and_no_threads_rejected(capsys, thread_lab):
    # Matches both 2bit-general (0) and help-center (15) or memes-media (16)
    code, _, err = run(capsys, "messages", "-s", FIT, "-c", "*-center", "--no-threads")
    assert code == int(ExitCode.BAD_ARGS)
    assert "A forum only has threads: drop --no-threads" in err


def test_messages_thread_403_results_in_partial_exit_code_9(capsys, thread_lab):
    t2_id = [t["id"] for t in thread_lab.threads["204"] if t["name"] == "dark mode"][0]
    thread_lab.thread_message_status[t2_id] = 403

    code, out, err = run(capsys, "messages", "-s", FIT, "-c", "help-center")
    assert code == int(ExitCode.PARTIAL)
    assert code == 9
    assert "Could not read thread \"dark mode\"" in err
    # Other thread is still rendered
    assert 'thread "cannot login"' in out
    assert "I cannot login to the system" in out
    assert "dark mode" not in out


def test_messages_channel_thread_search_error_results_in_partial_9(capsys, thread_lab):
    # Error listing threads of a text channel -> warning, partial exit code 9, channel messages kept
    thread_lab.thread_search_status["200"] = 403

    code, out, err = run(capsys, "messages", "-s", FIT, "-c", "2bit-general")
    assert code == int(ExitCode.PARTIAL)
    assert code == 9
    assert "Could not list threads of #2bit-general" in err
    assert "Hello text channel" in out
    assert "project discussion" not in out


def test_messages_thread_search_problem_warns_and_returns_9(capsys, thread_lab):
    # HTTP 202 on threads/search -> Stop.NOT_INDEXED -> FetchedThreads.problem is set
    thread_lab.thread_search_202.add("200")

    code, out, err = run(capsys, "messages", "-s", FIT, "-c", "2bit-general")
    assert code == int(ExitCode.PARTIAL)
    assert code == 9
    assert "Discord has not indexed the threads of this channel yet" in err
    assert "Hello text channel" in out


def test_messages_progress_json_with_threads(capsys, thread_lab):
    code, _, err = run(capsys, "messages", "-s", FIT, "-c", "help-center", "--progress-json")
    assert code == 0
    lines = [json.loads(line) for line in err.strip().splitlines() if line.strip()]
    thread_events = [ev for ev in lines if ev.get("event") == "thread"]
    assert len(thread_events) == 2
    for ev in thread_events:
        assert ev["channel_id"] == "204"
        assert "thread_id" in ev
        assert "index" in ev
        assert "total" in ev
        # Strict privacy check: no channel or thread names, no message contents!
        assert "name" not in ev
        assert "content" not in ev
        assert "text" not in ev
        assert "cannot login" not in json.dumps(ev)
        assert "dark mode" not in json.dumps(ev)


def test_messages_export_resumption_with_threads(tmp_path, capsys, thread_lab):
    out_dir = tmp_path / "export_run"
    # Perform export with threads to out_dir
    code, _, _ = run(
        capsys,
        "messages",
        "-s",
        FIT,
        "-c",
        "help-center",
        "-c",
        "2bit-general",
        "--out",
        str(out_dir),
    )
    # Target directory was created and contains channels and manifest
    assert out_dir.exists()
    manifest_file = out_dir / "manifest.json"
    assert manifest_file.exists()
    manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
    assert manifest["complete"] is True
    assert manifest["counts"]["threads"] == 3


# --- an interrupted export is continued only by a run with the same thread setting -------------------


class Probe(Events):
    """Stops the run (`Cancelled`) after `stop_after` finished channels and records what the run said."""

    def __init__(self, stop_after: int | None = None) -> None:
        super().__init__()
        self.stop_after = stop_after
        self.finished = 0
        self.resumed_calls: list[tuple[int, int]] = []
        self.notes: list[str] = []

    def channel_done(self, result) -> None:
        self.finished += 1
        if self.stop_after is not None and self.finished >= self.stop_after:
            raise Cancelled()

    def resumed(self, done: int, total: int) -> None:
        self.resumed_calls.append((done, total))

    def note(self, text: str) -> None:
        self.notes.append(text)


def run_service(mock: MockThreadDiscord, tmp_path: Path, request: MessagesRequest, events: Events):
    api = DiscordAPI("tok", transport=httpx.MockTransport(mock.handle), delay=0.0, mode="safe", sleep=lambda s: None)
    nothing = httpx.MockTransport(lambda r: httpx.Response(404))
    with Cache(tmp_path / "cache.db") as cache, Directory(cache, lambda: api) as directory:
        return run_messages(
            request,
            directory=directory,
            cdn=lambda: httpx.Client(transport=nothing),
            now=NOW,
            tz=CET,
            events=events,
        )


def two_text_channels(mock: MockThreadDiscord) -> None:
    """2bit-general (with one thread) and a second text channel without threads."""
    mock.channels_list.append(
        {"id": "206", "type": 0, "name": "2bit-second", "parent_id": "100", "position": 6, "last_message_id": None}
    )
    mock.messages["206"] = [make_message(at(8, 30), "Second channel", author=USER_A)]


def threads_request(target: Path, *, threads: bool) -> MessagesRequest:
    return MessagesRequest(channels=("200", "206"), server=FIT, out_dir=str(target), threads=threads)


def test_export_with_threads_is_not_continued_by_a_run_without_threads(tmp_path, thread_lab):
    two_text_channels(thread_lab)
    target = tmp_path / "export"
    with pytest.raises(Cancelled):
        run_service(thread_lab, tmp_path, threads_request(target, threads=True), Probe(stop_after=1))
    staging = target.with_name(target.name + ".partial")
    saved = json.loads((staging / "manifest.json").read_text(encoding="utf-8"))
    assert saved["counts"]["threads"] == 1 and saved["request"]["threads"] is True

    probe = Probe()
    outcome = run_service(thread_lab, tmp_path, threads_request(target, threads=False), probe)
    assert outcome.resumed == 0 and probe.resumed_calls == []
    assert not any("Continuing" in note for note in probe.notes)
    assert [result.channel.id for result in outcome.results] == ["200", "206"]  # both fetched again, no threads
    assert all(result.threads == () for result in outcome.results)
    manifest = json.loads((target / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["complete"] is True and manifest["request"]["threads"] is False
    assert "threads" not in manifest["counts"]
    assert "project discussion" not in (target / "messages.md").read_text(encoding="utf-8")
    assert not staging.exists()


def test_export_with_threads_is_continued_by_a_run_with_threads(tmp_path, thread_lab):
    two_text_channels(thread_lab)
    target = tmp_path / "export"
    with pytest.raises(Cancelled):
        run_service(thread_lab, tmp_path, threads_request(target, threads=True), Probe(stop_after=1))

    probe = Probe()
    outcome = run_service(thread_lab, tmp_path, threads_request(target, threads=True), probe)
    assert outcome.resumed == 1 and probe.resumed_calls == [(1, 2)]
    assert [result.channel.id for result in outcome.results] == ["206"]  # 200 was taken over with its thread
    manifest = json.loads((target / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["counts"]["threads"] == 1 and manifest["request"]["threads"] is True
    assert "project discussion" in (target / "messages.md").read_text(encoding="utf-8")
