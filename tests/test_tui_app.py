"""Textual Pilot integration tests and CLI/service equivalence tests for discoop TUI."""

from __future__ import annotations

import contextlib
from dataclasses import replace
from datetime import timedelta
import io
import json
from pathlib import Path
from typing import Any

import httpx
import pytest
from textual.widgets import OptionList, Static, TabbedContent

from discoop import cli, service
from discoop.api import DiscordAPI
from discoop.cache import Cache
from discoop.cli import command_help
from discoop.directory import Directory
from discoop.models import Channel, Server
from discoop.tokenstore import TokenStore
from discoop.tui.app import DiscoopApp
from discoop.tui.modals import HelpScreen
from discoop.tui.state import ExportSettings, SelectionState, WindowSpec, plan_jobs
from fake_messages import CET, FIT, NOW, FakeChannel, FakeDiscord, Network, series


def _make_dummy_api_factory(transport: httpx.MockTransport | None = None):
    def factory(token: str | None = None, **kw: Any) -> DiscordAPI:
        kw.setdefault("delay", 0.0)
        kw.setdefault("mode", "safe")
        if transport is not None:
            return DiscordAPI("dummy-token", transport=transport, **kw)

        def dummy_handler(request: httpx.Request) -> httpx.Response:
            path = request.url.path
            if "users/@me" in path:
                return httpx.Response(200, json={"id": "42", "username": "testuser", "global_name": "Test User"})
            if "guilds" in path:
                return httpx.Response(200, json=[])
            return httpx.Response(404, json={"message": "Not Found", "code": 10003})

        return DiscordAPI("dummy-token", transport=httpx.MockTransport(dummy_handler), **kw)

    return factory


async def test_responsive_breakpoints() -> None:
    """1. Responsive layout breakpoints:

    - With size=(140, 40), verify app.screen.has_class("-wide") is True.
    - With size=(75, 28), verify app.screen.has_class("-narrow") is True,
      and pressing "2" / "3" / "1" switches the narrow tabs without losing selection state.
    """
    dummy_api = _make_dummy_api_factory()

    # 1. Wide breakpoint
    wide_app = DiscoopApp(api_factory=dummy_api)
    async with wide_app.run_test(size=(140, 40)) as pilot:
        await pilot.pause()
        assert wide_app.screen.has_class("-wide")
        assert not wide_app.screen.has_class("-narrow")

    # 2. Narrow breakpoint and tab switching
    narrow_app = DiscoopApp(api_factory=dummy_api)
    async with narrow_app.run_test(size=(75, 28)) as pilot:
        await pilot.pause()
        assert narrow_app.screen.has_class("-narrow")
        assert not narrow_app.screen.has_class("-wide")
        assert narrow_app.screen.has_class("show-tab-1")
        assert narrow_app.current_narrow_tab == 1

        # Populate selection state before switching tabs
        server = Server("100", "VUT FIT", 390)
        channel = Channel("101", "100", "isc-public", 0, None, 1)
        assert narrow_app.selection.toggle(server, channel) is True
        assert narrow_app.selection.is_selected("101")

        # Press "2" -> switch to narrow tab 2 (Export & Settings)
        await pilot.press("2")
        await pilot.pause()
        assert narrow_app.current_narrow_tab == 2
        assert narrow_app.screen.has_class("show-tab-2")
        assert not narrow_app.screen.has_class("show-tab-1")
        # Selection state is preserved
        assert narrow_app.selection.is_selected("101")

        # Press "3" -> switch to narrow tab 3 (Run & Output)
        await pilot.press("3")
        await pilot.pause()
        assert narrow_app.current_narrow_tab == 3
        assert narrow_app.screen.has_class("show-tab-3")
        assert not narrow_app.screen.has_class("show-tab-2")
        # Selection state is preserved
        assert narrow_app.selection.is_selected("101")

        # Press "1" -> switch back to narrow tab 1 (Servers & Channels)
        await pilot.press("1")
        await pilot.pause()
        assert narrow_app.current_narrow_tab == 1
        assert narrow_app.screen.has_class("show-tab-1")
        assert not narrow_app.screen.has_class("show-tab-3")
        # Selection state is preserved
        assert narrow_app.selection.is_selected("101")
        assert "101" in narrow_app.selection.selected


