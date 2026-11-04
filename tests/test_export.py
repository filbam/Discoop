"""`discoop messages --out/--zip`: attachments, export folder and zip, manifest. Discord and its CDN are fakes."""

import json
import zipfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from discoop import cli
from discoop.api import DiscordAPI
from discoop.attachments import cdn_client
from discoop.tokenstore import TokenStore
from fake_messages import (
    CET,
    FIT,
    NOW,
    USER_B,
    FakeCDN,
    FakeChannel,
    FakeDiscord,
    Network,
    message,
    signed_url,
)

# These tests run through the CLI, which reads the real clock: a URL that is "still valid" must not run out on
# the day the tests are run (with +20 hours it did, 2026-11-04 07:00 UTC, and the tests started to fail).
SOON = NOW + timedelta(days=3650)
PDF, PNG, SCRIPT, NOTE = "800000000000000001", "800000000000000002", "800000000000000003", "800000000000000004"
PDF_PATH = f"files/2bit-general/{PDF}_zadanie.pdf"
PNG_PATH = f"files/2bit-general/{PNG}_graf (1).png"
SCRIPT_PATH = f"files/2bit-general/{SCRIPT}__.._evil_name_.sh"  # the name was "../../evil:name?.sh"
NOTE_PATH = f"files/2bit-terminy/{NOTE}__CON.txt"  # CON is a reserved name on Windows
ALL_FILES = [
    "channels/2bit-general.md",
    "channels/2bit-terminy.md",
    PNG_PATH,
    PDF_PATH,
    SCRIPT_PATH,
    NOTE_PATH,
    "manifest.json",
    "messages.jsonl",
    "messages.md",
]
SUMMARY = ["channels: 2", "messages: 4", "files: 4"]


def at(hour: int, minute: int = 0) -> datetime:
    """A time on 2026-11-03, given in UTC+01:00."""
    return datetime(2026, 11, 3, hour, minute, tzinfo=CET).astimezone(UTC)


def content(attachment_id: str) -> bytes:
    return f"test file {attachment_id}\n".encode() * 8


def file(attachment_id: str, filename: str, kind: str, *, channel="200", url_name=None, expires=SOON, data=None) -> dict:
    """An attachment as Discord sends it. `url_name` is the name in the URL, which Discord keeps URL-safe."""
    url = signed_url(channel, attachment_id, url_name or filename, expires=expires)
    size = len(data if data is not None else content(attachment_id))
    return {"id": attachment_id, "filename": filename, "size": size, "url": url, "proxy_url": url, "content_type": kind}


def general() -> list[dict]:
    return [
        message(
            at(10),
            "Zadanie a graf",
            attachments=[
                file(PDF, "zadanie.pdf", "application/pdf"),
                file(PNG, "graf (1).png", "image/png", url_name="graf_1.png"),
            ],
        ),
        message(at(10, 30), "pozor", author=USER_B, attachments=[file(SCRIPT, "../../evil:name?.sh", "text/x-sh", url_name="evil_name.sh")]),
        message(at(11), "bez prílohy"),
    ]


def terminy() -> list[dict]:
    return [message(at(9), "termíny", channel_id="202", attachments=[file(NOTE, "CON.txt", "text/plain", channel="202")])]


@pytest.fixture
def env(monkeypatch, tmp_path):
    """Logged in; fake Discord and CDN on one logged transport; the current folder is pytest's tmp_path."""
    TokenStore.default().save("tok")
    monkeypatch.setattr(cli, "utc_now", lambda: NOW)
    monkeypatch.setattr(cli, "LOCAL_ZONE", CET)
    monkeypatch.chdir(tmp_path)
    discord = FakeDiscord({"200": FakeChannel(general()), "202": FakeChannel(terminy())})
    cdn = FakeCDN()
    network = Network(discord, cdn)
    transport = httpx.MockTransport(network.handle)
    sleeps: list[float] = []
    monkeypatch.setattr(
        cli, "DiscordAPI", lambda token, **kw: DiscordAPI(token, transport=transport, sleep=sleeps.append, **kw)
    )
    monkeypatch.setattr(cli, "cdn_client", lambda: cdn_client(transport))

    def serve(*channels: str, data: dict[str, bytes] | None = None) -> None:
        for channel_id in channels:
            for raw in discord.channels[channel_id].messages:
                for attachment in raw["attachments"]:
                    cdn.add(attachment["url"], (data or {}).get(attachment["id"]) or content(attachment["id"]))

    serve("200", "202")
    return SimpleNamespace(discord=discord, cdn=cdn, network=network, sleeps=sleeps, tmp=tmp_path, serve=serve)


