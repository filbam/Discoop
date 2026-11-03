import json
from collections import Counter
from datetime import UTC, datetime, timedelta, timezone

import httpx
import pytest

from discoop import cli
from discoop.api import DiscordAPI
from discoop.cache import Cache
from discoop.models import Channel, ChannelMessages, Server
from discoop.normalize import Normalizer, known_users
from discoop.render import Query, jsonout, text
from discoop.snowflake import Window
from discoop.tokenstore import TokenStore
from fake_messages import BOT, NOW, USER_A, USER_B, FakeChannel, message, series

CET = timezone(timedelta(hours=1))
FIT = "461541385204400138"
GUILDS = [{"id": FIT, "name": "VUT FIT", "approximate_member_count": 5000}]
CHANNELS = [
    {"id": "100", "type": 4, "name": "general", "position": 1},
    {"id": "200", "type": 0, "name": "2bit-general", "parent_id": "100", "position": 0},
    {"id": "202", "type": 0, "name": "2bit-terminy", "parent_id": "100", "position": 1},
    {"id": "203", "type": 0, "name": "general", "parent_id": "100", "position": 2},
    {"id": "204", "type": 15, "name": "help-center", "position": 3},
    {"id": "205", "type": 5, "name": "2bit-info", "parent_id": "100", "position": 4},
]
DEADLINE = 1794005940  # 2026-11-06 23:59 in UTC+01:00
FILE_URL = "https://cdn.discordapp.com/attachments/200/800000000000000001/zadanie.pdf?ex=1&is=2&hm=3&"


def at(hour: int, minute: int = 0) -> datetime:
    """A time on 2026-11-03, given in UTC+01:00."""
    return datetime(2026, 11, 3, hour, minute, tzinfo=CET).astimezone(UTC)


def conversation() -> list[dict]:
    question = message(at(9, 15), "Kedy je deadline na <#202>? <@&777>")
    answer = message(
        at(10),
        f"<@{USER_A['id']}> do piatku <t:{DEADLINE}:F>, zadanie je v prílohe <:peepolove:827833315666558996>",
        author=USER_B,
        type=19,
        mentions=[USER_A],
        edited_timestamp=at(10, 5).isoformat(),
        message_reference={"type": 0, "channel_id": "200", "message_id": question["id"], "guild_id": FIT},
        referenced_message=question,
        attachments=[
            {"id": "800000000000000001", "filename": "zadanie.pdf", "size": 421888, "url": FILE_URL,
             "content_type": "application/pdf"}
        ],
        reactions=[
            {"emoji": {"id": None, "name": "✅"}, "count": 3},
            {"emoji": {"id": "827833315666558996", "name": "peepolove"}, "count": 1},
        ],
    )
    announcement = message(
        at(11, 30),
        "",
        author=BOT,
        pinned=True,
        flags=32,
        embeds=[
            {"type": "rich", "title": "Nový termín", "description": "Projekt 1",
             "fields": [{"name": "Odovzdanie", "value": f"<t:{DEADLINE}>"}]}
        ],
    )
    announcement["thread"] = {"id": announcement["id"], "type": 11, "name": "Projekt 1 – otázky", "message_count": 14}
    orphan_reply = message(
        at(11, 40),
        "súhlasím",
        author=USER_B,
        type=19,
        message_reference={"type": 0, "channel_id": "200", "message_id": "1"},
    )
    link = message(
        at(11, 50),
        "https://www.fit.vut.cz/study/",
        embeds=[{"type": "link", "url": "https://www.fit.vut.cz/study/", "title": "Studium"}],
    )
    joined = message(at(11, 55), "", author=USER_B, type=7)
    return [question, answer, announcement, orphan_reply, link, joined]


