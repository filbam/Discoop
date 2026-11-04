from collections import Counter

import httpx
import pytest

from discoop import cli
from discoop.api import DiscordAPI
from discoop.cache import Cache, cache_path
from discoop.config import Config
from discoop.models import Channel, Server, group_by_category
from discoop.tokenstore import TokenStore

FIT = "461541385204400138"
GUILDS = [
    {"id": FIT, "name": "VUT FIT", "approximate_member_count": 5000},
    {"id": "2", "name": "Gaming", "approximate_member_count": 12},
]
CHANNELS = [
    {"id": "100", "type": 4, "name": "general", "position": 254},
    {"id": "101", "type": 4, "name": "volitelne", "position": 240},
    {"id": "200", "type": 0, "name": "2bit-general", "parent_id": "100", "position": 3},
    {"id": "201", "type": 2, "name": "hospoda", "parent_id": "100", "position": 0},
    {"id": "202", "type": 0, "name": "2bit-terminy", "parent_id": "100", "position": 1},
    {"id": "203", "type": 0, "name": "aeu-private🔒", "parent_id": "101", "position": 0},  # Preserves emoji to verify Unicode channel handling
    {"id": "204", "type": 15, "name": "help-center", "position": 2},
    {"id": "205", "type": 0, "name": "___hidden___", "flags": 131072, "position": 4},
]


@pytest.fixture
def discord(monkeypatch):
    """Logged in, with a fake Discord answering the guild and channel lists."""
    TokenStore.default().save("tok")
    calls: Counter = Counter()

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path.removeprefix("/api/v9")
        calls[path] += 1
        if path == "/users/@me/guilds":
            return httpx.Response(200, json=GUILDS)
        if path == f"/guilds/{FIT}/channels":
            return httpx.Response(200, json=CHANNELS)
        return httpx.Response(403, json={"message": "Missing Access", "code": 50001})

    transport = httpx.MockTransport(handler)
    monkeypatch.setattr(cli, "DiscordAPI", lambda token, **kw: DiscordAPI(token, transport=transport))
    return calls


def run(capsys, *args):
    with pytest.raises(SystemExit) as e:
        cli.main(["--agent", *args])
    captured = capsys.readouterr()
    return e.value.code, captured.out, captured.err


def test_servers_are_fetched_once_then_cached(capsys, discord):
    code, out, _ = run(capsys, "servers")
    assert code == 0
    assert out == f"id\tmembers\tname\n2\t12\tGaming\n{FIT}\t5000\tVUT FIT\n"
    run(capsys, "servers")
    assert discord["/users/@me/guilds"] == 1
    run(capsys, "servers", "--refresh")
    assert discord["/users/@me/guilds"] == 2


def test_channels_in_sidebar_order_without_hidden(capsys, discord):
    code, out, _ = run(capsys, "channels", "-s", "vut fit")
    assert code == 0
    assert out.splitlines() == [
        "id\ttype\tcategory\tname",
        "204\tforum\t\thelp-center",
        "203\ttext\tvolitelne\taeu-private🔒",
        "202\ttext\tgeneral\t2bit-terminy",
        "200\ttext\tgeneral\t2bit-general",
        "201\tvoice\tgeneral\thospoda",
    ]


def test_type_filter(capsys, discord):
    _, out, _ = run(capsys, "channels", "-s", FIT, "--type", "forum,voice")
    assert [line.split("\t")[0] for line in out.splitlines()[1:]] == ["204", "201"]
    code, _, err = run(capsys, "channels", "-s", FIT, "--type", "chat")
    assert code == 8 and "Known types" in err


def test_default_server_from_config(capsys, discord):
    code, _, err = run(capsys, "channels")
    assert code == 8 and "config set default-server" in err
    code, out, _ = run(capsys, "config", "set", "default-server", "VUT fit")
    assert (code, out) == (0, f"default-server = {FIT} (VUT FIT)\n")
    assert Config.default().get("default-server") == FIT
    code, out, _ = run(capsys, "channels")
    assert code == 0 and "2bit-general" in out