def run(capsys, *args):
    with pytest.raises(SystemExit) as e:
        cli.main(["--agent", *args])
    captured = capsys.readouterr()
    return e.value.code, captured.out, captured.err


def export(capsys, *args):
    return run(capsys, "messages", "-s", FIT, "-c", "200", "-c", "202", *args)


def files_in(root: Path) -> dict[str, bytes]:
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file()}


# --- folder ----------------------------------------------------------------------------------------


def test_out_folder(capsys, env):
    code, out, err = export(capsys, "--out", "exports/fit")
    root = env.tmp / "exports" / "fit"
    assert (code, err) == (0, "")
    assert out.splitlines() == [
        f"export: {root}",
        "channels: 2",
        "messages: 4",
        "tokens: ~186 (estimate, about 4 characters per token)",
        "files: 4",
        "downloaded: 4",
        "already_present: 0",
        "failed: 0",
        "skipped: 0",
        "truncated: no",
    ]
    saved = files_in(root)
    assert sorted(saved) == sorted(ALL_FILES)
    assert saved[PDF_PATH] == content(PDF) and saved[NOTE_PATH] == content(NOTE)
    assert all(b"\r\n" not in saved[name] for name in ("messages.md", "messages.jsonl", "manifest.json"))

    md = saved["messages.md"].decode()
    assert md.startswith("# VUT FIT / #2bit-general\nrange: 2026-11-02 12:00 .. 2026-11-03 12:00 (UTC+01:00)")
    assert "\n- [file] [zadanie.pdf](files/2bit-general/800000000000000001_zadanie.pdf) 232B\n" in md
    assert f"\n- [file] ![graf (1).png](<{PNG_PATH}>) 232B\n" in md  # an image, shown inline
    assert f"[../../evil:name?.sh]({SCRIPT_PATH}) 232B" in md
    assert "\n\n# VUT FIT / #2bit-terminy\n" in md
    assert md.endswith("\n") and "https://" not in md
    channel_md = saved["channels/2bit-general.md"].decode()
    assert f"](../{PDF_PATH}) 232B" in channel_md and "2bit-terminy" not in channel_md

    jsonl = [json.loads(line) for line in saved["messages.jsonl"].decode().splitlines()]
    assert [m["text"] for m in jsonl] == ["Zadanie a graf", "pozor", "bez prílohy", "termíny"]
    assert [a["path"] for a in jsonl[0]["attachments"]] == [PDF_PATH, PNG_PATH]
    assert jsonl[0]["attachments"][0]["url"].startswith("https://cdn.discordapp.com/attachments/200/")

    manifest = json.loads(saved["manifest.json"])
    assert manifest["tool"] == "discoop" and manifest["complete"] is True
    assert manifest["created"] == "2026-11-03T12:00:00+01:00"
    assert manifest["query"] == {
        "from": "2026-11-02T12:00:00+01:00", "to": "2026-11-03T12:00:00+01:00", "last": None, "max_messages": 5000,
        "include_system": False, "mode": "safe", "files": True, "max_file_size": 50 * 1024 * 1024,
    }
    assert manifest["counts"] == {
        "channels": 2, "messages": 4, "files": 4, "downloaded": 4, "present": 0, "failed": 0, "skipped": 0
    }
    assert manifest["channels"][1] == {
        "server": {"id": FIT, "name": "VUT FIT"}, "channel": {"id": "202", "name": "2bit-terminy"}, "messages": 1,
        "files": 1, "truncated": False, "markdown": "channels/2bit-terminy.md", "folder": "files/2bit-terminy",
    }
    assert manifest["attachments"][0] == {
        "id": PDF, "message_id": jsonl[0]["id"], "channel_id": "200", "filename": "zadanie.pdf", "size": 232,
        "status": "downloaded", "path": PDF_PATH, "reason": None,
    }


def test_token_only_goes_to_the_api(capsys, env):
    env.discord.channels["202"] = FakeChannel(
        [message(at(9), "starý odkaz", attachments=[file(NOTE, "CON.txt", "text/plain", expires=NOW - timedelta(hours=1))])]
    )
    env.serve("202")
    code, _, _ = export(capsys, "--out", "exports/fit")
    assert code == 0 and env.discord.refresh_batches  # the expired URL was refreshed through the API
    api = [r for r in env.network.log if r.url.host == "discord.com"]
    cdn = [r for r in env.network.log if r.url.host != "discord.com"]
    assert len(cdn) == 4
    assert all(r.headers["authorization"] == "tok" and r.url.path.startswith("/api/v9/") for r in api)
    assert all("authorization" not in r.headers for r in cdn)
    assert all("tok" not in str(r.url) for r in cdn)


