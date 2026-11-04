"""Exports with threads: a channel and its threads are one unit (one folder, one channels/*.md, one manifest entry).

Discord and its CDN are fakes (tests/export_helpers.py); the threads are built by hand, nothing fetches them yet.
"""

import json
import zipfile
from dataclasses import replace
from pathlib import Path

import pytest

from discoop import export as ex
from discoop.attachments import DOWNLOADED, PRESENT, SKIPPED, FileJob, Progress, plan
from discoop.models import Attachment, Author, Channel, ChannelMessages, Message, Thread
from export_helpers import (
    GENERAL,
    NOW,
    OPTIONS,
    QUERY,
    SERVER,
    TERMINY,
    Boom,
    Lab,
    content,
    debris,
    reference,
    stream,
    tree,
)
from fake_messages import CET, FIT

SHARED = "800000000000000003"
FILE_NOTES, FILE_CSV, FILE_ZIP = "800000000000000011", "800000000000000012", "800000000000000013"


@pytest.fixture
def lab():
    return Lab()


def manifest_of(root: Path) -> dict:
    return json.loads((root / "manifest.json").read_text(encoding="utf-8"))


def zip_tree(path: Path) -> dict[str, bytes]:
    with zipfile.ZipFile(path) as archive:
        return {name: archive.read(name) for name in archive.namelist()}


def attachment(attachment_id: str, name: str = "a.bin") -> Attachment:
    return Attachment(attachment_id, name, None, 3, f"https://cdn.discordapp.com/attachments/1/{attachment_id}/{name}")


def posted(message_id: str, *attachments: Attachment) -> Message:
    return Message(message_id, 0, NOW, None, Author("1", "A", "a"), "", attachments=attachments)


# --- plan and with_paths ---------------------------------------------------------------------------


def test_plan_walks_the_threads_after_the_channel_and_saves_a_file_once():
    shared = attachment("800000000000000001", "a.pdf")
    own, only_here = attachment("800000000000000002", "b.pdf"), attachment("800000000000000004", "d.pdf")
    anonymous = attachment("", "c.pdf")
    thread_a = ChannelMessages(
        SERVER, Channel("7001", FIT, "t1", 11, parent_id="200"), (posted("7001000", shared, own, anonymous),)
    )
    thread_b = ChannelMessages(
        SERVER, Channel("7002", FIT, "t2", 11, parent_id="200"), (posted("7002000", only_here, anonymous),)
    )
    parent = ChannelMessages(
        SERVER, Channel("200", FIT, "x", 0), (posted("10", shared),), threads=(thread_a, thread_b)
    )
    other = ChannelMessages(SERVER, Channel("202", FIT, "y", 0), (posted("11", own, attachment("800000000000000005")),))

    seen: dict[str, FileJob] = {}
    jobs = plan([parent, other], {"200": "x", "202": "y"}, seen)
    assert [(j.message_id, j.channel_id, j.path) for j in jobs] == [
        ("10", "200", "files/x/800000000000000001_a.pdf"),  # the channel first
        ("7001000", "200", "files/x/800000000000000002_b.pdf"),  # a thread's file is the channel's job and folder
        ("7001000", "200", "files/x/7001000-2_c.pdf"),
        ("7002000", "200", "files/x/800000000000000004_d.pdf"),
        ("7002000", "200", "files/x/7002000-1_c.pdf"),  # no attachment ID: the key is message and position
        ("11", "202", "files/y/800000000000000005_a.bin"),  # `own` was seen in the thread already
    ]
    assert plan([parent, other], {"200": "x", "202": "y"}, seen) == []  # nothing new the second time
    assert [j.path for j in plan([parent, other], {"200": "x", "202": "y"})] == [j.path for j in jobs]
    assert "7001" not in {j.channel_id for j in jobs}  # a thread has no folder: it is not in `folders`


def test_with_paths_reaches_the_messages_of_the_threads():
    saved, lost = attachment("800000000000000001", "a.pdf"), attachment("800000000000000002", "b.pdf")
    thread = ChannelMessages(
        SERVER, Channel("7001", FIT, "t", 11, parent_id="200"), (posted("7001000", saved, lost),)
    )
    parent = ChannelMessages(SERVER, Channel("200", FIT, "x", 0), (posted("10", saved),), threads=(thread,))
    jobs = plan([parent], {"200": "x"})
    jobs[0].status, jobs[1].status = DOWNLOADED, "failed"
    (result,) = ex.with_paths([parent], jobs)
    assert result.messages[0].attachments[0].path == "files/x/800000000000000001_a.pdf"
    assert [a.path for a in result.threads[0].messages[0].attachments] == ["files/x/800000000000000001_a.pdf", None]
    assert result.threads[0].thread is None and result.threads[0].channel == thread.channel  # the rest is kept
    assert parent.threads[0].messages[0].attachments[0].path is None  # the original is untouched


