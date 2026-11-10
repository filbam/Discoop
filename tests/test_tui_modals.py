"""Pilot tests of the TUI dialogs. Offline: a fake Discord, an in-memory keyring and made-up messages."""

from __future__ import annotations

import asyncio
import base64
from datetime import timedelta
import json
from pathlib import Path
import re
import threading
import time
from typing import Any

import httpx
import pytest
from rich.text import Text
from textual.widgets import Button, Footer, Input, Label, Static

from discoop.cli import command_help
from discoop.config import Config
from discoop.models import Author, Channel, ChannelMessages, Message, Server
from discoop.remote_auth.crypto import OAEP_SHA256, RemoteAuthKeys, UserPayload
from discoop.remote_auth.protocol import LoginTicket
from discoop.tokenstore import TokenStore
from discoop.tui import modals
from discoop.tui.app import DiscoopApp
from discoop.tui.modals import (
    WINDOW_CANCELLED,
    HelpScreen,
    LoginModal,
    PreviewScreen,
    SettingsModal,
    TimeWindowModal,
)
from discoop.tui.state import WindowSpec
from discoop.tui.widgets import ActionRow, ChoiceRow, ConfirmRow, InputRow, TextView, wrapped
from fake_messages import NOW
from test_tui_app import _make_dummy_api_factory, notifications, screen_text, started, wait_until

QR_URL = "https://discord.com/ra/" + "a1B2c3D4e5" * 4 + "xyz"  # as long as a real one: 43 characters of fingerprint
USER = UserPayload(id="42", discriminator="0001", avatar=None, username="student_a")


def make_app(api_factory: Any = None) -> DiscoopApp:
    return DiscoopApp(api_factory=api_factory or _make_dummy_api_factory())


def shown_rows(app: DiscoopApp) -> list[Any]:
    rows = [*app.screen.query(ChoiceRow), *app.screen.query(InputRow), *app.screen.query(ActionRow)]
    rows += app.screen.query(Label)
    return [row for row in rows if row.display and all(parent.display for parent in row.ancestors)]


def painted(app: DiscoopApp) -> str:
    return screen_text(app, app.screen.region)


def preview_results(*texts: str) -> list[ChannelMessages]:
    author = Author("1", "Student A", "student_a")
    messages = tuple(
        Message(str(1000 + number), 0, NOW + timedelta(minutes=number), None, author, text)
        for number, text in enumerate(texts)
    )
    return [ChannelMessages(Server("1", "Study Group"), Channel("2", "1", "general", 0), messages)]


async def waits_forever(listener: Any, **kwargs: Any) -> LoginTicket:
    listener.on_connecting(1)
    listener.on_qr(QR_URL, time.monotonic() + 120)
    await asyncio.Event().wait()
    raise AssertionError("never comes back")


# ==================== All dialogs ====================


async def open_help(app: DiscoopApp, pilot: Any) -> None:
    await pilot.press("f1")


async def open_cli_help(app: DiscoopApp, pilot: Any) -> None:
    await pilot.press("f1")
    await pilot.pause()
    await pilot.press("right")


async def open_settings(app: DiscoopApp, pilot: Any) -> None:
    await pilot.press("f2")


async def open_login(app: DiscoopApp, pilot: Any) -> None:
    await pilot.press("f3")


async def open_login_with_a_token(app: DiscoopApp, pilot: Any) -> None:
    TokenStore.default().save("fake-token")
    await pilot.press("f3")


async def open_qr(app: DiscoopApp, pilot: Any) -> None:
    app.push_screen(LoginModal(_make_dummy_api_factory(), wait_for_ticket_fn=waits_forever))
    await pilot.pause()
    await pilot.press("g")


async def open_window(app: DiscoopApp, pilot: Any) -> None:
    app.push_screen(TimeWindowModal("general"))


async def open_window_error(app: DiscoopApp, pilot: Any) -> None:
    app.push_screen(TimeWindowModal("general"))
    await pilot.pause()
    app.screen.query_one("#modal-input-from", Input).value = "not-a-date"
    await pilot.press("enter")


async def open_preview(app: DiscoopApp, pilot: Any) -> None:
    app.push_screen(PreviewScreen(preview_results("first", "second")))


@pytest.mark.parametrize(
    "open_dialog",
    [
        open_help,
        open_cli_help,
        open_settings,
        open_login,
        open_login_with_a_token,
        open_qr,
        open_window,
        open_window_error,
        open_preview,
    ],
)
@pytest.mark.parametrize("size", [(140, 40), (80, 24)])
async def test_every_visible_row_of_a_dialog_shows_text(open_dialog: Any, size: tuple[int, int]) -> None:
    app = make_app()
    async with app.run_test(size=size) as pilot:
        await started(app, pilot)
        await open_dialog(app, pilot)
        await pilot.pause(0.05)
        assert app.screen is not app.screen_stack[0]

        assert not app.screen.query(Button)
        rows = shown_rows(app)
        assert rows
        for row in rows:
            assert row.region.height >= 1, row
            assert screen_text(app, row.region).strip(), row
        assert not re.search("[\U0001f300-\U0001faff☀-➿]", painted(app)), "no emoji"
        assert app.screen.focused is not None or app.screen.has_class("-qr"), "the keyboard works at once"


