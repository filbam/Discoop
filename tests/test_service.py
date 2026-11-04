"""Tests for discoop.service and related CLI commands."""

from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

import httpx
import pytest

from discoop import cli, service
from discoop.api import DiscordAPI
from discoop.cache import Cache
from discoop.directory import Directory
from discoop.errors import DiscoopError, ExitCode
from discoop.models import Channel, ChannelMessages, Server
from discoop.service import Events, MessagesOutcome, MessagesRequest
from discoop.snowflake import from_time

NOW = datetime(2026, 11, 3, 12, 0, tzinfo=UTC)
CET = timezone(timedelta(hours=1))


def make_message(msg_id: str, content: str, channel_id: str, when: datetime) -> dict:
    return {
        "id": msg_id,
        "type": 0,
        "channel_id": channel_id,
        "content": content,
        "author": {"id": "1", "username": "alice", "global_name": "Alice", "discriminator": "0"},
        "timestamp": when.isoformat(),
        "edited_timestamp": None,
        "attachments": [],
        "embeds": [],
        "mentions": [],
        "mention_roles": [],
        "pinned": False,
        "flags": 0,
        "components": [],
    }


def test_messages_request_to_argv_and_to_command_str():
    # 1. Defaults
    req = MessagesRequest(channels=("ch1",))
    assert req.to_argv() == ["messages", "-c", "ch1", "--safe"]
    assert req.to_command_str() == "discoop messages -c ch1 --safe"

    # 2. Fully populated with special characters needing quoting
    req_full = MessagesRequest(
        server="VUT FIT",
        channels=("isc-public", "2bit-general"),
        from_="7d",
        to="now",
        last=25,
        max_messages=1000,
        include_system=True,
        mode="fast",
        delay=0.5,
        out_dir="exports/my run",
        zip_file="exports/my archive.zip",
        print_messages=True,
        no_files=True,
        max_file_size=25.5,
        output_format="json",
    )
    expected_argv = [
        "messages",
        "-s", "VUT FIT",
        "-c", "isc-public",
        "-c", "2bit-general",
        "--from", "7d",
        "--to", "now",
        "--last", "25",
        "--max-messages", "1000",
        "--include-system",
        "--fast",
        "--delay", "0.5",
        "--out", "exports/my run",
        "--zip", "exports/my archive.zip",
        "--print",
        "--no-files",
        "--max-file-size", "25.5",
        "--format", "json",
    ]
    assert req_full.to_argv() == expected_argv
    cmd_str = req_full.to_command_str()
    assert cmd_str.startswith("discoop messages -s 'VUT FIT'") or cmd_str.startswith('discoop messages -s "VUT FIT"')
    assert "-c isc-public -c 2bit-general" in cmd_str
    assert "--fast" in cmd_str
    assert "--format json" in cmd_str


def test_messages_request_mode_variations():
    req_safe = MessagesRequest(channels=("c1",), mode="safe")
    assert "--safe" in req_safe.to_argv()

    req_fast = MessagesRequest(channels=("c1",), mode="fast")
    assert "--fast" in req_fast.to_argv()
    assert "--safe" not in req_fast.to_argv()

    req_other = MessagesRequest(channels=("c1",), mode="custom")
    assert "--safe" not in req_other.to_argv()
    assert "--fast" not in req_other.to_argv()