async def test_server_and_channel_selection_updates_command_bar() -> None:
    """2. Cached servers & channel selection:

    - Pre-populate Cache.default() with 2 servers (Server("100", "VUT FIT", 390), Server("200", "AI Club", 25))
      and channels for "100" (category type=4, text channel type=0, forum channel type=15).
    - Launch DiscoopApp under run_test(size=(140, 40)).
    - Verify servers appear in #server-list.
    - Select channel "101" (isc-public) via app.selection.toggle(...) or tree interaction and trigger UI refresh;
      verify #command-preview shows `discoop messages -s 100 -c 101 --from 7d --safe --out ...`.
    - Verify category (type=4) and forum (type=15) cannot be selected (app.selection.toggle returns False).
    """
    server_fit = Server("100", "VUT FIT", 390)
    server_ai = Server("200", "AI Club", 25)
    category_ch = Channel("10", "100", "General", 4, None, 0)
    text_ch = Channel("101", "100", "isc-public", 0, "10", 1)
    forum_ch = Channel("103", "100", "announcements-forum", 15, "10", 2)

    with Cache.default() as cache:
        cache.replace_servers([server_fit, server_ai])
        cache.replace_channels("100", [category_ch, text_ch, forum_ch])

    dummy_api = _make_dummy_api_factory()
    app = DiscoopApp(api_factory=dummy_api)

    async with app.run_test(size=(140, 40)) as pilot:
        # Allow background workers on on_mount to populate cached servers and channels
        await pilot.pause()

        server_list = app.query_one("#server-list", OptionList)
        assert server_list.option_count == 2
        prompts = [str(server_list.get_option_at_index(i).prompt) for i in range(server_list.option_count)]
        assert any("VUT FIT" in p for p in prompts)
        assert any("AI Club" in p for p in prompts)

        # Verify category (type=4) and forum (type=15) cannot be selected
        assert app.selection.toggle(server_fit, category_ch) is False
        assert not app.selection.is_selected(category_ch.id)
        assert app.selection.toggle(server_fit, forum_ch) is False
        assert not app.selection.is_selected(forum_ch.id)

        # Select text channel "101"
        assert app.selection.toggle(server_fit, text_ch) is True
        assert app.selection.is_selected(text_ch.id)

        # Trigger UI refresh
        app._rebuild_channel_tree()
        app._update_selected_ui()
        app._update_command_preview()

        preview = app.query_one("#command-preview", Static)
        cmd_str = str(preview.content)
        assert "discoop messages" in cmd_str
        assert "-s 100" in cmd_str
        assert "-c 101" in cmd_str
        assert "--from 7d" in cmd_str
        assert "--safe" in cmd_str
        assert "--out" in cmd_str


async def test_custom_window_splits_into_two_jobs() -> None:
    """3. Custom per-channel time window:

    - Select 2 channels ("101" and "102"), set custom window on "102"
      (WindowSpec(from_="2026-10-01", to="2026-10-31")), verify plan_jobs / #command-preview
      shows 2 commands with 01-7d and 02-2026-10-01_2026-10-31.
    """
    server = Server("100", "VUT FIT", 390)
    ch1 = Channel("101", "100", "isc-public", 0, None, 1)
    ch2 = Channel("102", "100", "isc-private", 0, None, 2)

    with Cache.default() as cache:
        cache.replace_servers([server])
        cache.replace_channels("100", [ch1, ch2])

    dummy_api = _make_dummy_api_factory()
    app = DiscoopApp(api_factory=dummy_api)

    async with app.run_test(size=(140, 40)) as pilot:
        await pilot.pause()

        # Select both channels
        app.selection.toggle(server, ch1)
        app.selection.toggle(server, ch2)

        # Set custom window on "102"
        custom_spec = WindowSpec(from_="2026-10-01", to="2026-10-31")
        app.selection.set_custom_window("102", custom_spec)

        app._rebuild_channel_tree()
        app._update_selected_ui()
        app._update_command_preview()

        # Verify plan_jobs produces 2 jobs with expected folder slugs
        jobs = plan_jobs(app.selection, app.settings)
        assert len(jobs) == 2
        assert any("01-7d" in (j.request.out_dir or "") for j in jobs)
        assert any("02-2026-10-01_2026-10-31" in (j.request.out_dir or "") for j in jobs)

        # Verify #command-preview shows both commands joined by &&
        preview = app.query_one("#command-preview", Static)
        cmd_str = str(preview.content)
        assert "01-7d" in cmd_str
        assert "02-2026-10-01_2026-10-31" in cmd_str
        assert " && " in cmd_str
        assert "--from 2026-10-01 --to 2026-10-31" in cmd_str


