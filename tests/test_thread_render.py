"""Threads (forum posts, threads of text channels) in the text, Markdown and JSON renderings.

Everything is hand-built; nothing is fetched. The files of the export are tested in test_export_threads.py.
"""

import json
from dataclasses import replace
from datetime import timedelta

import pytest

from discoop.models import Attachment, Channel, ChannelMessages, Message, StartedThread, Thread
from discoop.render import jsonout, text
from export_helpers import AUTHOR, FORUM, GENERAL, QUERY, SERVER, Lab
from fake_messages import CET, NOW

HEADER = "range: 2026-11-02 12:00 .. 2026-11-03 12:00 (UTC+01:00)"


def msg(channel_id: str, number: int, line: str, **fields) -> Message:
    return Message(f"{channel_id}{number:03d}", 0, NOW - timedelta(minutes=30 - number), None, AUTHOR, line, **fields)


def nested(
    parent: Channel, thread_id: str, name: str, lines: tuple[str, ...] = ("reply",), **fields
) -> ChannelMessages:
    """A thread with the given message texts and Thread metadata (`known=False` in `fields`: none)."""
    known = fields.pop("known", True)
    truncated = fields.pop("truncated", False)
    info = Thread(
        thread_id,
        parent.id,
        name,
        11,
        created=NOW - timedelta(hours=3),
        last_activity=NOW - timedelta(hours=1),
        **fields,
    )
    messages = tuple(msg(thread_id, n, line) for n, line in enumerate(lines))
    where = info.as_channel(parent.server_id)
    return ChannelMessages(SERVER, where, messages, truncated, thread=info if known else None)


def channel(*lines: str, threads: tuple[ChannelMessages, ...] = (), parent: Channel = GENERAL) -> ChannelMessages:
    messages = tuple(msg(parent.id, n, line) for n, line in enumerate(lines))
    return ChannelMessages(SERVER, parent, messages, threads=threads)


@pytest.fixture
def lab():
    return Lab()


# --- text ------------------------------------------------------------------------------------------


def test_a_channel_without_threads_renders_as_it_always_did():
    result = channel("hello", "second\nline")
    assert text.plain([result], QUERY, CET) == (
        "=== VUT FIT / #2bit-general ===\n"
        f"{HEADER} | messages: 2 | files: 0\n"
        "\n"
        "[2026-11-03 11:30] Student A (@student_a)\n"
        "hello\n"
        "[2026-11-03 11:31] Student A (@student_a)\n"
        "second\n"
        "line"
    )
    assert text.plain([channel()], QUERY, CET).endswith("(no messages)")
    assert "thread" not in text.markdown([result], QUERY, CET)


def test_plain_text_with_one_thread():
    started = StartedThread("7001", "Project 1", 2)
    first = replace(msg("200", 0, "who has project?"), thread=started)
    thread = nested(GENERAL, "7001", "Project 1", ("me", "me too"), archived=True)
    result = replace(channel(threads=(thread,)), messages=(first,))
    assert text.plain([result], QUERY, CET) == (
        "=== VUT FIT / #2bit-general ===\n"
        f"{HEADER} | messages: 1 | threads: 1 (2 messages) | files: 0\n"
        "\n"
        "[2026-11-03 11:30] Student A (@student_a)\n"
        "who has project?\n"
        '  [thread] "Project 1" 2 messages\n'
        "\n"
        '--- thread "Project 1" ---\n'
        "created: 2026-11-03 09:00 | last activity: 2026-11-03 11:00 | messages: 2 | files: 0 | archived: yes\n"
        "\n"
        "[2026-11-03 11:30] Student A (@student_a)\n"
        "me\n"
        "[2026-11-03 11:31] Student A (@student_a)\n"
        "me too"
    )


