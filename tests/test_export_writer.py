"""ExportWriter: channel-by-channel export, resuming, the safety of a finished export, partial results.

Discord and its CDN are fakes (tests/export_helpers.py); nothing leaves the process.
"""

import json
import os
import re
import shutil
import zipfile
from dataclasses import replace
from datetime import timedelta
from pathlib import Path

import pytest

from discoop import export as ex
from discoop.attachments import DOWNLOADED, FAILED, PRESENT, SKIPPED, FileJob, Progress
from discoop.errors import DiscoopError, ExitCode
from discoop.models import Attachment, Channel
from discoop.render import Query
from discoop.snowflake import Window
from discoop.split import split_markdown
from export_helpers import (
    CHANNELS,
    FILES,
    GENERAL,
    INFO,
    NOW,
    OPTIONS,
    QUERY,
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


@pytest.fixture
def lab():
    return Lab()


def manifest_of(root: Path) -> dict:
    return json.loads((root / "manifest.json").read_text(encoding="utf-8"))


def fingerprint(channels=CHANNELS, query=QUERY, options=OPTIONS) -> str:
    return ex.request_fingerprint(channels, query, options, CET)


# --- exit code, partial, request -------------------------------------------------------------------


def test_partial_has_its_own_exit_code():
    assert ExitCode.PARTIAL == 9 and ExitCode(9).name == "PARTIAL"
    assert len({code.value for code in ExitCode}) == len(ExitCode)


def test_is_partial():
    def job(status: str) -> FileJob:
        attachment = Attachment("1", "a.bin", None, 3, "https://cdn.discordapp.com/a")
        return FileJob(attachment, "10", "200", "files/x/1_a.bin", attachment.url, status)

    skipped = ex.SkippedChannel("202", ex.SKIP_NO_ACCESS)
    assert not ex.is_partial([], [])
    assert not ex.is_partial([], [job(DOWNLOADED), job(PRESENT)])
    assert not ex.is_partial([], [job(SKIPPED)])  # too large or --no-files: a choice, not a loss
    assert ex.is_partial([], [job(DOWNLOADED), job(FAILED)])
    assert ex.is_partial([skipped], [])
    assert ex.is_partial([ex.SkippedChannel("202", ex.SKIP_NOT_FOUND)], [job(DOWNLOADED)])


def test_skip_reason_codes():
    assert ex.skip_reason(ExitCode.NO_ACCESS) == "no_access"
    assert ex.skip_reason(ExitCode.NOT_FOUND) == "not_found"
    with pytest.raises(ValueError):
        ex.skip_reason(ExitCode.NETWORK)


def test_request_fingerprint_depends_on_the_request_only():
    base = fingerprint()
    assert base == fingerprint()
    assert fingerprint([TERMINY, GENERAL, INFO]) != base  # the order of the export
    assert fingerprint([GENERAL, TERMINY]) != base
    assert fingerprint(options=ex.Options(files=False)) != base
    assert fingerprint(options=ex.Options(max_file_size=1)) != base
    assert fingerprint(query=Query(Window(NOW - timedelta(days=2), NOW), None, 5000, False)) != base
    assert fingerprint(query=Query(QUERY.window, None, 5000, True)) != base
    assert fingerprint(query=Query(QUERY.window, 10, 5000, False)) != base
    assert fingerprint(query=Query(QUERY.window, None, 5000, False, mode="fast")) == base  # only the pace differs
    renamed = Channel("200", FIT, "other-name", 0)  # other folder names: files would land elsewhere
    assert fingerprint([renamed, TERMINY, INFO]) != base


def test_request_summary_has_no_names():
    summary = ex.request_summary(CHANNELS, QUERY, OPTIONS, CET)
    assert summary == {
        "servers": [FIT],
        "channels": ["200", "202", "203"],
        "from": "2026-11-02T12:00:00+01:00",
        "to": "2026-11-03T12:00:00+01:00",
        "last": None,
        "max_messages": 5000,
        "include_system": False,
        "files": True,
        "max_file_size": None,
        "threads": True,
        "since_last": False,
    }


# --- byte for byte ---------------------------------------------------------------------------------


@pytest.mark.parametrize("as_zip", [False, True], ids=["folder", "zip"])
def test_channel_by_channel_equals_a_single_pass(tmp_path, lab, as_zip):
    results = lab.results()
    one_go = tmp_path / ("one.zip" if as_zip else "one")
    lab.export_all(one_go, as_zip, results)

    target = tmp_path / ("streamed.zip" if as_zip else "streamed")
    writer = lab.writer(target, as_zip)
    with writer:
        stream(writer, results)
        exported = writer.close(complete=True)

    def files(path: Path) -> dict[str, bytes]:
        if not as_zip:
            return tree(path)
        with zipfile.ZipFile(path) as archive:
            return {name: archive.read(name) for name in archive.namelist()}

    streamed = files(target)
    expected = reference(results)
    for name, raw in expected.items():
        assert streamed[name] == raw, name  # the same bytes as one render of everything
    assert sorted(streamed) == sorted([*expected, "manifest.json"])
    assert streamed == files(one_go)  # also the manifest
    assert b"\r" not in streamed["messages.md"] + streamed["messages.jsonl"]
    assert exported.complete and not exported.partial and exported.path == target
    # The shared file is saved once, in the folder of the channel that had it first.
    assert sum(1 for name in streamed if name.endswith("chart (1).png")) == 1
    assert lab.downloads["/attachments/200/800000000000000003/file.bin"] == 2  # once per export run, not per channel
    if as_zip:
        with zipfile.ZipFile(target) as archive:
            assert archive.getinfo("messages.md").compress_type == zipfile.ZIP_DEFLATED
            assert archive.getinfo(next(n for n in archive.namelist() if n.startswith("files/"))).compress_type == (
                zipfile.ZIP_STORED
            )
    # Nothing but the export is left next to it.
    assert sorted(p.name for p in tmp_path.iterdir()) == sorted(["one.zip" if as_zip else "one", target.name])
    assert not debris(tmp_path)


def test_an_export_without_channels(tmp_path, lab):
    exported = lab.export_all(tmp_path / "empty", False, [])
    assert (tmp_path / "empty" / "messages.md").read_bytes() == b"\n"
    assert (tmp_path / "empty" / "messages.jsonl").read_bytes() == b""
    assert exported.complete and manifest_of(tmp_path / "empty")["counts"]["channels"] == 0


def test_folder_names_do_not_depend_on_arrival_order(tmp_path, lab):
    first, second = Channel("301", FIT, "general", 0), Channel("302", FIT, "General", 0)  # one folder on Windows
    results = [lab.result(first, [("810000000000000001", "a.bin")]), lab.result(second, [("810000000000000002", "b.bin")])]
    writer = lab.writer(tmp_path / "x")
    with writer:
        writer.open([first, second])
        writer.add_channel(results[1])  # arrives first, still gets the name it has in the order of the targets
        writer.add_channel(results[0])
        writer.close(complete=True)
    data = manifest_of(tmp_path / "x")
    folders = {item["channel"]["id"]: item["folder"] for item in data["channels"]}
    assert folders == {"301": "files/general", "302": "files/General_302"}
    assert [item["channel"]["id"] for item in data["channels"]] == ["302", "301"]  # the order of arrival


def test_a_channel_that_is_no_target_is_added_to_the_targets(tmp_path, lab):
    thread = Channel("999", FIT, "a-thread", 11, parent_id="200")
    writer = lab.writer(tmp_path / "x")
    with writer:
        writer.open([GENERAL])
        writer.add_channel(lab.result(GENERAL))
        writer.add_channel(lab.result(thread, [("820000000000000001", "t.bin")]))
        writer.close(complete=True)
    data = manifest_of(tmp_path / "x")
    assert data["targets"] == ["200", "999"] and data["request"]["channels"] == ["200"]
    assert (tmp_path / "x" / "channels" / "a-thread.md").is_file()


# --- crash and resume ------------------------------------------------------------------------------


@pytest.mark.parametrize("as_zip", [False, True], ids=["folder", "zip"])
def test_crash_in_the_second_channel_then_resume(tmp_path, lab, as_zip):
    target = tmp_path / ("fit.zip" if as_zip else "fit")
    results = lab.results()
    with pytest.raises(Boom), lab.writer(target, as_zip) as writer:
        stream(writer, results, stop_after=1)

    staging = ex.staging_path(target)
    assert staging.name == target.name + ".partial"
    assert not target.exists()  # nothing is published before the export is finished
    assert sorted(p.name for p in tmp_path.iterdir()) == [staging.name]
    data = manifest_of(staging)
    assert (data["complete"], data["interrupted"], data["partial"]) == (False, True, False)
    assert data["targets"] == ["200", "202", "203"] and [c["channel"]["id"] for c in data["channels"]] == ["200"]
    assert not debris(staging)
    first_run = lab.downloads
    assert sorted(first_run) == sorted(f"/attachments/200/{attachment_id}/file.bin" for attachment_id, _ in FILES["200"])

    request = fingerprint()
    resume = ex.find_unfinished(target, request)
    assert resume is not None and resume.created == NOW
    assert dict(resume.done) == {"200": ex.ChannelDone(messages=2, files=2, truncated=False)}
    assert resume.fingerprint == request and resume.skipped == {}

    writer = lab.writer(target, as_zip)
    with writer:
        writer.open(CHANNELS, resume)
        assert writer.done == ["200"] and writer.pending == ["202", "203"]
        for result in results:
            if result.channel.id not in resume.done:
                writer.add_channel(result)
        exported = writer.close(complete=True)

    # The file of the first channel was fetched once; the others once as well.
    assert all(count == 1 for count in lab.downloads.values()), lab.downloads
    assert len(lab.downloads) == 4 and lab.downloads.keys() >= first_run.keys()
    assert [r.channel.id for r in exported.results] == ["202", "203"]  # this run's channels
    assert exported.manifest["counts"]["channels"] == 3 and len(exported.jobs) == 4  # the whole export
    assert exported.complete and not exported.interrupted and not staging.exists()

    expected = reference(results)
    if as_zip:
        with zipfile.ZipFile(target) as archive:
            final = {name: archive.read(name) for name in archive.namelist()}
    else:
        final = tree(target)
    for name, raw in expected.items():
        assert final[name] == raw, name
    done = json.loads(final["manifest.json"])
    assert (done["complete"], done["interrupted"], done["partial"]) == (True, False, False)
    assert "offsets" not in done
    assert not debris(tmp_path)
    assert sorted(p.name for p in tmp_path.iterdir()) == [target.name]


def test_a_killed_run_leaves_a_torn_tail_that_resume_cuts_off(tmp_path, lab):
    target = tmp_path / "fit"
    results = lab.results()
    writer = lab.writer(target)  # no `with` and no close: like a process that is killed
    writer.open([r.channel for r in results])
    writer.add_channel(results[0])
    staging = ex.staging_path(target)
    data = manifest_of(staging)
    assert (data["complete"], data["interrupted"]) == (False, False)  # nobody got to say "interrupted"
    # The next channel was half written: bytes after the committed length, a half channel file, a half manifest.
    with (staging / "messages.md").open("ab") as file:
        file.write(b"\n# VUT FIT / #2bit-terminy\nhalf a channel")
    with (staging / "messages.jsonl").open("ab") as file:
        file.write(b'{"id": "2020')
    (staging / "channels" / "2bit-terminy.md").write_bytes(b"half")
    (staging / "manifest.json.part").write_bytes(b"{")
    (staging / "files" / "x").mkdir(parents=True)
    (staging / "files" / "x" / "800000000000000002_CON.txt.part").write_bytes(b"cut")

    resume = ex.find_unfinished(target, fingerprint())
    assert resume is not None and list(resume.done) == ["200"]
    writer = lab.writer(target)
    with writer:
        writer.open(CHANNELS, resume)
        for result in results[1:]:
            writer.add_channel(result)
        writer.close(complete=True)
    final = tree(target)
    for name, raw in reference(results).items():
        assert final[name] == raw, name
    assert not debris(tmp_path) and [p.name for p in tmp_path.iterdir()] == ["fit"]
    assert "files/x/800000000000000002_CON.txt.part" not in final  # debris in the staging folder is not published


def test_a_run_that_died_while_publishing_is_finished_by_the_next_one(tmp_path, lab):
    target = tmp_path / "fit"
    results = lab.results()
    writer = lab.writer(target)
    writer.open([r.channel for r in results])
    for result in results:
        writer.add_channel(result)  # everything is fetched, but close() never ran
    staging = ex.staging_path(target)
    with (staging / "messages.md").open("ab") as file:
        file.write(b"torn")
    resume = ex.find_unfinished(target, fingerprint())
    assert resume is not None and list(resume.done) == ["200", "202", "203"]
    requests = len(lab.cdn.requests)
    writer = lab.writer(target)
    with writer:
        writer.open(CHANNELS, resume)
        assert writer.pending == []
        writer.close(complete=True)
    assert len(lab.cdn.requests) == requests
    for name, raw in reference(results).items():
        assert tree(target)[name] == raw, name
    assert not ex.staging_path(target).exists()


def test_interrupt_during_a_download_keeps_the_finished_channels(tmp_path, lab):
    class Stop(Progress):
        def file(self, number, total, job):
            if job.channel_id == "202":
                raise KeyboardInterrupt

    target = tmp_path / "fit"
    results = lab.results()
    with pytest.raises(KeyboardInterrupt), lab.writer(target, progress=Stop()) as writer:
        stream(writer, results)
    staging = ex.staging_path(target)
    assert not target.exists() and not debris(staging)
    data = manifest_of(staging)
    assert data["interrupted"] is True and [c["channel"]["id"] for c in data["channels"]] == ["200"]
    resume = ex.find_unfinished(target, fingerprint())
    assert resume is not None and list(resume.done) == ["200"]


def test_nothing_is_kept_when_the_first_channel_fails(tmp_path, lab):
    target = tmp_path / "fit"
    with pytest.raises(Boom), lab.writer(target) as writer:
        stream(writer, lab.results(), stop_after=0)
    assert list(tmp_path.iterdir()) == []  # no staging folder for an export that has nothing in it


def test_skipped_channels_are_not_resumed_as_done(tmp_path, lab):
    target = tmp_path / "fit"
    results = lab.results()
    writer = lab.writer(target)
    with pytest.raises(Boom), writer:
        writer.open(CHANNELS)
        writer.add_channel(results[0])
        writer.add_skipped(TERMINY, ex.SKIP_NO_ACCESS)
        raise Boom
    data = manifest_of(ex.staging_path(target))
    assert data["skipped_channels"] == [{"id": "202", "reason": "no_access"}] and data["partial"] is True
    resume = ex.find_unfinished(target, fingerprint())
    assert list(resume.done) == ["200"] and dict(resume.skipped) == {"202": "no_access"}
    writer = lab.writer(target)
    with writer:
        writer.open(CHANNELS, resume)
        assert writer.pending == ["202", "203"]  # the skipped one is tried again
        writer.add_channel(results[1])  # and now it works
        writer.add_channel(results[2])
        exported = writer.close(complete=True)
    assert not exported.partial and manifest_of(target)["skipped_channels"] == []


def test_resume_keeps_the_original_creation_time(tmp_path, lab):
    target = tmp_path / "fit"
    results = lab.results()
    with pytest.raises(Boom), lab.writer(target) as writer:
        stream(writer, results, stop_after=1)
    resume = ex.find_unfinished(target)  # without a fingerprint: just look, e.g. to read `created`
    assert resume.created == NOW
    later = lab.writer(target, created=NOW + timedelta(hours=5))  # a caller that passed another time
    with later:
        later.open(CHANNELS, resume)
        for result in results[1:]:
            later.add_channel(result)
        later.close(complete=True)
    assert manifest_of(target)["created"] == "2026-11-03T12:00:00+01:00"


# --- the request does not match ------------------------------------------------------------------------


def test_another_request_starts_clean(tmp_path, lab):
    target = tmp_path / "fit"
    results = lab.results()
    with pytest.raises(Boom), lab.writer(target) as writer:
        stream(writer, results, stop_after=2)  # channels 200 and 202 are done
    old = ex.find_unfinished(target)
    assert old is not None and list(old.done) == ["200", "202"]

    other = [GENERAL, INFO]
    assert ex.find_unfinished(target, fingerprint(other)) is None  # a different request: no resume
    assert ex.find_unfinished(target, fingerprint()) is not None

    writer = lab.writer(target)
    with pytest.raises(ValueError):  # a Resume of another request is refused
        writer.open(other, old)
    writer = lab.writer(target)
    with writer:
        writer.open(other)  # no resume: the old partial data is deleted, not mixed in
        assert writer.done == [] and writer.pending == ["200", "203"]
        for result in [r for r in results if r.channel in other]:
            writer.add_channel(result)
        writer.close(complete=True)
    final = tree(target)
    assert "channels/2bit-terminy.md" not in final and "files/2bit-terminy/800000000000000002__CON.txt" not in final
    assert not any(b"2bit-terminy" in raw for raw in final.values())
    assert manifest_of(target)["targets"] == ["200", "203"] and manifest_of(target)["counts"]["channels"] == 2
    assert not ex.staging_path(target).exists()


def test_the_export_function_never_resumes(tmp_path, lab):
    target = tmp_path / "fit"
    results = lab.results()
    with pytest.raises(Boom), lab.writer(target) as writer:
        stream(writer, results, stop_after=1)
    before = sum(lab.downloads.values())
    lab.export_all(target, False, results)
    assert sum(lab.downloads.values()) == before + 4  # all four files again: nothing taken over from the staging folder
    assert tree(target)["messages.md"] == reference(results)["messages.md"]


def test_a_damaged_unfinished_export_is_not_resumable(tmp_path, lab):
    target = tmp_path / "fit"
    results = lab.results()

    def interrupted() -> Path:
        shutil.rmtree(ex.staging_path(target), ignore_errors=True)
        with pytest.raises(Boom), lab.writer(target) as writer:
            stream(writer, results, stop_after=1)
        return ex.staging_path(target)

    staging = interrupted()
    assert ex.find_unfinished(target, fingerprint()) is not None
    (staging / "messages.md").write_bytes(b"short")  # shorter than the manifest says
    assert ex.find_unfinished(target, fingerprint()) is None
    staging = interrupted()
    (staging / "channels" / "2bit-general.md").unlink()
    assert ex.find_unfinished(target, fingerprint()) is None
    staging = interrupted()
    next(p for p in (staging / "files").rglob("*") if p.is_file()).unlink()  # a downloaded file is gone
    assert ex.find_unfinished(target, fingerprint()) is None
    staging = interrupted()
    (staging / "manifest.json").write_text("{not json", encoding="utf-8")
    assert ex.find_unfinished(target, fingerprint()) is None
    assert ex.find_unfinished(tmp_path / "never-exported") is None


# --- manifest ------------------------------------------------------------------------------------------


def test_manifest_fields(tmp_path, lab):
    results = lab.results()
    writer = lab.writer(tmp_path / "fit")
    with writer:
        writer.open(CHANNELS)
        for result in results[:2]:
            writer.add_channel(result)
        writer.add_skipped(INFO, ex.SKIP_NOT_FOUND)
        exported = writer.close(complete=True)
    data = manifest_of(tmp_path / "fit")
    assert list(data)[:6] == ["tool", "version", "complete", "interrupted", "partial", "created"]
    assert (data["complete"], data["interrupted"], data["partial"]) == (True, False, True)
    assert data["targets"] == ["200", "202", "203"]
    assert data["skipped_channels"] == [{"id": "203", "reason": "not_found"}]
    assert data["request"] == {"fingerprint": fingerprint(), **ex.request_summary(CHANNELS, QUERY, OPTIONS, CET)}
    assert data["counts"]["channels"] == 2 and "offsets" not in data
    assert exported.partial and exported.skipped == (ex.SkippedChannel("203", "not_found"),)
    assert exported.manifest["partial"] is True
    # the old fields keep their shape
    assert data["tool"] == "discoop" and data["created"] == "2026-11-03T12:00:00+01:00"
    assert data["query"]["mode"] == "safe" and data["truncated"] is False
    assert set(data["channels"][0]) == {"server", "channel", "messages", "files", "truncated", "markdown", "folder"}
    # no free text and no names of people in the new fields
    new_fields = json.dumps([data["request"], data["targets"], data["skipped_channels"]])
    assert "student" not in new_fields.casefold() and "2bit" not in new_fields


def test_interrupted_and_partial_flags(tmp_path, lab):
    results = lab.results()
    target = tmp_path / "fit"
    lab.cdn.missing.add("/attachments/200/800000000000000002/file.bin")  # a file that cannot be fetched
    writer = lab.writer(target)
    with writer:
        writer.open(CHANNELS)
        writer.add_channel(results[0])
        writer.add_channel(results[1])
        exported = writer.close(complete=False)
    assert not exported.complete and exported.interrupted and exported.partial
    assert exported.path == ex.staging_path(target) and exported.target == target
    data = manifest_of(exported.path)
    assert (data["complete"], data["interrupted"], data["partial"]) == (False, True, True)
    assert [a["status"] for a in data["attachments"]] == ["downloaded", "downloaded", "failed"]
    assert writer.close(complete=True) is exported  # closing again gives the first result


def test_size_skips_and_no_files_are_not_partial(tmp_path, lab):
    results = lab.results()
    big = ex.Options(files=True, max_file_size=10)
    exported = lab.export_all(tmp_path / "big", False, results, options=big)
    assert exported.count(SKIPPED) == 4 and not exported.partial and manifest_of(tmp_path / "big")["partial"] is False
    before = len(lab.cdn.requests)
    exported = lab.export_all(tmp_path / "nofiles", False, results, options=ex.Options(files=False))
    assert len(lab.cdn.requests) == before and not exported.partial
    assert {a["reason"] for a in manifest_of(tmp_path / "nofiles")["attachments"]} == {"--no-files"}
    assert not (tmp_path / "nofiles" / "files").exists()


def test_misuse_is_refused(tmp_path, lab):
    results = lab.results()
    writer = lab.writer(tmp_path / "fit")
    with pytest.raises(RuntimeError):
        writer.add_channel(results[0])  # not open
    writer.open(CHANNELS)
    with pytest.raises(RuntimeError):
        writer.open(CHANNELS)
    writer.add_channel(results[0])
    with pytest.raises(ValueError):
        writer.add_channel(results[0])  # twice
    with pytest.raises(ValueError):
        writer.add_skipped(TERMINY, "boom")  # not a code
    with pytest.raises(ValueError):
        writer.add_skipped(GENERAL, ex.SKIP_NO_ACCESS)  # already in the export
    with pytest.raises(ValueError):
        writer.close(complete=True)  # two channels are still open
    writer.close(complete=False)
    with pytest.raises(RuntimeError):
        writer.add_channel(results[1])


# --- a finished export stays whole -------------------------------------------------------------------------


def snapshot(path: Path) -> dict[str, tuple[bytes, int]]:
    """Bytes and modification time of every file: even touching one would show."""
    return {
        p.relative_to(path).as_posix(): (p.read_bytes(), p.stat().st_mtime_ns) for p in sorted(path.rglob("*")) if p.is_file()
    }


def refreshed(lab: Lab):
    """The same request a day later: new text in the first channel, a new file, another file replaced."""
    results = lab.results()
    first = lab.result(
        GENERAL, [("800000000000000001", "assignment.pdf"), ("800000000000000009", "new.bin")], texts=("fresh text",)
    )
    return [first, *results[1:]]


@pytest.mark.parametrize("kill", [False, True], ids=["error", "kill"])
def test_a_finished_folder_export_survives_an_interrupted_refresh(tmp_path, lab, kill):
    target = tmp_path / "fit"
    lab.export_all(target, False, lab.results())
    before = snapshot(target)
    assert manifest_of(target)["complete"] is True

    new = refreshed(lab)
    writer = lab.writer(target)
    if kill:
        writer.open([r.channel for r in new])
        writer.add_channel(new[0])  # ... and the process is gone
    else:
        with pytest.raises(Boom), writer:
            stream(writer, new, stop_after=1)  # crash while fetching the second channel
    assert snapshot(target) == before  # not one byte, not one timestamp of the finished export changed
    assert sorted(p.name for p in tmp_path.iterdir()) == ["fit", "fit.partial"]
    data = manifest_of(target)
    assert data["complete"] is True
    for entry in data["attachments"]:
        assert (target / entry["path"]).read_bytes() == content(entry["id"])
    ex.check_target(target, False)  # still a valid target for the next run

    # ... and the refresh can be finished later.
    request = fingerprint()
    resume = ex.find_unfinished(target, request)
    assert resume is not None and list(resume.done) == ["200"]
    writer = lab.writer(target)
    requests = len(lab.cdn.requests)
    with writer:
        writer.open(CHANNELS, resume)
        for result in new[1:]:
            writer.add_channel(result)
        writer.close(complete=True)
    final = tree(target)
    assert b"fresh text" in final["messages.md"] and manifest_of(target)["complete"] is True
    assert not ex.staging_path(target).exists() and not debris(tmp_path)
    assert (target / "files/2bit-general/800000000000000009_new.bin").read_bytes() == content("800000000000000009")
    # files of the finished export were taken over (`present`), not fetched again
    assert len(lab.cdn.requests) - requests == 0
    assert {a["id"]: a["status"] for a in manifest_of(target)["attachments"]}["800000000000000002"] == PRESENT


def test_a_finished_zip_survives_an_interrupted_refresh(tmp_path, lab):
    target = tmp_path / "fit.zip"
    lab.export_all(target, True, lab.results())
    before = (target.read_bytes(), target.stat().st_mtime_ns)

    new = refreshed(lab)
    with pytest.raises(Boom), lab.writer(target, True) as writer:
        stream(writer, new, stop_after=2)
    assert (target.read_bytes(), target.stat().st_mtime_ns) == before
    assert sorted(p.name for p in tmp_path.iterdir()) == ["fit.zip", "fit.zip.partial"]
    ex.check_target(target, True)
    assert not debris(tmp_path)

    resume = ex.find_unfinished(target, fingerprint())
    assert resume is not None and list(resume.done) == ["200", "202"]
    requests = len(lab.cdn.requests)
    with lab.writer(target, True) as writer:
        writer.open(CHANNELS, resume)
        writer.add_channel(new[2])
        writer.close(complete=True)
    assert len(lab.cdn.requests) == requests  # the old files came out of the old zip
    with zipfile.ZipFile(target) as archive:
        assert json.loads(archive.read("manifest.json"))["complete"] is True
        assert b"fresh text" in archive.read("messages.md")
        assert archive.read("files/2bit-general/800000000000000009_new.bin") == content("800000000000000009")
    assert sorted(p.name for p in tmp_path.iterdir()) == ["fit.zip"]


def test_a_request_of_another_shape_does_not_hurt_a_finished_export(tmp_path, lab):
    """The staging folder of an unrelated request is deleted, the finished export in the target never."""
    target = tmp_path / "fit"
    lab.export_all(target, False, lab.results())
    before = snapshot(target)
    with pytest.raises(Boom), lab.writer(target) as writer:
        stream(writer, lab.results(), stop_after=1)
    other = lab.writer(target)
    with pytest.raises(Boom), other:
        other.open([GENERAL])  # another request: the staging folder is made anew
        raise Boom
    assert snapshot(target) == before


def test_publishing_adds_to_a_folder_and_drops_stale_channel_files(tmp_path, lab):
    target = tmp_path / "fit"
    lab.export_all(target, False, lab.results())
    pdf = target / "files" / "2bit-general" / "800000000000000001_assignment.pdf"
    pdf.write_bytes(b"cut short")  # a file that is not whole is downloaded again ...
    pdf.with_name(pdf.name + ".part").write_bytes(b"an old unfinished download")  # ... and its leftover goes
    lab.export_all(target, False, [lab.result(GENERAL, [("800000000000000001", "assignment.pdf")])])  # one channel only
    final = tree(target)
    assert final["files/2bit-general/800000000000000001_assignment.pdf"] == content("800000000000000001")
    assert "channels/2bit-terminy.md" not in final  # the channel of the older run goes ...
    assert "files/2bit-terminy/800000000000000002__CON.txt" in final  # ... its saved file stays
    assert not debris(tmp_path) and not ex.staging_path(target).exists()
    assert manifest_of(target)["counts"]["channels"] == 1


def test_an_empty_target_folder_is_filled(tmp_path, lab):
    target = tmp_path / "fit"
    target.mkdir()
    lab.export_all(target, False, lab.results())
    assert manifest_of(target)["complete"] is True and not ex.staging_path(target).exists()


# --- files that are rewritten ------------------------------------------------------------------------------


def test_atomic_writes_retry_after_permission_errors(tmp_path, lab, monkeypatch):
    real = os.replace
    refused = {"manifest.json": 2}

    def flaky(source, destination):
        name = Path(destination).name
        if refused.get(name):
            refused[name] -= 1
            raise PermissionError(13, "Access is denied")
        return real(source, destination)

    monkeypatch.setattr(os, "replace", flaky)
    sleeps: list[float] = []
    writer = lab.writer(tmp_path / "fit", sleep=sleeps.append)
    with writer:
        stream(writer, lab.results())
        writer.close(complete=True)
    assert sleeps == [0.05, 0.1]  # the first manifest write needed two more tries
    assert manifest_of(tmp_path / "fit")["complete"] is True
    assert not debris(tmp_path)


def test_atomic_write_gives_up_after_the_last_retry(tmp_path, lab, monkeypatch):
    real = os.replace

    def locked(source, destination):
        if Path(destination).name == "manifest.json":
            raise PermissionError(13, "Access is denied")
        return real(source, destination)

    monkeypatch.setattr(os, "replace", locked)
    sleeps: list[float] = []
    writer = lab.writer(tmp_path / "fit", sleep=sleeps.append)
    with pytest.raises(DiscoopError) as e:
        writer.open(CHANNELS)
    assert e.value.code == ExitCode.ERROR and "Cannot write the export" in e.value.message
    assert sleeps == [0.05, 0.1, 0.2, 0.4]
    assert not debris(tmp_path)  # the temporary file is removed again


def test_replace_of_the_final_zip_is_retried_too(tmp_path, lab, monkeypatch):
    real = os.replace
    refused = {"fit.zip": 1}

    def flaky(source, destination):
        name = Path(destination).name
        if refused.get(name):
            refused[name] -= 1
            raise PermissionError(13, "Access is denied")
        return real(source, destination)

    monkeypatch.setattr(os, "replace", flaky)
    sleeps: list[float] = []
    with lab.writer(tmp_path / "fit.zip", True, sleep=sleeps.append) as writer:
        stream(writer, lab.results())
        writer.close(complete=True)
    assert sleeps == [0.05] and zipfile.is_zipfile(tmp_path / "fit.zip")


# --- targets -----------------------------------------------------------------------------------------------


def test_a_foreign_staging_folder_is_never_touched(tmp_path, lab):
    target = tmp_path / "fit"
    staging = ex.staging_path(target)
    staging.mkdir()
    (staging / "notes.txt").write_text("my notes", encoding="utf-8")
    with pytest.raises(DiscoopError) as e:
        ex.check_target(target, False)
    assert e.value.code == ExitCode.BAD_ARGS and "fit.partial" in e.value.message
    with pytest.raises(DiscoopError) as e:
        lab.writer(target).open(CHANNELS)
    assert e.value.code == ExitCode.BAD_ARGS
    assert (staging / "notes.txt").read_text(encoding="utf-8") == "my notes"
    assert not target.exists()
    zip_target = tmp_path / "fit.zip"
    ex.staging_path(zip_target).write_text("a file", encoding="utf-8")  # a file where the staging folder should be
    with pytest.raises(DiscoopError):
        ex.check_target(zip_target, True)


def test_an_empty_or_unfinished_staging_folder_is_a_valid_target(tmp_path, lab):
    target = tmp_path / "fit"
    ex.staging_path(target).mkdir()
    ex.check_target(target, False)
    results = lab.results()
    with pytest.raises(Boom), lab.writer(target) as writer:
        stream(writer, results, stop_after=1)
    ex.check_target(target, False)  # an unfinished export of ours
    assert ex.staging_path(target).is_dir()


def test_staging_paths(tmp_path):
    assert ex.staging_path(tmp_path / "fit") == tmp_path / "fit.partial"
    assert ex.staging_path(tmp_path / "fit.zip") == tmp_path / "fit.zip.partial"


# --- bytes_to_download (the disk space check) -----------------------------------------------------------

SHARED_ID = "800000000000000003"


def size_of(*attachment_ids: str) -> int:
    return sum(len(content(attachment_id)) for attachment_id in attachment_ids)


def test_bytes_to_download_counts_each_attachment_once(tmp_path, lab):
    results = lab.threaded_results()
    general, forum = results[0], results[1]
    writer = lab.writer(tmp_path / "export")
    with writer:
        writer.open([result.channel for result in results])
        # GENERAL has two files itself and two in its threads; SHARED is posted in the channel and in a thread
        assert writer.bytes_to_download(general) == size_of("800000000000000001", SHARED_ID, "800000000000000011", "800000000000000012")
        assert writer.bytes_to_download(forum) == size_of("800000000000000013")
        writer.add_channel(general)
        # SHARED was saved with GENERAL: INFO only has the other file to download
        assert writer.bytes_to_download(lab.result(INFO, FILES["203"])) == size_of("800000000000000004")
        assert writer.bytes_to_download(general) == 0


def test_bytes_to_download_is_zero_without_files_or_over_the_size_limit(tmp_path, lab):
    result = lab.result(GENERAL, FILES["200"])
    no_files = lab.writer(tmp_path / "a", options=ex.Options(files=False))
    with no_files:
        no_files.open([GENERAL])
        assert no_files.bytes_to_download(result) == 0
    small = lab.writer(tmp_path / "b", options=ex.Options(files=True, max_file_size=10))
    with small:
        small.open([GENERAL])
        assert small.bytes_to_download(result) == 0
    exact = lab.writer(tmp_path / "c", options=ex.Options(files=True, max_file_size=len(content(SHARED_ID))))
    with exact:
        exact.open([GENERAL])
        assert exact.bytes_to_download(result) == size_of("800000000000000001", SHARED_ID)  # the limit itself is allowed


def test_bytes_to_download_leaves_out_an_attachment_without_a_url(tmp_path, lab):
    result = lab.result(GENERAL, FILES["200"])
    message = result.messages[-1]
    bare = tuple(replace(attachment, url="") for attachment in message.attachments)
    result = replace(result, messages=(*result.messages[:-1], replace(message, attachments=bare)))
    writer = lab.writer(tmp_path / "export")
    with writer:
        writer.open([GENERAL])
        assert writer.bytes_to_download(result) == 0


@pytest.mark.parametrize("as_zip", [False, True], ids=["folder", "zip"])
def test_bytes_to_download_leaves_out_files_of_an_earlier_export(tmp_path, lab, as_zip, monkeypatch):
    target = tmp_path / ("fit.zip" if as_zip else "fit")
    lab.export_all(target, as_zip, [lab.result(GENERAL, FILES["200"])])
    opened: list[Path] = []
    real = ex._zip_files
    monkeypatch.setattr(ex, "_zip_files", lambda path: (opened.append(path), real(path))[1])

    again = lab.result(GENERAL, FILES["200"])  # the same two files
    another = lab.result(INFO, [(SHARED_ID, "chart (1).png"), ("800000000000000004", "other.bin")])
    writer = lab.writer(target, as_zip)
    with writer:
        writer.open([GENERAL, INFO])
        assert writer.bytes_to_download(again) == 0
        assert writer.bytes_to_download(another) == size_of("800000000000000004")  # SHARED is in the export
    assert len(opened) == (1 if as_zip else 0)  # an old zip is read once, however many files and calls there are


def test_bytes_to_download_leaves_out_files_of_the_staging_folder(tmp_path, lab):
    results = lab.results()
    channels = [result.channel for result in results]
    target = tmp_path / "export"
    first = lab.writer(target)
    with pytest.raises(Boom):
        with first:
            stream(first, results, stop_after=1)  # GENERAL is saved in `export.partial`
    resume = ex.find_unfinished(target, ex.request_fingerprint(channels, QUERY, OPTIONS, CET))
    assert resume is not None
    writer = lab.writer(target)
    with writer:
        writer.open(channels, resume)
        assert writer.bytes_to_download(results[0]) == 0  # finished by the first run
        assert writer.bytes_to_download(results[1]) == size_of("800000000000000002")
        # a file that was downloaded just before the crash, when its channel was not committed yet
        stray = ex.staging_path(target) / "files" / "2bit-terminy" / "800000000000000002_CON.txt"
        stray.parent.mkdir(parents=True)
        stray.write_bytes(content("800000000000000002"))
        assert writer.bytes_to_download(results[1]) == 0
        assert writer.bytes_to_download(results[2]) == size_of("800000000000000004")  # SHARED came with GENERAL


# --- parts (--max-tokens): made with the export, published with it ---------------------------------------


def parts_of(files: dict[str, bytes]) -> dict[str, str]:
    return {
        name: data.decode("utf-8") for name, data in files.items() if re.fullmatch(r"parts/part-\d{3}\.md", name)
    }


def zip_tree(path: Path) -> dict[str, bytes]:
    with zipfile.ZipFile(path) as archive:
        return {name: archive.read(name) for name in archive.namelist()}


def export_tree(target: Path, as_zip: bool) -> dict[str, bytes]:
    return zip_tree(target) if as_zip else tree(target)


def write_export(lab, target: Path, as_zip: bool = False, results=None, **kw) -> ex.Exported:
    writer = lab.writer(target, as_zip, **kw)
    with writer:
        stream(writer, results or lab.results())
        return writer.close(complete=True)


@pytest.mark.parametrize("as_zip", [False, True], ids=["folder", "zip"])
def test_parts_are_published_with_the_export(tmp_path, lab, as_zip):
    target = tmp_path / ("fit.zip" if as_zip else "fit")
    write_export(lab, target, as_zip, max_tokens=150)
    files = export_tree(target, as_zip)
    expected = split_markdown(files["messages.md"].decode("utf-8"), 150)
    assert len(expected) > 1
    parts = parts_of(files)
    assert sorted(parts) == [f"parts/part-{number:03d}.md" for number in range(1, len(expected) + 1)]
    assert [parts[name] for name in sorted(parts)] == expected
    assert expected[0].startswith(f"<!-- discoop part 1 of {len(expected)} -->\n")
    assert "part-0" not in json.dumps(json.loads(files["manifest.json"]))  # the manifest does not list parts
    assert not as_zip or not debris(tmp_path)


def test_a_folder_and_a_zip_get_the_same_parts(tmp_path, lab):
    write_export(lab, tmp_path / "folder", False, max_tokens=150)
    write_export(lab, tmp_path / "fit.zip", True, max_tokens=150)
    assert parts_of(tree(tmp_path / "folder")) == parts_of(zip_tree(tmp_path / "fit.zip")) != {}


def test_no_parts_without_max_tokens(tmp_path, lab):
    write_export(lab, tmp_path / "fit")
    assert not (tmp_path / "fit" / "parts").exists()


@pytest.mark.parametrize("as_zip", [False, True], ids=["folder", "zip"])
def test_a_crash_before_the_end_leaves_no_parts_in_the_target(tmp_path, lab, as_zip):
    target = tmp_path / ("fit.zip" if as_zip else "fit")
    writer = lab.writer(target, as_zip, max_tokens=150)
    with pytest.raises(Boom):
        with writer:
            stream(writer, lab.results(), stop_after=2)
    assert not target.exists()
    assert not (ex.staging_path(target) / "parts").exists()  # parts are only made when the export is finished


@pytest.mark.parametrize("as_zip", [False, True], ids=["folder", "zip"])
def test_an_interrupted_run_leaves_the_parts_of_a_finished_export_alone(tmp_path, lab, as_zip):
    target = tmp_path / ("fit.zip" if as_zip else "fit")
    write_export(lab, target, as_zip, max_tokens=150)
    before = export_tree(target, as_zip)
    assert parts_of(before)
    other = Query(Window(NOW - timedelta(days=2), NOW), None, 5000, False)  # another request: it starts anew
    writer = lab.writer(target, as_zip, query=other, max_tokens=60)
    with pytest.raises(Boom):
        with writer:
            stream(writer, lab.results(), stop_after=1)
    assert export_tree(target, as_zip) == before


def test_a_reexport_replaces_the_old_parts(tmp_path, lab):
    target = tmp_path / "fit"
    write_export(lab, target, max_tokens=60)
    many = parts_of(tree(target))
    assert len(many) > 2
    (target / "parts" / "notes.txt").write_text("mine", encoding="utf-8")  # not a part: stays

    write_export(lab, target, max_tokens=100_000)
    assert sorted(parts_of(tree(target))) == ["parts/part-001.md"]
    assert parts_of(tree(target))["parts/part-001.md"].startswith("<!-- discoop part 1 of 1 -->\n")
    assert (target / "parts" / "notes.txt").read_text(encoding="utf-8") == "mine"

    (target / "parts" / "notes.txt").unlink()
    write_export(lab, target)  # without --max-tokens: the old parts do not fit the new messages.md either
    assert not (target / "parts").exists()


def test_a_reexport_into_a_zip_replaces_the_old_parts(tmp_path, lab):
    target = tmp_path / "fit.zip"
    write_export(lab, target, True, max_tokens=60)
    write_export(lab, target, True, max_tokens=100_000)
    assert sorted(parts_of(zip_tree(target))) == ["parts/part-001.md"]
    write_export(lab, target, True)
    assert parts_of(zip_tree(target)) == {}


@pytest.mark.parametrize("as_zip", [False, True], ids=["folder", "zip"])
def test_an_interrupted_export_is_continued_and_gets_its_parts(tmp_path, lab, as_zip):
    results = lab.results()
    one_go = tmp_path / ("one.zip" if as_zip else "one")
    write_export(lab, one_go, as_zip, results, max_tokens=150)

    target = tmp_path / ("fit.zip" if as_zip else "fit")
    first = lab.writer(target, as_zip)  # the first run has no max_tokens: the parts are made at the end only
    with pytest.raises(Boom):
        with first:
            stream(first, results, stop_after=2)
    channels = [result.channel for result in results]
    resume = ex.find_unfinished(target, ex.request_fingerprint(channels, QUERY, OPTIONS, CET))
    assert resume is not None and list(resume.done) == ["200", "202"]
    writer = lab.writer(target, as_zip, max_tokens=150)
    with writer:
        writer.open(channels, resume)
        writer.add_channel(results[2])
        writer.close(complete=True)
    assert parts_of(export_tree(target, as_zip)) == parts_of(export_tree(one_go, as_zip)) != {}


def test_parts_a_crashed_finish_left_in_the_staging_folder_do_not_get_published(tmp_path, lab):
    target = tmp_path / "fit"
    writer = lab.writer(target, max_tokens=100_000)
    with writer:
        stream(writer, lab.results())
        stale = ex.staging_path(target) / "parts" / "part-009.md"
        stale.parent.mkdir()
        stale.write_text("an old split", encoding="utf-8")
        writer.close(complete=True)
    assert sorted(parts_of(tree(target))) == ["parts/part-001.md"]


def test_a_message_larger_than_the_limit_is_reported_to_the_warning_callback(tmp_path, lab):
    told: list[str] = []
    write_export(lab, tmp_path / "fit", max_tokens=1, on_warning=told.append)
    assert told and all("exceeds max_tokens" in text for text in told)
    assert sorted(parts_of(tree(tmp_path / "fit"))) == [f"parts/part-{n:03d}.md" for n in range(1, len(told) + 1)]


def test_max_tokens_must_be_positive(tmp_path, lab):
    with pytest.raises(ValueError, match="at least 1"):
        lab.writer(tmp_path / "fit", max_tokens=0)