def test_expired_urls_are_refreshed_in_batches_before_downloading(capsys, env):
    expired = [
        message(at(10) + timedelta(seconds=n), f"súbor {n}", seq=n, attachments=[
            file(f"81000000000000{n:04d}", f"f{n}.txt", "text/plain", expires=NOW - timedelta(minutes=5))
        ])
        for n in range(60)
    ]
    env.discord.channels["200"] = FakeChannel(expired)
    env.serve("200")
    code, out, _ = run(capsys, "messages", "-s", FIT, "-c", "200", "--out", "exports/x", "--fast")
    assert code == 0 and "downloaded: 60" in out
    assert [len(batch) for batch in env.discord.refresh_batches] == [50, 10]
    assert len(env.cdn.requests) == 60 and all(r.url.params["hm"] == "fresh" for r in env.cdn.requests)
    # API requests (servers, channels, messages, 2 thread searches, 2 refreshes) keep the configured delay between them.
    api_requests = sum(env.discord.calls.values())
    assert api_requests == 7 and len(env.sleeps) == api_requests - 1 and min(env.sleeps) > 0.5


def test_url_refused_by_the_cdn_is_refreshed(capsys, env):
    env.cdn.revoked.add("a1")  # every original signature, although `ex` is still ahead
    code, out, err = export(capsys, "--out", "exports/fit")
    assert (code, err) == (0, "")
    assert "downloaded: 4" in out
    assert [len(batch) for batch in env.discord.refresh_batches] == [3, 1]


FAILED_FILE_WARNING = (
    "WARNING: 1 of 4 files could not be downloaded; manifest.json lists them as failed:"
    " ../../evil:name?.sh (HTTP 404 (also after refreshing the URL))."
)


def test_failed_file_does_not_stop_the_export(capsys, env):
    env.cdn.missing.add(f"/attachments/200/{SCRIPT}/evil_name.sh")
    code, out, err = export(capsys, "--out", "exports/fit")
    assert code == 9
    assert "downloaded: 3" in out and "failed: 1" in out
    # Without --verbose the plain mode prints the warning only; the partial-result note is a verbose one
    assert err == FAILED_FILE_WARNING + "\n"
    root = env.tmp / "exports" / "fit"
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    failed = [a for a in manifest["attachments"] if a["status"] == "failed"]
    assert failed == [{
        "id": SCRIPT, "message_id": failed[0]["message_id"], "channel_id": "200", "filename": "../../evil:name?.sh",
        "size": 232, "status": "failed", "path": None, "reason": "HTTP 404 (also after refreshing the URL)",
    }]
    assert not (root / SCRIPT_PATH).exists() and not list(root.rglob("*.part"))
    md = (root / "messages.md").read_text(encoding="utf-8")
    assert "- [file] ../../evil:name?.sh 232B https://cdn.discordapp.com/attachments/200/" in md  # the URL instead


def test_failed_file_ends_the_verbose_report_with_the_partial_result_note(capsys, env):
    env.cdn.missing.add(f"/attachments/200/{SCRIPT}/evil_name.sh")
    code, out, err = run(capsys, "-v", "messages", "-s", FIT, "-c", "200", "-c", "202", "--out", "exports/fit")
    assert code == 9
    assert err.splitlines()[-3:] == [
        FAILED_FILE_WARNING,
        "Messages from the last 24 hours. For more use --from 7d, --from 2026-10-01 or --from all.",
        "Partial result (exit code 9): 1 file not downloaded."
        " Run the same command again to try them again; files already saved are not downloaded again.",
    ]


def test_download_error_marks_file_failed_and_export_continues(capsys, env):
    orig_handle = env.cdn.handle

    def cdn_handle(request: httpx.Request) -> httpx.Response:
        if SCRIPT in request.url.path:
            return httpx.Response(302, headers={"Location": str(request.url)})
        return orig_handle(request)

    env.cdn.handle = cdn_handle
    code, out, err = export(capsys, "--out", "exports/fit")
    assert code == 9
    assert "downloaded: 3" in out and "failed: 1" in out
    assert "Exceeded maximum allowed redirects" in err
    root = env.tmp / "exports" / "fit"
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    failed = [a for a in manifest["attachments"] if a["status"] == "failed"]
    assert len(failed) == 1
    assert failed[0]["id"] == SCRIPT
    assert failed[0]["reason"].startswith("download error: Exceeded maximum allowed redirects")
    assert not (root / SCRIPT_PATH).exists()


