"""Tests for resilient export in service, CLI and TUI (R2-A).

Covers:
- Crash in channel 2 of 3 and rerun completes without refetching channel 1 (verifying request counts).
- Ctrl+C (KeyboardInterrupt -> exit code 130) and Cancelled leaves resumable .partial with announcement.
- Exit code 9 (PARTIAL) on skipped channel (console and export) and failed attachment.
- Exit code 0 on --max-file-size skipped files and --no-files.
- Resumed note and accurate overall summary totals.
- Rejection of --print when resuming an export with already saved channels before any API calls.
- Completed export stays untouched after a subsequent interrupted run.
- TUI summary on partial outcome, skipped channels, and interruption (keeps export name).
"""

from datetime import UTC, datetime, timedelta
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
from textual.widgets import Input

from discoop import cli, service
from discoop.api import DiscordAPI
from discoop.attachments import cdn_client
from discoop.cache import Cache
from discoop.directory import Directory
from discoop.errors import DiscoopError, ExitCode
from discoop.models import Channel, Server
from discoop.render import Query
from discoop.snowflake import Window
from discoop.tokenstore import TokenStore
from discoop.tui.app import DiscoopApp
from fake_messages import CET, FIT, NOW, FakeCDN, FakeChannel, FakeDiscord, Network, message, signed_url


def at(hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 11, 3, hour, minute, tzinfo=CET).astimezone(UTC)


@pytest.fixture
def resilient_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    TokenStore.default().save("tok")
    monkeypatch.setattr(cli, "utc_now", lambda: NOW)
    monkeypatch.setattr(cli, "LOCAL_ZONE", CET)
    monkeypatch.chdir(tmp_path)

    msg200 = message(
        at(10),
        "hello 200",
        attachments=[
            {
                "id": "800000000000000001",
                "filename": "assignment.pdf",
                "size": 100,
                "url": signed_url("200", "800000000000000001", "assignment.pdf", expires=NOW + timedelta(hours=24)),
                "content_type": "application/pdf",
            }
        ],
    )
    msg202 = message(
        at(10, 5),
        "hello 202",
        attachments=[
            {
                "id": "800000000000000002",
                "filename": "deadlines.txt",
                "size": 200,
                "url": signed_url("202", "800000000000000002", "deadlines.txt", expires=NOW + timedelta(hours=24)),
                "content_type": "text/plain",
            }
        ],
    )
    msg203 = message(
        at(10, 10),
        "hello 203",
        attachments=[
            {
                "id": "800000000000000003",
                "filename": "info.png",
                "size": 300,
                "url": signed_url("203", "800000000000000003", "info.png", expires=NOW + timedelta(hours=24)),
                "content_type": "image/png",
            }
        ],
    )

    discord = FakeDiscord({
        "200": FakeChannel([msg200]),
        "202": FakeChannel([msg202]),
        "203": FakeChannel([msg203]),
    })
    cdn = FakeCDN()
    cdn.add(msg200["attachments"][0]["url"], b"pdf content " * 10)
    cdn.add(msg202["attachments"][0]["url"], b"txt content " * 10)
    cdn.add(msg203["attachments"][0]["url"], b"png content " * 10)

    network = Network(discord, cdn)
    transport = httpx.MockTransport(network.handle)
    sleeps: list[float] = []

    monkeypatch.setattr(
        cli, "DiscordAPI", lambda token, **kw: DiscordAPI(token, transport=transport, sleep=sleeps.append, **kw)
    )
    monkeypatch.setattr(cli, "cdn_client", lambda: cdn_client(transport))

    def make_api(token: str = "tok", **kw: Any) -> DiscordAPI:
        kw.setdefault("delay", 0.0)
        return DiscordAPI(token, transport=transport, sleep=sleeps.append, **kw)

    return SimpleNamespace(
        discord=discord,
        cdn=cdn,
        network=network,
        sleeps=sleeps,
        tmp=tmp_path,
        msg200=msg200,
        msg202=msg202,
        msg203=msg203,
        transport=transport,
        api=make_api,
    )


def run(capsys: pytest.CaptureFixture, *args: str) -> tuple[int, str, str]:
    with pytest.raises(SystemExit) as exc_info:
        cli.main(["--agent", *args])
    captured = capsys.readouterr()
    return exc_info.value.code, captured.out, captured.err