# --- a folder and a zip ----------------------------------------------------------------------------


def test_a_folder_export_keeps_the_threads_with_their_channel(tmp_path, lab):
    results = lab.threaded_results()
    exported = lab.export_all(tmp_path / "fit", False, results)
    final = tree(tmp_path / "fit")

    assert exported.complete and not exported.partial and not debris(tmp_path)
    assert sorted(final) == sorted(
        [
            "manifest.json",
            "messages.md",
            "messages.jsonl",
            "channels/2bit-general.md",
            "channels/2bit-forum.md",
            "channels/2bit-terminy.md",
            "files/2bit-general/800000000000000001_zadanie.pdf",
            f"files/2bit-general/{SHARED}_graf (1).png",
            f"files/2bit-general/{FILE_NOTES}_poznamky.txt",  # a thread's files: in the folder of its channel
            f"files/2bit-general/{FILE_CSV}_vysledky.csv",
            f"files/2bit-forum/{FILE_ZIP}_priloha.zip",
            "files/2bit-terminy/800000000000000002__CON.txt",
        ]
    )  # no folder, no channels/*.md and no files of their own for the threads
    assert final[f"files/2bit-general/{FILE_NOTES}_poznamky.txt"] == content(FILE_NOTES)

    channel_md = final["channels/2bit-general.md"].decode()
    assert channel_md.startswith("# VUT FIT / #2bit-general\n")
    assert channel_md.index("## thread \"poznamky\"") < channel_md.index("## thread \"graf\"")
    assert f"(../files/2bit-general/{FILE_NOTES}_poznamky.txt) 232B" in channel_md  # `../` as for the channel's own
    assert f"(<../files/2bit-general/{SHARED}_graf (1).png>) 232B" in channel_md
    assert "https://" not in channel_md
    forum_md = final["channels/2bit-forum.md"].decode()
    assert forum_md.count("## thread") == 2 and "(no messages)" not in forum_md and "2bit-general" not in forum_md
    messages_md = final["messages.md"].decode()
    assert messages_md == (
        final["channels/2bit-general.md"].decode().replace("../files/", "files/")
        + "\n"
        + final["channels/2bit-forum.md"].decode().replace("../files/", "files/")
        + "\n"
        + final["channels/2bit-terminy.md"].decode().replace("../files/", "files/")
    )

    rows = [json.loads(line) for line in final["messages.jsonl"].decode().splitlines()]
    assert len(rows) == 13 and [r["channel"]["id"] for r in rows].count("200") == 7  # flat, under the parent
    assert rows[2]["thread"]["id"] == "7001" and rows[2]["attachments"] == []
    thread_file = next(a for r in rows for a in r["attachments"] if a["id"] == FILE_NOTES)
    assert thread_file["path"] == f"files/2bit-general/{FILE_NOTES}_poznamky.txt"

    assert exported.results[0].threads[0].messages[-1].attachments[0].path == thread_file["path"]  # the paths are set
    assert len(exported.jobs) == 6 and exported.count(DOWNLOADED) == 6


def test_the_manifest_counts_the_threads_of_a_channel(tmp_path, lab):
    exported = lab.export_all(tmp_path / "fit", False, lab.threaded_results())
    data = manifest_of(tmp_path / "fit")
    assert data == exported.manifest
    assert data["counts"] == {
        "channels": 3, "messages": 4, "threads": 4, "thread_messages": 9, "files": 6,
        "downloaded": 6, "present": 0, "failed": 0, "skipped": 0,
    }  # fmt: skip
    general, forum, terminy = data["channels"]
    assert general == {
        "server": {"id": FIT, "name": "VUT FIT"}, "channel": {"id": "200", "name": "2bit-general"},
        "messages": 2, "threads": 2, "thread_messages": 5,
        "files": 5,  # the files of the channel and of its threads, as posted (SHARED twice)
        "truncated": False, "markdown": "channels/2bit-general.md", "folder": "files/2bit-general",
    }  # fmt: skip
    assert (forum["messages"], forum["threads"], forum["thread_messages"], forum["files"]) == (0, 2, 4, 1)
    assert "threads" not in terminy and "thread_messages" not in terminy  # as before threads existed
    assert list(terminy) == ["server", "channel", "messages", "files", "truncated", "markdown", "folder"]
    # the files of a thread belong to the channel that holds it
    owner = {a["id"]: a["channel_id"] for a in data["attachments"]}
    assert owner == {
        "800000000000000001": "200", SHARED: "200", FILE_NOTES: "200", FILE_CSV: "200", FILE_ZIP: "210",
        "800000000000000002": "202",
    }
    assert [a["id"] for a in data["attachments"]][:4] == ["800000000000000001", SHARED, FILE_NOTES, FILE_CSV]
    # no names of threads in the manifest, no entries of their own
    text = json.dumps(data, ensure_ascii=False)
    assert "poznamky" not in text.replace("poznamky.txt", "") and "Ako na projekt" not in text and "Termin" not in text
    assert data["targets"] == ["200", "210", "202"] and len(data["channels"]) == 3


