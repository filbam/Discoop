"""Tests for TUI state management, job planning, bridge, and event dispatch."""

from datetime import timedelta
from pathlib import Path
import threading
import time
from typing import Any

import httpx
import pytest

from discoop import service
from discoop.api import DiscordAPI
from discoop.cache import Cache
from discoop.directory import Directory
from discoop.errors import DiscoopError, ExitCode
from discoop.models import CATEGORY, Channel, Server
from discoop.tui.bridge import CancelToken, Cancelled, TuiEvents
from discoop.tui.state import (
    ExportSettings,
    PlannedJob,
    SelectionState,
    WindowSpec,
    filter_channels,
    plan_jobs,
)
from fake_messages import CET, FIT, NOW, FakeChannel, FakeDiscord, Network, series


def test_window_spec_slug() -> None:
    # Default window: 7d
    assert WindowSpec().slug() == "7d"

    # Last only
    assert WindowSpec(from_=None, to=None, last=50).slug() == "last-50"

    # Explicit date range
    assert WindowSpec(from_="2026-10-01", to="2026-10-31").slug() == "2026-10-01_2026-10-31"

    # Explicit date range with last
    assert (
        WindowSpec(from_="2026-10-01", to="2026-10-31", last=20).slug()
        == "2026-10-01_2026-10-31_last-20"
    )

    # When to="now", "now" is omitted from the slug
    assert WindowSpec(from_="7d", to="now").slug() == "7d"
    assert WindowSpec(from_="2026-10-01", to="now", last=10).slug() == "2026-10-01_last-10"

    # Without from, --last means the whole history; to="now" is an open end
    assert WindowSpec(from_=None, to="now", last=50).slug() == "last-50"
    assert WindowSpec(from_=None, to="2026-10-31", last=5).slug() == "all_2026-10-31_last-5"
    assert WindowSpec(from_=None, to="2026-10-31").slug() == "24h_2026-10-31"
    assert WindowSpec(from_=None, to=None).slug() == "24h"

    # Sanitization of forbidden path characters
    assert (
        WindowSpec(from_="2026/10/01", to="2026/10/31").slug()
        == "2026_10_01_2026_10_31"
    )


def test_window_spec_label() -> None:
    # Default window
    assert WindowSpec().label() == "7d → now"

    # Last only
    assert WindowSpec(from_=None, to=None, last=50).label() == "last 50"

    # Date range
    assert WindowSpec(from_="2026-10-01", to="2026-10-31").label() == "2026-10-01 → 2026-10-31"

    # Date range with last
    assert (
        WindowSpec(from_="2026-10-01", to="2026-10-31", last=20).label()
        == "2026-10-01 → 2026-10-31 (last 20)"
    )

    # No from: 24h, or the whole history with last
    assert WindowSpec(from_=None, to=None).label() == "24h → now"
    assert WindowSpec(from_=None, to="now", last=50).label() == "last 50"
    assert WindowSpec(from_=None, to="2026-10-31", last=5).label() == "all → 2026-10-31 (last 5)"

    # All to now
    assert WindowSpec(from_="all", to=None).label() == "all → now"


def test_selection_state_toggle_and_selectability() -> None:
    server = Server(id="s1", name="Server 1")
    text_ch = Channel(id="c1", server_id="s1", name="general", type=0)
    category_ch = Channel(id="c2", server_id="s1", name="Chat", type=4)  # CATEGORY
    forum_ch = Channel(id="c3", server_id="s1", name="feedback", type=15)  # forum (not in MESSAGE_TYPES)
    voice_ch = Channel(id="c4", server_id="s1", name="Lobby", type=2)  # voice (in MESSAGE_TYPES)

    state = SelectionState()

    # Category and forum are not selectable
    assert not state.is_selectable(category_ch)
    assert not state.is_selectable(forum_ch)
    assert state.is_selectable(text_ch)
    assert state.is_selectable(voice_ch)

    # Toggling unselectable channel returns False and does not select it
    assert not state.toggle(server, category_ch)
    assert not state.is_selected("c2")
    assert not state.toggle(server, forum_ch)
    assert not state.is_selected("c3")

    # Toggling selectable channel selects it
    assert state.toggle(server, text_ch)
    assert state.is_selected("c1")
    assert state.selected["c1"] == (server, text_ch)

    # Toggling selected channel deselects it
    assert not state.toggle(server, text_ch)
    assert not state.is_selected("c1")
    assert "c1" not in state.selected