async def test_a_dialog_keeps_its_row_messages_from_the_app() -> None:
    """Regression risk: the app starts an export on any ActionRow.Pressed that reaches it."""
    app = make_app()
    async with app.run_test(size=(140, 40)) as pilot:
        await started(app, pilot)
        await pilot.press("f2")
        await pilot.pause()
        app.screen.query_one("#row-cfg-save", ActionRow).focus()
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()
        assert not isinstance(app.screen, SettingsModal)
        assert "No channels selected." not in notifications(app)


# ==================== Time window ====================


async def test_enter_in_a_window_field_saves() -> None:
    app = make_app()
    async with app.run_test(size=(140, 40)) as pilot:
        await started(app, pilot)
        dismissed: list[Any] = []
        app.push_screen(TimeWindowModal("general", global_spec=WindowSpec(from_="2026-10-01")), dismissed.append)
        await pilot.pause()
        assert app.focused is app.screen.query_one("#row-modal-window")

        await pilot.press("down", "down")  # To
        await pilot.pause()
        assert app.focused is app.screen.query_one("#modal-input-to", Input)
        await pilot.press(*"2026-10-15", "enter")
        await pilot.pause()

        assert dismissed == [WindowSpec(from_="2026-10-01", to="2026-10-15", last=None, max_messages=5000)]


async def test_window_row_and_fields_follow_each_other() -> None:
    app = make_app()
    async with app.run_test(size=(140, 40)) as pilot:
        await started(app, pilot)
        spec = WindowSpec(from_="2026-10-01", to="2026-10-15", last=20)
        modal = TimeWindowModal("general", current_spec=spec)
        dismissed: list[Any] = []
        app.push_screen(modal, dismissed.append)
        await pilot.pause()
        window = modal.query_one("#row-modal-window", ChoiceRow)
        assert window.value == "custom"

        await pilot.press("right")  # from custom to the first preset, which clears To and Last N
        await pilot.pause()
        assert window.value == "24h"
        assert modal.field("#modal-input-from") == "24h"
        assert modal.field("#modal-input-to") == ""
        assert modal.field("#modal-input-last") == ""

        modal.query_one("#modal-input-from", Input).value = "2w"
        await pilot.pause()
        assert window.value == "custom"
        modal.query_one("#modal-input-from", Input).value = "30d"
        await pilot.pause()
        assert window.value == "30d"
        modal.query_one("#modal-input-last", Input).value = "5"
        await pilot.pause()
        assert window.value == "custom"

        await pilot.press("enter")  # Enter on a choice row saves too
        await pilot.pause()
        assert dismissed == [WindowSpec(from_="30d", to=None, last=5, max_messages=5000)]


async def test_a_bad_window_stays_in_the_dialog() -> None:
    app = make_app()
    async with app.run_test(size=(140, 40)) as pilot:
        await started(app, pilot)
        modal = TimeWindowModal("general")
        app.push_screen(modal)
        await pilot.pause()
        error = modal.query_one("#modal-error", Label)
        assert not error.display

        modal.query_one("#modal-input-from", Input).value = "not-a-date"
        await pilot.press("enter")
        await pilot.pause()
        assert app.screen is modal
        assert error.display
        assert "not-a-date" in str(error.content)
        assert "not-a-date" in screen_text(app, error.region)

        modal.query_one("#modal-input-from", Input).value = "7d"
        modal.query_one("#modal-input-max", Input).value = "0"
        await pilot.press("enter")
        await pilot.pause()
        assert app.screen is modal
        assert "at least 1" in str(error.content)

        modal.query_one("#modal-input-max", Input).value = "100"
        await pilot.press("enter")
        await pilot.pause()
        assert app.screen is not modal


async def test_use_global_window_and_escape() -> None:
    app = make_app()
    async with app.run_test(size=(140, 40)) as pilot:
        await started(app, pilot)
        dismissed: list[Any] = []
        app.push_screen(TimeWindowModal("general"), dismissed.append)
        await pilot.pause()
        await pilot.press("escape")
        await pilot.pause()
        assert dismissed == [WINDOW_CANCELLED]

        app.push_screen(TimeWindowModal("general"), dismissed.append)
        await pilot.pause()
        app.screen.query_one("#row-modal-global", ActionRow).focus()
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()
        assert dismissed == [WINDOW_CANCELLED, None]


async def test_window_title_takes_brackets_literally() -> None:
    app = make_app()
    async with app.run_test(size=(140, 40)) as pilot:
        await started(app, pilot)
        app.push_screen(TimeWindowModal("[bold]general"))
        await pilot.pause()
        assert "#[bold]general" in painted(app)


# ==================== Settings ====================