EXPECTED_TEXT = f"""\
=== VUT FIT / #2bit-general ===
range: 2026-11-02 12:00 .. 2026-11-03 12:00 (UTC+01:00) | messages: 5 | files: 1

[2026-11-03 09:15] Student A (@student_a)
Kedy je deadline na #2bit-terminy? @role:777
[2026-11-03 10:00] @student_b (edited) reply-to Student A: "Kedy je deadline na #2bit-terminy? @role:777"
@Student A do piatku 2026-11-06 23:59, zadanie je v prílohe :peepolove:
  [file] zadanie.pdf 412KB {FILE_URL}
  [reactions] ✅3 :peepolove:1
[2026-11-03 11:30] @fit_bot [bot] (pinned)
  [embed] "Nový termín"
    Projekt 1
    Odovzdanie: 2026-11-06 23:59
  [thread] "Projekt 1 – otázky" 14 messages
[2026-11-03 11:40] @student_b reply-to (message not available)
súhlasím
[2026-11-03 11:50] Student A (@student_a)
https://www.fit.vut.cz/study/
  [link] "Studium"
"""


@pytest.fixture
def discord(monkeypatch):
    """Logged in; a fake Discord with one server, its channels and their messages."""
    TokenStore.default().save("tok")
    monkeypatch.setattr(cli, "utc_now", lambda: NOW)
    monkeypatch.setattr(cli, "LOCAL_ZONE", CET)
    fake = FakeDiscord()
    transport = httpx.MockTransport(fake.handle)
    monkeypatch.setattr(cli, "DiscordAPI", lambda token, **kw: DiscordAPI(token, transport=transport))
    return fake


ERROR_CODES = {401: 0, 403: 50001, 404: 10003}  # Missing Access, Unknown Channel