def test_crash_in_channel_2_and_rerun_resumes_without_refetching_channel_1(
    resilient_env: SimpleNamespace, capsys: pytest.CaptureFixture
) -> None:
    """A crash while fetching channel 2 keeps channel 1 in .partial; rerun fetches only channels 2 and 3."""
    env = resilient_env
    target = env.tmp / "test_export"

    # Make channel 202 fail with HTTP 500
    env.discord.status["202"] = (500, 0)

    code, out, err = run(capsys, "messages", "-s", FIT, "-c", "200", "-c", "202", "-c", "203", "--out", str(target))
    assert code == int(ExitCode.ERROR)
    assert "Saved 1 of 3 channels in" in err
    assert "Run the same command again to continue." in err

    staging = target.with_suffix(".partial")
    assert staging.is_dir()
    manifest_initial = json.loads((staging / "manifest.json").read_text(encoding="utf-8"))
    assert manifest_initial["complete"] is False
    assert manifest_initial["interrupted"] is True
    initial_channel_ids = [item["channel"]["id"] for item in manifest_initial["channels"]]
    assert "200" in initial_channel_ids
    assert "202" not in initial_channel_ids

    # Record requests on channel 200 before resumed run
    ch200_msg_requests_before = len(env.discord.channels["200"].requests)
    cdn_ch200_requests_before = sum(1 for r in env.cdn.requests if "800000000000000001" in r.url.path)
    assert ch200_msg_requests_before >= 1
    assert cdn_ch200_requests_before >= 1

    # Fix channel 202 and rerun
    del env.discord.status["202"]

    code, out, err = run(
        capsys, "-v", "messages", "-s", FIT, "-c", "200", "-c", "202", "-c", "203", "--out", str(target)
    )
    assert code == 0
    assert "Continuing an unfinished export: 1 of 3 channels are already saved." in err

    # Channel 200 messages and files were not fetched again
    assert len(env.discord.channels["200"].requests) == ch200_msg_requests_before
    cdn_ch200_requests_after = sum(1 for r in env.cdn.requests if "800000000000000001" in r.url.path)
    assert cdn_ch200_requests_after == cdn_ch200_requests_before

    # Channels 202 and 203 were fetched
    assert len(env.discord.channels["202"].requests) >= 1
    assert len(env.discord.channels["203"].requests) >= 1

    # Published to target and staging is cleaned up
    assert target.is_dir()
    assert not staging.exists()
    final_manifest = json.loads((target / "manifest.json").read_text(encoding="utf-8"))
    assert final_manifest["complete"] is True
    assert final_manifest["interrupted"] is False
    final_channel_ids = [item["channel"]["id"] for item in final_manifest["channels"]]
    assert set(final_channel_ids) == {"200", "202", "203"}
    assert final_manifest["counts"]["channels"] == 3


