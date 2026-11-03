"""Textual Pilot integration tests and CLI/service equivalence tests for discoop TUI."""

from __future__ import annotations

import asyncio
import base64
import contextlib
from dataclasses import replace
from datetime import timedelta
import io
import json
from pathlib import Path
import time
from typing import Any

import httpx
import pytest
from textual.widgets import Input, Label, OptionList, Static, TabbedContent

from discoop import cli, service
from discoop.api import DiscordAPI
from discoop.cache import Cache
from discoop.cli import command_help
from discoop.directory import Directory
from discoop.models import Channel, Server
from discoop.remote_auth.crypto import OAEP_SHA256, RemoteAuthKeys, UserPayload
from discoop.remote_auth.protocol import LoginTicket
from discoop.tokenstore import TokenStore
from discoop.tui.app import DiscoopApp
from discoop.tui.modals import HelpScreen, LoginModal
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


async def test_login_modal_qr_code_display_and_login() -> None:
    """Test LoginModal QR generation, rendering scannable code, and finishing login."""
    keys = RemoteAuthKeys()
    user = UserPayload(id="42", discriminator="0001", avatar=None, username="qr_user")
    token_value = "qr-auth-token-xyz"

    def mock_handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if "remote-auth/login" in path:
            body = json.loads(request.content)
            assert body == {"ticket": "test-ticket-999"}
            encrypted = keys.public_key.encrypt(token_value.encode("utf-8"), OAEP_SHA256)
            return httpx.Response(200, json={"encrypted_token": base64.b64encode(encrypted).decode("ascii")})
        if "users/@me" in path:
            return httpx.Response(200, json={"id": "42", "username": "qr_user", "global_name": "QR User"})
        if "guilds" in path:
            return httpx.Response(200, json=[])
        return httpx.Response(404, json={"message": "Not Found"})

    api_factory = _make_dummy_api_factory(transport=httpx.MockTransport(mock_handler))

    qr_shown = asyncio.Event()
    finish_login = asyncio.Event()

    async def fake_wait_for_ticket(listener: Any, **kwargs: Any) -> LoginTicket:
        listener.on_connecting(1)
        listener.on_qr("https://discord.com/ra/testfingerprint123", time.monotonic() + 120)
        qr_shown.set()
        await finish_login.wait()
        listener.on_scanned(user)
        return LoginTicket(ticket="test-ticket-999", keys=keys, user=user)

    app = DiscoopApp(api_factory=api_factory)
    async with app.run_test(size=(140, 40)) as pilot:
        await pilot.pause()

        # Push LoginModal with fake wait_for_ticket_fn
        modal = LoginModal(api_factory=api_factory, wait_for_ticket_fn=fake_wait_for_ticket)
        app.push_screen(modal)
        await pilot.pause()

        assert isinstance(app.screen, LoginModal)

        # Click the Generate QR Code button
        await pilot.click("#btn-login-qr")

        # Wait until QR code is displayed
        await qr_shown.wait()
        await pilot.pause()

        # Assert QR code is displayed
        qr_box = modal.query_one("#qr-box", Static)
        assert "▀" in str(qr_box.content)

        # Assert status label mentions scanning the QR code
        status_lbl = modal.query_one("#qr-status-lbl", Label)
        assert "Scan this QR code with the Discord mobile app" in str(status_lbl.content)

        # Assert countdown label shows remaining time
        countdown_lbl = modal.query_one("#qr-countdown-lbl", Label)
        assert "Expires in" in str(countdown_lbl.content)

        # Signal fake_wait_for_ticket to proceed with scanned and return ticket
        finish_login.set()
        await pilot.pause()
        await asyncio.sleep(0.05)
        await pilot.pause()

        # Modal should be dismissed
        assert not isinstance(app.screen, LoginModal)

        # Token should be stored
        stored = TokenStore.default().load()
        assert stored is not None
        assert stored.token == token_value


async def test_login_modal_listener_callbacks() -> None:
    """Test listener callback state updates in LoginModal."""
    api_factory = _make_dummy_api_factory()
    modal = LoginModal(api_factory=api_factory)

    app = DiscoopApp(api_factory=api_factory)
    async with app.run_test(size=(140, 40)) as pilot:
        app.push_screen(modal)
        await pilot.pause()

        # on_connecting (session 1)
        modal.on_connecting(1)
        assert str(modal.query_one("#qr-status-lbl", Label).content) == "Connecting to Discord QR gateway..."
        assert str(modal.query_one("#qr-box", Static).content) == ""

        # on_qr
        modal.on_qr("https://discord.com/ra/test1234", time.monotonic() + 60)
        assert "▀" in str(modal.query_one("#qr-box", Static).content)
        assert "Scan this QR code" in str(modal.query_one("#qr-status-lbl", Label).content)
        assert "Expires in" in str(modal.query_one("#qr-countdown-lbl", Label).content)

        # on_restart
        modal.on_restart("qr code expired")
        assert str(modal.query_one("#qr-box", Static).content) == ""
        assert "expired" in str(modal.query_one("#qr-status-lbl", Label).content).lower()
        assert str(modal.query_one("#qr-countdown-lbl", Label).content) == ""

        # on_connecting (session 2)
        modal.on_connecting(2)
        assert str(modal.query_one("#qr-status-lbl", Label).content) == "Getting a new QR code..."

        # on_scanned
        user = UserPayload(id="123", discriminator="0001", avatar=None, username="phone_user")
        modal.on_scanned(user)
        assert str(modal.query_one("#qr-box", Static).content) == ""
        assert "phone_user" in str(modal.query_one("#qr-status-lbl", Label).content)

        await pilot.press("escape")
        await pilot.pause()
        assert not isinstance(app.screen, LoginModal)


async def test_login_modal_paste_token_and_logout() -> None:
    """Test manual token pasting and logout in LoginModal."""
    TokenStore.default().delete()

    api_factory = _make_dummy_api_factory()
    app = DiscoopApp(api_factory=api_factory)
    async with app.run_test(size=(140, 40)) as pilot:
        await pilot.pause()

        # Open LoginModal
        modal = LoginModal(api_factory=api_factory)
        app.push_screen(modal)
        await pilot.pause()

        # Try save with empty token -> error
        await pilot.click("#btn-login-save")
        await pilot.pause()
        assert "Please enter a Discord token" in str(modal.query_one("#login-error", Label).content)

        # Enter token and save (pause to avoid double-click threshold)
        await asyncio.sleep(0.5)
        modal.query_one("#input-token", Input).value = "pasted-secret-token"
        await pilot.click("#btn-login-save")
        await pilot.pause()

        assert not isinstance(app.screen, LoginModal)
        assert TokenStore.default().load().token == "pasted-secret-token"

        # Reopen LoginModal to test logout
        modal2 = LoginModal(api_factory=api_factory)
        app.push_screen(modal2)
        await pilot.pause()

        assert modal2.query_one("#btn-login-logout") is not None
        await pilot.click("#btn-login-logout")
        await pilot.pause()

        assert not isinstance(app.screen, LoginModal)
        assert TokenStore.default().load() is None