class FakeDiscord:
    def __init__(self) -> None:
        self.calls: Counter = Counter()
        self.channels = {"200": FakeChannel(conversation())} | {c: FakeChannel([]) for c in ("202", "203", "205")}
        self.status: dict[str, int | tuple[int, int]] = {}  # channel ID -> forced status (and JSON error code)

    def handle(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path.removeprefix("/api/v9")
        self.calls[path] += 1
        if path == "/users/@me/guilds":
            return httpx.Response(200, json=GUILDS)
        if path == f"/guilds/{FIT}/channels":
            return httpx.Response(200, json=CHANNELS)
        parts = path.strip("/").split("/")
        if parts[0] == "channels":
            channel_id = parts[1]
            if channel_id in self.status:
                forced = self.status[channel_id]
                status, code = forced if isinstance(forced, tuple) else (forced, ERROR_CODES[forced])
                return httpx.Response(status, json={"message": "error", "code": code})
            if len(parts) == 2:
                known = next((c for c in CHANNELS if c["id"] == channel_id), None)
                if known:
                    return httpx.Response(200, json={**known, "guild_id": FIT})
                return httpx.Response(404, json={"message": "Unknown Channel", "code": 10003})
            if parts[2] == "messages" and channel_id in self.channels:
                return self.channels[channel_id].respond(request)
        return httpx.Response(404, json={"message": "Unknown Channel", "code": 10003})


def run(capsys, *args):
    with pytest.raises(SystemExit) as e:
        cli.main(["--agent", *args])
    captured = capsys.readouterr()
    return e.value.code, captured.out, captured.err


# --- text format -----------------------------------------------------------------------------------


def test_agent_text(capsys, discord):
    code, out, err = run(capsys, "messages", "-s", "VUT FIT", "-c", "2bit-general")
    assert code == 0
    assert out == EXPECTED_TEXT
    assert err == ""


def test_human_text_has_the_same_content(capsys, discord):
    with pytest.raises(SystemExit) as e:
        cli.main(["--human", "messages", "-s", "VUT FIT", "-c", "2bit-general"])
    captured = capsys.readouterr()
    assert e.value.code == 0
    # Same lines as the agent text, plus blank lines between messages; no wrapping inside URLs.
    assert [line for line in captured.out.splitlines() if line] == [line for line in EXPECTED_TEXT.splitlines() if line]
    assert "\n\n[2026-11-03 10:00]" in captured.out
    assert "last 24 hours" in captured.err


def test_system_messages_on_request(capsys, discord):
    _, out, _ = run(capsys, "messages", "-s", FIT, "-c", "200", "--include-system")
    assert "[2026-11-03 11:55] @student_b (system message, type 7)" in out
    assert "messages: 6" in out


def test_blank_lines_around_texts_are_trimmed(capsys, discord):
    """Regression: a text ending with blank lines gave two blank lines between messages in human mode."""
    embed = {"type": "rich", "description": "Popis\n", "fields": [{"name": "Pole", "value": "hodnota\n"}]}
    discord.channels["200"] = FakeChannel([
        message(at(10), "\n \nPrvý riadok\n\nDruhý riadok\n\n"),
        message(at(10, 1), " \n ", author=USER_B, attachments=[{"id": "1", "filename": "a.png", "size": 10, "url": "u"}]),
        message(at(10, 2), "Windows\r\nriadky\r\n"),
        message(at(10, 3), "", author=BOT, embeds=[embed]),
    ])
    _, out, _ = run(capsys, "messages", "-s", FIT, "-c", "200")
    assert out.splitlines()[3:] == [
        "[2026-11-03 10:00] Student A (@student_a)", "Prvý riadok", "", "Druhý riadok",
        "[2026-11-03 10:01] @student_b", "  [file] a.png 10B u",
        "[2026-11-03 10:02] Student A (@student_a)", "Windows", "riadky",
        "[2026-11-03 10:03] @fit_bot [bot]", "  [embed]", "    Popis", "    Pole: hodnota",
    ]
    assert all(line == line.rstrip() for line in out.splitlines())  # also no "  [embed] " with a trailing space
    with pytest.raises(SystemExit):
        cli.main(["--human", "messages", "-s", FIT, "-c", "200"])
    human = capsys.readouterr().out
    assert "\n\n\n" not in human
    assert "\nDruhý riadok\n\n[2026-11-03 10:01] @student_b\n" in human  # one blank line between messages
    _, out, _ = run(capsys, "messages", "-s", FIT, "-c", "200", "--format", "json")
    assert [m["text"] for m in json.loads(out)["messages"]] == [
        "Prvý riadok\n\nDruhý riadok", "", "Windows\nriadky", ""
    ]


def test_empty_channel(capsys, discord):
    code, out, _ = run(capsys, "messages", "-s", FIT, "-c", "2bit-info")
    assert code == 0
    assert out.splitlines()[-1] == "(no messages)"
    assert "messages: 0 | files: 0" in out


# --- json format -----------------------------------------------------------------------------------


def test_json(capsys, discord):
    code, out, _ = run(capsys, "messages", "-s", FIT, "-c", "2bit-general", "--format", "json")
    assert code == 0
    assert out.count("\n") == 1  # compact in agent mode
    data = json.loads(out)
    assert data["from"] == "2026-11-02T12:00:00+01:00"
    assert data["to"] == "2026-11-03T12:00:00+01:00"
    assert data["last"] is None and data["truncated"] is False
    assert data["channels"] == [
        {
            "server": {"id": FIT, "name": "VUT FIT"},
            "channel": {"id": "200", "name": "2bit-general"},
            "messages": 5,
            "files": 1,
            "truncated": False,
        }
    ]
    first, answer, announcement, orphan, _ = data["messages"]
    assert set(answer) == {
        "id", "type", "server", "channel", "thread", "time", "edited", "author", "text", "reply_to",
        "attachments", "links", "reactions", "stickers", "pinned", "forwarded", "has_thread",
    }
    assert answer["time"] == "2026-11-03T10:00:00+01:00"
    assert answer["edited"] == "2026-11-03T10:05:00+01:00"
    assert answer["author"] == {"id": USER_B["id"], "name": "student_b", "username": "student_b", "bot": False}
    assert answer["text"].startswith("@Student A do piatku 2026-11-06 23:59")
    assert answer["reply_to"] == {
        "id": first["id"], "author": "Student A", "text": "Kedy je deadline na #2bit-terminy? @role:777"
    }
    assert answer["attachments"] == [
        {"id": "800000000000000001", "filename": "zadanie.pdf", "type": "application/pdf", "size": 421888,
         "url": FILE_URL}
    ]
    assert answer["reactions"] == [{"emoji": "✅", "count": 3, "super": 0}, {"emoji": ":peepolove:", "count": 1, "super": 0}]
    assert announcement["has_thread"] is True and announcement["pinned"] is True
    assert announcement["links"][0]["description"] == "Projekt 1\nOdovzdanie: 2026-11-06 23:59"
    assert orphan["reply_to"] == {"id": "1", "author": None, "text": None}
    # Unlike `text`, JSON keeps the URL of an embed that the message text already has.
    assert data["messages"][-1]["links"] == [
        {"kind": "link", "url": "https://www.fit.vut.cz/study/", "title": "Studium", "description": None}
    ]


def test_human_json_is_valid_and_indented(capsys, discord):
    with pytest.raises(SystemExit):
        cli.main(["--human", "messages", "-s", FIT, "-c", "200", "--format", "JSON"])
    out = capsys.readouterr().out
    assert json.loads(out)["channels"][0]["messages"] == 5
    assert '\n  "channels"' in out


# --- time window and limits ------------------------------------------------------------------------


def test_window_and_last(capsys, discord):
    discord.channels["200"] = FakeChannel(series(250, newest=NOW - timedelta(minutes=5), step=timedelta(minutes=10)))
    _, out, _ = run(capsys, "messages", "-s", FIT, "-c", "200", "--from", "2h")
    assert "messages: 12 |" in out
    _, out, _ = run(capsys, "messages", "-s", FIT, "-c", "200", "--last", "3")
    lines = out.splitlines()
    assert lines[1].startswith("range: all .. 2026-11-03 12:00 (UTC+01:00) | last: 3 | messages: 3")
    assert lines[3:] == ["[2026-11-03 11:35] Student A (@student_a)", "message 2",
                         "[2026-11-03 11:45] Student A (@student_a)", "message 1",
                         "[2026-11-03 11:55] Student A (@student_a)", "message 0"]
    _, out, _ = run(capsys, "messages", "-s", FIT, "-c", "200", "--from", "2026-11-03T11:00", "--to", "2026-11-03T11:40")
    assert "range: 2026-11-03 11:00 .. 2026-11-03 11:40 (UTC+01:00) | messages: 4 |" in out


def test_max_messages_truncates_with_a_warning(capsys, discord):
    discord.channels["200"] = FakeChannel(series(250, newest=NOW - timedelta(minutes=5), step=timedelta(minutes=10)))
    code, out, err = run(capsys, "messages", "-s", FIT, "-c", "200", "--from", "all", "--max-messages", "120")
    assert code == 0
    assert "messages: 120 | files: 0 | truncated: yes (--max-messages 120)" in out
    assert err.startswith("WARNING: Stopped at --max-messages 120 in #2bit-general (200) in VUT FIT")
    _, out, _ = run(capsys, "messages", "-s", FIT, "-c", "200", "--last", "10", "--format", "json")
    assert json.loads(out)["truncated"] is False  # --last is what was asked for, not a truncation


def test_verbose_progress_notes(capsys, discord):
    discord.channels["200"] = FakeChannel(series(250, newest=NOW - timedelta(minutes=5), step=timedelta(minutes=10)))
    _, _, err = run(capsys, "-v", "messages", "-s", FIT, "-c", "200", "--from", "all")
    assert err.splitlines() == [
        "Fetching #2bit-general (200) in VUT FIT",
        "Fetching #2bit-general (200) in VUT FIT: 100 messages, back to 2026-11-02 19:25",
        "Fetching #2bit-general (200) in VUT FIT: 200 messages, back to 2026-11-02 02:45",
    ]


# --- choosing channels -----------------------------------------------------------------------------


def test_channel_id_without_server_from_the_cache(capsys, discord):
    run(capsys, "channels", "-s", FIT)  # fills the cache
    code, out, _ = run(capsys, "messages", "-c", "200")
    assert code == 0 and out.startswith("=== VUT FIT / #2bit-general ===")
    assert discord.calls["/channels/200"] == 0


def test_channel_id_without_server_asks_discord(capsys, discord):
    code, out, _ = run(capsys, "messages", "-c", "200")
    assert code == 0 and out.startswith("=== VUT FIT / #2bit-general ===")
    assert discord.calls["/channels/200"] == 1
    with Cache.default() as cache:
        assert cache.channel("202").name == "2bit-terminy"  # the server's channels were cached on the way


def test_default_server_and_names(capsys, discord):
    code, _, err = run(capsys, "messages", "-c", "2bit-general")
    assert code == 8 and "default-server" in err
    run(capsys, "config", "set", "default-server", FIT)
    code, out, _ = run(capsys, "messages", "-c", "2BIT-General")
    assert code == 0 and "#2bit-general" in out
    code, out, _ = run(capsys, "messages", "-c", "general")  # the text channel, not the category
    assert code == 0 and out.startswith("=== VUT FIT / #general ===")


def test_pattern_and_repeated_channels(capsys, discord):
    _, out, _ = run(capsys, "messages", "-s", FIT, "-c", "2bit-*", "-c", "200")
    headers = [line for line in out.splitlines() if line.startswith("===")]
    assert headers == ["=== VUT FIT / #2bit-general ===", "=== VUT FIT / #2bit-terminy ===", "=== VUT FIT / #2bit-info ==="]


def test_pattern_with_only_forums(capsys, discord):
    code, _, err = run(capsys, "messages", "-s", FIT, "-c", "help-*")
    assert code == 4 and "#help-center" in err


@pytest.mark.parametrize(
    ("args", "code", "text"),
    [
        (["-c", "help-center"], 8, "is a forum channel"),
        (["-c", "100"], 8, "is a category"),
        (["-c", "nope"], 4, 'No channel matches "nope"'),
        (["-c", "999"], 4, 'No channel matches "999"'),
    ],
)
def test_bad_channels(capsys, discord, args, code, text):
    exit_code, out, err = run(capsys, "messages", "-s", FIT, *args)
    assert (exit_code, out) == (code, "")
    assert text in err


# --- errors ----------------------------------------------------------------------------------------


@pytest.mark.parametrize(("status", "code", "name"), [(403, 5, "NO_ACCESS"), (404, 4, "NOT_FOUND"), (401, 2, "AUTH_REQUIRED")])
def test_api_errors(capsys, discord, status, code, name):
    discord.status["200"] = status
    exit_code, out, err = run(capsys, "messages", "-s", FIT, "-c", "200")
    assert (exit_code, out) == (code, "")
    assert err.startswith(f"ERROR {name}")


def test_blocked_403_is_not_missing_access_and_is_not_skipped(capsys, discord):
    discord.status["202"] = (403, 10008)  # anti-abuse block
    code, out, err = run(capsys, "messages", "-s", FIT, "-c", "200", "-c", "202")
    assert (code, out) == (1, "")
    assert err.startswith("ERROR ERROR: Discord refused to read #2bit-terminy (202) in VUT FIT (403, code 10008)")
    assert "not a missing permission" in err


def test_empty_history_note(capsys, discord):
    _, _, err = run(capsys, "messages", "-s", FIT, "-c", "2bit-info", "--from", "all")
    assert err == ""  # agents see notes only with --verbose
    _, _, err = run(capsys, "-v", "messages", "-s", FIT, "-c", "2bit-info", "--from", "all")
    assert "Discord returned no messages for #2bit-info (205) in VUT FIT before 2026-11-03 12:00." in err
    assert "Read Message History" in err
    _, _, err = run(capsys, "-v", "messages", "-s", FIT, "-c", "200", "--from", "2026-11-03T11:57")
    assert "Read Message History" not in err  # older messages exist, the window is just quiet


def test_unknown_channel_id_without_server(capsys, discord):
    code, _, err = run(capsys, "messages", "-c", "999")
    assert code == 4 and err.startswith("ERROR NOT_FOUND")
    discord.status["998"] = 403
    code, _, err = run(capsys, "messages", "-c", "998")
    assert code == 5 and err.startswith("ERROR NO_ACCESS")


def test_one_unreadable_channel_among_several_is_skipped(capsys, discord):
    discord.status["202"] = 403
    code, out, err = run(capsys, "messages", "-s", FIT, "-c", "200", "-c", "202")
    assert code == 0
    assert [line for line in out.splitlines() if line.startswith("===")] == ["=== VUT FIT / #2bit-general ==="]
    assert err.startswith("WARNING: Skipped: No access to the messages of #2bit-terminy (202) in VUT FIT.")
    discord.status["200"] = 403
    code, out, err = run(capsys, "messages", "-s", FIT, "-c", "200", "-c", "202")
    assert (code, out) == (5, "")
    assert "ERROR NO_ACCESS: None of the channels could be read." in err


@pytest.mark.parametrize(
    ("args", "text"),
    [
        (["--from", "yesterday"], 'Cannot read --from "yesterday"'),
        (["--from", "1m"], 'Unknown unit "m"'),
        (["--to", "all"], '"all" only works with --from'),
        (["--from", "2026-11-03", "--to", "2026-11-01"], "must be before --to"),
        (["--last", "0"], "--last must be at least 1"),
        (["--last", "abc"], "abc"),
        (["--max-messages", "0"], "--max-messages must be at least 1"),
        (["--format", "xml"], 'Unknown format "xml"'),
    ],
)
def test_bad_args_never_call_discord(capsys, discord, args, text):
    code, out, err = run(capsys, "messages", "-s", FIT, "-c", "200", *args)
    assert (code, out) == (8, "")
    assert err.startswith("ERROR BAD_ARGS") and text in err
    assert sum(discord.calls.values()) == 0


def test_channel_is_required(capsys, discord):
    code, _, err = run(capsys, "messages", "-s", FIT)
    assert code == 8 and "--channel" in err


def test_not_logged_in(capsys):
    code, _, err = run(capsys, "messages", "-c", "200")
    assert code == 2 and err.startswith("ERROR AUTH_REQUIRED")


# --- normalizing and rendering without the CLI -----------------------------------------------------


def test_forwarded_message_and_stickers():
    forwarded = message(
        at(10),
        "",
        message_reference={"type": 1, "channel_id": "300", "message_id": "1"},
        message_snapshots=[{"message": {"content": "Pôvodný oznam", "attachments": [], "embeds": []}}],
        sticker_items=[{"id": "1", "name": "wave", "format_type": 1}],
    )
    normalized = Normalizer({}, known_users([forwarded]), CET).message(forwarded)
    assert normalized.forwarded and normalized.text == "Pôvodný oznam" and normalized.stickers == ("wave",)
    result = ChannelMessages(Server(FIT, "VUT FIT"), Channel("200", FIT, "2bit-general", 0), (normalized,))
    rendered = text.plain([result], Query(Window(None, NOW)), CET)
    assert "[2026-11-03 10:00] Student A (@student_a) (forwarded)\nPôvodný oznam\n  [sticker] wave" in rendered
    assert jsonout.document([result], Query(Window(None, NOW)), CET)["messages"][0]["forwarded"] is True


def test_unknown_mentions_keep_their_ids():
    normalizer = Normalizer({}, {}, CET)
    assert normalizer.text("<@123> <@!124> <#125> </poll:126> <a:dance:127>") == (
        "@user:123 @user:124 #channel:125 /poll :dance:"
    )


def test_sizes_in_text():
    attachments = [
        {"id": str(i), "filename": f"f{i}", "size": size, "url": "u"} for i, size in enumerate((512, 2048, 3 * 1024**2))
    ]
    m = Normalizer({}, {}, CET).message(message(at(10), "", attachments=attachments))
    result = ChannelMessages(Server(FIT, "VUT FIT"), Channel("200", FIT, "x", 0), (m,))
    rendered = text.plain([result], Query(Window(None, NOW)), CET)
    assert "f0 512B u" in rendered and "f1 2KB u" in rendered and "f2 3.0MB u" in rendered


def test_bot_command_answers_are_not_system_messages():
    m = Normalizer({}, {}, CET).message(message(at(10), "výsledok príkazu", author=BOT, type=20))
    result = ChannelMessages(Server(FIT, "VUT FIT"), Channel("200", FIT, "x", 0), (m,))
    assert "[2026-11-03 10:00] @fit_bot [bot]\nvýsledok príkazu" in text.plain([result], Query(Window(None, NOW)), CET)


QUERY = Query(Window(None, NOW))


def normalized(*raw: dict) -> ChannelMessages:
    normalizer = Normalizer({}, known_users(raw), CET)
    return ChannelMessages(Server(FIT, "VUT FIT"), Channel("200", FIT, "x", 0), tuple(normalizer.message(m) for m in raw))


def test_embeds_do_not_repeat_urls_from_the_text():
    """Regression: a GIF posted as a bare URL showed the URL twice, in the text and as `[image]`."""
    gif = "https://cdn.discordapp.com/attachments/300/400/cat.gif?ex=1&is=2&hm=3&"
    video = "https://www.youtube.com/watch?v=abc123"
    gallery = "https://example.com/post/1"
    result = normalized(
        message(at(10), gif, embeds=[{"type": "image", "url": gif}]),
        message(at(10, 1), f"Záznam ({video}).", embeds=[{"type": "video", "url": video, "title": "Prednáška 1"}]),
        message(at(10, 2), "pozri", embeds=[{"type": "rich", "url": gallery, "title": "Post"}, {"type": "rich", "url": gallery}]),
        message(at(10, 3), "", embeds=[{"type": "gifv", "url": "https://tenor.com/view/cat-1", "title": "Cat"}]),
    )
    assert text.plain([result], QUERY, CET).splitlines()[3:] == [
        "[2026-11-03 10:00] Student A (@student_a)", gif,  # the bare GIF: no [image] line
        "[2026-11-03 10:01] Student A (@student_a)", f"Záznam ({video}).", '  [video] "Prednáška 1"',
        "[2026-11-03 10:02] Student A (@student_a)", "pozri", f'  [embed] {gallery} "Post"',  # 2nd embed: same URL
        "[2026-11-03 10:03] Student A (@student_a)", '  [gif] https://tenor.com/view/cat-1 "Cat"',  # URL not in text
    ]
    links = [m["links"] for m in jsonout.document([result], QUERY, CET)["messages"]]
    assert links[0] == [{"kind": "image", "url": gif, "title": None, "description": None}]
    assert [link["url"] for link in links[2]] == [gallery, gallery]


def test_reactions_stay_on_one_line_with_super_reactions():
    """Super reactions are a part of an emoji's count (count_details.burst), not another reaction."""
    extra = {"burst_colors": [], "me_burst": False, "burst_me": False, "me": False}
    reactions = [
        {"emoji": {"id": None, "name": "🔥"}, "count": 5, "count_details": {"burst": 2, "normal": 3}, "burst_count": 2,
         **extra},
        {"emoji": {"id": None, "name": "✅"}, "count": 1, "count_details": {"burst": 0, "normal": 1}, "burst_count": 0,
         **extra},
        {"emoji": {"id": "827833315666558996", "name": "peepolove", "animated": True}, "count": 2, "burst_count": 1},
    ]
    result = normalized(message(at(10), "super", reactions=reactions))
    lines = [line for line in text.plain([result], QUERY, CET).splitlines() if "[reactions]" in line]
    assert lines == ["  [reactions] 🔥5 (2 super) ✅1 :peepolove:2 (1 super)"]
    assert jsonout.document([result], QUERY, CET)["messages"][0]["reactions"] == [
        {"emoji": "🔥", "count": 5, "super": 2},
        {"emoji": "✅", "count": 1, "super": 0},
        {"emoji": ":peepolove:", "count": 2, "super": 1},
    ]