def test_a_channel_without_threads_keeps_the_counts_it_always_had(tmp_path, lab):
    lab.export_all(tmp_path / "fit", False, lab.results())
    data = manifest_of(tmp_path / "fit")
    assert set(data["counts"]) == {"channels", "messages", "files", "downloaded", "present", "failed", "skipped"}
    plain = {"server", "channel", "messages", "files", "truncated", "markdown", "folder"}
    assert all(set(c) == plain for c in data["channels"])


def test_a_zip_is_the_same_as_a_folder(tmp_path, lab):
    results = lab.threaded_results()
    lab.export_all(tmp_path / "folder", False, results)
    lab.export_all(tmp_path / "fit.zip", True, results)
    packed = zip_tree(tmp_path / "fit.zip")
    assert packed == tree(tmp_path / "folder")
    with zipfile.ZipFile(tmp_path / "fit.zip") as archive:
        assert archive.getinfo(f"files/2bit-general/{FILE_NOTES}_poznamky.txt").compress_type == zipfile.ZIP_STORED
        assert archive.getinfo("channels/2bit-forum.md").compress_type == zipfile.ZIP_DEFLATED


def test_a_second_export_reuses_the_files_of_the_threads(tmp_path, lab):
    results = lab.threaded_results()
    lab.export_all(tmp_path / "fit", False, results)
    requests = len(lab.cdn.requests)
    exported = lab.export_all(tmp_path / "fit", False, results)
    assert len(lab.cdn.requests) == requests  # nothing is downloaded again
    assert exported.count(PRESENT) == 6 and exported.count(DOWNLOADED) == 0
    assert manifest_of(tmp_path / "fit")["counts"]["present"] == 6
    assert tree(tmp_path / "fit")["messages.md"] == reference(results)["messages.md"]


def test_files_that_are_not_saved_show_their_url_also_in_a_thread(tmp_path, lab):
    results = lab.threaded_results()
    lab.cdn.missing.add(f"/attachments/200/{FILE_NOTES}/file.bin")
    exported = lab.export_all(tmp_path / "fit", False, results)
    assert exported.partial and exported.manifest["partial"] is True
    failed = [a for a in exported.manifest["attachments"] if a["status"] == "failed"]
    assert [(a["id"], a["channel_id"], a["path"]) for a in failed] == [(FILE_NOTES, "200", None)]
    assert failed[0]["reason"].startswith("HTTP 404")
    channel_md = (tmp_path / "fit" / "channels" / "2bit-general.md").read_text(encoding="utf-8")
    assert f"/attachments/200/{FILE_NOTES}/file.bin" in channel_md  # the CDN URL instead of a path
    assert not any(name.endswith("_poznamky.txt") for name in tree(tmp_path / "fit"))


def test_no_files_skips_those_of_the_threads_as_well(tmp_path, lab):
    exported = lab.export_all(tmp_path / "fit", False, lab.threaded_results(), options=ex.Options(files=False))
    assert exported.count(SKIPPED) == 6 and not exported.partial
    assert not (tmp_path / "fit" / "files").exists()
    assert manifest_of(tmp_path / "fit")["counts"]["skipped"] == 6


def test_a_truncated_thread_is_recorded_for_its_channel(tmp_path, lab):
    general = lab.result(GENERAL, texts=("hi",))
    result = replace(general, threads=(lab.thread(GENERAL, "7001", "long", truncated=True),))
    lab.export_all(tmp_path / "fit", False, [result])
    data = manifest_of(tmp_path / "fit")
    assert data["truncated"] is True and data["channels"][0]["truncated"] is True
    assert "truncated: yes (--max-messages 5000)" in (tmp_path / "fit" / "channels" / "2bit-general.md").read_text(
        encoding="utf-8"
    )


# --- channel by channel ----------------------------------------------------------------------------