def test_run_messages_two_channels_across_servers(tmp_path):
    """Test fetching messages from 2 channels across 2 servers by ID without server,
    verifying Events callbacks are invoked."""
    s1_id, s2_id = "1001", "2002"
    c1_id, c2_id = "101", "201"

    guilds_data = [
        {"id": s1_id, "name": "Server 1", "approximate_member_count": 10},
        {"id": s2_id, "name": "Server 2", "approximate_member_count": 20},
    ]
    c1_data = {"id": c1_id, "name": "general-1", "type": 0, "guild_id": s1_id}
    c2_data = {"id": c2_id, "name": "general-2", "type": 0, "guild_id": s2_id}

    t1 = NOW - timedelta(hours=2)
    t2 = NOW - timedelta(hours=1)
    # Provide 26 messages so that with page_size=25 in safe mode, a second page is fetched,
    # triggering on_page (events.page) after the first page.
    all_c1 = [
        make_message(str(from_time(t1 - timedelta(minutes=i))), f"Msg 1-{i}", c1_id, t1 - timedelta(minutes=i))
        for i in range(26)
    ]
    all_c2 = [
        make_message(str(from_time(t2 - timedelta(minutes=i))), f"Msg 2-{i}", c2_id, t2 - timedelta(minutes=i))
        for i in range(26)
    ]

    def handle(request: httpx.Request) -> httpx.Response:
        path = request.url.path.removeprefix("/api/v9")
        if path == "/users/@me/guilds":
            return httpx.Response(200, json=guilds_data)
        if path == f"/channels/{c1_id}":
            return httpx.Response(200, json=c1_data)
        if path == f"/channels/{c2_id}":
            return httpx.Response(200, json=c2_data)
        if path == f"/guilds/{s1_id}/channels":
            return httpx.Response(200, json=[c1_data])
        if path == f"/guilds/{s2_id}/channels":
            return httpx.Response(200, json=[c2_data])
        if path == f"/channels/{c1_id}/messages":
            params = dict(request.url.params)
            limit = int(params.get("limit", 25))
            before = int(params["before"]) if "before" in params else None
            older = [m for m in all_c1 if before is None or int(m["id"]) < before]
            return httpx.Response(200, json=older[:limit])
        if path == f"/channels/{c2_id}/messages":
            params = dict(request.url.params)
            limit = int(params.get("limit", 25))
            before = int(params["before"]) if "before" in params else None
            older = [m for m in all_c2 if before is None or int(m["id"]) < before]
            return httpx.Response(200, json=older[:limit])
        return httpx.Response(404, json={"message": "Not Found", "code": 10003})

    transport = httpx.MockTransport(handle)
    api = DiscordAPI("token", transport=transport, delay=0.0, mode="safe")
    with Cache(tmp_path / "cache.db") as cache, Directory(cache, lambda: api) as directory:
        class TrackingEvents(Events):
            def __init__(self):
                super().__init__()
                self.channel_starts = []
                self.pages = []
                self.channel_dones = []

            def channel_start(self, index: int, total: int, server: Server, channel: Channel) -> None:
                self.channel_starts.append((index, total, server.id, channel.id))

            def page(self, kept: int, oldest_id: int) -> None:
                self.pages.append((kept, oldest_id))

            def channel_done(self, result: ChannelMessages) -> None:
                self.channel_dones.append(result)

        events = TrackingEvents()
        req = MessagesRequest(channels=(c1_id, c2_id), server=None, from_="24h")

        outcome = service.run_messages(
            req,
            directory=directory,
            now=NOW,
            tz=CET,
            events=events,
        )

        assert len(outcome.results) == 2
        assert outcome.skipped == []
        assert outcome.exported is None
        assert outcome.results[0].server.id == s1_id
        assert outcome.results[0].channel.id == c1_id
        assert len(outcome.results[0].messages) == 26

        assert outcome.results[1].server.id == s2_id
        assert outcome.results[1].channel.id == c2_id
        assert len(outcome.results[1].messages) == 26

        # Verify Events callbacks
        assert events.channel_starts == [
            (1, 2, s1_id, c1_id),
            (2, 2, s2_id, c2_id),
        ]
        assert len(events.pages) == 2
        assert len(events.channel_dones) == 2


def test_load_all_caches_all_and_skips_403(tmp_path):
    """Test service.load_all() with httpx.MockTransport verifying all servers and
    their channels are cached, and a 403 server is gracefully skipped."""
    s1_id, s2_id, s3_id = "1001", "2002", "3003"
    c1_id, c3_id = "101", "301"

    guilds_data = [
        {"id": s1_id, "name": "Server 1", "approximate_member_count": 10},
        {"id": s2_id, "name": "Server 2 (Forbidden)", "approximate_member_count": 5},
        {"id": s3_id, "name": "Server 3", "approximate_member_count": 15},
    ]
    c1_data = [{"id": c1_id, "name": "c1", "type": 0}]
    c3_data = [{"id": c3_id, "name": "c3", "type": 0}]

    def handle(request: httpx.Request) -> httpx.Response:
        path = request.url.path.removeprefix("/api/v9")
        if path == "/users/@me/guilds":
            return httpx.Response(200, json=guilds_data)
        if path == f"/guilds/{s1_id}/channels":
            return httpx.Response(200, json=c1_data)
        if path == f"/guilds/{s2_id}/channels":
            # 403 Missing Access
            return httpx.Response(403, json={"code": 50001, "message": "Missing Access"})
        if path == f"/guilds/{s3_id}/channels":
            return httpx.Response(200, json=c3_data)
        return httpx.Response(404, json={"message": "Not Found", "code": 10003})

    transport = httpx.MockTransport(handle)
    api = DiscordAPI("token", transport=transport, delay=0.0)
    with Cache(tmp_path / "cache.db") as cache, Directory(cache, lambda: api) as directory:
        on_server_calls = []

        def on_server(index: int, total: int, server: Server) -> None:
            on_server_calls.append((index, total, server.id))

        all_data = service.load_all(directory, on_server=on_server)

        assert len(all_data) == 3
        # Server 1
        assert all_data[0][0].id == s1_id
        assert [c.id for c in all_data[0][1]] == [c1_id]
        # Server 2 (403 skipped to empty channel list)
        assert all_data[1][0].id == s2_id
        assert all_data[1][1] == []
        # Server 3
        assert all_data[2][0].id == s3_id
        assert [c.id for c in all_data[2][1]] == [c3_id]

        assert on_server_calls == [
            (1, 3, s1_id),
            (2, 3, s2_id),
            (3, 3, s3_id),
        ]

        # Verify cache content
        cached_servers = cache.servers()
        assert [s.id for s in cached_servers] == [s1_id, s2_id, s3_id]
        assert [c.id for c in cache.channels(s1_id)] == [c1_id]
        assert cache.channels(s2_id) == []
        assert [c.id for c in cache.channels(s3_id)] == [c3_id]