def test_selection_state_select_many_and_deselect() -> None:
    server = Server(id="s1", name="Server 1")
    c1 = Channel(id="c1", server_id="s1", name="general", type=0)
    c2 = Channel(id="c2", server_id="s1", name="random", type=0)
    cat = Channel(id="cat1", server_id="s1", name="Category", type=CATEGORY)

    state = SelectionState()
    # select_many only selects selectable channels and returns count of newly added
    added = state.select_many(server, [c1, c2, cat])
    assert added == 2
    assert state.is_selected("c1")
    assert state.is_selected("c2")
    assert not state.is_selected("cat1")

    # Calling select_many again with already-selected channels returns 0
    assert state.select_many(server, [c1, c2]) == 0

    # Deselect many
    state.deselect_many(["c1"])
    assert not state.is_selected("c1")
    assert state.is_selected("c2")


def test_selection_state_custom_windows() -> None:
    server = Server(id="s1", name="Server 1")
    c1 = Channel(id="c1", server_id="s1", name="general", type=0)

    state = SelectionState()
    state.toggle(server, c1)

    # Initial window is global
    assert state.window_for("c1") == state.global_window
    assert not state.has_custom_window("c1")

    # Set custom window
    custom = WindowSpec(from_="30d", last=100)
    state.set_custom_window("c1", custom)
    assert state.window_for("c1") == custom
    assert state.has_custom_window("c1")

    # Setting custom window equal to global removes it
    state.set_custom_window("c1", state.global_window)
    assert not state.has_custom_window("c1")
    assert state.window_for("c1") == state.global_window

    # Set custom window again, then deselect channel removes custom window
    state.set_custom_window("c1", custom)
    assert state.has_custom_window("c1")
    state.toggle(server, c1)  # deselect
    assert not state.has_custom_window("c1")


def test_selection_state_clear_server_and_clear_all() -> None:
    s1 = Server(id="s1", name="Server 1")
    s2 = Server(id="s2", name="Server 2")
    c1 = Channel(id="c1", server_id="s1", name="c1", type=0)
    c2 = Channel(id="c2", server_id="s1", name="c2", type=0)
    c3 = Channel(id="c3", server_id="s2", name="c3", type=0)

    state = SelectionState()
    state.toggle(s1, c1)
    state.toggle(s1, c2)
    state.toggle(s2, c3)
    state.set_custom_window("c1", WindowSpec(last=10))

    assert len(state.selected) == 3
    state.clear_server("s1")

    assert not state.is_selected("c1")
    assert not state.is_selected("c2")
    assert not state.has_custom_window("c1")
    assert state.is_selected("c3")

    state.clear_all()
    assert len(state.selected) == 0
    assert len(state.custom_windows) == 0


def test_plan_jobs_empty_selection() -> None:
    state = SelectionState()
    settings = ExportSettings()
    assert plan_jobs(state, settings) == []


def test_plan_jobs_single_job_same_server() -> None:
    server = Server(id="srv-100", name="Guild One")
    c1 = Channel(id="ch-1", server_id="srv-100", name="general", type=0)
    c2 = Channel(id="ch-2", server_id="srv-100", name="random", type=0)

    state = SelectionState()
    state.toggle(server, c1)
    state.toggle(server, c2)

    settings = ExportSettings(target="folder", path="exports/my-test-export")
    jobs = plan_jobs(state, settings)

    assert len(jobs) == 1
    job = jobs[0]
    assert isinstance(job, PlannedJob)
    assert job.number == 1
    assert job.total == 1
    assert job.window == state.global_window
    assert job.targets == ((server, c1), (server, c2))
    assert job.request.server == "srv-100"
    assert job.request.channels == ("ch-1", "ch-2")
    assert job.request.out_dir == "exports/my-test-export"
    assert job.request.zip_file is None
    assert not job.request.print_messages