def test_rerun_into_the_same_folder(capsys, env):
    export(capsys, "--out", "exports/fit")
    root = env.tmp / "exports" / "fit"
    downloaded = len(env.cdn.requests)
    (root / PDF_PATH).write_bytes(b"cut short")  # an incomplete file is downloaded again
    (root / PNG_PATH).unlink()
    (root / f"{PNG_PATH}.part").write_bytes(b"interrupted")  # an interrupted download, too
    code, out, _ = export(capsys, "--out", "exports/fit")
    assert code == 0 and "downloaded: 2" in out and "already_present: 2" in out
    assert [r.url.path for r in env.cdn.requests[downloaded:]] == [
        f"/attachments/200/{PDF}/zadanie.pdf", f"/attachments/200/{PNG}/graf_1.png"
    ]
    assert sorted(files_in(root)) == sorted(ALL_FILES)
    assert files_in(root)[PDF_PATH] == content(PDF)

    downloaded = len(env.cdn.requests)
    code, out, _ = run(capsys, "messages", "-s", FIT, "-c", "200", "--out", "exports/fit")
    assert code == 0 and "files: 3" in out and "downloaded: 0" in out and "already_present: 3" in out
    assert len(env.cdn.requests) == downloaded
    # The files of this run are rewritten; the other channel's Markdown goes, its downloaded files stay.
    assert not (root / "channels" / "2bit-terminy.md").exists() and (root / NOTE_PATH).exists()
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    assert [a["status"] for a in manifest["attachments"]] == ["present"] * 3


# --- zip -------------------------------------------------------------------------------------------


def test_zip_has_the_same_content_as_the_folder(capsys, env):
    export(capsys, "--out", "exports/fit")
    code, out, err = export(capsys, "--zip", "exports/fit.zip")
    archive = env.tmp / "exports" / "fit.zip"
    assert (code, err) == (0, "")
    assert out.splitlines()[0] == f"export: {archive}"
    with zipfile.ZipFile(archive) as z:
        zipped = {name: z.read(name) for name in z.namelist()}
        assert z.getinfo(PDF_PATH).compress_type == zipfile.ZIP_STORED
        assert z.getinfo("messages.md").compress_type == zipfile.ZIP_DEFLATED
    assert zipped == files_in(env.tmp / "exports" / "fit")
    assert sorted(p.name for p in (env.tmp / "exports").iterdir()) == ["fit", "fit.zip"]  # no temporary leftovers

    downloaded = len(env.cdn.requests)
    code, out, _ = export(capsys, "--zip", "exports/fit.zip")  # again: files come from the old zip
    assert code == 0 and "already_present: 4" in out and len(env.cdn.requests) == downloaded
    with zipfile.ZipFile(archive) as z:
        assert z.read(PDF_PATH) == content(PDF)
        assert json.loads(z.read("manifest.json"))["counts"]["present"] == 4


# --- options ---------------------------------------------------------------------------------------


def test_no_files(capsys, env):
    code, out, err = export(capsys, "--out", "exports/fit", "--no-files")
    root = env.tmp / "exports" / "fit"
    assert (code, err) == (0, "")
    assert "downloaded: 0" in out and "skipped: 4" in out
    assert env.cdn.requests == [] and not (root / "files").exists()
    assert "- [file] zadanie.pdf 232B https://cdn.discordapp.com/attachments/200/" in (root / "messages.md").read_text(
        encoding="utf-8"
    )
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["query"]["files"] is False
    assert {(a["status"], a["reason"]) for a in manifest["attachments"]} == {("skipped", "--no-files")}


def test_max_file_size(capsys, env):
    big = b"v" * (2 * 1024 * 1024 + 1)
    env.discord.channels["202"] = FakeChannel([message(at(9), "video", attachments=[file(NOTE, "prednaska.mp4", "video/mp4", data=big)])])
    env.serve("202", data={NOTE: big})
    code, out, err = export(capsys, "--out", "exports/fit", "--max-file-size", "2")
    assert code == 0 and "skipped: 1" in out
    assert err == (
        "WARNING: 1 files larger than --max-file-size were not downloaded (use --max-file-size 0 for all):"
        " prednaska.mp4 (2.0MB).\n"
    )
    code, out, err = export(capsys, "--out", "exports/fit", "--max-file-size", "0")
    assert (code, err) == (0, "") and "downloaded: 1" in out and "already_present: 3" in out
    assert (env.tmp / "exports/fit/files/2bit-terminy" / f"{NOTE}_prednaska.mp4").read_bytes() == big