async def test_settings_mode_reaches_the_config_and_the_main_screen(tmp_path: Path) -> None:
    app = make_app()
    async with app.run_test(size=(140, 40)) as pilot:
        await started(app, pilot)
        assert app.settings.mode == "safe"

        await pilot.press("f2")
        await pilot.pause()
        modal = app.screen
        assert isinstance(modal, SettingsModal)
        mode = modal.query_one("#row-cfg-mode", ChoiceRow)
        assert app.focused is mode
        assert mode.value == "safe"

        await pilot.press("left")  # wraps around
        await pilot.pause()
        assert mode.value == "fast"

        modal.query_one("#input-cfg-export-dir", Input).value = str(tmp_path)
        modal.query_one("#input-cfg-server", Input).value = "Study Group"
        modal.query_one("#input-cfg-delay", Input).focus()
        await pilot.pause()
        await pilot.press("enter")  # Enter in a field saves
        await pilot.pause()

        assert not isinstance(app.screen, SettingsModal)
        config = Config.default()
        assert config.get("mode") == "fast"
        assert config.get("default-server") == "Study Group"
        assert config.get("export-dir") == str(tmp_path)
        assert app.settings.mode == "fast"
        assert app.query_one("#row-mode", ChoiceRow).value == "fast"
        assert str(app.query_one("#mode-indicator", Label).content) == "fast"


async def test_settings_export_folder_shows_the_real_default(tmp_path: Path) -> None:
    app = make_app()
    async with app.run_test(size=(140, 40)) as pilot:
        await started(app, pilot)
        await pilot.press("f2")
        await pilot.pause()
        field = app.screen.query_one("#input-cfg-export-dir", Input)
        assert field.value == ""
        assert field.placeholder == str(tmp_path / "documents" / "discoop")
        assert not (tmp_path / "documents").exists()


async def test_settings_escape_changes_nothing() -> None:
    app = make_app()
    async with app.run_test(size=(140, 40)) as pilot:
        await started(app, pilot)
        await pilot.press("f2", "right")
        await pilot.pause()
        await pilot.press("escape")
        await pilot.pause()
        assert not isinstance(app.screen, SettingsModal)
        assert Config.default().get("mode") == "safe"
        assert app.settings.mode == "safe"


async def test_settings_keep_a_browser_path_they_do_not_show(tmp_path: Path) -> None:
    """`browser-path` (for `login --browser`) is a known setting that the dialog has no row for yet: saving the other
    rows must neither break the dialog nor lose the value."""
    program = tmp_path / "chrome.exe"
    program.write_text("not really a browser", encoding="utf-8")
    Config.default().set("browser-path", str(program))
    app = make_app()
    async with app.run_test(size=(140, 40)) as pilot:
        await started(app, pilot)
        await pilot.press("f2", "left")  # open the dialog, change the mode
        await pilot.pause()
        modal = app.screen
        assert isinstance(modal, SettingsModal)
        modal.query_one("#input-cfg-delay", Input).focus()
        await pilot.press("enter")
        await pilot.pause()
        assert not isinstance(app.screen, SettingsModal)
    config = Config.default()
    assert config.get("mode") == "fast"
    assert config.get("browser-path") == str(program)


async def test_settings_reject_a_bad_delay() -> None:
    app = make_app()
    async with app.run_test(size=(140, 40)) as pilot:
        await started(app, pilot)
        await pilot.press("f2")
        await pilot.pause()
        modal = app.screen
        modal.query_one("#input-cfg-delay", Input).value = "-1"
        await pilot.press("enter")
        await pilot.pause()
        assert app.screen is modal
        assert "not a valid delay" in str(modal.query_one("#settings-error", Label).content)
        assert Config.default().get("delay") == 1.0


async def test_settings_open_with_a_broken_config() -> None:
    app = make_app()
    async with app.run_test(size=(140, 40)) as pilot:
        await started(app, pilot)
        path = Config.default().path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("not = valid = toml", encoding="utf-8")

        await pilot.press("f2")
        await pilot.pause()
        assert isinstance(app.screen, SettingsModal)
        assert "Cannot read" in str(app.screen.query_one("#settings-error", Label).content)


# ==================== Login ====================


async def test_login_modal_qr_code_display_and_login() -> None:
    keys = RemoteAuthKeys()
    user = UserPayload(id="42", discriminator="0001", avatar=None, username="qr_user")
    token_value = "qr-auth-token-xyz"

    def mock_handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if "remote-auth/login" in path:
            assert json.loads(request.content) == {"ticket": "test-ticket-999"}
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
        await started(app, pilot)
        modal = LoginModal(api_factory=api_factory, wait_for_ticket_fn=fake_wait_for_ticket)
        app.push_screen(modal)
        await pilot.pause()
        assert app.focused is modal.query_one("#row-login-qr")

        await pilot.press("enter")  # the Generate row, like g
        await qr_shown.wait()
        await pilot.pause()

        assert "▀" in str(modal.query_one("#qr-box", Static).content)
        assert "Scan it in the Discord app" in str(modal.query_one("#qr-status-lbl", Label).content)
        assert "Expires in" in str(modal.query_one("#qr-countdown-lbl", Label).content)
        assert not modal.query_one("#login-form").display

        finish_login.set()
        await wait_until(pilot, lambda: not isinstance(app.screen, LoginModal))

        stored = TokenStore.default().load()
        assert stored is not None
        assert stored.token == token_value
        assert any("qr_user" in message for message in notifications(app))