def test_several_threads_keep_their_order_and_show_what_is_known(lab):
    results = lab.threaded_results()
    out = text.plain(results, QUERY, CET)
    headings = [line for line in out.split("\n") if line.startswith(("=== ", "--- thread"))]
    assert headings == [
        "=== VUT FIT / #2bit-general ===",
        '--- thread "notes" ---',
        '--- thread "chart" ---',
        "=== VUT FIT / #2bit-forum ===",
        '--- thread "How to do the project?" ---',
        '--- thread "Deadline" ---',
        "=== VUT FIT / #2bit-terminy ===",
    ]
    assert f"{HEADER} | messages: 2 | threads: 2 (5 messages) | files: 5" in out
    info = [line for line in out.split("\n") if line.startswith("created: ")]
    assert info == [
        "created: 2026-11-03 09:00 | last activity: 2026-11-03 11:00 | messages: 3 | files: 1",
        "created: 2026-11-03 09:00 | last activity: 2026-11-03 11:00 | messages: 2 | files: 2 | archived: yes",
        # tag names come from the forum; the tag 999 is not listed there any more and is dropped
        "created: 2026-11-03 09:00 | last activity: 2026-11-03 11:00 | messages: 2 | files: 1 | tags: Solved",
        "created: 2026-11-03 09:00 | last activity: 2026-11-03 11:00 | messages: 2 | files: 0 | tags: Question"
        " | locked: yes",
    ]
    assert "threads:" not in out.split("=== VUT FIT / #2bit-terminy ===")[1]  # a channel without threads has no count
    assert out.count("\n\n--- thread") == 4 and "\n\n\n" not in out  # one blank line before each section, never two


def test_a_forum_without_messages_of_its_own_has_only_its_threads(lab):
    forum = lab.threaded_results()[1]
    lines = text.plain([forum], QUERY, CET).split("\n")
    assert lines[:4] == [
        "=== VUT FIT / #2bit-forum ===",
        f"{HEADER} | messages: 0 | threads: 2 (4 messages) | files: 1",
        "",
        '--- thread "How to do the project?" ---',
    ]
    assert "(no messages)" not in lines
    # nothing at all in it: that is still what it says
    assert text.plain([ChannelMessages(SERVER, FORUM, ())], QUERY, CET).endswith("(no messages)")


def test_a_thread_without_messages_or_metadata_and_a_truncated_one():
    quiet = nested(GENERAL, "7001", "quiet", (), known=False)
    cut = nested(GENERAL, "7002", "cut", ("x",), truncated=True, locked=True)
    result = channel("hi", threads=(quiet, cut))
    out = text.plain([result], QUERY, CET)
    assert '--- thread "quiet" ---\nmessages: 0 | files: 0\n\n(no messages)\n\n--- thread "cut" ---\n' in out
    assert "locked: yes | truncated: yes (--max-messages 5000)" in out
    assert out.count("truncated") == 1  # the channel itself was not cut short


def test_markdown_has_a_second_level_heading_and_relative_links(lab):
    url = "https://cdn.discordapp.com/x"
    file = Attachment("800000000000000011", "chart.png", "image/png", 10, url, "files/g/a.png")
    thread = nested(GENERAL, "7001", "notes")
    thread = replace(thread, messages=(replace(thread.messages[0], attachments=(file,)),))
    out = text.markdown([channel("hi", threads=(thread,))], QUERY, CET, link_prefix="../")
    assert '\n\n## thread "notes"\ncreated: ' in out
    assert "- [file] ![chart.png](../files/g/a.png) 10B" in out
    assert out.index("# VUT FIT") < out.index("## thread") and "--- thread" not in out


def test_styled_output_has_the_thread_sections(lab):
    rendered = text.styled(lab.threaded_results(), QUERY, CET).plain
    assert '--- thread "Deadline" ---' in rendered and "threads: 2 (5 messages)" in rendered


def test_threads_of_several_channels_are_separated_by_one_blank_line(lab):
    out = text.markdown(lab.threaded_results(), QUERY, CET).split("\n")
    at = out.index("# VUT FIT / #2bit-forum")
    assert out[at - 1] == "" and out[at - 2] != ""


# --- JSON ------------------------------------------------------------------------------------------