def test_ui_plain_mode_exits_bad_args(capsys):
    """Test ui command in plain mode (cli.main(["--plain", "ui"])) exits with code 8 (BAD_ARGS)."""
    with pytest.raises(SystemExit) as e:
        cli.main(["--plain", "ui"])
    assert e.value.code == int(ExitCode.BAD_ARGS)
    assert e.value.code == 8
    captured = capsys.readouterr()
    assert "ERROR BAD_ARGS: discoop ui requires an interactive terminal." in captured.err

    # Also test via --agent alias
    with pytest.raises(SystemExit) as e_agent:
        cli.main(["--agent", "ui"])
    assert e_agent.value.code == 8


def test_command_help():
    """Test command_help() returns the root help (including NOTE FOR AI AGENTS)
    and command_help(("messages",)) returns messages help (including --safe and --fast)."""
    root_help = cli.command_help()
    assert "NOTE FOR AI AGENTS" in root_help
    assert "GETTING STARTED" in root_help
    assert "discoop ui" in root_help
    assert "discoop messages" in root_help

    messages_help = cli.command_help(("messages",))
    assert "--safe" in messages_help
    assert "--fast" in messages_help
    assert "--channel" in messages_help
    assert "--delay" in messages_help
    assert "Pacing modes:" in messages_help

    # Test other subcommands specified in the prompt
    servers_help = cli.command_help(("servers",))
    assert "List your servers" in servers_help

    channels_help = cli.command_help(("channels",))
    assert "List the channels of a server" in channels_help

    login_help = cli.command_help(("login",))
    assert "Log in" in login_help

    status_help = cli.command_help(("status",))
    assert "Check that the stored login still works" in status_help

    logout_help = cli.command_help(("logout",))
    assert "Forget the stored login" in logout_help

    config_help = cli.command_help(("config",))
    assert "Show or change settings" in config_help

    ui_help = cli.command_help(("ui",))
    assert "interactive terminal" in ui_help.lower()


def test_validate_export_target_validation():
    # Both --out and --zip
    with pytest.raises(DiscoopError) as exc_info:
        service.validate_export_target("dir", "file.zip", False, False, None)
    assert exc_info.value.code == ExitCode.BAD_ARGS

    # Flag without target
    with pytest.raises(DiscoopError) as exc_info:
        service.validate_export_target(None, None, True, False, None)
    assert exc_info.value.code == ExitCode.BAD_ARGS

    # Negative file size
    with pytest.raises(DiscoopError) as exc_info:
        service.validate_export_target("dir", None, False, False, -1.0)
    assert exc_info.value.code == ExitCode.BAD_ARGS


def test_cancelled_exception():
    assert issubclass(service.Cancelled, Exception)


def test_messages_request_threads_argv():
    req_default = MessagesRequest(channels=("c1",))
    assert req_default.threads is True
    assert "--no-threads" not in req_default.to_argv()

    req_no_threads = MessagesRequest(channels=("c1",), threads=False)
    assert req_no_threads.threads is False
    assert "--no-threads" in req_no_threads.to_argv()


def test_list_threads_validates_container(tmp_path):
    category_channel = Channel("100", "srv1", "general-cat", 4)
    voice_channel = Channel("101", "srv1", "voice", 2)
    cache = Cache(tmp_path / "cache.db")
    directory = Directory(cache, lambda: DiscordAPI("tok"))
    window = service.Window(None, NOW)

    with pytest.raises(DiscoopError) as exc_cat:
        service.list_threads(directory, category_channel, window)
    assert exc_cat.value.code == ExitCode.BAD_ARGS
    assert "it cannot have threads" in exc_cat.value.message

    with pytest.raises(DiscoopError) as exc_voice:
        service.list_threads(directory, voice_channel, window)
    assert exc_voice.value.code == ExitCode.BAD_ARGS


def test_resolve_targets_forum_and_media(tmp_path):
    forum_channel = Channel("204", "1001", "help-forum", 15)
    media_channel = Channel("205", "1001", "memes-media", 16)
    category_channel = Channel("100", "1001", "cat", 4)
    server = Server("1001", "Server 1")

    cache = Cache(tmp_path / "cache.db")
    cache.replace_servers([server])
    cache.replace_channels("1001", [forum_channel, media_channel, category_channel])
    directory = Directory(cache, lambda: DiscordAPI("tok"))

    targets = service.resolve_targets(directory, "1001", ["help-forum", "memes-media"])
    assert len(targets) == 2
    assert targets[0][1].id == "204"
    assert targets[1][1].id == "205"

    with pytest.raises(DiscoopError) as exc:
        service.resolve_targets(directory, "1001", ["100"])
    assert exc.value.code == ExitCode.BAD_ARGS
    assert "is a category, not a channel" in exc.value.message


def test_threads_command_help():
    threads_help = cli.command_help(("threads",))
    assert "List the threads and forum posts of a channel" in threads_help
    assert "--channel" in threads_help
    assert "--from" in threads_help
    assert "--refresh" in threads_help