def test_plan_jobs_single_job_cross_servers() -> None:
    s1 = Server(id="srv-1", name="Guild 1")
    s2 = Server(id="srv-2", name="Guild 2")
    c1 = Channel(id="ch-1", server_id="srv-1", name="announcements", type=0)
    c2 = Channel(id="ch-2", server_id="srv-2", name="general", type=0)

    state = SelectionState()
    state.toggle(s1, c1)
    state.toggle(s2, c2)

    settings = ExportSettings(target="folder", path="exports/cross")
    jobs = plan_jobs(state, settings)

    assert len(jobs) == 1
    job = jobs[0]
    assert job.request.server is None
    assert job.request.channels == ("ch-1", "ch-2")
    assert job.request.out_dir == "exports/cross"


def test_plan_jobs_multiple_jobs_folder_and_zip() -> None:
    s1 = Server(id="srv-1", name="Guild 1")
    c1 = Channel(id="ch-1", server_id="srv-1", name="general", type=0)
    c2 = Channel(id="ch-2", server_id="srv-1", name="random", type=0)
    c3 = Channel(id="ch-3", server_id="srv-1", name="archive", type=0)

    state = SelectionState()
    state.toggle(s1, c1)
    state.toggle(s1, c2)
    state.toggle(s1, c3)

    # 2 channels with global window 7d, 1 channel with custom window 2026-10-01..2026-10-31
    custom_win = WindowSpec(from_="2026-10-01", to="2026-10-31")
    state.set_custom_window("ch-3", custom_win)

    # 1. Folder target
    folder_settings = ExportSettings(target="folder", path="exports/discoop-export")
    folder_jobs = plan_jobs(state, folder_settings)
    assert len(folder_jobs) == 2

    job1, job2 = folder_jobs
    assert job1.number == 1
    assert job1.total == 2
    assert job1.window.slug() == "7d"
    assert job1.request.channels == ("ch-1", "ch-2")
    assert job1.request.out_dir == "exports/discoop-export/01-7d"
    assert job1.request.zip_file is None

    assert job2.number == 2
    assert job2.total == 2
    assert job2.window.slug() == "2026-10-01_2026-10-31"
    assert job2.request.channels == ("ch-3",)
    assert job2.request.out_dir == "exports/discoop-export/02-2026-10-01_2026-10-31"
    assert job2.request.zip_file is None

    # 2. Zip target
    zip_settings = ExportSettings(target="zip", path="exports/discoop-export.zip")
    zip_jobs = plan_jobs(state, zip_settings)
    assert len(zip_jobs) == 2

    zjob1, zjob2 = zip_jobs
    assert zjob1.request.out_dir is None
    assert zjob1.request.zip_file == "exports/discoop-export-01-7d.zip"

    assert zjob2.request.out_dir is None
    assert zjob2.request.zip_file == "exports/discoop-export-02-2026-10-01_2026-10-31.zip"


def _fake_api_factory(channels: dict[str, FakeChannel]):
    transport = httpx.MockTransport(Network(FakeDiscord(channels), None).handle)

    def api_factory(token: str | None = None, **kw: Any) -> DiscordAPI:
        kw.setdefault("delay", 0.0)
        return DiscordAPI("test-token", transport=transport, **kw)

    return api_factory