def test_keyboard_interrupt_exits_130_and_leaves_resumable_partial(
    resilient_env: SimpleNamespace, capsys: pytest.CaptureFixture
) -> None:
    """Ctrl+C (KeyboardInterrupt) exits with code 130 and leaves a resumable .partial staging folder."""
    env = resilient_env
    target = env.tmp / "export_ctrl_c"

    def raise_keyboard_interrupt(request: httpx.Request) -> httpx.Response:
        raise KeyboardInterrupt()

    env.discord.channels["202"].respond = raise_keyboard_interrupt

    code, out, err = run(capsys, "messages", "-s", FIT, "-c", "200", "-c", "202", "-c", "203", "--out", str(target))
    assert code == 130
    assert "Saved 1 of 3 channels in" in err
    assert "Run the same command again to continue." in err

    staging = target.with_suffix(".partial")
    assert staging.is_dir()
    manifest = json.loads((staging / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["complete"] is False
    assert manifest["interrupted"] is True
    channel_ids = [item["channel"]["id"] for item in manifest["channels"]]
    assert "200" in channel_ids


def test_service_cancelled_leaves_resumable_partial(resilient_env: SimpleNamespace) -> None:
    """Service Cancelled exception closes the writer with complete=False and calls events.interrupted."""
    env = resilient_env
    target = env.tmp / "export_cancelled"

    def raise_cancelled(request: httpx.Request) -> httpx.Response:
        raise service.Cancelled("User cancelled in TUI")

    env.discord.channels["202"].respond = raise_cancelled

    class RecordingEvents(service.Events):
        def __init__(self) -> None:
            super().__init__()
            self.interrupted_called = False
            self.saved = 0
            self.total = 0
            self.path: Path | None = None

        def interrupted(self, saved: int, total: int, path: Path) -> None:
            self.interrupted_called = True
            self.saved = saved
            self.total = total
            self.path = path

    events = RecordingEvents()
    req = service.MessagesRequest(
        channels=("200", "202", "203"),
        server=FIT,
        out_dir=str(target),
    )
    with Cache.default() as cache, Directory(cache, env.api) as directory:
        with pytest.raises(service.Cancelled):
            service.run_messages(
                req,
                directory=directory,
                cdn=lambda: cdn_client(env.transport),
                now=NOW,
                tz=CET,
                events=events,
            )

    assert events.interrupted_called
    assert events.saved == 1
    assert events.total == 3
    assert events.path == target.with_suffix(".partial")
    assert events.path.is_dir()


def test_partial_exit_code_on_skipped_channel_console(
    resilient_env: SimpleNamespace, capsys: pytest.CaptureFixture
) -> None:
    """Skipping an inaccessible channel in console mode returns exit code 9 (PARTIAL)."""
    env = resilient_env
    env.discord.status["202"] = 403  # NO_ACCESS

    code, out, err = run(capsys, "-v", "messages", "-s", FIT, "-c", "200", "-c", "202")
    assert code == int(ExitCode.PARTIAL)
    assert "WARNING: Skipped: No access to the messages of #2bit-terminy (202) in VUT FIT." in err
    assert "Partial result (exit code 9): 1 channel skipped. Run the same command again to try them again." in err


def test_partial_exit_code_on_skipped_channel_export(
    resilient_env: SimpleNamespace, capsys: pytest.CaptureFixture
) -> None:
    """Skipping an inaccessible channel in export mode returns exit code 9 and writes manifest with skipped channels."""
    env = resilient_env
    target = env.tmp / "export_skipped"
    env.discord.status["202"] = 403  # NO_ACCESS

    code, out, err = run(capsys, "-v", "messages", "-s", FIT, "-c", "200", "-c", "202", "--out", str(target))
    assert code == int(ExitCode.PARTIAL)
    assert target.is_dir()

    manifest = json.loads((target / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["complete"] is True
    assert manifest["partial"] is True
    channel_ids = [item["channel"]["id"] for item in manifest["channels"]]
    assert channel_ids == ["200"]
    assert len(manifest["skipped_channels"]) == 1
    assert manifest["skipped_channels"][0]["id"] == "202"
    assert manifest["skipped_channels"][0]["reason"] == "no_access"

    assert "Partial result (exit code 9): 1 channel skipped." in err
    assert "files already saved are not downloaded again." in err


def test_partial_exit_code_on_failed_attachment(
    resilient_env: SimpleNamespace, capsys: pytest.CaptureFixture
) -> None:
    """A failed attachment download returns exit code 9 (PARTIAL) and manifest marks file failed."""
    env = resilient_env
    target = env.tmp / "export_failed_attachment"
    # Make attachment 404 on CDN
    env.cdn.missing.add(httpx.URL(env.msg200["attachments"][0]["url"]).path)

    code, out, err = run(capsys, "-v", "messages", "-s", FIT, "-c", "200", "--out", str(target))
    assert code == int(ExitCode.PARTIAL)
    assert target.is_dir()

    manifest = json.loads((target / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["complete"] is True
    assert manifest["partial"] is True
    assert manifest["counts"]["failed"] == 1

    assert "Partial result (exit code 9): 1 file not downloaded." in err
    assert "1 of 1 files could not be downloaded" in err


def test_exit_code_0_on_max_file_size_and_no_files(
    resilient_env: SimpleNamespace, capsys: pytest.CaptureFixture
) -> None:
    """Files skipped deliberately via --max-file-size or --no-files exit with code 0 (not 9)."""
    env = resilient_env

    # 1. --max-file-size
    target_size = env.tmp / "export_size"
    code, out, err = run(
        capsys, "messages", "-s", FIT, "-c", "200", "--out", str(target_size), "--max-file-size", "0.00001"
    )
    assert code == 0
    assert "files larger than --max-file-size were not downloaded" in err
    manifest_size = json.loads((target_size / "manifest.json").read_text(encoding="utf-8"))
    assert manifest_size["partial"] is False
    assert manifest_size["counts"]["skipped"] == 1

    # 2. --no-files
    target_nofiles = env.tmp / "export_nofiles"
    code, out, err = run(capsys, "messages", "-s", FIT, "-c", "200", "--out", str(target_nofiles), "--no-files")
    assert code == 0
    manifest_nofiles = json.loads((target_nofiles / "manifest.json").read_text(encoding="utf-8"))
    assert manifest_nofiles["partial"] is False


def test_resume_note_and_accurate_summary_totals(
    resilient_env: SimpleNamespace, capsys: pytest.CaptureFixture
) -> None:
    """Summary totals after resuming reflect the full export from manifest, not only newly fetched channels."""
    env = resilient_env
    target = env.tmp / "export_summary_totals"

    # Interrupt on channel 202
    env.discord.status["202"] = (500, 0)
    run(capsys, "messages", "-s", FIT, "-c", "200", "-c", "202", "-c", "203", "--out", str(target))
    del env.discord.status["202"]

    # Resume with -v to capture notes
    code, out, err = run(
        capsys, "-v", "messages", "-s", FIT, "-c", "200", "-c", "202", "-c", "203", "--out", str(target)
    )
    assert code == 0
    assert "Continuing an unfinished export: 1 of 3 channels are already saved." in err

    # Summary key-value lines include all 3 channels and all 3 files
    lines = [line.strip() for line in out.splitlines()]
    assert "channels: 3" in lines
    assert "messages: 3" in lines
    assert "files: 3" in lines
    assert "downloaded: 3" in lines


def test_resume_with_print_rejected_before_api(
    resilient_env: SimpleNamespace, capsys: pytest.CaptureFixture
) -> None:
    """When resuming an export with already saved channels, --print is rejected before any API calls."""
    env = resilient_env
    target = env.tmp / "export_print_rejected"

    # Save channel 200 into staging
    env.discord.status["202"] = (500, 0)
    run(capsys, "messages", "-s", FIT, "-c", "200", "-c", "202", "--out", str(target))
    del env.discord.status["202"]

    # Reset API call counter
    env.discord.calls.clear()

    # Rerun with --print
    code, out, err = run(capsys, "messages", "-s", FIT, "-c", "200", "-c", "202", "--out", str(target), "--print")
    assert code == int(ExitCode.BAD_ARGS)
    assert "--print cannot be used while continuing an unfinished export" in err
    assert "1 of 2 channels were saved by the run that was interrupted" in err

    # Zero Discord API calls were made
    assert sum(env.discord.calls.values()) == 0


def test_finished_export_untouched_on_subsequent_interrupted_run(
    resilient_env: SimpleNamespace, capsys: pytest.CaptureFixture
) -> None:
    """An existing finished export is never damaged or touched if a subsequent run targeting it is interrupted."""
    env = resilient_env
    target = env.tmp / "export_untouched"

    # Complete an export
    code, out, err = run(capsys, "messages", "-s", FIT, "-c", "200", "--out", str(target))
    assert code == 0
    assert target.is_dir()

    snapshot = {p.relative_to(target).as_posix(): p.read_bytes() for p in target.rglob("*") if p.is_file()}
    assert "manifest.json" in snapshot
    assert "messages.md" in snapshot

    # Subsequent run targeting the same folder with 3 channels, interrupted on channel 202
    env.discord.status["202"] = (500, 0)
    code, out, err = run(capsys, "messages", "-s", FIT, "-c", "200", "-c", "202", "-c", "203", "--out", str(target))
    assert code == int(ExitCode.ERROR)

    # All files in the finished export are 100% untouched
    current_files = {p.relative_to(target).as_posix(): p.read_bytes() for p in target.rglob("*") if p.is_file()}
    assert current_files == snapshot


@pytest.mark.asyncio
async def test_tui_summary_on_partial_skipped_and_interrupted(resilient_env: SimpleNamespace) -> None:
    """TUI logs skipped channels, partial advice with F5, keeps export name on interrupted and partial."""
    env = resilient_env
    app = DiscoopApp(api_factory=env.api)
    async with app.run_test(size=(140, 40)) as pilot:
        # Wait for startup to finish
        while app.cancel_token is not None:
            await pilot.pause(0.02)

        # 1. Interrupted event handling
        app._export_jobs = [
            SimpleNamespace(
                request=SimpleNamespace(out_dir="exports/discord-export-2026-1104-1200", zip_file=None),
                total=1,
                number=1,
            )
        ]
        app._handle_bridge_event("interrupted", {
            "saved": 2,
            "total": 5,
            "path": Path("exports/discord-export-2026-1104-1200.partial"),
        })

        log_lines = "\n".join(strip.text for strip in app.query_one("#event-log").lines)
        assert "Saved 2 of 5 channels in" in log_lines
        assert "Press F5 to start the same export again and continue." in log_lines
        assert app.query_one("#input-name", Input).value == "discord-export-2026-1104-1200"

        # 2. Partial export with skipped channel
        srv = Server(FIT, "VUT FIT", 5000)
        ch_skipped = Channel("202", FIT, "2bit-terminy", 0)
        outcome = service.MessagesOutcome(
            results=[],
            skipped=[DiscoopError(ExitCode.NO_ACCESS, "No access to the messages of #2bit-terminy (202) in VUT FIT.")],
            exported=None,
            query=Query(Window(NOW - timedelta(days=1), NOW), None, 5000, False),
            skipped_channels=[ch_skipped],
        )
        assert outcome.partial is True

        app._export_finished([outcome], preview_format=None)
        log_lines = "\n".join(strip.text for strip in app.query_one("#event-log").lines)
        assert "Not exported: #2bit-terminy (no access)." in log_lines
        assert "The result is partial. Press F5 to start the same export again" in log_lines
