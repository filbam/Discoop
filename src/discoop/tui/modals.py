"""Modal dialogs for the discoop TUI.

Provides:
- TimeWindowModal: per-channel custom time window configuration.
- HelpScreen: interactive guide and live CLI reference (--help).
- PreviewScreen: terminal inspection and format switching for fetched messages.
- SettingsModal: user configuration editor.
- LoginModal: token authentication and logout manager.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Sequence
from datetime import datetime
from pathlib import Path
import time
from typing import Any

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.timer import Timer
from textual.widgets import (
    Button,
    Input,
    Label,
    Static,
    TabbedContent,
    TabPane,
)

from discoop import login as login_flow
from discoop.api import DiscordAPI
from discoop.cache import clear_cache
from discoop.cli import LOCAL_ZONE
from discoop.config import Config
from discoop.errors import DiscoopError
from discoop.models import ChannelMessages
from discoop.qr import qr_text
from discoop.remote_auth.crypto import UserPayload
from discoop.remote_auth.protocol import GATEWAY_URL, LoginTicket, wait_for_ticket
from discoop.remote_auth.trace import Trace
from discoop.render import Query, jsonout, text as text_render
from discoop.snowflake import Window, parse_window, utc_now
from discoop.tokenstore import TokenStore
from discoop.tui.state import WindowSpec

# Graceful import of command_help
try:
    from discoop.cli import command_help
except (ImportError, AttributeError):

    def command_help(path: Sequence[str] = ()) -> str:  # type: ignore[no-redef]
        try:
            from typer.testing import CliRunner
            from discoop.cli import app

            runner = CliRunner()
            args = list(path) + ["--help"]
            res = runner.invoke(app, args)
            return res.output or f"Help for {path}"
        except Exception as e:
            return f"discoop help ({e})"


WINDOW_CANCELLED = object()


class TimeWindowModal(ModalScreen[Any]):
    """Modal for configuring a custom time window for a channel."""

    BINDINGS = [
        Binding("escape", "cancel", "Cancel"),
        Binding("enter", "save", "Save"),
    ]

    def __init__(
        self,
        channel_name: str,
        current_spec: WindowSpec | None = None,
        global_spec: WindowSpec | None = None,
    ) -> None:
        super().__init__()
        self.channel_name = channel_name
        self.current_spec = current_spec
        self.global_spec = global_spec or WindowSpec()

    def compose(self) -> ComposeResult:
        spec = self.current_spec or self.global_spec
        with Container(classes="modal-dialog"):
            yield Label(f"Custom Time Window: #{self.channel_name}", classes="modal-title")

            yield Label("Quick Presets:", classes="section-label")
            with Horizontal(classes="button-bar"):
                yield Button("24h", id="btn-modal-24h")
                yield Button("7d", id="btn-modal-7d")
                yield Button("30d", id="btn-modal-30d")
                yield Button("All", id="btn-modal-all")

            with Vertical():
                with Horizontal(classes="input-row"):
                    yield Label("From (--from):")
                    yield Input(
                        value=spec.from_ or "",
                        placeholder="e.g. 24h, 7d, 2026-10-01, all",
                        id="modal-input-from",
                    )
                with Horizontal(classes="input-row"):
                    yield Label("To (--to):")
                    yield Input(
                        value=spec.to or "",
                        placeholder="e.g. now, 2026-10-15 (optional)",
                        id="modal-input-to",
                    )
                with Horizontal(classes="input-row"):
                    yield Label("Last (--last):")
                    yield Input(
                        value=str(spec.last) if spec.last is not None else "",
                        placeholder="N most recent messages (optional)",
                        id="modal-input-last",
                    )
                with Horizontal(classes="input-row"):
                    yield Label("Max messages:")
                    yield Input(
                        value=str(spec.max_messages),
                        placeholder="Safety limit (default: 5000)",
                        id="modal-input-max",
                    )

            yield Label("", id="modal-error", classes="error-text")

            with Horizontal(classes="modal-buttons"):
                yield Button("Save Window", variant="primary", id="btn-modal-save")
                yield Button("Use Global Window", variant="warning", id="btn-modal-use-global")
                yield Button("Cancel", variant="default", id="btn-modal-cancel")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        button_id = event.button.id
        if button_id == "btn-modal-24h":
            self.query_one("#modal-input-from", Input).value = "24h"
            self.query_one("#modal-input-to", Input).value = ""
            self.query_one("#modal-input-last", Input).value = ""
        elif button_id == "btn-modal-7d":
            self.query_one("#modal-input-from", Input).value = "7d"
            self.query_one("#modal-input-to", Input).value = ""
            self.query_one("#modal-input-last", Input).value = ""
        elif button_id == "btn-modal-30d":
            self.query_one("#modal-input-from", Input).value = "30d"
            self.query_one("#modal-input-to", Input).value = ""
            self.query_one("#modal-input-last", Input).value = ""
        elif button_id == "btn-modal-all":
            self.query_one("#modal-input-from", Input).value = "all"
            self.query_one("#modal-input-to", Input).value = ""
            self.query_one("#modal-input-last", Input).value = ""
        elif button_id == "btn-modal-save":
            self.action_save()
        elif button_id == "btn-modal-use-global":
            self.dismiss(None)
        elif button_id == "btn-modal-cancel":
            self.action_cancel()

    def action_cancel(self) -> None:
        self.dismiss(WINDOW_CANCELLED)

    def action_save(self) -> None:
        error_label = self.query_one("#modal-error", Label)
        error_label.update("")

        from_raw = self.query_one("#modal-input-from", Input).value.strip() or None
        to_raw = self.query_one("#modal-input-to", Input).value.strip() or None
        last_raw = self.query_one("#modal-input-last", Input).value.strip()
        max_raw = self.query_one("#modal-input-max", Input).value.strip()

        last_val: int | None = None
        if last_raw:
            try:
                last_val = int(last_raw)
                if last_val < 1:
                    error_label.update("--last must be at least 1.")
                    return
            except ValueError:
                error_label.update("--last must be a valid number.")
                return

        max_val = 5000
        if max_raw:
            try:
                max_val = int(max_raw)
                if max_val < 1:
                    error_label.update("--max-messages must be at least 1.")
                    return
            except ValueError:
                error_label.update("--max-messages must be a valid number.")
                return

        # Validate with parse_window
        try:
            parse_window(
                from_raw,
                to_raw,
                now=utc_now(),
                tz=LOCAL_ZONE,
                whole_history=last_val is not None,
            )
        except DiscoopError as e:
            error_label.update(e.message)
            return
        except Exception as e:
            error_label.update(str(e))
            return

        spec = WindowSpec(
            from_=from_raw,
            to=to_raw,
            last=last_val,
            max_messages=max_val,
        )
        self.dismiss(spec)


class HelpScreen(ModalScreen[None]):
    """Modal displaying interactive TUI navigation guide and CLI reference."""

    BINDINGS = [
        Binding("escape", "dismiss", "Close"),
        Binding("f1", "dismiss", "Close"),
        Binding("question_mark", "dismiss", "Close"),
    ]

    COMMANDS: Sequence[tuple[str, Sequence[str]]] = (
        ("discoop (main)", ()),
        ("messages", ("messages",)),
        ("servers", ("servers",)),
        ("channels", ("channels",)),
        ("config", ("config",)),
        ("login", ("login",)),
        ("status", ("status",)),
        ("logout", ("logout",)),
        ("ui", ("ui",)),
    )

    def compose(self) -> ComposeResult:
        with Container(classes="modal-dialog", id="help-dialog"):
            yield Label("Help & Reference", classes="modal-title")
            with TabbedContent(initial="tab-tui-guide"):
                with TabPane("Using the TUI", id="tab-tui-guide"):
                    yield Static(self._tui_guide_text())
                with TabPane("CLI Reference (--help)", id="tab-cli-help"):
                    with Horizontal(classes="button-bar"):
                        for title, path in self.COMMANDS:
                            cmd_id = f"cmd-{'main' if not path else path[0]}"
                            yield Button(title, id=cmd_id)
                    with VerticalScroll(id="cli-help-scroll"):
                        yield Static("", id="cli-help-content")

            with Horizontal(classes="modal-buttons"):
                yield Button("Close (Esc)", variant="primary", id="btn-help-close")

    def on_mount(self) -> None:
        self._show_cli_help(())

    def _tui_guide_text(self) -> str:
        return """\