def test_plan_jobs_preview_target() -> None:
    s1 = Server(id="srv-1", name="Guild 1")
    c1 = Channel(id="ch-1", server_id="srv-1", name="general", type=0)
    state = SelectionState()
    state.toggle(s1, c1)

    jobs = plan_jobs(state, ExportSettings(target="preview", preview_format="jsonl", files=False, max_file_size=5.0))

    assert len(jobs) == 1
    request = jobs[0].request
    assert request.out_dir is None
    assert request.zip_file is None
    assert request.print_messages is False
    assert request.no_files is False
    assert request.max_file_size is None
    assert request.output_format == "jsonl"
    assert request.to_argv()[-2:] == ["--format", "jsonl"]
    # The same combination of options that the CLI accepts: console output only.
    assert (
        service.validate_export_target(
            request.out_dir, request.zip_file, request.print_messages, request.no_files, request.max_file_size
        )
        is None
    )


def test_plan_jobs_preview_runs_through_service() -> None:
    server = Server(FIT, "VUT FIT", 5000)
    channel = Channel("200", FIT, "2bit-general", 0, None, 0)
    api_factory = _fake_api_factory({"200": FakeChannel(series(3, newest=NOW, step=timedelta(minutes=5)))})

    with Cache.default() as cache:
        cache.replace_servers([server])
        cache.replace_channels(FIT, [channel])

    state = SelectionState()
    state.toggle(server, channel)
    jobs = plan_jobs(state, ExportSettings(target="preview", preview_format="md"))

    emitted: list[str] = []
    events = TuiEvents(CancelToken(), lambda name, payload: emitted.append(name))
    with Cache.default() as cache, Directory(cache, api_factory) as directory:
        outcome = service.run_messages(jobs[0].request, directory=directory, now=NOW, tz=CET, events=events)

    assert outcome.exported is None
    assert len(outcome.results) == 1
    assert outcome.results[0].messages
    assert emitted[0] == "channel_start"
    assert emitted[-1] == "channel_done"


def test_plan_jobs_paths_and_suffixes() -> None:
    s1 = Server(id="srv-1", name="Guild 1")
    c1 = Channel(id="ch-1", server_id="srv-1", name="a", type=0)
    c2 = Channel(id="ch-2", server_id="srv-1", name="b", type=0)
    state = SelectionState()
    state.toggle(s1, c1)
    state.toggle(s1, c2)
    state.set_custom_window("ch-2", WindowSpec(from_="30d"))

    # Trailing slashes of both kinds do not double up.
    out = [j.request.out_dir for j in plan_jobs(state, ExportSettings(target="folder", path="out\\sub\\"))]
    assert out == ["out\\sub/01-7d", "out\\sub/02-30d"]
    out = [j.request.out_dir for j in plan_jobs(state, ExportSettings(target="folder", path="out/"))]
    assert out == ["out/01-7d", "out/02-30d"]

    # An upper-case suffix counts as a zip name and no second .zip is added.
    zips = [j.request.zip_file for j in plan_jobs(state, ExportSettings(target="zip", path="out/Run.ZIP"))]
    assert zips == ["out/Run-01-7d.zip", "out/Run-02-30d.zip"]
    single = SelectionState()
    single.toggle(s1, c1)
    assert plan_jobs(single, ExportSettings(target="zip", path="out/Run.ZIP"))[0].request.zip_file == "out/Run.ZIP"
    assert plan_jobs(single, ExportSettings(target="zip", path="out/Run"))[0].request.zip_file == "out/Run.zip"

    # A path that names a folder gets a file name instead of a hidden ".zip".
    assert plan_jobs(single, ExportSettings(target="zip", path="out/"))[0].request.zip_file == "out/discoop-export.zip"

    # Blank path falls back to the default.
    assert plan_jobs(single, ExportSettings(target="folder", path="  "))[0].request.out_dir == "exports/discoop-export"