async def test_login_modal_listener_callbacks() -> None:
    api_factory = _make_dummy_api_factory()
    modal = LoginModal(api_factory=api_factory)
    app = DiscoopApp(api_factory=api_factory)
    async with app.run_test(size=(140, 40)) as pilot:
        await started(app, pilot)
        app.push_screen(modal)
        await pilot.pause()

        modal.on_connecting(1)
        assert str(modal.query_one("#qr-status-lbl", Label).content) == "Connecting to the Discord QR gateway..."
        assert str(modal.query_one("#qr-box", Static).content) == ""

        modal.on_qr("https://discord.com/ra/test1234", time.monotonic() + 60)
        assert "▀" in str(modal.query_one("#qr-box", Static).content)
        assert "Scan it" in str(modal.query_one("#qr-status-lbl", Label).content)
        assert "Expires in" in str(modal.query_one("#qr-countdown-lbl", Label).content)

        modal.on_restart("qr code expired")
        assert str(modal.query_one("#qr-box", Static).content) == ""
        assert "expired" in str(modal.query_one("#qr-status-lbl", Label).content).lower()
        assert str(modal.query_one("#qr-countdown-lbl", Label).content) == ""

        modal.on_connecting(2)
        assert str(modal.query_one("#qr-status-lbl", Label).content) == "Getting a new QR code..."

        modal.on_scanned(UserPayload(id="123", discriminator="0001", avatar=None, username="phone_user"))
        assert str(modal.query_one("#qr-box", Static).content) == ""
        assert "phone_user" in str(modal.query_one("#qr-status-lbl", Label).content)

        await pilot.press("escape")
        await pilot.pause()
        assert not isinstance(app.screen, LoginModal)


async def test_login_modal_paste_token_and_logout() -> None:
    api_factory = _make_dummy_api_factory()
    app = DiscoopApp(api_factory=api_factory)
    async with app.run_test(size=(140, 40)) as pilot:
        await started(app, pilot)
        modal = LoginModal(api_factory=api_factory)
        app.push_screen(modal)
        await pilot.pause()

        await pilot.press("down")  # the token field
        await pilot.pause()
        token_input = modal.query_one("#input-token", Input)
        assert app.focused is token_input
        assert token_input.password

        await pilot.press("enter")
        await pilot.pause()
        assert "Please enter a Discord token" in str(modal.query_one("#login-error", Label).content)

        await pilot.press(*"pasted-secret-token", "enter")
        await wait_until(pilot, lambda: not isinstance(app.screen, LoginModal))
        assert TokenStore.default().load().token == "pasted-secret-token"

        modal2 = LoginModal(api_factory=api_factory)
        app.push_screen(modal2)
        await pilot.pause()
        logout = modal2.query_one("#row-login-logout", ConfirmRow)
        await pilot.press("down", "down", "down")
        await pilot.pause()
        assert app.focused is logout
        await pilot.press("enter", "enter")
        await pilot.pause()
        assert not isinstance(app.screen, LoginModal)
        assert TokenStore.default().load() is None


async def test_login_shows_a_refused_token_and_can_try_again() -> None:
    answers = [401, 200]

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(answers.pop(0), json={"id": "42", "username": "student_a", "message": "no", "code": 0})

    api_factory = _make_dummy_api_factory(transport=httpx.MockTransport(handler))
    app = DiscoopApp(api_factory=api_factory)
    async with app.run_test(size=(140, 40)) as pilot:
        await started(app, pilot)
        modal = LoginModal(api_factory=api_factory)
        app.push_screen(modal)
        await pilot.pause()
        row = modal.query_one("#row-login-save", ActionRow)
        modal.query_one("#input-token", Input).value = "expired-token"
        row.focus()
        await pilot.pause()
        await pilot.press("enter")
        error = modal.query_one("#login-error", Label)
        await wait_until(pilot, lambda: error.display)
        assert app.screen is modal
        assert TokenStore.default().load() is None
        assert "Verify" in str(row.content)

        await pilot.press("enter")
        await wait_until(pilot, lambda: app.screen is not modal)
        assert TokenStore.default().load().token == "expired-token"


class SlowDiscord:
    """A `get_me` that hangs until the test lets it go."""

    def __init__(self) -> None:
        self.calls = 0
        self.arrived = threading.Event()
        self.release = threading.Event()

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.calls += 1
        self.arrived.set()
        self.release.wait(10)
        return httpx.Response(200, json={"id": "42", "username": "student_a"})