@pytest.mark.parametrize("as_zip", [False, True], ids=["folder", "zip"])
def test_channel_by_channel_equals_a_single_pass_with_threads(tmp_path, lab, as_zip):
    results = lab.threaded_results()
    one_go = tmp_path / ("one.zip" if as_zip else "one")
    lab.export_all(one_go, as_zip, results)

    target = tmp_path / ("streamed.zip" if as_zip else "streamed")
    writer = lab.writer(target, as_zip)
    with writer:
        stream(writer, results)
        exported = writer.close(complete=True)

    streamed = zip_tree(target) if as_zip else tree(target)
    expected = reference(results)
    assert any("## thread" in raw.decode() for name, raw in expected.items() if name.endswith(".md"))
    for name, raw in expected.items():
        assert streamed[name] == raw, name  # the same bytes as one render of everything
    assert sorted(streamed) == sorted([*expected, "manifest.json"])
    assert streamed == (zip_tree(one_go) if as_zip else tree(one_go))  # also the manifest
    assert exported.complete and not exported.partial and len(exported.jobs) == 6
    assert lab.downloads[f"/attachments/200/{FILE_NOTES}/file.bin"] == 2  # once per export run
    assert not debris(tmp_path)


def test_add_channel_takes_a_channel_and_its_threads_as_one_unit(tmp_path, lab):
    general = lab.threaded_results()[0]
    writer = lab.writer(tmp_path / "fit")
    with writer:
        writer.open([GENERAL])
        jobs = writer.add_channel(general)
        assert writer.done == ["200"] and writer.pending == []  # the threads are not channels of the export
        assert sorted(job.attachment.id for job in jobs) == ["800000000000000001", SHARED, FILE_NOTES, FILE_CSV]
        assert {job.channel_id for job in jobs} == {"200"} and all(job.status == DOWNLOADED for job in jobs)
        with pytest.raises(ValueError):
            writer.add_channel(general)  # the whole unit is in already
        writer.close(complete=True)
    data = manifest_of(tmp_path / "fit")
    assert data["targets"] == ["200"] and data["counts"]["threads"] == 2


def test_the_files_of_all_threads_can_be_fetched_in_one_go(tmp_path, lab):
    results = lab.threaded_results()
    writer = lab.writer(tmp_path / "fit")
    with writer:
        writer.open([r.channel for r in results])
        writer.fetch_files(results)  # one progress bar for everything, before the channels are added
        assert lab.downloads[f"/attachments/200/{FILE_ZIP}/file.bin"] == 1
        for result in results:
            writer.add_channel(result)
        writer.close(complete=True)
    assert lab.downloads[f"/attachments/200/{FILE_ZIP}/file.bin"] == 1  # not fetched again by add_channel
    for name, raw in reference(results).items():
        assert tree(tmp_path / "fit")[name] == raw, name


# --- crash and resume ------------------------------------------------------------------------------


@pytest.mark.parametrize("as_zip", [False, True], ids=["folder", "zip"])
def test_crash_after_a_channel_with_threads_then_resume(tmp_path, lab, as_zip):
    target = tmp_path / ("fit.zip" if as_zip else "fit")
    results = lab.threaded_results()
    channels = [r.channel for r in results]
    with pytest.raises(Boom), lab.writer(target, as_zip) as writer:
        stream(writer, results, stop_after=1)

    staging = ex.staging_path(target)
    data = manifest_of(staging)
    assert (data["complete"], data["interrupted"]) == (False, True)
    (entry,) = data["channels"]
    assert (entry["channel"]["id"], entry["threads"], entry["thread_messages"], entry["files"]) == ("200", 2, 5, 5)
    assert data["counts"]["threads"] == 2 and data["counts"]["thread_messages"] == 5
    first_run = lab.downloads
    assert len(first_run) == 4  # the channel's two files and the two files of its threads
    assert not debris(staging)

    request = ex.request_fingerprint(channels, QUERY, OPTIONS, CET)
    resume = ex.find_unfinished(target, request)
    assert resume is not None
    assert dict(resume.done) == {
        "200": ex.ChannelDone(messages=2, files=5, truncated=False, threads=2, thread_messages=5)
    }

    writer = lab.writer(target, as_zip)
    with writer:
        writer.open(channels, resume)
        assert writer.done == ["200"] and writer.pending == ["210", "202"]
        for result in results:
            if result.channel.id not in resume.done:
                writer.add_channel(result)
        exported = writer.close(complete=True)

    assert all(count == 1 for count in lab.downloads.values()), lab.downloads  # no file of the first run again
    assert len(lab.downloads) == 6 and lab.downloads.keys() >= first_run.keys()
    assert exported.complete and not staging.exists() and not debris(tmp_path)
    assert [r.channel.id for r in exported.results] == ["210", "202"]  # this run's channels
    assert len(exported.jobs) == 6  # the whole export, also the thread files of the first run
    assert exported.manifest["counts"]["threads"] == 4 and exported.manifest["counts"]["thread_messages"] == 9

    final = zip_tree(target) if as_zip else tree(target)
    for name, raw in reference(results).items():
        assert final[name] == raw, name
    done = json.loads(final["manifest.json"])
    assert done["counts"] == {
        "channels": 3, "messages": 4, "threads": 4, "thread_messages": 9, "files": 6,
        "downloaded": 6, "present": 0, "failed": 0, "skipped": 0,
    }  # fmt: skip