def test_set_custom_window_follows_global_window_changes() -> None:
    server = Server(id="s1", name="Server 1")
    c1 = Channel(id="c1", server_id="s1", name="general", type=0)
    state = SelectionState()
    state.toggle(server, c1)

    # A window equal to the global one is not stored: the channel keeps following the global window.
    state.set_custom_window("c1", WindowSpec())
    state.global_window = WindowSpec(from_="30d")
    assert state.window_for("c1") == WindowSpec(from_="30d")
    assert not state.has_custom_window("c1")

    # A stored custom window stays when the global one changes; None removes it.
    state.set_custom_window("c1", WindowSpec(from_="1d"))
    state.global_window = WindowSpec(from_="3d")
    assert state.window_for("c1") == WindowSpec(from_="1d")
    state.set_custom_window("c1", None)
    assert state.window_for("c1") == WindowSpec(from_="3d")


def test_filter_channels() -> None:
    cat1 = Channel(id="10", server_id="s1", name="Information", type=CATEGORY)
    c1 = Channel(id="11", server_id="s1", name="přípravné-kurzy🔒", type=0, parent_id="10")
    c2 = Channel(id="12", server_id="s1", name="rules", type=0, parent_id="10")

    cat2 = Channel(id="20", server_id="s1", name="Community Hub", type=CATEGORY)
    c3 = Channel(id="21", server_id="s1", name="general-chat", type=0, parent_id="20")
    c4 = Channel(id="22", server_id="s1", name="gaming", type=0, parent_id="20")

    all_channels = [cat1, c1, c2, cat2, c3, c4]

    # Empty query returns full list
    assert filter_channels(all_channels, "") == all_channels
    assert filter_channels(all_channels, "   ") == all_channels

    # Diacritics/emoji insensitivity: 'pripravne' matches 'přípravné-kurzy🔒' and keeps parent category
    filtered = filter_channels(all_channels, "pripravne")
    assert filtered == [cat1, c1]

    # ID match: the whole '22' matches 'gaming' and keeps parent 'Community Hub', a part of an ID matches nothing
    filtered_id = filter_channels(all_channels, "22")
    assert filtered_id == [cat2, c4]
    assert filter_channels(all_channels, "2") == []

    # Category name match: 'community' matches category and includes ALL child channels
    filtered_cat = filter_channels(all_channels, "community")
    assert filtered_cat == [cat2, c3, c4]

    # A channel without a category matches alone and is not pulled in by an unrelated category
    loose = Channel(id="30", server_id="s1", name="community-loose", type=0)
    with_loose = [*all_channels, loose]
    assert filter_channels(with_loose, "loose") == [loose]
    assert filter_channels(with_loose, "community") == [cat2, c3, c4, loose]
    assert filter_channels(with_loose, "nothing-here") == []


def test_cancel_token_basics_and_multithreading() -> None:
    token = CancelToken()
    assert not token.is_cancelled

    token.check()  # should not raise
    token.sleep(0.01)  # should not raise

    token.cancel()
    assert token.is_cancelled

    with pytest.raises(Cancelled, match="Stopped by user."):
        token.check()

    with pytest.raises(Cancelled, match="Stopped by user."):
        token.sleep(1.0)

    # Multithreading cancellation test: sleep should wake immediately when cancel is called
    fresh_token = CancelToken()
    started = threading.Event()
    raised_cancelled = threading.Event()
    duration: list[float] = []

    def sleeper() -> None:
        started.set()
        t0 = time.monotonic()
        try:
            fresh_token.sleep(5.0)
        except Cancelled:
            duration.append(time.monotonic() - t0)
            raised_cancelled.set()

    thread = threading.Thread(target=sleeper, daemon=True)
    thread.start()
    started.wait(timeout=1.0)
    time.sleep(0.05)
    fresh_token.cancel()
    thread.join(timeout=1.0)

    assert raised_cancelled.is_set()
    assert len(duration) == 1
    # Should have woken up almost immediately (well under the 5.0s timeout)
    assert duration[0] < 0.5