async def test_verifying_a_token_does_not_block_the_ui() -> None:
    discord = SlowDiscord()
    api_factory = _make_dummy_api_factory(transport=httpx.MockTransport(discord.handle))
    app = DiscoopApp(api_factory=api_factory)
    async with app.run_test(size=(140, 40)) as pilot:
        await started(app, pilot)
        modal = LoginModal(api_factory=api_factory)
        app.push_screen(modal)
        await pilot.pause()
        token_input = modal.query_one("#input-token", Input)
        token_input.value = "pasted-token"
        token_input.focus()
        await pilot.pause()

        try:
            await pilot.press("enter")
            await wait_until(pilot, discord.arrived.is_set)
            assert "Verifying" in str(modal.query_one("#row-login-save", ActionRow).content)

            ticks: list[int] = []
            modal.set_interval(0.01, lambda: ticks.append(1))
            await wait_until(pilot, lambda: len(ticks) >= 3)  # the event loop runs during get_me

            await pilot.press("enter")  # a second Enter starts nothing
            await pilot.press("g")  # types into the field, and no QR login starts
            await pilot.pause()
            assert discord.calls == 1
            assert not modal.has_class("-qr")
        finally:
            discord.release.set()

        await wait_until(pilot, lambda: app.screen is not modal)
        assert TokenStore.default().load().token == "pasted-token"


async def test_escape_during_verification_stores_nothing() -> None:
    discord = SlowDiscord()
    api_factory = _make_dummy_api_factory(transport=httpx.MockTransport(discord.handle))
    app = DiscoopApp(api_factory=api_factory)
    async with app.run_test(size=(140, 40)) as pilot:
        await started(app, pilot)
        modal = LoginModal(api_factory=api_factory)
        app.push_screen(modal)
        await pilot.pause()
        token_input = modal.query_one("#input-token", Input)
        token_input.value = "pasted-token"
        token_input.focus()
        await pilot.pause()

        try:
            await pilot.press("enter")
            await wait_until(pilot, discord.arrived.is_set)
            await pilot.press("escape")
            await pilot.pause()
            assert app.screen is not modal
        finally:
            discord.release.set()
        await pilot.pause(0.1)
        assert TokenStore.default().load() is None


async def test_logout_needs_confirmation() -> None:
    TokenStore.default().save("fake-token")
    app = make_app()
    async with app.run_test(size=(140, 40)) as pilot:
        await started(app, pilot)
        modal = LoginModal(api_factory=_make_dummy_api_factory())
        app.push_screen(modal)
        await pilot.pause()
        logout = modal.query_one("#row-login-logout", ConfirmRow)
        logout.focus()
        await pilot.pause()

        await pilot.press("enter")
        await pilot.pause()
        assert app.screen is modal
        assert TokenStore.default().load() is not None
        assert str(logout.content) == "Press Enter again to confirm"
        assert "Press Enter again to confirm" in screen_text(app, logout.region)

        await pilot.press("up")  # moving away takes the question back
        await pilot.pause()
        assert str(logout.content) == "[ Log out ]"
        await pilot.press("down", "enter")
        await pilot.pause()
        assert app.screen is modal
        assert TokenStore.default().load() is not None

        await pilot.press("escape")
        await pilot.pause()
        assert TokenStore.default().load() is not None


async def test_closing_login_stops_the_qr_worker_and_the_timer() -> None:
    cancelled = asyncio.Event()

    async def fake_wait_for_ticket(listener: Any, **kwargs: Any) -> LoginTicket:
        listener.on_qr(QR_URL, time.monotonic() + 120)
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            cancelled.set()
            raise
        raise AssertionError("never comes back")

    app = make_app()
    async with app.run_test(size=(140, 40)) as pilot:
        await started(app, pilot)
        modal = LoginModal(_make_dummy_api_factory(), wait_for_ticket_fn=fake_wait_for_ticket)
        app.push_screen(modal)
        await pilot.pause()
        await pilot.press("g")
        await wait_until(pilot, lambda: "▀" in str(modal.query_one("#qr-box", Static).content))
        timer = modal._countdown_timer
        assert timer is not None

        await pilot.press("g")  # the running login stays the only one
        await pilot.pause()
        assert modal._countdown_timer is timer
        assert len(modal.workers) == 1

        await pilot.press("escape")
        await wait_until(pilot, lambda: app.screen is not modal)
        assert cancelled.is_set()
        assert modal._countdown_timer is None
        assert not modal.workers


async def test_a_failed_qr_login_goes_back_to_the_form() -> None:
    async def refused(listener: Any, **kwargs: Any) -> LoginTicket:
        listener.on_connecting(1)
        raise ConnectionError("no route to host")

    app = make_app()
    async with app.run_test(size=(140, 40)) as pilot:
        await started(app, pilot)
        modal = LoginModal(_make_dummy_api_factory(), wait_for_ticket_fn=refused)
        app.push_screen(modal)
        await pilot.pause()
        await pilot.press("g")
        error = modal.query_one("#login-error", Label)
        await wait_until(pilot, lambda: error.display)
        assert "no route to host" in str(error.content)
        assert modal.query_one("#login-form").display
        assert app.focused is modal.query_one("#row-login-qr")
        assert modal._countdown_timer is None