def test_unknown_server_refreshes_the_cache_once(capsys, discord):
    with Cache.default() as cache:
        cache.replace_servers([Server("2", "Gaming")])  # stale: VUT FIT is missing
    code, _, _ = run(capsys, "channels", "-s", "VUT FIT")
    assert code == 0 and discord["/users/@me/guilds"] == 1
    code, _, err = run(capsys, "channels", "-s", "Nope")
    assert code == 4
    assert err.startswith('ERROR NOT_FOUND: No server matches "Nope".')
    assert discord["/users/@me/guilds"] == 2


def test_server_without_access(capsys, discord):
    code, _, err = run(capsys, "channels", "-s", "Gaming")
    assert code == 5 and err.startswith("ERROR NO_ACCESS")


def test_not_logged_in(capsys):
    code, _, err = run(capsys, "servers")
    assert code == 2 and err.startswith("ERROR AUTH_REQUIRED")


def test_logout_clears_the_cache(capsys, discord):
    run(capsys, "servers")
    assert cache_path().exists()
    run(capsys, "logout")
    assert not cache_path().exists()


def test_human_tree(capsys, discord):
    with pytest.raises(SystemExit):
        cli.main(["--human", "channels", "-s", "VUT FIT"])
    out = capsys.readouterr().out
    assert "VUT FIT" in out and "#2bit-general" in out and "help-center  forum" in out
    assert "___hidden___" not in out


def test_config_list_and_unset(capsys):
    _, out, _ = run(capsys, "config", "list")
    assert out.splitlines()[0] == "key\tvalue\tdescription"
    assert "delay\t1.0\t" in out
    run(capsys, "config", "set", "delay", "0.5")
    assert Config.default().get("delay") == 0.5
    _, out, _ = run(capsys, "config", "unset", "delay")
    assert out == "delay reset to its default.\n"


def test_group_by_category_ignores_unknown_parents():
    groups = group_by_category([Channel("1", FIT, "orphan", 0, parent_id="999")])
    assert groups == [(None, [Channel("1", FIT, "orphan", 0, parent_id="999")])]


import json


def test_servers_format_json(capsys, discord):
    code, out, _ = run(capsys, "servers", "--format", "json")
    assert code == 0
    data = json.loads(out)
    assert data == [
        {"id": "2", "name": "Gaming", "member_count": 12},
        {"id": FIT, "name": "VUT FIT", "member_count": 5000},
    ]
    # Cache note goes to stderr, stdout is clean JSON
    code, out, err = run(capsys, "-v", "servers", "--format", "json")
    assert code == 0
    assert json.loads(out) == data
    assert "From the local cache" in err


def test_channels_format_json(capsys, discord):
    code, out, _ = run(capsys, "channels", "-s", "vut fit", "--format", "json")
    assert code == 0
    data = json.loads(out)
    assert data == [
        {"id": "204", "name": "help-center", "type": 15, "type_name": "forum", "category": None, "position": 2},
        {"id": "203", "name": "aeu-private🔒", "type": 0, "type_name": "text", "category": "volitelne", "position": 0},
        {"id": "202", "name": "2bit-terminy", "type": 0, "type_name": "text", "category": "general", "position": 1},
        {"id": "200", "name": "2bit-general", "type": 0, "type_name": "text", "category": "general", "position": 3},
        {"id": "201", "name": "hospoda", "type": 2, "type_name": "voice", "category": "general", "position": 0},
    ]

    # Type filter is respected
    code, out, _ = run(capsys, "channels", "-s", FIT, "--type", "forum,voice", "--format", "json")
    assert code == 0
    assert [c["id"] for c in json.loads(out)] == ["204", "201"]

    # Cache note goes to stderr
    code, out, err = run(capsys, "-v", "channels", "-s", FIT, "--format", "json")
    assert code == 0
    assert json.loads(out) == data
    assert "From the local cache" in err

    # Human mode with --format json does not print "Use --flat" note
    with pytest.raises(SystemExit) as exc:
        cli.main(["--human", "channels", "-s", "VUT FIT", "--format", "json"])
    captured = capsys.readouterr()
    assert exc.value.code == 0
    assert json.loads(captured.out) == data
    assert "Use --flat" not in captured.err
    assert "Use --flat" not in captured.out