def test_tui_events_and_cancellation() -> None:
    token = CancelToken()
    emitted: list[tuple[str, dict]] = []

    def emit(name: str, payload: dict) -> None:
        emitted.append((name, payload))

    events = TuiEvents(token, emit)
    server = Server(id="srv-1", name="Guild")
    channel = Channel(id="ch-1", server_id="srv-1", name="general", type=0)

    events.channel_start(2, 3, server, channel)
    assert emitted[-1] == ("channel_start", {"index": 2, "total": 3, "server": server, "channel": channel})

    events.page(15, 987654321)
    assert emitted[-1] == ("page", {"count": 15, "oldest_id": 987654321})

    events.pause(1.5, "reading pause")
    assert emitted[-1] == ("pause", {"seconds": 1.5, "reason": "reading pause"})

    result = service.ChannelMessages(server, channel, (), False)
    events.channel_done(result)
    assert emitted[-1] == ("channel_done", {"result": result})

    error = DiscoopError(ExitCode.NO_ACCESS, "No access to #general.")
    events.skipped(error)
    assert emitted[-1] == ("skipped", {"error": error, "reason": "No access to #general."})

    events.warning("Warning text")
    assert emitted[-1] == ("warning", {"message": "Warning text"})

    events.note("Note text")
    assert emitted[-1] == ("note", {"text": "Note text"})

    # Download progress emissions; the service reaches them through events.downloads
    events.downloads.start(10, 50000)
    assert emitted[-1] == ("dl_start", {"files": 10, "total_bytes": 50000})

    events.downloads.file(3, 10, "job")
    assert emitted[-1] == ("dl_file", {"number": 3, "total": 10, "job": "job"})

    events.downloads.advance(1024)
    assert emitted[-1] == ("dl_advance", {"size": 1024})

    events.downloads.note("Refreshing 2 expired file URLs")
    assert emitted[-1] == ("note", {"text": "Refreshing 2 expired file URLs"})

    events.downloads.finish()
    assert emitted[-1] == ("dl_finish", {})

    # When the token is cancelled, progress callbacks raise Cancelled
    token.cancel()

    with pytest.raises(Cancelled):
        events.page(20, 123)

    with pytest.raises(Cancelled):
        events.channel_start(1, 1, server, channel)

    with pytest.raises(Cancelled):
        events.pause(1.0, "rate limit")

    with pytest.raises(Cancelled):
        events.downloads.start(1, 100)

    with pytest.raises(Cancelled):
        events.downloads.file(1, 1, "job")

    with pytest.raises(Cancelled):
        events.downloads.advance(100)

    # finish runs in a `finally` of the downloader and must not replace the original error
    events.downloads.finish()
    assert emitted[-1] == ("dl_finish", {})


def test_cancel_between_channels_writes_nothing(tmp_path: Path) -> None:
    server = Server(FIT, "VUT FIT", 5000)
    channels = [Channel("200", FIT, "one", 0, None, 0), Channel("201", FIT, "two", 0, None, 1)]
    api_factory = _fake_api_factory(
        {c.id: FakeChannel(series(2, newest=NOW, step=timedelta(minutes=5))) for c in channels}
    )
    with Cache.default() as cache:
        cache.replace_servers([server])
        cache.replace_channels(FIT, channels)

    token = CancelToken()

    def emit(name: str, payload: dict) -> None:
        if name == "channel_done":
            token.cancel()

    state = SelectionState()
    for channel in channels:
        state.toggle(server, channel)
    target = tmp_path / "out" / "run.zip"
    jobs = plan_jobs(state, ExportSettings(target="zip", path=str(target)))

    with Cache.default() as cache, Directory(cache, api_factory) as directory:
        with pytest.raises(Cancelled):
            service.run_messages(jobs[0].request, directory=directory, now=NOW, tz=CET, events=TuiEvents(token, emit))

    # Cancelled during fetching: nothing was exported, not even a partial zip.
    assert not target.exists()
    assert not list(tmp_path.rglob("*.part"))