def test_print_puts_messages_on_stdout_and_the_summary_on_stderr(capsys, env):
    code, out, err = export(capsys, "-v", "--out", "exports/fit", "--print")
    assert code == 0
    assert out.startswith("=== VUT FIT / #2bit-general ===\n")
    assert f"\n  [file] zadanie.pdf 232B {PDF_PATH}\n" in out
    assert f"Exported to {env.tmp / 'exports' / 'fit'}: 2 channels, 4 messages, 4 files (4 downloaded," in err
    assert "Downloading 3/3: files/2bit-general/" in err  # --verbose progress
    assert "Downloading 1/1: files/2bit-terminy/" in err
    code, out, _ = export(capsys, "--out", "exports/fit", "--print", "--format", "json")
    assert json.loads(out)["messages"][0]["attachments"][0]["path"] == PDF_PATH


def test_human_mode(capsys, env):
    for target in ("--out", "--zip"):
        with pytest.raises(SystemExit) as e:
            cli.main(["--human", "messages", "-s", FIT, "-c", "200", "-c", "202", target, f"exports/fit-{target[2:]}"])
        captured = capsys.readouterr()
        assert e.value.code == 0
        assert "Export" in captured.out and "already present" in captured.out
    assert (env.tmp / "exports" / "fit-out" / "manifest.json").exists()
    assert zipfile.is_zipfile(env.tmp / "exports" / "fit-zip")


def test_export_dir_setting(capsys, env):
    base = env.tmp / "exporty"
    code, out, _ = run(capsys, "config", "set", "export-dir", str(base))
    assert (code, out) == (0, f"export-dir = {base}\n")
    code, out, _ = export(capsys, "--zip", "fit.zip")  # relative: inside export-dir
    assert code == 0 and out.startswith(f"export: {base / 'fit.zip'}\n")
    code, out, _ = export(capsys, "--out", str(env.tmp / "elsewhere"))  # absolute: as given
    assert code == 0 and (env.tmp / "elsewhere" / "manifest.json").exists()


def test_export_mode_manifest(capsys, env):
    code, out, _ = export(capsys, "--out", "exports/fast-mode", "--fast")
    assert code == 0
    root = env.tmp / "exports" / "fast-mode"
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["query"]["mode"] == "fast"


@pytest.mark.parametrize(
    ("args", "text"),
    [
        (["--out", "notes"], "is not empty and is not a discoop export"),
        (["--zip", "old.zip"], "exists and is not a discoop export"),
        (["--zip", "notes"], "is a folder"),
        (["--out", "old.zip"], "is a file"),
        (["--out", "a", "--zip", "b.zip"], "--out and --zip cannot be used together"),
        (["--print"], "--print only works with --out or --zip"),
        (["--no-files", "--max-file-size", "5"], "--no-files, --max-file-size only work with --out or --zip"),
        (["--out", "x", "--max-file-size", "-1"], "--max-file-size cannot be negative"),
    ],
)
def test_export_targets_are_checked_before_any_request(capsys, env, args, text):
    (env.tmp / "notes").mkdir()
    (env.tmp / "notes" / "todo.txt").write_text("my notes", encoding="utf-8")
    (env.tmp / "old.zip").write_bytes(b"not a zip")
    code, out, err = export(capsys, *args)
    assert (code, out) == (8, "")
    assert err.startswith("ERROR BAD_ARGS") and text in err
    assert sum(env.discord.calls.values()) == 0
    assert sorted(p.name for p in env.tmp.iterdir() if p.name not in ("data", "config")) == ["notes", "old.zip"]
    assert (env.tmp / "notes" / "todo.txt").read_text(encoding="utf-8") == "my notes"


# --- console formats -------------------------------------------------------------------------------


def test_md_and_jsonl_in_the_console(capsys, env):
    code, out, _ = export(capsys, "--format", "md")
    assert code == 0 and out.startswith("# VUT FIT / #2bit-general\n")
    assert "\n- [file] zadanie.pdf 232B https://cdn.discordapp.com/attachments/200/" in out
    assert "\n\n[2026-11-03 10:30] @student_b\npozor\n" in out  # a blank line between messages
    code, out, _ = export(capsys, "--format", "jsonl")
    lines = [json.loads(line) for line in out.splitlines()]
    assert code == 0 and len(lines) == 4
    assert lines[0]["channel"] == {"id": "200", "name": "2bit-general"} and lines[0]["attachments"][0]["path"] is None
    assert env.cdn.requests == []  # the console never downloads files