[bold cyan]KEYBOARD NAVIGATION[/bold cyan]
  [bold]Arrows / J, K[/bold]   Navigate lists (servers, channels, selection)
  [bold]Space[/bold]           Toggle selection of highlighted channel or category
  [bold]Tab / 1, 2, 3[/bold]   Switch panels or narrow tabs
  [bold]r[/bold]               Load channels for currently highlighted server
  [bold]R[/bold]               Load all servers & channels (safe pacing)
  [bold]s[/bold]               Refresh servers list from Discord
  [bold]e[/bold]               Set custom time window for selected channel
  [bold]/[/bold]               Focus channel search filter
  [bold]c[/bold]               Copy live CLI command to system clipboard
  [bold]F5[/bold]              Start export / preview job
  [bold]Esc[/bold]             Stop running export, or close modal
  [bold]F1 / ?[/bold]          Open this help screen
  [bold]q[/bold]               Quit discoop

[bold cyan]SAFE VS FAST MODE[/bold cyan]
  [bold]Safe mode (🛡️)[/bold]
    Emulates human scrolling in Discord with realistic pauses between
    message batches and channel switches. Recommended to avoid automated
    detection and ratelimits.
  [bold]Fast mode (⚡)[/bold]
    Downloads messages as quickly as the Discord API ratelimits allow.