def test_jsonl_is_flat_with_the_parent_channel_and_the_thread(lab):
    results = lab.threaded_results()
    rows = [json.loads(line) for line in jsonout.lines(results, CET)]
    assert [row["id"] for row in rows] == [
        "200000", "200900", "7001000", "7001001", "7001900", "7002000", "7002900",  # the channel, then its threads
        "8001000", "8001900", "8002000", "8002001",  # a forum has only threads
        "202000", "202900",
    ]  # fmt: skip
    own, in_thread = rows[0], rows[2]
    assert own["thread"] is None and own["channel"] == {"id": "200", "name": "2bit-general"}
    assert in_thread["channel"] == {"id": "200", "name": "2bit-general"}  # the parent, not the thread
    assert in_thread["thread"] == {"id": "7001", "name": "notes", "parent_id": "200", "tags": []}
    assert rows[7]["thread"] == {"id": "8001", "name": "How to do the project?", "parent_id": "210", "tags": ["Solved"]}
    assert rows[9]["thread"]["tags"] == ["Question"]  # the unknown tag is dropped here as well
    assert rows[9]["channel"]["id"] == "210" and rows[11]["thread"] is None
    assert all(set(row) == set(rows[0]) for row in rows)  # the same keys everywhere
    assert not any("threads" in row for row in rows)  # no nesting


def test_a_message_that_started_a_thread_is_not_in_a_thread():
    started = replace(msg("200", 0, "q"), thread=StartedThread("7001", "Project 1", 2))
    result = replace(channel(threads=(nested(GENERAL, "7001", "Project 1"),)), messages=(started,))
    first, second = (json.loads(line) for line in jsonout.lines([result], CET))
    assert first["has_thread"] is True and first["thread"] is None
    assert second["has_thread"] is False and second["thread"]["id"] == "7001"


def test_a_thread_without_metadata_has_no_tags():
    row = json.loads(jsonout.lines([channel(threads=(nested(GENERAL, "7001", "t", known=False),))], CET)[0])
    assert row["thread"] == {"id": "7001", "name": "t", "parent_id": "200", "tags": []}


def test_the_json_document_and_its_summaries(lab):
    results = lab.threaded_results()
    document = jsonout.document(results, QUERY, CET)
    assert [m["id"] for m in document["messages"]] == [json.loads(line)["id"] for line in jsonout.lines(results, CET)]
    channels = document["channels"]
    counts = [(c["channel"]["id"], c["messages"], c.get("threads"), c.get("thread_messages")) for c in channels]
    assert counts == [
        ("200", 2, 2, 5),
        ("210", 0, 2, 4),
        ("202", 2, None, None),
    ]
    assert [c["files"] for c in channels] == [5, 1, 1]  # the files of the threads are in
    assert list(channels[0]) == ["server", "channel", "messages", "threads", "thread_messages", "files", "truncated"]
    assert list(channels[2]) == ["server", "channel", "messages", "files", "truncated"]  # as before threads existed
    assert document["truncated"] is False


def test_a_truncated_thread_makes_its_channel_and_the_document_truncated():
    result = channel("a", threads=(nested(GENERAL, "7001", "cut", truncated=True),))
    assert result.truncated is False and result.any_truncated is True
    document = jsonout.document([result], QUERY, CET)
    assert document["truncated"] is True and document["channels"][0]["truncated"] is True
    assert jsonout.header([channel("a")], QUERY, CET)["truncated"] is False


# --- the model -------------------------------------------------------------------------------------


def test_counts_of_a_channel_include_its_threads(lab):
    general, forum, terminy = lab.threaded_results()
    assert (len(general.messages), general.thread_message_count) == (2, 5)
    assert (general.total_messages, general.file_count) == (7, 5)
    assert (forum.total_messages, forum.file_count, forum.any_truncated) == (4, 1, False)
    assert general.parts() == (general, *general.threads) and terminy.parts() == (terminy,)
    assert terminy.total_messages == 2 and terminy.thread_message_count == 0
    assert general.threads[0].threads == () and general.threads[0].thread is not None