def test_a_channel_cut_short_in_the_files_of_its_threads_is_not_finished(tmp_path, lab):
    """The unit of a crash is the channel: files of its threads that were saved do not make it a finished channel."""

    class Stop(Progress):
        def file(self, number, total, job):
            if job.attachment.id == FILE_CSV:  # the last file of the channel, in its second thread
                raise KeyboardInterrupt

    general, forum, terminy = lab.threaded_results()
    results = [terminy, general, forum]
    channels = [r.channel for r in results]
    target = tmp_path / "fit"
    with pytest.raises(KeyboardInterrupt), lab.writer(target, progress=Stop()) as writer:
        stream(writer, results)

    staging = ex.staging_path(target)
    data = manifest_of(staging)
    assert [c["channel"]["id"] for c in data["channels"]] == ["202"] and data["interrupted"] is True
    assert "threads" not in data["counts"] and (staging / "files" / "2bit-general").is_dir()  # saved, but not recorded
    assert "7001" not in (staging / "messages.jsonl").read_text(encoding="utf-8")  # no half a channel in the output
    assert "poznamky" not in (staging / "messages.md").read_text(encoding="utf-8")

    resume = ex.find_unfinished(target, ex.request_fingerprint(channels, QUERY, OPTIONS, CET))
    assert resume is not None and list(resume.done) == ["202"]
    writer = lab.writer(target)
    with writer:
        writer.open(channels, resume)
        for result in results:
            if result.channel.id not in resume.done:
                writer.add_channel(result)
        writer.close(complete=True)
    final = tree(target)
    for name, raw in reference(results).items():
        assert final[name] == raw, name
    # What the first run saved of the channel is reused from the staging folder: every file was fetched once.
    assert len(lab.downloads) == 6 and all(count == 1 for count in lab.downloads.values()), lab.downloads
    assert not debris(tmp_path) and [p.name for p in tmp_path.iterdir()] == ["fit"]


def test_the_thread_counts_survive_a_resume_that_adds_nothing(tmp_path, lab):
    """A run that died after the last channel but before publishing: the finished channels carry their thread counts."""
    target = tmp_path / "fit"
    results = [lab.threaded_results()[0], lab.result(TERMINY, texts=("x",))]
    channels = [r.channel for r in results]
    writer = lab.writer(target)
    writer.open(channels)
    for result in results:
        writer.add_channel(result)  # close() never ran
    resume = ex.find_unfinished(target, ex.request_fingerprint(channels, QUERY, OPTIONS, CET))
    assert resume is not None
    assert resume.done["200"].threads == 2 and resume.done["202"] == ex.ChannelDone(1, 0, False)
    requests = len(lab.cdn.requests)
    writer = lab.writer(target)
    with writer:
        writer.open(channels, resume)
        assert writer.pending == []
        exported = writer.close(complete=True)
    assert len(lab.cdn.requests) == requests
    assert exported.manifest["counts"]["threads"] == 2 and exported.manifest["channels"][0]["thread_messages"] == 5
    for name, raw in reference(results).items():
        assert tree(target)[name] == raw, name


def test_a_thread_typed_result_on_its_own_is_still_just_a_channel(tmp_path, lab):
    """Nothing forces a caller to nest: a thread added by itself behaves as before (see the older writer tests)."""
    info = Thread("7001", "200", "alone", 11, created=NOW, last_activity=NOW)
    solo = lab.result(info.as_channel(FIT), [("820000000000000001", "t.bin")])
    writer = lab.writer(tmp_path / "x")
    with writer:
        writer.open([GENERAL])
        writer.add_channel(lab.result(GENERAL))
        writer.add_channel(solo)
        writer.close(complete=True)
    data = manifest_of(tmp_path / "x")
    assert data["targets"] == ["200", "7001"] and "threads" not in data["counts"]
    assert (tmp_path / "x" / "channels" / "alone.md").is_file()
