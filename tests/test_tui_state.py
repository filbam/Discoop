"""Tests for TUI state management, job planning, bridge, and event dispatch."""

from datetime import datetime, timedelta
import os
from pathlib import Path
import threading
import time
from typing import Any
import zipfile

import httpx
import pytest

from discoop import paths, service
from discoop.api import DiscordAPI
from discoop.cache import Cache
from discoop.config import Config
from discoop.directory import Directory
from discoop.errors import DiscoopError, ExitCode
from discoop.models import CATEGORY, Channel, Server
from discoop.tui.bridge import CancelToken, Cancelled, TuiEvents
from discoop.tui.state import (
    ExportSettings,
    PlannedJob,
    SelectionState,
    WindowSpec,
    default_folder,
    default_name,
    export_folder,
    export_stamp,
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
    forum_ch = Channel(id="c3", server_id="s1", name="feedback", type=15)  # forum (FORUM_TYPES: its posts are threads)
    voice_ch = Channel(id="c4", server_id="s1", name="Lobby", type=2)  # voice (in MESSAGE_TYPES)
    media_ch = Channel(id="c5", server_id="s1", name="gallery", type=16)  # media (FORUM_TYPES)
    directory_ch = Channel(id="c6", server_id="s1", name="hall", type=14)  # directory: nothing to download

    state = SelectionState()

    # A category and a directory channel are not selectable, forums and media channels are
    assert not state.is_selectable(category_ch)
    assert not state.is_selectable(directory_ch)
    assert state.is_selectable(forum_ch)
    assert state.is_selectable(media_ch)
    assert state.is_selectable(text_ch)
    assert state.is_selectable(voice_ch)

    # Toggling unselectable channel returns False and does not select it
    assert not state.toggle(server, category_ch)
    assert not state.is_selected("c2")
    assert not state.toggle(server, directory_ch)
    assert not state.is_selected("c6")

    # A forum and a media channel are toggled like any other channel
    assert state.toggle(server, forum_ch)
    assert state.toggle(server, media_ch)
    assert state.is_selected("c3") and state.is_selected("c5")
    assert not state.toggle(server, forum_ch)
    assert not state.toggle(server, media_ch)
    assert not state.selected

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


def test_plan_jobs_single_job_same_server(tmp_path: Path) -> None:
    server = Server(id="srv-100", name="Guild One")
    c1 = Channel(id="ch-1", server_id="srv-100", name="general", type=0)
    c2 = Channel(id="ch-2", server_id="srv-100", name="random", type=0)

    state = SelectionState()
    state.toggle(server, c1)
    state.toggle(server, c2)

    settings = ExportSettings(target="folder", folder=str(tmp_path / "exports"), name="my-test-export")
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
    assert job.request.out_dir == (tmp_path / "exports" / "my-test-export").as_posix()
    assert job.request.zip_file is None
    assert not job.request.print_messages


def test_plan_jobs_single_job_cross_servers(tmp_path: Path) -> None:
    s1 = Server(id="srv-1", name="Guild 1")
    s2 = Server(id="srv-2", name="Guild 2")
    c1 = Channel(id="ch-1", server_id="srv-1", name="announcements", type=0)
    c2 = Channel(id="ch-2", server_id="srv-2", name="general", type=0)

    state = SelectionState()
    state.toggle(s1, c1)
    state.toggle(s2, c2)

    settings = ExportSettings(target="folder", folder=str(tmp_path), name="cross")
    jobs = plan_jobs(state, settings)

    assert len(jobs) == 1
    job = jobs[0]
    assert job.request.server is None
    assert job.request.channels == ("ch-1", "ch-2")
    assert job.request.out_dir == (tmp_path / "cross").as_posix()


def test_plan_jobs_multiple_jobs_folder_and_zip(tmp_path: Path) -> None:
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
    base = (tmp_path / "exports").as_posix()
    folder_settings = ExportSettings(target="folder", folder=str(tmp_path / "exports"), name="discoop-export")
    folder_jobs = plan_jobs(state, folder_settings)
    assert len(folder_jobs) == 2

    job1, job2 = folder_jobs
    assert job1.number == 1
    assert job1.total == 2
    assert job1.window.slug() == "7d"
    assert job1.request.channels == ("ch-1", "ch-2")
    assert job1.request.out_dir == f"{base}/discoop-export/01-7d"
    assert job1.request.zip_file is None

    assert job2.number == 2
    assert job2.total == 2
    assert job2.window.slug() == "2026-10-01_2026-10-31"
    assert job2.request.channels == ("ch-3",)
    assert job2.request.out_dir == f"{base}/discoop-export/02-2026-10-01_2026-10-31"
    assert job2.request.zip_file is None

    # 2. Zip target
    zip_settings = ExportSettings(target="zip", folder=str(tmp_path / "exports"), name="discoop-export.zip")
    zip_jobs = plan_jobs(state, zip_settings)
    assert len(zip_jobs) == 2

    zjob1, zjob2 = zip_jobs
    assert zjob1.request.out_dir is None
    assert zjob1.request.zip_file == f"{base}/discoop-export-01-7d.zip"

    assert zjob2.request.out_dir is None
    assert zjob2.request.zip_file == f"{base}/discoop-export-02-2026-10-01_2026-10-31.zip"


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
    jobs = plan_jobs(state, ExportSettings(target="zip", folder=str(tmp_path / "out"), name="run"))
    assert jobs[0].request.zip_file == target.as_posix()

    with Cache.default() as cache, Directory(cache, api_factory) as directory:
        with pytest.raises(Cancelled):
            service.run_messages(jobs[0].request, directory=directory, now=NOW, tz=CET, events=TuiEvents(token, emit))

    # Cancelled during fetching: nothing was exported, not even a partial zip.
    assert not target.exists()
    assert not list(tmp_path.rglob("*.part"))




STAMP_NOW = datetime(2026, 11, 4, 1, 8)
AUTO = "discord-export-2026-1104-0108"


def _one_channel() -> SelectionState:
    state = SelectionState()
    state.toggle(Server(id="srv-1", name="Guild 1"), Channel(id="ch-1", server_id="srv-1", name="a", type=0))
    return state


def _two_windows() -> SelectionState:
    state = _one_channel()
    state.toggle(Server(id="srv-1", name="Guild 1"), Channel(id="ch-2", server_id="srv-1", name="b", type=0))
    state.set_custom_window("ch-2", WindowSpec(from_="30d"))
    return state


def _target(settings: ExportSettings, state: SelectionState | None = None, now: datetime = STAMP_NOW) -> str | None:
    request = plan_jobs(state or _one_channel(), settings, now)[0].request
    return request.out_dir or request.zip_file


def _documents(tmp_path: Path) -> Path:
    """The default folder of the tests: `discoop` in the Documents folder that conftest moved into tmp_path."""
    return tmp_path / "documents" / "discoop"


def test_export_stamp_and_default_name() -> None:
    assert export_stamp(STAMP_NOW) == "2026-1104-0108"
    assert export_stamp(datetime(2026, 12, 31, 23, 59)) == "2026-1231-2359"
    assert default_name(STAMP_NOW) == AUTO
    assert default_name().startswith("discord-export-")


def test_default_export_dir_is_discoop_in_documents(tmp_path: Path) -> None:
    assert paths.default_export_dir().name == "discoop"
    assert paths.default_export_dir().parent == paths.documents_dir() == tmp_path / "documents"
    assert not paths.documents_dir().exists(), "asking for the folder creates nothing"


def test_documents_dir_comes_from_platformdirs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.undo()  # the real functions of discoop.paths; only the folder platformdirs reports is replaced
    moved = tmp_path / "Moved Documents"
    monkeypatch.setattr("discoop.paths.user_documents_dir", lambda: str(moved))
    assert paths.documents_dir() == moved
    assert paths.default_export_dir() == moved / "discoop"
    assert not moved.exists()


def test_empty_fields_are_documents_discoop_and_the_automatic_name(tmp_path: Path) -> None:
    assert default_folder(ExportSettings()) == _documents(tmp_path)
    assert export_folder(ExportSettings()) == _documents(tmp_path)
    assert _target(ExportSettings(target="folder")) == f"{_documents(tmp_path).as_posix()}/{AUTO}"
    assert _target(ExportSettings(target="zip")) == f"{_documents(tmp_path).as_posix()}/{AUTO}.zip"
    assert not (tmp_path / "documents").exists(), "planning creates nothing"


def test_spaces_count_as_empty(tmp_path: Path) -> None:
    documents = _documents(tmp_path).as_posix()
    assert _target(ExportSettings(folder="   ", name="  ")) == f"{documents}/{AUTO}"
    assert _target(ExportSettings(folder="  ", name=" semester ")) == f"{documents}/semester"
    assert _target(ExportSettings(export_dir="   ")) == f"{documents}/{AUTO}"


def test_own_name_in_the_default_folder(tmp_path: Path) -> None:
    documents = _documents(tmp_path).as_posix()
    assert _target(ExportSettings(target="folder", name="semester")) == f"{documents}/semester"
    assert _target(ExportSettings(target="zip", name="semester")) == f"{documents}/semester.zip"


def test_own_folder_with_the_automatic_name(tmp_path: Path) -> None:
    mine = tmp_path / "mine"
    assert _target(ExportSettings(target="folder", folder=str(mine))) == f"{mine.as_posix()}/{AUTO}"
    assert _target(ExportSettings(target="zip", folder=str(mine))) == f"{mine.as_posix()}/{AUTO}.zip"
    assert _target(ExportSettings(folder=f"{mine}{os.sep}")) == f"{mine.as_posix()}/{AUTO}", "a trailing separator"


def test_relative_folder_lies_inside_the_default_folder(tmp_path: Path) -> None:
    documents = _documents(tmp_path)
    assert export_folder(ExportSettings(folder="semester")) == documents / "semester"
    assert export_folder(ExportSettings(folder="semester/ws")) == documents / "semester" / "ws"
    assert export_folder(ExportSettings(folder="./semester")) == documents / "semester"
    assert export_folder(ExportSettings(folder="../other")) == documents.parent / "other"
    assert _target(ExportSettings(folder="semester", name="x")) == f"{documents.as_posix()}/semester/x"


def test_absolute_folder_is_used_as_it_is(tmp_path: Path) -> None:
    absolute = tmp_path / "elsewhere" / "exports"
    assert export_folder(ExportSettings(folder=str(absolute))) == absolute
    assert export_folder(ExportSettings(folder=str(absolute), export_dir=str(tmp_path / "cfg"))) == absolute
    assert _target(ExportSettings(folder=str(absolute), name="x")) == f"{absolute.as_posix()}/x"


def test_tilde_is_the_home_folder(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    home = tmp_path / "home"
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    assert export_folder(ExportSettings(folder="~")) == home
    assert export_folder(ExportSettings(folder="~/semester")) == home / "semester"
    assert _target(ExportSettings(folder="~/semester", name="x")) == f"{home.as_posix()}/semester/x"


def test_export_dir_of_the_config_replaces_documents(tmp_path: Path) -> None:
    configured = tmp_path / "from-config"
    settings = ExportSettings(export_dir=str(configured))
    assert default_folder(settings) == configured
    assert _target(settings) == f"{configured.as_posix()}/{AUTO}"
    assert _target(ExportSettings(export_dir=f"{configured}{os.sep}", name="x")) == f"{configured.as_posix()}/x"
    # A relative Folder is relative to that default folder, an absolute one is not.
    assert export_folder(ExportSettings(export_dir=str(configured), folder="sub")) == configured / "sub"
    assert export_folder(ExportSettings(export_dir=str(configured), folder=str(tmp_path / "abs"))) == tmp_path / "abs"
    assert not (tmp_path / "documents").exists()


NASTY_NAMES = ["../evil", "..\\..\\evil", "a/b/c", 'a:b*c?"d', "a|b<c>d", "..", ".", "CON", "nul.txt", " . ", "/", "x" * 400]


@pytest.mark.parametrize("name", NASTY_NAMES)
@pytest.mark.parametrize("target", ["folder", "zip"])
def test_a_name_is_never_a_path(tmp_path: Path, name: str, target: str) -> None:
    out = Path(_target(ExportSettings(target=target, folder=str(tmp_path / "out"), name=name)) or "")
    assert out.parent == tmp_path / "out", f"{name!r} left the folder"
    assert out.name not in ("", ".", "..")
    assert not set(out.name) & set('/\\:*?"<>|')


def test_a_name_is_cleaned_of_invalid_characters(tmp_path: Path) -> None:
    documents = _documents(tmp_path).as_posix()
    assert _target(ExportSettings(name='a:b*c?"d')) == f"{documents}/a_b_c__d"
    assert _target(ExportSettings(name="sem/ws")) == f"{documents}/sem_ws"
    assert _target(ExportSettings(name="../evil")) == f"{documents}/_evil"
    assert _target(ExportSettings(name="..")) == f"{documents}/export"
    assert _target(ExportSettings(name="CON")) == f"{documents}/_CON"
    assert _target(ExportSettings(target="zip", name="a/b")) == f"{documents}/a_b.zip"


def test_zip_suffix_is_not_doubled(tmp_path: Path) -> None:
    documents = _documents(tmp_path).as_posix()
    assert _target(ExportSettings(target="zip", name="Run")) == f"{documents}/Run.zip"
    assert _target(ExportSettings(target="zip", name="Run.zip")) == f"{documents}/Run.zip"
    assert _target(ExportSettings(target="zip", name="Run.ZIP")) == f"{documents}/Run.zip"
    assert _target(ExportSettings(target="zip", name="v1.2")) == f"{documents}/v1.2.zip"


def test_several_jobs_with_the_automatic_name(tmp_path: Path) -> None:
    documents = _documents(tmp_path).as_posix()
    folders = [j.request.out_dir for j in plan_jobs(_two_windows(), ExportSettings(target="folder"), STAMP_NOW)]
    assert folders == [f"{documents}/{AUTO}/01-7d", f"{documents}/{AUTO}/02-30d"]
    zips = [j.request.zip_file for j in plan_jobs(_two_windows(), ExportSettings(target="zip"), STAMP_NOW)]
    assert zips == [f"{documents}/{AUTO}-01-7d.zip", f"{documents}/{AUTO}-02-30d.zip"]


def test_several_jobs_with_an_own_name_and_folder(tmp_path: Path) -> None:
    mine = tmp_path / "mine"
    settings = ExportSettings(target="folder", folder=str(mine), name="semester")
    assert [j.request.out_dir for j in plan_jobs(_two_windows(), settings)] == [
        f"{mine.as_posix()}/semester/01-7d",
        f"{mine.as_posix()}/semester/02-30d",
    ]
    for name in ("semester", "semester.ZIP"):
        settings = ExportSettings(target="zip", folder=str(mine), name=name)
        assert [j.request.zip_file for j in plan_jobs(_two_windows(), settings)] == [
            f"{mine.as_posix()}/semester-01-7d.zip",
            f"{mine.as_posix()}/semester-02-30d.zip",
        ]


def test_preview_has_no_target(tmp_path: Path) -> None:
    request = plan_jobs(_one_channel(), ExportSettings(target="preview", folder="x", name="y"), STAMP_NOW)[0].request
    assert request.out_dir is None and request.zip_file is None
    assert not (tmp_path / "documents").exists()


def test_automatic_name_does_not_reuse_the_minute(tmp_path: Path) -> None:
    settings = ExportSettings(target="folder", folder=str(tmp_path))
    base = f"{tmp_path.as_posix()}/{AUTO}"
    assert _target(settings) == base
    (tmp_path / AUTO).mkdir()
    assert _target(settings) == f"{base}-2"
    (tmp_path / f"{AUTO}-2").mkdir()
    assert _target(settings) == f"{base}-3"

    # A zip of several jobs from the same minute counts too.
    zip_settings = ExportSettings(target="zip", folder=str(tmp_path / "z"))
    (tmp_path / "z").mkdir()
    (tmp_path / "z" / f"{AUTO}-01-7d.zip").write_bytes(b"")
    assert _target(zip_settings) == f"{(tmp_path / 'z').as_posix()}/{AUTO}-2.zip"


def test_a_name_typed_by_the_user_continues_the_export(tmp_path: Path) -> None:
    (tmp_path / "semester").mkdir()
    (tmp_path / "semester.zip").write_bytes(b"")
    folder = tmp_path.as_posix()
    assert _target(ExportSettings(target="folder", folder=str(tmp_path), name="semester")) == f"{folder}/semester"
    assert _target(ExportSettings(target="zip", folder=str(tmp_path), name="semester")) == f"{folder}/semester.zip"


def test_paths_are_absolute_with_slashes_and_survive_the_command_line() -> None:
    for settings in (ExportSettings(), ExportSettings(folder="sub", name="x"), ExportSettings(target="zip")):
        request = plan_jobs(_one_channel(), settings, STAMP_NOW)[0].request
        out = request.out_dir or request.zip_file or ""
        assert Path(out).is_absolute()
        assert "\\" not in out
        command = request.to_command_str()
        assert "\\" not in command
        assert f" {out} " in f"{command} ", "no quoting is needed, so it also works in cmd and PowerShell"


def test_planned_paths_are_accepted_by_the_service_without_doubling_export_dir(tmp_path: Path) -> None:
    configured = tmp_path / "from-config"
    Config.default().set("export-dir", str(configured))
    export_dir = Config.default().get("export-dir")
    for folder, expected in (("", configured), ("sub", configured / "sub"), (str(tmp_path / "abs"), tmp_path / "abs")):
        as_folder = ExportSettings(target="folder", export_dir=export_dir, folder=folder)
        request = plan_jobs(_one_channel(), as_folder, STAMP_NOW)[0].request
        # The way the service reads --out: an absolute path is not joined with the export-dir of the config.
        resolved, as_zip = service.validate_export_target(request.out_dir, None, False, False, None) or (None, None)
        assert resolved == (expected / AUTO).resolve()
        assert as_zip is False

        as_zip_settings = ExportSettings(target="zip", export_dir=export_dir, folder=folder)
        request = plan_jobs(_one_channel(), as_zip_settings, STAMP_NOW)[0].request
        resolved, as_zip = service.validate_export_target(None, request.zip_file, False, False, None) or (None, None)
        assert resolved == (expected / f"{AUTO}.zip").resolve()
        assert as_zip is True


@pytest.mark.parametrize("target", ["folder", "zip"])
def test_export_creates_the_missing_default_folder(tmp_path: Path, target: str) -> None:
    server = Server(FIT, "VUT FIT", 5000)
    channel = Channel("200", FIT, "2bit-general", 0, None, 0)
    api_factory = _fake_api_factory({"200": FakeChannel(series(3, newest=NOW, step=timedelta(minutes=5)))})
    with Cache.default() as cache:
        cache.replace_servers([server])
        cache.replace_channels(FIT, [channel])
    state = SelectionState()
    state.toggle(server, channel)
    job = plan_jobs(state, ExportSettings(target=target, files=False), STAMP_NOW)[0]
    assert not (tmp_path / "documents").exists()

    with Cache.default() as cache, Directory(cache, api_factory) as directory:
        outcome = service.run_messages(job.request, directory=directory, now=NOW, tz=CET)

    assert outcome.exported is not None
    suffix = ".zip" if target == "zip" else ""
    assert outcome.exported.path == (_documents(tmp_path) / f"{AUTO}{suffix}").resolve()
    if target == "zip":
        assert zipfile.is_zipfile(outcome.exported.path)
    else:
        assert (outcome.exported.path / "manifest.json").is_file()
