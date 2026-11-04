"""Pilot and unit tests for R4-G: TUI state, profiles, threads switch, open folder, ETA progress."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
import logging
from pathlib import Path
import re
from typing import Any
from unittest.mock import MagicMock
import warnings

import httpx
import pytest
from textual.widgets import Input, Label

from discoop import profiles
from discoop.api import DiscordAPI
from discoop.cache import Cache
from discoop.models import Channel, Server
from discoop.progress import format_eta
from discoop.snowflake import Window, from_time
from discoop.tokenstore import TokenStore
from discoop.tui import modals, tuistate
from discoop.tui.app import DiscoopApp
from discoop.tui.bridge import CancelToken, TuiEvents
from discoop.tui.modals import HelpScreen, LoadProfileModal, LoginModal, SaveProfileModal
from discoop.tui.state import ExportSettings, SelectionState, WindowSpec, plan_jobs
from discoop.tui.tuistate import (
    extract_app_state,
    format_activity,
    format_last_exported,
    load_raw_state,
    load_user_state,
    restore_app_state,
    save_raw_state,
    save_user_state,
)
from discoop.tui.widgets import ActionRow, ChoiceRow, InputRow, TextView
from fake_messages import CET, FIT, NOW, FakeChannel, FakeDiscord, Network, series
from test_tui_app import (
    _export_network,
    _export_to,
    _make_dummy_api_factory,
    _seed_export,
    _select,
    log_text,
    notifications,
    screen_text,
    started,
    wait_until,
)

SERVER_1 = Server("100", "FIT Guild", 100)
CH_GENERAL = Channel("200", "100", "general", 0, None, 0)
CH_DATES = Channel("201", "100", "dates", 0, None, 1)


def make_test_app(api_factory: Any = None, open_folder: Any = None) -> DiscoopApp:
    def dummy_factory(token: str | None = None, **kw: Any) -> DiscordAPI:
        kw.setdefault("delay", 0.0)
        messages_200 = series(4, newest=NOW, step=timedelta(minutes=5))
        discord = FakeDiscord({"200": FakeChannel(messages_200)})
        network = Network(discord, None)
        return DiscordAPI("test-token", transport=httpx.MockTransport(network.handle), **kw)

    return DiscoopApp(api_factory=api_factory or dummy_factory, open_folder=open_folder)


# ==================== 1. TUI State Tests ====================


def test_tui_state_atomic_save_and_restore(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("discoop.paths.config_dir", lambda: tmp_path)

    selection = SelectionState()
    selection.toggle(SERVER_1, CH_GENERAL)
    selection.set_custom_window("200", WindowSpec(from_="30d", last=100))
    selection.global_window = WindowSpec(from_="24h", max_messages=1000)

    settings = ExportSettings(
        mode="fast",
        folder="custom_exports",
        name="my_export",
        threads=False,
    )

    last_exported = {"200": "2026-11-04T12:00:00+00:00"}
    extracted = extract_app_state(selection, settings, last_exported)

    # Save user state
    save_user_state("user_42", extracted)

    state_file = tmp_path / "tui-state.json"
    assert state_file.is_file()

    # Ensure no tokens in state file
    raw_content = state_file.read_text(encoding="utf-8")
    assert "token" not in raw_content.lower()
    assert "secret" not in raw_content.lower()

    # Load state for the same user
    loaded = load_user_state("user_42")
    assert loaded["settings"]["mode"] == "fast"
    assert loaded["settings"]["folder"] == "custom_exports"
    assert loaded["settings"]["name"] == "my_export"
    assert loaded["settings"]["threads"] is False
    assert loaded["global_window"]["from"] == "24h"
    assert loaded["global_window"]["max_messages"] == 1000
    assert "200" in loaded["selection"]

    # Different user gets empty state
    assert load_user_state("other_user") == {}

    # Restore into fresh state objects
    new_selection = SelectionState()
    new_settings = ExportSettings()
    servers = [SERVER_1]
    channels = {"100": [CH_GENERAL, CH_DATES]}

    restored_count, restored_exported = restore_app_state(
        loaded, servers, channels, new_selection, new_settings
    )
    assert restored_count == 1
    assert new_selection.is_selected("200")
    assert not new_selection.is_selected("201")
    assert new_settings.mode == "fast"
    assert new_settings.folder == "custom_exports"
    assert new_settings.name == "my_export"
    assert new_settings.threads is False
    assert new_selection.global_window.from_ == "24h"
    assert new_selection.has_custom_window("200")
    assert new_selection.window_for("200").from_ == "30d"
    assert restored_exported == last_exported


def test_tui_state_corrupted_file_handling(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setattr("discoop.paths.config_dir", lambda: tmp_path)

    # Non-existent file
    assert load_user_state("user_1") == {}
    assert load_raw_state() == {}

    # Corrupted / invalid JSON
    state_file = tmp_path / "tui-state.json"
    state_file.write_text("NOT A JSON {{{", encoding="utf-8")
    with warnings.catch_warnings(), caplog.at_level(logging.WARNING, logger="discoop.tui.tuistate"):
        warnings.simplefilter("error")  # a Python warning inside the running TUI would be painted into the terminal
        assert load_user_state("user_1") == {}
    messages = [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]
    assert len(messages) == 1
    assert messages[0].startswith("Corrupted tui-state file (") and messages[0].endswith(f"): {state_file}")

    # Root not a dict
    caplog.clear()
    state_file.write_text("[1, 2, 3]", encoding="utf-8")
    with warnings.catch_warnings(), caplog.at_level(logging.WARNING, logger="discoop.tui.tuistate"):
        warnings.simplefilter("error")
        assert load_user_state("user_1") == {}
    assert [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING] == [
        f"Corrupted tui-state file (root is not a dict): {state_file}"
    ]


def test_tui_state_discards_unknown_channels_and_servers(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("discoop.paths.config_dir", lambda: tmp_path)

    stale_state = {
        "selection": {
            "200": {"server_id": "100", "custom_window": None},
            "999": {"server_id": "100", "custom_window": None},  # deleted channel
            "888": {"server_id": "999", "custom_window": None},  # deleted server
        },
        "settings": {"mode": "safe", "folder": "", "name": "", "threads": True},
        "last_exported": {"200": "2026-11-04T10:00:00+00:00"},
    }

    selection = SelectionState()
    settings = ExportSettings()
    servers = [SERVER_1]
    channels = {"100": [CH_GENERAL]}  # only channel 200 exists

    restored_count, _ = restore_app_state(stale_state, servers, channels, selection, settings)
    assert restored_count == 1
    assert selection.is_selected("200")
    assert not selection.is_selected("999")
    assert not selection.is_selected("888")


# ==================== 2. Threads Switch Tests ====================


async def test_threads_switch_ui_and_cli_command() -> None:
    app = make_test_app()
    async with app.run_test(size=(140, 40)) as pilot:
        await started(app, pilot)

        threads_row = app.query_one("#row-threads", ChoiceRow)
        assert threads_row.value == "yes"
        assert app.settings.threads is True

        # Toggle to 'no'
        threads_row.action_step(1)
        await pilot.pause()
        assert threads_row.value == "no"
        assert app.settings.threads is False

        # Plan jobs and verify --no-threads
        selection = SelectionState()
        selection.toggle(SERVER_1, CH_GENERAL)
        jobs = plan_jobs(selection, app.settings)
        assert len(jobs) == 1
        assert jobs[0].request.threads is False
        argv = jobs[0].request.to_argv()
        assert "--no-threads" in argv

        # Toggle back to 'yes'
        threads_row.action_step(1)
        await pilot.pause()
        assert threads_row.value == "yes"
        assert app.settings.threads is True
        jobs = plan_jobs(selection, app.settings)
        assert jobs[0].request.threads is True
        assert "--no-threads" not in jobs[0].request.to_argv()


# ==================== 3. Profiles Tests ====================


async def test_profiles_save_and_load_flow(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("discoop.paths.config_dir", lambda: tmp_path)

    app = make_test_app()
    async with app.run_test(size=(140, 40)) as pilot:
        await started(app, pilot)

        # Setup servers and channels in app
        app.servers = [SERVER_1]
        app.channels_by_server = {"100": [CH_GENERAL, CH_DATES]}
        app.selection.toggle(SERVER_1, CH_GENERAL)
        app.settings.mode = "fast"
        app.selection.global_window = WindowSpec(from_="30d", last=25)

        # Press 'P' to save profile
        await pilot.press("P")
        await pilot.pause()
        assert isinstance(app.screen, SaveProfileModal)

        # Type profile name and submit
        name_input = app.screen.query_one("#input-profile-name", Input)
        name_input.value = "test-prof"
        await pilot.press("enter")
        await pilot.pause()
        assert not isinstance(app.screen, SaveProfileModal)

        # Verify profile is in profiles.json
        saved = profiles.load()
        assert "test-prof" in saved
        assert saved["test-prof"]["mode"] == "fast"
        assert saved["test-prof"]["channels"] == ["200"]
        assert saved["test-prof"]["from"] == "30d"
        assert saved["test-prof"]["last"] == 25

        # Modify current app state
        app.selection.clear_all()
        app.settings.mode = "safe"
        app.selection.global_window = WindowSpec(from_="7d")
        assert not app.selection.selected

        # Press 'p' to load profile
        await pilot.press("p")
        await pilot.pause()
        assert isinstance(app.screen, LoadProfileModal)

        # Confirm loading 'test-prof'
        await pilot.press("enter")
        await pilot.pause()
        assert not isinstance(app.screen, LoadProfileModal)

        # Verify state is restored from profile
        assert app.selection.is_selected("200")
        assert app.settings.mode == "fast"
        assert app.selection.global_window.from_ == "30d"
        assert app.selection.global_window.last == 25


# ==================== 4. Open Export Folder Tests ====================


async def test_open_export_folder_with_mock_callable(tmp_path: Path) -> None:
    mock_open = MagicMock()
    app = make_test_app(open_folder=mock_open)
    async with app.run_test(size=(140, 40)) as pilot:
        await started(app, pilot)

        # Before export: press 'o' should not call mock_open
        await pilot.press("o")
        await pilot.pause()
        mock_open.assert_not_called()

        # Simulate finished export setting _last_export_folder
        export_target = tmp_path / "my_finished_export"
        export_target.mkdir()
        app._last_export_folder = export_target

        # Press 'o' now calls mock_open
        await pilot.press("o")
        await pilot.pause()
        mock_open.assert_called_once_with(export_target)


# ==================== 5. ETA and Progress Calculations ====================


def test_tui_events_eta_and_progress_emission() -> None:
    emitted: list[tuple[str, dict[str, Any]]] = []

    def sink(name: str, payload: dict[str, Any]) -> None:
        emitted.append((name, payload))

    token = CancelToken()
    clock_time = 1000.0

    def mock_clock() -> float:
        return clock_time

    # Window from 10 days ago to now
    now_dt = datetime(2026, 11, 4, 12, 0, tzinfo=timezone.utc)
    window = Window(now_dt - timedelta(days=10), now_dt)

    events = TuiEvents(token, sink, window=window, clock=mock_clock)
    server = Server("1", "Guild")
    channel = Channel("100000000000000000", "1", "chat", 0)

    events.channel_start(1, 1, server, channel)
    assert emitted[-1][0] == "channel_start"

    # Simulate fetching a page midway through the window
    start_id = from_time(window.start)
    end_id = from_time(window.end)
    mid_id = start_id + (end_id - start_id) // 2

    clock_time += 10.0  # 10 seconds elapsed
    events.page(100, mid_id)

    assert emitted[-1][0] == "page"
    payload = emitted[-1][1]
    assert payload["count"] == 100
    assert payload["oldest_id"] == mid_id
    assert payload["fraction"] is not None
    assert 0.45 <= payload["fraction"] <= 0.55
    assert payload["eta_seconds"] is not None
    assert payload["eta_seconds"] > 0

    # Test formatting of ETA string
    formatted = format_eta(payload["eta_seconds"])
    assert "s" in formatted or "min" in formatted


async def test_app_page_event_displays_eta_in_status() -> None:
    app = make_test_app()
    async with app.run_test(size=(140, 40)) as pilot:
        await started(app, pilot)
        app._current_channel = "general"

        # Dispatch bridge page event with fraction and ETA
        app._handle_bridge_event("page", {"count": 120, "oldest_id": 12345, "fraction": 0.42, "eta_seconds": 180})
        await pilot.pause()

        status = str(app.query_one("#run-status", Label).content)
        assert "#general: 120 messages" in status
        assert "~42%" in status
        assert "3 min left" in status


# ==================== 6. Activity and Export Date Formatting ====================


def test_activity_and_last_exported_formatting() -> None:
    now = datetime(2026, 11, 4, 12, 0, tzinfo=timezone.utc)

    # Empty / None
    assert format_activity(None) == ""
    assert format_last_exported(None) == ""

    # Snowflake from 2 days ago
    msg_dt = now - timedelta(days=2)
    flake = from_time(msg_dt)
    assert format_activity(flake, now=now) == "2d ago"

    # Snowflake from 3 hours ago
    msg_dt_3h = now - timedelta(hours=3)
    flake_3h = from_time(msg_dt_3h)
    assert format_activity(flake_3h, now=now) == "3h ago"

    # Last exported 5 hours ago
    exported_dt = (now - timedelta(hours=5)).isoformat()
    assert format_last_exported(exported_dt, now=now) == "exported 5h ago"


# ==================== 7. Layout in 80x24 and Wide Window ====================


async def test_layout_narrow_80x24_and_wide() -> None:
    # 80x24 layout
    app_narrow = make_test_app()
    async with app_narrow.run_test(size=(80, 24)) as pilot:
        await started(app_narrow, pilot)
        assert app_narrow.screen.has_class("-narrow")
        assert app_narrow.query_one("#main-columns") is not None
        assert app_narrow.query_one("#run-status") is not None
        assert app_narrow.query_one("#command-bar") is not None

    # Wide layout
    app_wide = make_test_app()
    async with app_wide.run_test(size=(140, 40)) as pilot:
        await started(app_wide, pilot)
        assert app_wide.screen.has_class("-wide")
        assert app_wide.query_one("#tree-pane").display is True
        assert app_wide.query_one("#export-pane").display is True
        assert app_wide.query_one("#log-pane").display is True


# ==================== 8. Keys: P, p and o, nothing else ====================


async def test_ctrl_s_and_ctrl_o_do_nothing(tmp_path: Path) -> None:
    mock_open = MagicMock()
    app = make_test_app(open_folder=mock_open)
    async with app.run_test(size=(140, 40)) as pilot:
        await started(app, pilot)
        app.servers = [SERVER_1]
        app.channels_by_server = {"100": [CH_GENERAL, CH_DATES]}
        app.selection.toggle(SERVER_1, CH_GENERAL)
        profiles.save("kept", {"channels": ["200"], "from": "7d", "mode": "safe"})
        app._last_export_folder = tmp_path
        app.refresh_bindings()
        await pilot.pause()

        assert "ctrl+s" not in app.active_bindings and "ctrl+o" not in app.active_bindings
        assert not {"ctrl+s", "ctrl+o"} & {binding.key for binding in DiscoopApp.BINDINGS}
        screen = app.screen
        await pilot.press("ctrl+s")
        await pilot.pause()
        assert app.screen is screen, "Ctrl+S opens no dialog"
        await pilot.press("ctrl+o")
        await pilot.pause()
        assert app.screen is screen, "Ctrl+O opens no dialog"
        mock_open.assert_not_called()
        assert profiles.names() == ["kept"]

        # The documented keys still do their jobs
        await pilot.press("P")
        await pilot.pause()
        assert isinstance(app.screen, SaveProfileModal)
        await pilot.press("escape")
        await pilot.pause()
        await pilot.press("p")
        await pilot.pause()
        assert isinstance(app.screen, LoadProfileModal)
        await pilot.press("escape")
        await pilot.pause()
        await pilot.press("o")
        await pilot.pause()
        mock_open.assert_called_once_with(tmp_path)


async def test_help_documents_p_capital_p_and_o_and_not_the_ctrl_keys() -> None:
    app = make_test_app()
    async with app.run_test(size=(140, 60)) as pilot:
        await started(app, pilot)
        await pilot.press("f1")
        await pilot.pause()
        assert isinstance(app.screen, HelpScreen)
        guide = str(app.screen.query_one("#help-content", TextView).content)

        def row(key: str) -> str:
            lines = [line.strip() for line in guide.splitlines() if re.match(rf"\s+{re.escape(key)}\s{{2,}}\S", line)]
            assert len(lines) == 1, f"one row for {key}: {lines}"
            return lines[0]

        assert row("P").endswith("save the selection, time window and mode as a profile")
        assert row("p").endswith("load a saved profile")
        assert row("o").endswith("open the folder of the last export")
        assert row("L").endswith("load the channels of all servers (safe pace, Esc stops)"), "L is not for profiles"
        assert "profile" not in row("L")
        assert "ctrl+s" not in guide.lower() and "ctrl+o" not in guide.lower()
        flat = " ".join(guide.split())
        assert "Press P to save" in flat and "Press p to load" in flat and "press o to open" in flat
        keys = [key for key, _ in modals.GUIDE_KEYS]
        assert {"P", "p", "o"} <= set(keys) and "Ctrl+S" not in keys and "Ctrl+O" not in keys


async def test_footer_lists_p_and_o_and_not_the_ctrl_keys(tmp_path: Path) -> None:
    app = make_test_app()
    async with app.run_test(size=(140, 40)) as pilot:
        await started(app, pilot)

        def footer() -> dict[str, str]:
            return {key.key: str(key.description) for key in app.query("FooterKey")}

        keys = footer()
        assert keys["p"] == "Profile" and keys["L"] == "Load all"
        assert "o" not in keys, "nothing to open before an export"
        assert not {"ctrl+s", "ctrl+o"} & set(keys)
        assert [key for key, text in keys.items() if "rofile" in text] == ["p"], "L is not for profiles"

        app._last_export_folder = tmp_path
        app.refresh_bindings()
        await pilot.pause()
        keys = footer()
        assert keys["o"] == "Open" and keys["p"] == "Profile" and keys["L"] == "Load all"
        assert not {"ctrl+s", "ctrl+o"} & set(keys)


# ==================== 9. A failing disk must not take the TUI down ====================


async def test_a_failing_state_write_is_logged_once_and_the_tui_goes_on(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    real_save = tuistate.save_raw_state

    def broken(data: dict[str, Any]) -> None:
        raise OSError("disk full")

    app = make_test_app()
    async with app.run_test(size=(140, 40)) as pilot:
        await started(app, pilot)
        app.current_user_id = "42"
        app._state_loaded = True
        app.servers = [SERVER_1]
        app.channels_by_server = {"100": [CH_GENERAL, CH_DATES]}

        monkeypatch.setattr(tuistate, "save_raw_state", broken)
        with caplog.at_level(logging.WARNING, logger="discoop.tui.app"):
            app.selection.toggle(SERVER_1, CH_GENERAL)
            app._selection_changed(["200"])  # a save runs on every change
            app.query_one("#row-mode", ChoiceRow).action_step(1)  # and so does a form change
            app.query_one("#input-name", Input).value = "my-export"
            await wait_until(pilot, lambda: app.settings.name == "my-export")
        assert app.is_running
        assert app.selection.is_selected("200"), "the selection lives on in memory"
        messages = [r.getMessage() for r in caplog.records if r.name == "discoop.tui.app"]
        assert len(messages) >= 2 and all("Could not save the TUI state: disk full" in m for m in messages)
        assert log_text(app).count("Could not save the selection and form for next time: disk full") == 1
        assert load_raw_state() == {}

        # The disk works again: the next change is saved and the warning can come back later
        monkeypatch.setattr(tuistate, "save_raw_state", real_save)
        app._save_tui_state()
        saved = load_user_state("42")
        assert saved["selection"].keys() == {"200"} and saved["settings"]["name"] == "my-export"
        assert app._state_save_failed is False

        monkeypatch.setattr(tuistate, "save_raw_state", broken)
        app._save_tui_state()
        assert log_text(app).count("Could not save the selection and form for next time") == 2

        await pilot.press("q")  # quitting saves once more: with a broken disk it still quits
        await pilot.pause()


async def test_a_state_file_that_cannot_be_created_does_not_crash(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    app = make_test_app()
    async with app.run_test(size=(140, 40)) as pilot:
        await started(app, pilot)
        app.current_user_id = "42"
        app._state_loaded = True
        blocked = tmp_path / "blocked"
        blocked.write_text("a file where the config folder should be", encoding="utf-8")
        monkeypatch.setattr("discoop.paths.config_dir", lambda: blocked)

        with pytest.raises(OSError):  # the failure is real, not a mock
            save_user_state("42", {})
        app.query_one("#row-threads", ChoiceRow).action_step(1)
        await pilot.pause()
        assert app.is_running and app.settings.threads is False
        assert "Could not save the selection and form for next time" in log_text(app)


async def test_a_failing_profile_write_is_reported_and_the_tui_goes_on(monkeypatch: pytest.MonkeyPatch) -> None:
    def broken(name: str, profile: dict[str, Any]) -> None:
        raise OSError("read-only file system")

    app = make_test_app()
    async with app.run_test(size=(140, 40)) as pilot:
        await started(app, pilot)
        app.servers = [SERVER_1]
        app.channels_by_server = {"100": [CH_GENERAL, CH_DATES]}
        app.selection.toggle(SERVER_1, CH_GENERAL)
        monkeypatch.setattr(profiles, "save", broken)

        await pilot.press("P")
        await pilot.pause()
        app.screen.query_one("#input-profile-name", Input).value = "trouble"
        await pilot.press("enter")
        await pilot.pause()
        assert app.is_running and not isinstance(app.screen, SaveProfileModal)
        assert "Could not save profile 'trouble': read-only file system" in notifications(app)
        assert "Profile 'trouble' saved." not in notifications(app)


async def test_a_hand_edited_profile_with_wrong_types_does_not_crash() -> None:
    profiles._profiles_file().parent.mkdir(parents=True, exist_ok=True)
    profiles._profiles_file().write_text(
        json.dumps({"odd": {"from": 5, "to": ["x"], "last": "many", "channels": 7, "mode": "warp"}, "scalar": 5}),
        encoding="utf-8",
    )
    app = make_test_app()
    async with app.run_test(size=(140, 40)) as pilot:
        await started(app, pilot)
        app.servers = [SERVER_1]
        app.channels_by_server = {"100": [CH_GENERAL, CH_DATES]}
        app.selection.toggle(SERVER_1, CH_GENERAL)
        mode = app.settings.mode

        await pilot.press("p")  # "odd" is the first name
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()
        assert app.is_running and not isinstance(app.screen, LoadProfileModal)
        assert "Loaded profile 'odd'." in notifications(app)
        assert app.settings.mode == mode, "an unknown mode is ignored"
        window = app.selection.global_window
        assert (window.from_, window.to, window.last) == ("7d", None, None), "wrong types fall back to the defaults"
        assert not app.selection.selected, "channels that are not a list select nothing"

        app._apply_profile("scalar", 5)  # type: ignore[arg-type]
        await pilot.pause()
        assert "Profile 'scalar' is not valid." in notifications(app)


# ==================== 10. Saved state and the account ====================


def seed_club_cache() -> None:
    TokenStore.default().save("fake-token")
    with Cache.default() as cache:
        cache.replace_servers([SERVER_1])
        cache.replace_channels("100", [CH_GENERAL, CH_DATES])


async def test_the_form_sync_at_startup_does_not_wipe_the_saved_state() -> None:
    """The startup worker knows the account before the state is read: a change in between must not save."""
    seed_club_cache()
    exported = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    save_user_state(
        "42",
        {
            "selection": {"200": {"server_id": "100", "custom_window": None}, "999": {"server_id": "100"}},
            "global_window": {"from": "30d", "to": None, "last": None, "max_messages": 777},
            "settings": {"mode": "fast", "folder": "", "name": "kept-name", "threads": False},
            "last_exported": {"201": exported},
        },
    )
    app = DiscoopApp(api_factory=_make_dummy_api_factory())
    async with app.run_test(size=(140, 40)) as pilot:
        await started(app, pilot)
        await wait_until(pilot, lambda: app._state_loaded)
        assert app.current_user_id == "42"
        assert app.selection.selected.keys() == {"200"}
        assert app.selection.global_window.from_ == "30d" and app.selection.global_window.max_messages == 777
        assert app.settings.mode == "fast" and app.settings.name == "kept-name" and app.settings.threads is False
        assert app.last_exported == {"201": exported}
        await pilot.pause()
        saved = load_user_state("42")
        assert saved["selection"].keys() == {"200"}, "the stale channel is gone, the rest is not"
        assert saved["last_exported"] == {"201": exported}
        assert saved["settings"]["name"] == "kept-name"


def club_api_factory(token: str | None = None, **kw: Any) -> DiscordAPI:
    """A Discord where account 42 is a member of SERVER_1 only, so that reloading the server list keeps it."""

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("/users/@me"):
            return httpx.Response(200, json={"id": "42", "username": "testuser"})
        if path.endswith("/users/@me/guilds"):
            return httpx.Response(200, json=[{"id": SERVER_1.id, "name": SERVER_1.name}])
        return httpx.Response(404, json={"message": "Not Found", "code": 10003})

    kw["delay"] = 0.0
    kw.setdefault("mode", "safe")
    return DiscordAPI("dummy-token", transport=httpx.MockTransport(handler), **kw)


async def test_changing_the_login_keeps_the_saved_state_of_the_old_account() -> None:
    seed_club_cache()
    exported = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    save_user_state(
        "42",
        {"selection": {"200": {"server_id": "100", "custom_window": None}}, "last_exported": {"200": exported}},
    )
    app = DiscoopApp(api_factory=club_api_factory)
    async with app.run_test(size=(140, 40)) as pilot:
        await started(app, pilot)
        await wait_until(pilot, lambda: app._state_loaded)
        assert app.selection.is_selected("200") and app.last_exported == {"200": exported}

        await pilot.press("f3")
        await pilot.pause()
        assert isinstance(app.screen, LoginModal)
        await app.screen.dismiss(True)  # the account changed
        await pilot.pause()
        saved = load_user_state("42")
        assert saved["selection"].keys() == {"200"} and saved["last_exported"] == {"200": exported}, (
            "clearing the selection for the new account must not overwrite the old account's state"
        )

        await started(app, pilot)
        await wait_until(pilot, lambda: app._state_loaded and app.selection.is_selected("200"))
        assert app.last_exported == {"200": exported}


# ==================== 11. Profile names ====================


def test_validate_name_is_public_and_the_old_name_still_works() -> None:
    assert profiles.validate_name("  my-prof_1.v2 ") == "my-prof_1.v2"
    assert profiles._validate_name is profiles.validate_name
    for bad in ("", "   ", ".", "..", "a..b", "a/b", "a\\b", "a b", "ä"):
        with pytest.raises(ValueError):
            profiles.validate_name(bad)


async def test_save_profile_dialog_validates_with_the_public_function(monkeypatch: pytest.MonkeyPatch) -> None:
    app = make_test_app()
    async with app.run_test(size=(140, 40)) as pilot:
        await started(app, pilot)
        app.servers = [SERVER_1]
        app.channels_by_server = {"100": [CH_GENERAL, CH_DATES]}
        app.selection.toggle(SERVER_1, CH_GENERAL)

        await pilot.press("P")
        await pilot.pause()
        name = app.screen.query_one("#input-profile-name", Input)
        error = app.screen.query_one("#profile-save-error", Label)
        name.value = "bad/name"
        await pilot.press("enter")
        await pilot.pause()
        assert isinstance(app.screen, SaveProfileModal), "an invalid name keeps the dialog open"
        assert "Invalid profile name" in str(error.content)

        calls: list[str] = []

        def spy(raw: str) -> str:
            calls.append(raw)
            raise ValueError("the public validator said no")

        monkeypatch.setattr(profiles, "validate_name", spy)
        name.value = "fine-name"
        await pilot.press("enter")
        await pilot.pause()
        assert calls == ["fine-name"]
        assert "the public validator said no" in str(error.content)