async def test_qr_code_keeps_its_black_and_white_in_the_terminal_theme() -> None:
    app = make_app()
    async with app.run_test(size=(140, 40)) as pilot:
        await started(app, pilot)
        assert app.current_theme.ansi
        await open_qr(app, pilot)
        await pilot.pause(0.05)

        colors = set()
        rows = 0
        for strip in app.screen._compositor.render_strips():
            segments = [segment for segment in strip if "▀" in segment.text]
            rows += bool(segments)
            for segment in segments:
                colors |= {segment.style.color.name, segment.style.bgcolor.name}
        assert colors == {"#000000", "#ffffff"}
        assert rows == 23


async def test_qr_code_fits_an_80x24_window_in_one_piece() -> None:
    app = make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        await started(app, pilot)
        await open_qr(app, pilot)
        await pilot.pause(0.05)
        modal = app.screen
        box = modal.query_one("#qr-box").region

        assert modal.has_class("-short")
        assert box.y >= 0 and box.bottom <= 24
        assert box.height == 23
        assert sum("▀" in line for line in painted(app).splitlines()) == 23
        assert "Scan it" in painted(app), "the status stays visible"

        qr_line = painted(app).splitlines()[1]
        assert qr_line.index("▀") == (80 - qr_line.count("▀")) // 2, "centred"
        assert not modal.query_one(Footer).display

        await pilot.press("escape")
        await pilot.pause()
        assert not isinstance(app.screen, LoginModal)


async def test_qr_code_scrolls_in_an_even_shorter_window() -> None:
    app = make_app()
    async with app.run_test(size=(80, 18)) as pilot:
        await started(app, pilot)
        await open_qr(app, pilot)
        await pilot.pause(0.05)
        pane = app.screen.query_one(".dialog-scroll")
        assert pane.max_scroll_y > 0

        await pilot.press("end")
        await wait_until(pilot, lambda: pane.scroll_y == pane.max_scroll_y)
        await pilot.press("up")
        await wait_until(pilot, lambda: pane.scroll_y < pane.max_scroll_y)


async def test_qr_view_keeps_frame_and_footer_in_a_tall_window() -> None:
    app = make_app()
    async with app.run_test(size=(100, 40)) as pilot:
        await started(app, pilot)
        await open_qr(app, pilot)
        await pilot.pause(0.05)
        modal = app.screen
        assert modal.has_class("-tall")
        assert modal.query_one(Footer).display
        assert "Login" in painted(app)


# ==================== Preview ====================

TRICKY = ("[bold]not markup[/bold] and [1]", '["json", {"a": 1}]', "[/closing] tag")


@pytest.mark.parametrize("fmt", ["text", "md", "json", "jsonl"])
async def test_preview_shows_brackets_literally(fmt: str) -> None:
    app = make_app()
    async with app.run_test(size=(140, 40)) as pilot:
        await started(app, pilot)
        app.push_screen(PreviewScreen(preview_results(*TRICKY), initial_format=fmt))
        await pilot.pause()
        view = app.screen.query_one("#preview-content", TextView)
        assert "[bold]not markup[/bold] and [1]" in str(view.content)
        await pilot.press("end")  # the JSON header takes more than a screen
        await wait_until(pilot, lambda: view.scroll_y == view.max_scroll_y)
        assert "[/closing] tag" in painted(app)


async def test_preview_format_row_switches_and_keeps_the_rendered_text() -> None:
    app = make_app()
    async with app.run_test(size=(140, 40)) as pilot:
        await started(app, pilot)
        modal = PreviewScreen(preview_results("hello"))
        rendered: list[str] = []
        render = modal._render_format
        modal._render_format = lambda fmt: rendered.append(fmt) or render(fmt)
        app.push_screen(modal)
        await pilot.pause()
        assert app.focused is modal.query_one("#row-preview-format")

        await pilot.press("right")
        await pilot.pause()
        assert modal.current_format == "md"
        await pilot.press("right")
        await pilot.pause()
        assert modal.current_format == "json"
        assert '"text": "hello"' in str(modal.query_one("#preview-content", TextView).content)
        await pilot.press("left", "left", "right", "right")
        await pilot.pause()
        assert rendered == ["text", "md", "json"]