[bold cyan]TIME WINDOWS[/bold cyan]
  You can set a global window (applied to all selected channels) or override
  it per channel using the [bold]e[/bold] shortcut. Presets include [bold]24h[/bold], [bold]7d[/bold], [bold]30d[/bold],
  or [bold]all[/bold] (entire channel history).
"""

    def _show_cli_help(self, path: Sequence[str]) -> None:
        try:
            help_text = command_help(path)
        except Exception as e:
            help_text = f"Error loading help for {path}: {e}"
        cli_content = self.query_one("#cli-help-content", Static)
        cli_content.update(help_text)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        button_id = event.button.id
        if button_id == "btn-help-close":
            self.dismiss(None)
            return

        for title, path in self.COMMANDS:
            cmd_id = f"cmd-{'main' if not path else path[0]}"
            if button_id == cmd_id:
                self._show_cli_help(path)
                return


class PreviewScreen(ModalScreen[None]):
    """Modal displaying fetched channel messages with format switcher and search."""

    BINDINGS = [
        Binding("escape", "dismiss", "Close"),
        Binding("slash", "focus_search", "Search"),
    ]

    def __init__(
        self,
        results: Sequence[ChannelMessages],
        query: Query | None = None,
        initial_format: str = "text",
    ) -> None:
        super().__init__()
        self.results = results
        self.export_query = query or Query(Window(None, utc_now()))
        self.current_format = initial_format

    def compose(self) -> ComposeResult:
        with Container(classes="modal-dialog", id="preview-dialog"):
            yield Label("Message Preview", classes="modal-title")
            with Horizontal(id="preview-controls"):
                yield Button("Text", id="btn-fmt-text")
                yield Button("Markdown", id="btn-fmt-md")
                yield Button("JSON", id="btn-fmt-json")
                yield Button("JSONL", id="btn-fmt-jsonl")
                yield Input(
                    placeholder="Search messages (/ to focus)...",
                    id="preview-search",
                )

            with VerticalScroll(id="preview-scroll"):
                yield Static("", id="preview-content")

            with Horizontal(classes="modal-buttons"):
                yield Button("Save to file", variant="primary", id="btn-preview-save")
                yield Button("Close (Esc)", variant="default", id="btn-preview-close")

    def on_mount(self) -> None:
        self._render_content()

    def action_focus_search(self) -> None:
        self.query_one("#preview-search", Input).focus()

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "preview-search":
            self._render_content()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        btn_id = event.button.id
        if btn_id == "btn-preview-close":
            self.dismiss(None)
        elif btn_id == "btn-fmt-text":
            self.current_format = "text"
            self._render_content()
        elif btn_id == "btn-fmt-md":
            self.current_format = "md"
            self._render_content()
        elif btn_id == "btn-fmt-json":
            self.current_format = "json"
            self._render_content()
        elif btn_id == "btn-fmt-jsonl":
            self.current_format = "jsonl"
            self._render_content()
        elif btn_id == "btn-preview-save":
            self._save_to_file()

    def _get_rendered_text(self) -> str | Text:
        fmt = self.current_format
        if fmt == "md":
            return text_render.markdown(self.results, self.export_query, LOCAL_ZONE)
        if fmt == "json":
            return jsonout.dumps(self.results, self.export_query, LOCAL_ZONE, indent=2)
        if fmt == "jsonl":
            return "\n".join(jsonout.lines(self.results, LOCAL_ZONE))
        # Plain / styled text
        return text_render.styled(self.results, self.export_query, LOCAL_ZONE)

    def _render_content(self) -> None:
        search_filter = self.query_one("#preview-search", Input).value.strip().lower()
        content = self._get_rendered_text()
        content_widget = self.query_one("#preview-content", Static)

        if not search_filter:
            content_widget.update(content)
            return

        # Simple filter by lines
        raw_text = content.plain if isinstance(content, Text) else str(content)
        filtered_lines = [line for line in raw_text.splitlines() if search_filter in line.lower()]
        if not filtered_lines:
            content_widget.update(f"[dim](no lines matching '{search_filter}')[/dim]")
        else:
            content_widget.update("\n".join(filtered_lines))

    def _save_to_file(self) -> None:
        content = self._get_rendered_text()
        raw_text = content.plain if isinstance(content, Text) else str(content)
        ext_map = {"text": "txt", "md": "md", "json": "json", "jsonl": "jsonl"}
        ext = ext_map.get(self.current_format, "txt")
        out_dir = Path("exports")
        out_dir.mkdir(parents=True, exist_ok=True)
        file_path = out_dir / f"discoop-preview.{ext}"
        try:
            file_path.write_text(raw_text, encoding="utf-8")
            self.notify(f"Saved preview to {file_path}", title="Saved")
        except Exception as e:
            self.notify(f"Failed to save preview: {e}", severity="error")


class SettingsModal(ModalScreen[bool]):
    """Modal for editing discoop user settings (config.toml)."""

    BINDINGS = [
        Binding("escape", "cancel", "Cancel"),
    ]

    def compose(self) -> ComposeResult:
        config = Config.default()
        with Container(classes="modal-dialog"):
            yield Label("Configuration Settings", classes="modal-title")

            with Vertical():
                with Horizontal(classes="input-row"):
                    yield Label("Default Server:")
                    yield Input(
                        value=str(config.get("default-server") or ""),
                        placeholder="Server ID or name",
                        id="input-cfg-server",
                    )
                with Horizontal(classes="input-row"):
                    yield Label("Download Mode:")
                    yield Input(
                        value=str(config.get("mode") or "safe"),
                        placeholder="safe or fast",
                        id="input-cfg-mode",
                    )
                with Horizontal(classes="input-row"):
                    yield Label("Delay (seconds):")
                    yield Input(
                        value=str(config.get("delay") or 1.0),
                        placeholder="e.g. 1.0",
                        id="input-cfg-delay",
                    )
                with Horizontal(classes="input-row"):
                    yield Label("Export Folder:")
                    yield Input(
                        value=str(config.get("export-dir") or ""),
                        placeholder="Default export directory (optional)",
                        id="input-cfg-export-dir",
                    )

            yield Label("", id="settings-error", classes="error-text")

            with Horizontal(classes="modal-buttons"):
                yield Button("Save Settings", variant="primary", id="btn-cfg-save")
                yield Button("Cancel", variant="default", id="btn-cfg-cancel")

    def action_cancel(self) -> None:
        self.dismiss(False)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-cfg-cancel":
            self.action_cancel()
        elif event.button.id == "btn-cfg-save":
            self._save()

    def _save(self) -> None:
        error_label = self.query_one("#settings-error", Label)
        error_label.update("")

        server = self.query_one("#input-cfg-server", Input).value.strip()
        mode = self.query_one("#input-cfg-mode", Input).value.strip().lower()
        delay_raw = self.query_one("#input-cfg-delay", Input).value.strip()
        export_dir = self.query_one("#input-cfg-export-dir", Input).value.strip()

        if mode not in ("safe", "fast"):
            error_label.update("Mode must be 'safe' or 'fast'.")
            return

        try:
            delay = float(delay_raw)
            if delay < 0:
                error_label.update("Delay cannot be negative.")
                return
        except ValueError:
            error_label.update("Delay must be a valid number.")
            return

        try:
            config = Config.default()
            if server:
                config.set("default-server", server)
            else:
                config.unset("default-server")

            config.set("mode", mode)
            config.set("delay", delay)

            if export_dir:
                config.set("export-dir", export_dir)
            else:
                config.unset("export-dir")

            self.notify("Settings saved successfully.", title="Saved")
            self.dismiss(True)
        except Exception as e:
            error_label.update(f"Failed to save config: {e}")


class LoginModal(ModalScreen[bool]):
    """Modal for managing Discord login token or logging out."""

    BINDINGS = [
        Binding("escape", "cancel", "Cancel"),
        Binding("g", "generate_qr", "Generate QR"),
    ]

    def __init__(
        self,
        api_factory: Callable[..., DiscordAPI] | None = None,
        wait_for_ticket_fn: Callable[..., Awaitable[LoginTicket | None]] = wait_for_ticket,
    ) -> None:
        super().__init__()
        self.api_factory = api_factory or DiscordAPI
        self.wait_for_ticket_fn = wait_for_ticket_fn
        self._qr_deadline: float | None = None
        self._countdown_timer: Timer | None = None

    def compose(self) -> ComposeResult:
        store = TokenStore.default()
        stored = store.load()

        with Container(classes="modal-dialog login-modal-dialog"):
            yield Label("Discord Authentication", classes="modal-title")

            if stored is not None:
                yield Label(f"🟢 Token currently stored in {stored.location}", id="login-status-lbl")
            else:
                yield Label("🔴 No token currently stored.", id="login-status-lbl")

            yield Label("Log in via Discord mobile app:", classes="section-label")
            with Vertical(id="qr-container"):
                yield Button("📱 Generate QR Code", id="btn-login-qr")
                yield Static("", id="qr-box")
                yield Label("", id="qr-status-lbl")
                yield Label("", id="qr-countdown-lbl")

            yield Label("Or paste your Discord user token below:", classes="section-label")

            yield Input(
                password=True,
                placeholder="Paste Discord token here...",
                id="input-token",
            )
            yield Label("", id="login-error", classes="error-text")

            with Horizontal(classes="modal-buttons"):
                yield Button("Verify & Save Token", variant="primary", id="btn-login-save")
                if stored is not None:
                    yield Button("Logout / Clear", variant="error", id="btn-login-logout")
                yield Button("Cancel", variant="default", id="btn-login-cancel")

    def on_unmount(self) -> None:
        if self._countdown_timer is not None:
            self._countdown_timer.stop()
            self._countdown_timer = None

    def action_cancel(self) -> None:
        if self._countdown_timer is not None:
            self._countdown_timer.stop()
            self._countdown_timer = None
        self.dismiss(False)

    def action_generate_qr(self) -> None:
        self._start_qr_login()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        btn_id = event.button.id
        if btn_id == "btn-login-cancel":
            self.action_cancel()
        elif btn_id == "btn-login-logout":
            TokenStore.default().delete()
            clear_cache()
            if self._countdown_timer is not None:
                self._countdown_timer.stop()
                self._countdown_timer = None
            self.notify("Logged out and cache cleared.", title="Logout")
            self.dismiss(True)
        elif btn_id == "btn-login-save":
            self._verify_token()
        elif btn_id == "btn-login-qr":
            self._start_qr_login()

    def _start_qr_login(self) -> None:
        self.query_one("#login-error", Label).update("")
        if self._countdown_timer is not None:
            self._countdown_timer.stop()
        self._countdown_timer = self.set_interval(1.0, self._tick_countdown)
        self.run_worker(self._run_qr_login(), exclusive=True, group="qr")

    def _tick_countdown(self) -> None:
        if not self.is_mounted:
            return
        if self._qr_deadline is not None:
            left = max(0, int(self._qr_deadline - time.monotonic()))
            self.query_one("#qr-countdown-lbl", Label).update(f"Expires in {left // 60}:{left % 60:02d}")
        else:
            self.query_one("#qr-countdown-lbl", Label).update("")

    def on_connecting(self, session: int) -> None:
        self._qr_deadline = None
        self.query_one("#qr-box", Static).update("")
        self.query_one("#qr-countdown-lbl", Label).update("")
        if session > 1:
            self.query_one("#qr-status-lbl", Label).update("Getting a new QR code...")
        else:
            self.query_one("#qr-status-lbl", Label).update("Connecting to Discord QR gateway...")

    def on_qr(self, url: str, deadline: float | None) -> None:
        self._qr_deadline = deadline
        self.query_one("#qr-box", Static).update(qr_text(url))
        self.query_one("#qr-status-lbl", Label).update(
            "Scan this QR code with the Discord mobile app (Settings > Scan QR Code)."
        )
        self._tick_countdown()

    def on_scanned(self, user: UserPayload) -> None:
        self._qr_deadline = None
        self.query_one("#qr-box", Static).update("")
        self.query_one("#qr-countdown-lbl", Label).update("")
        self.query_one("#qr-status-lbl", Label).update(
            f"Scanned as {user.username}! Confirm the login on your phone..."
        )

    def on_restart(self, reason: str) -> None:
        self._qr_deadline = None
        self.query_one("#qr-box", Static).update("")
        self.query_one("#qr-countdown-lbl", Label).update("")
        self.query_one("#qr-status-lbl", Label).update(
            f"{reason.capitalize()}, getting a new QR code..."
        )

    async def _run_qr_login(self) -> None:
        try:
            ticket = await self.wait_for_ticket_fn(self)
            if ticket is None:
                return

            def _exchange_and_store() -> tuple[dict[str, Any], str]:
                with Trace(None) as trace:
                    with self.api_factory(None) as api:
                        token = login_flow.exchange_ticket(ticket, api, trace)
                me, location = login_flow.verify_and_store(token, TokenStore.default(), self.api_factory)
                return me, location

            me, _ = await asyncio.to_thread(_exchange_and_store)
            clear_cache()
            if self._countdown_timer is not None:
                self._countdown_timer.stop()
                self._countdown_timer = None
            self.notify(f"Logged in as {me.get('username', 'user')}!", title="Success")
            self.dismiss(True)
        except asyncio.CancelledError:
            pass
        except DiscoopError as e:
            if self._countdown_timer is not None:
                self._countdown_timer.stop()
                self._countdown_timer = None
            self.query_one("#login-error", Label).update(e.message)
        except Exception as e:
            if self._countdown_timer is not None:
                self._countdown_timer.stop()
                self._countdown_timer = None
            self.query_one("#login-error", Label).update(f"Login failed: {e}")

    def _verify_token(self) -> None:
        error_label = self.query_one("#login-error", Label)
        error_label.update("")
        token = self.query_one("#input-token", Input).value.strip().strip('"')

        if not token:
            error_label.update("Please enter a Discord token.")
            return

        try:
            me, location = login_flow.verify_and_store(token, TokenStore.default(), self.api_factory)
            clear_cache()
            if self._countdown_timer is not None:
                self._countdown_timer.stop()
                self._countdown_timer = None
            self.notify(f"Logged in as {me.get('username', 'user')}!", title="Success")
            self.dismiss(True)
        except DiscoopError as e:
            error_label.update(e.message)
        except Exception as e:
            error_label.update(f"Verification failed: {e}")