async def test_help_screen_shows_guide_and_cli_help() -> None:
    """4. Help screen:

    - Press "f1" via await pilot.press("f1") to open HelpScreen.
    - Verify the modal screen is HelpScreen.
    - Verify the CLI help content matches command_help(()) (contains NOTE FOR AI AGENTS
      and GETTING STARTED) and switching to messages help shows --safe and --fast.
    - Press "escape" to close HelpScreen.
    """
    dummy_api = _make_dummy_api_factory()
    app = DiscoopApp(api_factory=dummy_api)

    async with app.run_test(size=(140, 40)) as pilot:
        await pilot.pause()

        # Press F1 to open HelpScreen
        await pilot.press("f1")
        await pilot.pause()

        assert isinstance(app.screen, HelpScreen)
        help_screen = app.screen

        # Verify root CLI help matches command_help(())
        expected_root_help = command_help(())
        assert "NOTE FOR AI AGENTS" in expected_root_help
        assert "GETTING STARTED" in expected_root_help

        cli_content = help_screen.query_one("#cli-help-content", Static)
        assert str(cli_content.content) == expected_root_help
        assert "NOTE FOR AI AGENTS" in str(cli_content.content)
        assert "GETTING STARTED" in str(cli_content.content)

        # Switch to the CLI Reference tab and select "messages" command help
        tabbed = help_screen.query_one(TabbedContent)
        tabbed.active = "tab-cli-help"
        await pilot.pause()

        # Click the messages command button
        await pilot.click("#cmd-messages")
        await pilot.pause()

        messages_help_content = str(cli_content.content)
        assert "--safe" in messages_help_content
        assert "--fast" in messages_help_content

        # Press Escape to close HelpScreen
        await pilot.press("escape")
        await pilot.pause()

        assert not isinstance(app.screen, HelpScreen)


def test_cli_and_service_export_equivalence(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """5. CLI vs Service Equivalence:

    - Given a PlannedJob produced by plan_jobs(selection, settings), verify that
      running service.run_messages(job.request, ...) produces the exact same manifest.json
      structure (query, channels, stats) as running the CLI with job.request.to_argv().
    """
    TokenStore.default().save("test-token")

    # Fixed time and timezone for deterministic manifest.json
    monkeypatch.setattr(cli, "utc_now", lambda: NOW)
    monkeypatch.setattr(cli, "LOCAL_ZONE", CET)

    service_out = tmp_path / "export_service"
    cli_out = tmp_path / "export_cli"

    # Setup fake Discord channel messages
    messages_200 = series(6, newest=NOW, step=timedelta(minutes=5))
    discord = FakeDiscord({"200": FakeChannel(messages_200)})
    network = Network(discord, None)
    transport = httpx.MockTransport(network.handle)

    def api_factory(token: str | None = None, **kw: Any) -> DiscordAPI:
        kw.setdefault("delay", 0.0)
        return DiscordAPI("test-token", transport=transport, **kw)

    monkeypatch.setattr(cli, "DiscordAPI", api_factory)

    server = Server(FIT, "VUT FIT", 5000)
    channel = Channel("200", FIT, "2bit-general", 0, None, 0)

    with Cache.default() as cache:
        cache.replace_servers([server])
        cache.replace_channels(FIT, [channel])

    selection = SelectionState()
    selection.toggle(server, channel)
    settings = ExportSettings(
        mode="safe",
        files=False,
        target="folder",
        path=str(service_out),
    )

    jobs = plan_jobs(selection, settings)
    assert len(jobs) == 1
    job = jobs[0]

    # 1. Run via service
    with Cache.default() as cache, Directory(cache, api_factory) as directory:
        service_outcome = service.run_messages(
            job.request,
            directory=directory,
            now=NOW,
            tz=CET,
        )
    assert service_outcome.results

    # 2. Run via CLI using job.request.to_argv()
    cli_request = replace(job.request, out_dir=str(cli_out))
    cli_argv = cli_request.to_argv()

    out_capture = io.StringIO()
    with contextlib.redirect_stdout(out_capture):
        with pytest.raises(SystemExit) as exc_info:
            cli.main(["--agent", *cli_argv])
    assert exc_info.value.code == 0

    # 3. Compare manifest.json outputs
    manifest_service_file = service_out / "manifest.json"
    manifest_cli_file = cli_out / "manifest.json"
    assert manifest_service_file.exists()
    assert manifest_cli_file.exists()

    manifest_service = json.loads(manifest_service_file.read_text(encoding="utf-8"))
    manifest_cli = json.loads(manifest_cli_file.read_text(encoding="utf-8"))

    # Compare query
    assert manifest_service["query"] == manifest_cli["query"]

    # Compare channels (structure and contents)
    assert manifest_service["channels"] == manifest_cli["channels"]

    # Compare counts (stats)
    assert manifest_service["counts"] == manifest_cli["counts"]

    # Compare other manifest structure fields
    assert manifest_service["tool"] == manifest_cli["tool"]
    assert manifest_service["complete"] == manifest_cli["complete"]
    assert manifest_service["truncated"] == manifest_cli["truncated"]
    assert manifest_service["created"] == manifest_cli["created"]