async def test_preview_search_filters_lines_after_a_pause(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(modals, "SEARCH_DELAY", 0.3)
    app = make_app()
    async with app.run_test(size=(140, 40)) as pilot:
        await started(app, pilot)
        modal = PreviewScreen(preview_results("alpha [one]", "beta [two]", "ALPHA three"))
        app.push_screen(modal)
        await pilot.pause()
        content = modal.query_one("#preview-content", TextView)
        updates: list[Any] = []
        update = content.update
        content.update = lambda text: updates.append(text) or update(text)

        await pilot.press("slash")
        await pilot.pause()
        search = modal.query_one("#preview-search", Input)
        assert app.focused is search

        await pilot.press(*"alpha")
        assert not updates, "nothing renders while the user types"
        await wait_until(pilot, lambda: updates)
        assert len(updates) == 1
        shown = str(content.content)
        assert "alpha [one]" in shown and "ALPHA three" in shown and "beta" not in shown

        search.value = "[/nothing]"
        await wait_until(pilot, lambda: len(updates) == 2)
        assert str(content.content) == "(no lines matching '[/nothing]')"
        assert "(no lines matching '[/nothing]')" in painted(app)

        await pilot.press("enter")  # back to the format row, the search stays
        await pilot.pause()
        assert app.focused is modal.query_one("#row-preview-format")
        assert search.value == "[/nothing]"


async def test_preview_scroll_keys_work_from_the_format_row() -> None:
    app = make_app()
    async with app.run_test(size=(100, 30)) as pilot:
        await started(app, pilot)
        modal = PreviewScreen(preview_results(*(f"message {number}" for number in range(300))))
        app.push_screen(modal)
        await pilot.pause()
        pane = modal.query_one(".dialog-scroll")
        row = modal.query_one("#row-preview-format")
        assert app.focused is row
        assert pane.max_scroll_y > 100

        await pilot.press("down")
        await wait_until(pilot, lambda: pane.scroll_y == 1)
        await pilot.press("pagedown")
        await wait_until(pilot, lambda: pane.scroll_y > 10)
        await pilot.press("up")
        await pilot.press("end")
        await wait_until(pilot, lambda: pane.scroll_y == pane.max_scroll_y)
        await pilot.press("pageup")
        await wait_until(pilot, lambda: pane.scroll_y < pane.max_scroll_y)
        await pilot.press("home")
        await wait_until(pilot, lambda: pane.scroll_y == 0)
        assert app.focused is row

        # ↑↓ from the search field scroll too
        await pilot.press("slash")
        await pilot.pause()
        await pilot.press("down")
        await wait_until(pilot, lambda: pane.scroll_y == 1)


async def test_preview_escape_leaves_the_search_then_closes() -> None:
    app = make_app()
    async with app.run_test(size=(100, 30)) as pilot:
        await started(app, pilot)
        app.push_screen(PreviewScreen(preview_results("hello")))
        await pilot.pause()
        await pilot.press("slash")
        await pilot.pause()
        await pilot.press("s")  # a letter in the search, not Save
        await pilot.pause()
        assert app.screen.field("#preview-search") == "s"
        assert not notifications(app)

        await pilot.press("escape")
        await pilot.pause()
        assert isinstance(app.screen, PreviewScreen)
        await pilot.press("escape")
        await pilot.pause()
        assert not isinstance(app.screen, PreviewScreen)


async def test_preview_tab_goes_between_format_and_search() -> None:
    app = make_app()
    async with app.run_test(size=(100, 30)) as pilot:
        await started(app, pilot)
        app.push_screen(PreviewScreen(preview_results("hello")))
        await pilot.pause()
        await pilot.press("tab")
        await pilot.pause()
        assert app.focused is app.screen.query_one("#preview-search", Input)
        await pilot.press("tab")
        await pilot.pause()
        assert app.focused is app.screen.query_one("#row-preview-format")


async def test_saving_a_preview_keeps_existing_files(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    existing = tmp_path / "exports" / "discoop-preview.txt"
    existing.parent.mkdir()
    existing.write_text("the user's earlier file", encoding="utf-8")

    app = make_app()
    async with app.run_test(size=(100, 30)) as pilot:
        await started(app, pilot)
        app.push_screen(PreviewScreen(preview_results("hello [world]")))
        await pilot.pause()

        await pilot.press("s")
        await pilot.pause()
        await pilot.press("s")
        await pilot.pause()

        assert existing.read_text(encoding="utf-8") == "the user's earlier file"
        second = existing.with_name("discoop-preview-2.txt")
        third = existing.with_name("discoop-preview-3.txt")
        assert "hello [world]" in second.read_text(encoding="utf-8")
        assert third.exists()
        assert any(str(second.resolve()) in message for message in notifications(app))


async def test_saving_a_preview_uses_the_export_folder(tmp_path: Path) -> None:
    Config.default().set("export-dir", str(tmp_path / "my [exports]"))
    app = make_app()
    async with app.run_test(size=(100, 30)) as pilot:
        await started(app, pilot)
        app.push_screen(PreviewScreen(preview_results("hello"), initial_format="jsonl"))
        await pilot.pause()
        await pilot.press("s")
        await pilot.pause()
        saved = tmp_path / "my [exports]" / "discoop-preview.jsonl"
        assert '"hello"' in saved.read_text(encoding="utf-8")
        assert any(str(saved) in message for message in notifications(app))


async def test_saving_a_preview_reports_a_failure(tmp_path: Path) -> None:
    blocked = tmp_path / "a-file"
    blocked.write_text("", encoding="utf-8")
    Config.default().set("export-dir", str(blocked / "folder"))
    app = make_app()
    async with app.run_test(size=(100, 30)) as pilot:
        await started(app, pilot)
        app.push_screen(PreviewScreen(preview_results("hello")))
        await pilot.pause()
        await pilot.press("s")
        await pilot.pause()
        assert isinstance(app.screen, PreviewScreen)
        assert any("Failed to save" in message for message in notifications(app))


async def test_text_view_wraps_and_keeps_styles() -> None:
    assert wrapped("short", 10) == [(0, 5)]
    assert wrapped("aaa bbb ccc", 5) == [(0, 4), (4, 8), (8, 11)]
    assert wrapped("x" * 12, 5) == [(0, 5), (5, 10), (10, 12)]
    assert wrapped("", 5) == [(0, 0)]
    assert wrapped("\u4e2d" * 4, 4) == [(0, 2), (2, 4)], "two cells each"

    app = make_app()
    async with app.run_test(size=(60, 24)) as pilot:
        await started(app, pilot)
        styled = Text("bold start ")
        styled.stylize("bold", 0, 10)
        styled.append("[not markup]\tafter a tab\n" + "word " * 30)
        modal = PreviewScreen(preview_results("x"))
        app.push_screen(modal)
        await pilot.pause()
        view = modal.query_one(TextView)
        view.update(styled)
        await pilot.pause()

        text = painted(app)
        assert "bold start [not markup] after a tab" in text
        assert "word word" in text
        assert view.virtual_size.height > 2
        strips = app.screen._compositor.render_strips()
        assert any(segment.style.bold and "bold start" in segment.text for strip in strips for segment in strip)


async def test_a_big_preview_changes_at_once() -> None:
    """Regression: a `Static` took seconds on the UI thread here, for every format and every search."""
    app = make_app()
    async with app.run_test(size=(100, 30)) as pilot:
        await started(app, pilot)
        modal = PreviewScreen(preview_results(*(f"message {number} " * 20 for number in range(5000))))
        app.push_screen(modal)
        await pilot.pause()
        view = modal.query_one(TextView)
        assert view.virtual_size.height > 5000

        started_at = time.monotonic()
        view.update(modal._plain())
        await pilot.pause()
        assert time.monotonic() - started_at < 2.0
        await pilot.press("end")
        await wait_until(pilot, lambda: view.scroll_y == view.max_scroll_y)
        assert "message 4999" in painted(app)


# ==================== Help ====================


async def test_help_screen_shows_guide_and_cli_help() -> None:
    app = make_app()
    async with app.run_test(size=(140, 40)) as pilot:
        await started(app, pilot)
        await pilot.press("f1")
        await pilot.pause()
        assert isinstance(app.screen, HelpScreen)
        content = app.screen.query_one("#help-content", TextView)
        topic = app.screen.query_one("#row-help-topic", ChoiceRow)
        assert app.focused is topic
        assert "Space" in str(content.content)

        await pilot.press("right")
        await pilot.pause()
        assert topic.value == "discoop"
        assert str(content.content) == command_help(())
        assert "NOTE FOR AI AGENTS" in str(content.content)

        await pilot.press("right")
        await pilot.pause()
        assert topic.value == "messages"
        assert "--safe" in str(content.content) and "--fast" in str(content.content)

        await pilot.press("escape")
        await pilot.pause()
        assert not isinstance(app.screen, HelpScreen)


async def test_help_lists_the_keys_of_the_adr() -> None:
    app = make_app()
    async with app.run_test(size=(140, 60)) as pilot:
        await started(app, pilot)
        await pilot.press("question_mark")
        await pilot.pause()
        guide = str(app.screen.query_one("#help-content", TextView).content)
        keys = {key for key, _ in modals.GUIDE_KEYS}
        expected = {"↑ ↓", "→", "←", "← →", "Space", "Enter", "Tab, Shift+Tab", "1 2 3", "/", "e", "x, Delete", "X", "a"}
        expected |= {"r", "R", "L", "F5", "Esc", "c", "F1, ?", "F2", "F3", "Ctrl+P", "q"}
        expected |= {"P", "p", "o"}  # save a profile, load a profile, open the export folder
        assert keys == expected
        for key in expected:
            assert key in guide
        for topic in ("Tree", "Selection", "Form", "Time windows", "Safe and fast"):
            assert topic in guide
        flat = " ".join(guide.split())
        for phrase in ("Folder and Name", "Documents/discoop", "discord-export", "Export folder in Settings"):
            assert phrase in flat
        assert "J, K" not in guide and "Arrows" not in guide
        assert not re.search("[\U0001f300-\U0001faff☀-➿]", guide)

        await pilot.press("question_mark")  # the same key closes it
        await pilot.pause()
        assert not isinstance(app.screen, HelpScreen)


async def test_cli_help_keeps_its_square_brackets() -> None:
    app = make_app()
    async with app.run_test(size=(140, 40)) as pilot:
        await started(app, pilot)
        await pilot.press("f1")
        await pilot.pause()
        await pilot.press("right", "right")
        await pilot.pause()
        assert "discoop messages [OPTIONS]" in painted(app)


async def test_help_scrolls_from_the_topic_row() -> None:
    app = make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        await started(app, pilot)
        await pilot.press("f1")
        await pilot.pause()
        pane = app.screen.query_one(".dialog-scroll")
        assert pane.max_scroll_y > 0
        await pilot.press("down", "down")
        await wait_until(pilot, lambda: pane.scroll_y == 2)
        await pilot.press("right")  # another topic starts at the top
        await wait_until(pilot, lambda: pane.scroll_y == 0)