def test_status_format_json(capsys, monkeypatch):
    TokenStore.default().save("tok")

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.removeprefix("/api/v9") == "/users/@me":
            return httpx.Response(200, json={"id": "42", "username": "alice", "global_name": "Alice"})
        return httpx.Response(404)

    transport = httpx.MockTransport(handler)
    monkeypatch.setattr(cli, "DiscordAPI", lambda token, **kw: DiscordAPI(token, transport=transport))

    code, out, _ = run(capsys, "status", "--format", "json")
    assert code == 0
    data = json.loads(out)
    assert data["logged_in"] == "yes"
    assert data["user"] == "Alice (@alice)"
    assert data["user_id"] == "42"
    assert isinstance(data["data_dir"], str)
    assert isinstance(data["token_storage"], str)


def test_config_list_format_json(capsys):
    code, out, _ = run(capsys, "config", "list", "--format", "json")
    assert code == 0
    data = json.loads(out)
    assert isinstance(data, dict)
    assert "delay" in data and "default-server" in data
    assert data["delay"] == 1.0


def test_invalid_format_fails_with_code_8(capsys):
    for cmd in (["servers"], ["channels", "-s", FIT], ["config", "list"]):
        code, _, err = run(capsys, *cmd, "--format", "xml")
        assert code == 8
        assert 'Unknown format "xml".' in err
        assert "Use one of: text, json." in err

    # Status validates --format even before checking login
    TokenStore.default().delete()
    code, _, err = run(capsys, "status", "--format", "xml")
    assert code == 8
    assert 'Unknown format "xml".' in err
    assert "Use one of: text, json." in err


from discoop.directory import Directory  # noqa: E402
from discoop.models import ForumTag, channel_from_api  # noqa: E402

FORUM_PAYLOAD = {
    "id": "204",
    "type": 15,
    "name": "help-center",
    "position": 2,
    "last_message_id": "1566814241946738698",  # in a forum: the newest post
    "available_tags": [
        {"id": "11", "name": "Exam", "moderated": False, "emoji_id": None, "emoji_name": None},
        {"id": "12", "name": "Project", "moderated": True},
        {"name": "no id, dropped"},
        "junk",
    ],
}


def test_channel_from_api_reads_the_last_message_and_forum_tags():
    channel = channel_from_api(FORUM_PAYLOAD, FIT)
    assert channel.last_message_id == "1566814241946738698"
    assert channel.available_tags == (ForumTag("11", "Exam"), ForumTag("12", "Project"))
    assert channel.tag_names(["12", "11", "77"]) == ("Project", "Exam")


def test_channel_from_api_without_the_new_fields():
    channel = channel_from_api({"id": "200", "type": 0, "name": "x"}, FIT)
    assert channel == Channel("200", FIT, "x", 0)
    assert (channel.last_message_id, channel.available_tags) == (None, ())
    empty = channel_from_api({"id": "200", "type": 0, "last_message_id": None, "available_tags": None}, FIT)
    assert (empty.last_message_id, empty.available_tags) == (None, ())
    assert channel_from_api({"id": "200", "type": 15, "last_message_id": 123}, FIT).last_message_id == "123"


def test_directory_keeps_the_new_channel_fields_through_the_cache():
    payload = [{"id": "100", "type": 4, "name": "general"}, FORUM_PAYLOAD, {"id": "200", "type": 0, "name": "x"}]
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        return httpx.Response(200, json=payload)

    server = Server(FIT, "VUT FIT")
    expected = Channel(
        "204",
        FIT,
        "help-center",
        15,
        position=2,
        last_message_id="1566814241946738698",
        available_tags=(ForumTag("11", "Exam"), ForumTag("12", "Project")),
    )
    for _ in range(2):  # the second Directory is a new run that reads the cache
        with Cache.default() as cache:
            directory = Directory(cache, lambda: DiscordAPI("tok", transport=httpx.MockTransport(handler)))
            channels = {c.id: c for c in directory.channels(server)}
            assert channels["204"] == expected
            assert channels["200"].last_message_id is None
        assert len(calls) == 1
