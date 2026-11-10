"""Modal dialogs of the discoop TUI, built like the main screen: a thin frame, rows one line high, the keys below.

Provides:
- TimeWindowModal: the custom time window of a channel.
- HelpScreen: the guide to the TUI and the `--help` of every command.
- PreviewScreen: fetched messages in any output format, with search and saving to a file.
- SettingsModal: the user configuration.
- LoginModal: QR login, browser login, a pasted token and logout.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Sequence
import itertools
from pathlib import Path
import time
from typing import Any

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen, ScreenResultType
from textual.timer import Timer
from textual.widgets import Footer, Input, Label, Static

from discoop import login as login_flow, paths, profiles
from discoop.api import DiscordAPI
from discoop.browser_login import Browser, wait_for_browser_token
from discoop.cache import clear_cache
from discoop.cli import LOCAL_ZONE, command_help
from discoop.config import DEFAULTS, DESCRIPTIONS, MODES, Config, parse_delay, parse_export_dir, parse_mode
from discoop.errors import DiscoopError, ExitCode
from discoop.models import ChannelMessages
from discoop.qr import qr_text
from discoop.remote_auth.crypto import UserPayload
from discoop.remote_auth.protocol import LoginTicket, wait_for_ticket
from discoop.remote_auth.trace import Trace
from discoop.render import Query, jsonout, text as text_render
from discoop.service import DEFAULT_MAX_MESSAGES, FORMATS
from discoop.snowflake import Window, parse_window, utc_now
from discoop.tokenstore import TokenStore
from discoop.tui.state import WINDOW_PRESETS, WindowSpec, window_preset
from discoop.tui.widgets import ActionRow, ChoiceRow, ConfirmRow, FormPanel, InputRow, TextView

WINDOW_CANCELLED = object()

SEARCH_DELAY = 0.2  # seconds of no typing before the preview follows the search
PREVIEW_FOLDER = "exports"  # without an export-dir in the config
PREVIEW_STEM = "discoop-preview"
PREVIEW_SUFFIXES = {"text": ".txt", "md": ".md", "json": ".json", "jsonl": ".jsonl"}

SAVE_LABEL = "[ Save (Enter) ]"
VERIFY_LABEL = "[ Verify and save token (Enter) ]"
BROWSER_HINT_TEXT = (
    "If your system asks for a passkey or security key, you can cancel that dialog and log in with your "
    "password or the QR code on the page. Press Esc to cancel and close the browser window."
)
QR_DIALOG_HEIGHT = 27  # the QR code, a status line, the frame and the Footer; less loses the frame and the Footer

GUIDE_TOPIC = "TUI guide"
CLI_TOPICS: dict[str, tuple[str, ...]] = {
    "discoop": (),
    "messages": ("messages",),
    "servers": ("servers",),
    "channels": ("channels",),
    "config": ("config",),
    "login": ("login",),
    "status": ("status",),
    "logout": ("logout",),
    "ui": ("ui",),
}

# The key table of ADR 0014.
GUIDE_KEYS = (
    ("↑ ↓", "move in the tree, the list and the form"),
    ("→", "tree: open a node or load a server, then go to its first child"),
    ("←", "tree: close a node, then go to its parent"),
    ("← →", "form: change a choice row (mode, target, format, ...)"),
    ("Space", "tree: select a channel or a whole category"),
    ("Enter", "tree: open or close a node, select a channel"),
    ("Enter", "form: confirm the field. On Start: run the export"),
    ("Tab, Shift+Tab", "switch panel"),
    ("1 2 3", "go to the tree, the Export panel, the log"),
    ("/", "filter the tree"),
    ("e", "tree or selected list: own time window of the channel"),
    ("x, Delete", "selected list: remove the channel"),
    ("X", "selected list: clear the whole selection"),
    ("a", "tree: select all shown channels of the server"),
    ("r", "tree: load the channels of the server again from Discord"),
    ("R", "load the server list again"),
    ("L", "load the channels of all servers (safe pace, Esc stops)"),
    ("F5", "start the export"),
    ("Esc", "stop the running operation, leave the filter, close a dialog"),
    ("c", "copy the CLI command"),
    ("P", "save the selection, time window and mode as a profile"),
    ("p", "load a saved profile"),
    ("o", "open the folder of the last export"),
    ("F1, ?", "this help"),
    ("F2", "settings"),
    ("F3", "login"),
    ("b", "login dialog: log in with browser"),
    ("Ctrl+P", "command palette (change the theme)"),
    ("q", "quit. A running operation is stopped first"),
)
GUIDE_SECTIONS = (
    (
        "Tree",
        "Servers, categories and channels are one tree, closed at the start. A server shows its channel count, "
        '"not loaded" until you open it, or "no access". Moving the cursor never calls Discord: only → or Enter '
        "on a server that is not loaded, r, R, L and F5 do. A channel shows, dimmed at the right edge, the time since "
        "its last message (2d) and, once you exported it, the date of the last export (exp 11-03). A narrow tree drops "
        "the export date first, then the time, and never shortens a name for them.",
    ),
    (
        "Selection",
        "[x] is selected, [~] is a category with some channels selected, [ ] is not selected. A category cannot be "
        "selected itself: selecting it selects its channels. Forums and media channels can be selected: their posts "
        "are downloaded as threads, so the Threads row must be yes. The Export panel lists the selected channels of "
        "all servers.",
    ),
    (
        "Form",
        "The Export panel has the form below the list. ↑ ↓ walk its rows, also out of a text field, ← → change a "
        "choice row. Target says where the export goes: a folder, a zip file or a preview on the screen. Folder and "
        "Name say where exactly. An empty Folder is the default folder, Documents/discoop. A relative Folder lies "
        "inside it, an absolute one or one starting with ~ is used as it is. Export folder in Settings (F2) changes "
        "the default folder for good, the Folder row for one export. An empty Name is discord-export and the date "
        "and time. A typed Name is only a name, never a path: slashes and characters a file name cannot have turn "
        "into _. The line under the log shows the same export as a CLI command.",
    ),
    (
        "Time windows",
        "The Window, From, To and Last N rows apply to every selected channel. Presets: 24h, 7d, 30d, all. Press e "
        "on a channel to give it its own window, marked with * in the list. Channels with the same window are "
        "exported together.",
    ),
    (
        "Safe and fast",
        "safe scrolls like a person, with pauses between pages and channels. It is the default. fast goes as "
        "quickly as Discord's rate limits allow, waiting Delay seconds between requests. Esc ends a pause at once.",
    ),
    (
        "Profiles and export folder",
        "Press P to save the current selection, time window and mode as a named profile. Press p to load a saved "
        "profile (stored in profiles.json in your config folder). After an export finishes, press o to open the "
        "export folder in your file manager.",
    ),
)


def guide_text() -> Text:
    text = Text()
    text.append("Keys\n", style="bold")
    for key, action in GUIDE_KEYS:
        text.append(f"  {key:<16}", style="bold")
        text.append(f"{action}\n")
    for title, body in GUIDE_SECTIONS:
        text.append(f"\n{title}\n", style="bold")
        text.append(f"{body}\n")
    return text


def write_new_file(folder: Path, stem: str, suffix: str, text: str) -> Path:
    """Write `text` to `stem<suffix>` in `folder`, or `stem-2<suffix>` and so on: nothing gets overwritten."""
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{stem}{suffix}"
    numbers = itertools.count(2)
    while True:
        try:
            with path.open("x", encoding="utf-8") as file:
                file.write(text)
            return path.resolve()
        except FileExistsError:
            path = folder / f"{stem}-{next(numbers)}{suffix}"


def dialog_box(title: str, *, id: str | None = None) -> Vertical:
    box = Vertical(classes="dialog", id=id)
    box.border_title = Text(title)  # a string would be read as markup, and a channel name can hold brackets
    return box


def dialog_footer() -> Footer:
    return Footer(compact=True, show_command_palette=False)


class Dialog(ModalScreen[ScreenResultType]):
    """Base of the dialogs. The app handles the same row messages for its form, so they stop here."""

    def on_choice_row_changed(self, event: ChoiceRow.Changed) -> None:
        event.stop()

    def on_action_row_pressed(self, event: ActionRow.Pressed) -> None:
        event.stop()

    def on_input_changed(self, event: Input.Changed) -> None:
        event.stop()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        event.stop()

    def field(self, selector: str) -> str:
        return self.query_one(selector, Input).value.strip()

    def show_error(self, message: str) -> None:
        """Show `message` in the error line of the dialog, which takes no room while it is empty."""
        label = self.query_one(".dialog-error", Label)
        label.update(message)
        label.display = bool(message)


class ScrollingDialog(Dialog[ScreenResultType]):
    """A dialog around one `.dialog-scroll` widget: the scroll keys work wherever the focus is, unless a row uses them."""

    BINDINGS = [
        Binding("up", "scroll_pane('scroll_up')", show=False),
        Binding("down", "scroll_pane('scroll_down')", show=False),
        Binding("pageup", "scroll_pane('page_up')", show=False),
        Binding("pagedown", "scroll_pane('page_down')", show=False),
        Binding("home", "scroll_pane('scroll_home')", show=False),
        Binding("end", "scroll_pane('scroll_end')", show=False),
    ]

    def action_scroll_pane(self, action: str) -> None:
        getattr(self.query_one(".dialog-scroll"), f"action_{action}")()


class TimeWindowModal(Dialog[Any]):
    """The custom time window of a channel. Dismisses with a `WindowSpec`, None (global window) or `WINDOW_CANCELLED`."""

    BINDINGS = [
        Binding("enter", "save", "Save", key_display="Enter"),
        Binding("escape", "cancel", "Cancel", key_display="Esc"),
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
        last = "" if spec.last is None else str(spec.last)
        with dialog_box(f"Time window: #{self.channel_name}", id="window-dialog"):
            with FormPanel(enter_moves=False):
                yield ChoiceRow(
                    "Window", WINDOW_PRESETS, window_preset(spec.from_, spec.to, spec.last), id="row-modal-window"
                )
                yield InputRow("From", "modal-input-from", value=spec.from_ or "", placeholder="7d, 2026-10-01, all")
                yield InputRow("To", "modal-input-to", value=spec.to or "", placeholder="now")
                yield InputRow(
                    "Last N", "modal-input-last", value=last, placeholder="all in window", input_type="integer"
                )
                yield InputRow("Max messages", "modal-input-max", value=str(spec.max_messages), input_type="integer")
                yield ActionRow(SAVE_LABEL, id="row-modal-save")
                yield ActionRow("[ Use global window ]", id="row-modal-global")
            yield Label("", id="modal-error", classes="dialog-error", markup=False)
        yield dialog_footer()

    def on_choice_row_changed(self, event: ChoiceRow.Changed) -> None:
        self.query_one("#modal-input-from", Input).value = event.value
        self.query_one("#modal-input-to", Input).value = ""
        self.query_one("#modal-input-last", Input).value = ""

    def on_input_changed(self, event: Input.Changed) -> None:
        preset = window_preset(
            self.field("#modal-input-from"), self.field("#modal-input-to"), self.field("#modal-input-last")
        )
        self.query_one("#row-modal-window", ChoiceRow).set_value(preset)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self.action_save()

    def on_action_row_pressed(self, event: ActionRow.Pressed) -> None:
        if event.row.id == "row-modal-global":
            self.dismiss(None)
        else:
            self.action_save()

    def action_cancel(self) -> None:
        self.dismiss(WINDOW_CANCELLED)

    def action_save(self) -> None:
        self.show_error("")
        from_raw = self.field("#modal-input-from") or None
        to_raw = self.field("#modal-input-to") or None
        last_raw = self.field("#modal-input-last")
        max_raw = self.field("#modal-input-max")

        last_val: int | None = None
        if last_raw:
            try:
                last_val = int(last_raw)
            except ValueError:
                self.show_error("Last N must be a whole number.")
                return
            if last_val < 1:
                self.show_error("Last N must be at least 1.")
                return

        max_val = DEFAULT_MAX_MESSAGES
        if max_raw:
            try:
                max_val = int(max_raw)
            except ValueError:
                self.show_error("Max messages must be a whole number.")
                return
            if max_val < 1:
                self.show_error("Max messages must be at least 1.")
                return

        try:
            parse_window(from_raw, to_raw, now=utc_now(), tz=LOCAL_ZONE, whole_history=last_val is not None)
        except DiscoopError as e:
            self.show_error(e.message)
            return

        self.dismiss(WindowSpec(from_=from_raw, to=to_raw, last=last_val, max_messages=max_val))


class HelpScreen(ScrollingDialog[None]):
    """The guide to the TUI and the `--help` of every command. ←→ pick the topic, the scroll keys read it."""

    BINDINGS = [
        Binding("escape", "close", "Close", key_display="Esc"),
        Binding("f1,question_mark", "close", show=False),
    ]

    def compose(self) -> ComposeResult:
        with dialog_box("Help", id="help-dialog"):
            yield ChoiceRow("Topic", (GUIDE_TOPIC, *CLI_TOPICS), id="row-help-topic")
            yield TextView(id="help-content", classes="dialog-scroll")
        yield dialog_footer()

    def on_mount(self) -> None:
        self._show_topic(GUIDE_TOPIC)

    def on_choice_row_changed(self, event: ChoiceRow.Changed) -> None:
        self._show_topic(event.value)

    def action_close(self) -> None:
        self.dismiss(None)

    def _show_topic(self, topic: str) -> None:
        content = guide_text() if topic == GUIDE_TOPIC else command_help(CLI_TOPICS[topic])
        self.query_one(TextView).update(content)


class PreviewScreen(ScrollingDialog[None]):
    """Fetched messages in any output format. ←→ change the format, the scroll keys read, / searches, s saves."""

    BINDINGS = [
        Binding("slash", "focus_search", "Search", key_display="/"),
        Binding("s", "save", "Save"),
        Binding("escape", "close", "Close", key_display="Esc"),
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
        self._rendered: dict[str, str | Text] = {}  # by format: a big export takes a while to render
        self._search_timer: Timer | None = None

    def compose(self) -> ComposeResult:
        with dialog_box("Preview", id="preview-dialog"):
            yield ChoiceRow("Format", FORMATS, self.current_format, id="row-preview-format")
            yield InputRow("Search", "preview-search", placeholder="/ to search")
            yield TextView(id="preview-content", classes="dialog-scroll")
        yield dialog_footer()

    def on_mount(self) -> None:
        self._show()

    def on_choice_row_changed(self, event: ChoiceRow.Changed) -> None:
        self.current_format = event.value
        self._show()

    def on_input_changed(self, event: Input.Changed) -> None:
        if self._search_timer is not None:
            self._search_timer.stop()
        self._search_timer = self.set_timer(SEARCH_DELAY, self._show)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self._leave_search()

    def action_focus_search(self) -> None:
        self.query_one("#preview-search", Input).focus()

    def action_close(self) -> None:
        if self.query_one("#preview-search", Input).has_focus:
            self._leave_search()
        else:
            self.dismiss(None)

    def _leave_search(self) -> None:
        self.query_one("#row-preview-format", ChoiceRow).focus()

    def _content(self) -> str | Text:
        fmt = self.current_format
        if fmt not in self._rendered:
            self._rendered[fmt] = self._render_format(fmt)
        return self._rendered[fmt]

    def _render_format(self, fmt: str) -> str | Text:
        if fmt == "md":
            return text_render.markdown(self.results, self.export_query, LOCAL_ZONE)
        if fmt == "json":
            return jsonout.dumps(self.results, self.export_query, LOCAL_ZONE, indent=2)
        if fmt == "jsonl":
            return "\n".join(jsonout.lines(self.results, LOCAL_ZONE))
        return text_render.styled(self.results, self.export_query, LOCAL_ZONE)

    def _plain(self) -> str:
        content = self._content()
        return content.plain if isinstance(content, Text) else content

    def _show(self) -> None:
        wanted = self.field("#preview-search").lower()
        content = self._content()
        if wanted:
            lines = [line for line in self._plain().splitlines() if wanted in line.lower()]
            content = "\n".join(lines) or f"(no lines matching '{wanted}')"
        self.query_one(TextView).update(content)

    def action_save(self) -> None:
        try:
            export_dir = Config.default().get("export-dir")
            folder = Path(export_dir or PREVIEW_FOLDER)
            path = write_new_file(folder, PREVIEW_STEM, PREVIEW_SUFFIXES[self.current_format], self._plain())
        except (DiscoopError, OSError) as e:
            self.notify(f"Failed to save the preview: {e}", severity="error", markup=False)
            return
        self.notify(f"Saved to {path}", title="Saved", markup=False)


class SettingsModal(Dialog[bool]):
    """The user configuration (config.toml). Dismisses with True once it is saved."""

    BINDINGS = [
        Binding("enter", "save", "Save", key_display="Enter"),
        Binding("escape", "cancel", "Cancel", key_display="Esc"),
    ]

    LABEL_WIDTH = 16

    def __init__(self) -> None:
        super().__init__()
        self._config_problem = ""

    def _current_values(self) -> dict[str, Any]:
        try:
            config = Config.default()
        except DiscoopError as e:
            self._config_problem = e.message
            return dict(DEFAULTS)
        return {key: config.get(key) for key in DESCRIPTIONS}

    def compose(self) -> ComposeResult:
        values = self._current_values()
        width = self.LABEL_WIDTH
        with dialog_box("Settings", id="settings-dialog"):
            with FormPanel(enter_moves=False):
                yield ChoiceRow("Mode", MODES, values["mode"], label_width=width, id="row-cfg-mode")
                yield InputRow(
                    "Delay", "input-cfg-delay", value=str(values["delay"]), input_type="number", label_width=width
                )
                yield InputRow(
                    "Default server",
                    "input-cfg-server",
                    value=values.get("default-server") or "",
                    placeholder="server name or ID",
                    label_width=width,
                )
                yield InputRow(
                    "Export folder",
                    "input-cfg-export-dir",
                    value=values.get("export-dir") or "",
                    placeholder=str(paths.default_export_dir()),
                    label_width=width,
                )
                yield ActionRow(SAVE_LABEL, id="row-cfg-save")
            yield Label("", id="settings-error", classes="dialog-error", markup=False)
        yield dialog_footer()

    def on_mount(self) -> None:
        self.show_error(self._config_problem)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self.action_save()

    def on_action_row_pressed(self, event: ActionRow.Pressed) -> None:
        self.action_save()

    def action_cancel(self) -> None:
        self.dismiss(False)

    def action_save(self) -> None:
        self.show_error("")
        server = self.field("#input-cfg-server")
        export_dir = self.field("#input-cfg-export-dir")
        try:
            mode = parse_mode(self.query_one("#row-cfg-mode", ChoiceRow).value)
            delay = parse_delay(self.field("#input-cfg-delay"))
            export_dir = parse_export_dir(export_dir) if export_dir else ""

            config = Config.default()
            config.set("mode", mode)
            config.set("delay", delay)
            if server:
                config.set("default-server", server)
            else:
                config.unset("default-server")
            if export_dir:
                config.set("export-dir", export_dir)
            else:
                config.unset("export-dir")
        except (DiscoopError, OSError) as e:
            self.show_error(str(e))
            return
        self.notify("Settings saved.", title="Saved")
        self.dismiss(True)


class SaveProfileModal(Dialog[str | None]):
    """Dialog to save current selection and settings as a named profile."""

    BINDINGS = [
        Binding("enter", "save", "Save", key_display="Enter"),
        Binding("escape", "cancel", "Cancel", key_display="Esc"),
    ]

    def __init__(self, default_name: str = "") -> None:
        super().__init__()
        self.default_name = default_name

    def compose(self) -> ComposeResult:
        with dialog_box("Save profile", id="save-profile-dialog"):
            with FormPanel(enter_moves=False):
                yield InputRow(
                    "Name",
                    "input-profile-name",
                    value=self.default_name,
                    placeholder="letters, numbers, dash, underscore",
                )
                yield ActionRow("[ Save profile (Enter) ]", id="row-profile-save")
            yield Label("", id="profile-save-error", classes="dialog-error", markup=False)
        yield dialog_footer()

    def on_action_row_pressed(self, event: ActionRow.Pressed) -> None:
        self.action_save()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self.action_save()

    def action_save(self) -> None:
        name = self.field("#input-profile-name")
        if not name:
            self.show_error("Please enter a profile name.")
            return
        try:
            clean = profiles.validate_name(name)
        except ValueError as err:
            self.show_error(str(err))
            return
        self.dismiss(clean)

    def action_cancel(self) -> None:
        self.dismiss(None)


class LoadProfileModal(Dialog[str | None]):
    """Dialog to pick and load a saved profile."""

    BINDINGS = [
        Binding("enter", "load", "Load", key_display="Enter"),
        Binding("escape", "cancel", "Cancel", key_display="Esc"),
    ]

    def __init__(self, profile_names: Sequence[str]) -> None:
        super().__init__()
        self.profile_names = list(profile_names)

    def compose(self) -> ComposeResult:
        with dialog_box("Load profile", id="load-profile-dialog"):
            if not self.profile_names:
                yield Label("No saved profiles found.", classes="dialog-error")
                yield ActionRow("[ Close (Esc) ]", id="row-profile-close")
            else:
                with FormPanel(enter_moves=False):
                    yield ChoiceRow(
                        "Profile", tuple(self.profile_names), self.profile_names[0], id="row-profile-choice"
                    )
                    yield ActionRow("[ Load profile (Enter) ]", id="row-profile-load")
            yield Label("", id="profile-load-error", classes="dialog-error", markup=False)
        yield dialog_footer()

    def on_action_row_pressed(self, event: ActionRow.Pressed) -> None:
        if not self.profile_names:
            self.dismiss(None)
        else:
            self.action_load()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self.action_load()

    def action_load(self) -> None:
        if not self.profile_names:
            self.dismiss(None)
            return
        choice_row = self.query_one("#row-profile-choice", ChoiceRow)
        self.dismiss(choice_row.value)

    def action_cancel(self) -> None:
        self.dismiss(None)


class LoginModal(ScrollingDialog[bool]):
    """QR login, browser login, a pasted token and logout. Dismisses with True when the account changed.

    `g` swaps the form for the QR code, which a phone can only read in one piece. In a short window the frame and the
    Footer give way to it, and in an even shorter one the scroll keys move it. `b` opens the user's own browser.
    """

    BINDINGS = [
        Binding("g", "generate_qr", "QR code"),
        Binding("b", "browser_login", "Browser"),
        Binding("escape", "cancel", "Cancel", key_display="Esc"),
    ]

    VERTICAL_BREAKPOINTS = [(0, "-short"), (QR_DIALOG_HEIGHT, "-tall")]

    def __init__(
        self,
        api_factory: Callable[..., DiscordAPI] | None = None,
        wait_for_ticket_fn: Callable[..., Awaitable[LoginTicket | None]] = wait_for_ticket,
        find_browser_fn: Callable[[], Browser] = login_flow.find_login_browser,
        wait_for_browser_token_fn: Callable[..., Awaitable[str]] = wait_for_browser_token,
    ) -> None:
        super().__init__()
        self.api_factory = api_factory or DiscordAPI
        self.wait_for_ticket_fn = wait_for_ticket_fn
        self.find_browser_fn = find_browser_fn
        self.wait_for_browser_token_fn = wait_for_browser_token_fn
        self._busy = False  # a login is on its way, by QR code, browser or token
        self._qr_deadline: float | None = None
        self._countdown_timer: Timer | None = None
        self._browser_name = "Browser"

    def compose(self) -> ComposeResult:
        stored = TokenStore.default().load()
        status = "No token stored." if stored is None else f"Token stored in {stored.location}."
        box = VerticalScroll(id="login-dialog", classes="dialog dialog-scroll")
        box.can_focus = False
        box.border_title = "Login"
        with box:
            with FormPanel(enter_moves=False, id="login-form"):
                yield Label(status, id="login-status-lbl", markup=False)
                yield ActionRow("[ Generate QR code (g) ]", id="row-login-qr")
                yield ActionRow("[ Log in with browser (b) ]", id="row-login-browser")
                yield InputRow("Token", "input-token", placeholder="paste a Discord token", password=True)
                yield ActionRow(VERIFY_LABEL, id="row-login-save")
                if stored is not None:
                    yield ConfirmRow("[ Log out ]", "Press Enter again to confirm", id="row-login-logout")
            with Horizontal(id="qr-status"):
                yield Label("", id="qr-status-lbl", markup=False)
                yield Label("", id="qr-countdown-lbl", markup=False)
            yield Static("", id="qr-box", markup=False)
            yield Label(BROWSER_HINT_TEXT, id="browser-hint", markup=False)
            yield Label("", id="login-error", classes="dialog-error", markup=False)
        yield dialog_footer()

    def on_unmount(self) -> None:
        self._stop_countdown()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self._verify_token()

    def on_action_row_pressed(self, event: ActionRow.Pressed) -> None:
        if event.row.id == "row-login-qr":
            self.action_generate_qr()
        elif event.row.id == "row-login-browser":
            self.action_browser_login()
        elif event.row.id == "row-login-save":
            self._verify_token()
        elif event.row.id == "row-login-logout":
            self._log_out()

    def action_cancel(self) -> None:
        self.workers.cancel_node(self)
        self._stop_countdown()
        self.dismiss(False)

    def action_generate_qr(self) -> None:
        if self._busy:
            return
        self._busy = True
        self.show_error("")
        self.set_class(True, "-qr")
        self._countdown_timer = self.set_interval(1.0, self._tick_countdown)
        self.run_worker(self._guarded(self._qr_login()), group="login")

    def action_browser_login(self) -> None:
        if self._busy:
            return
        self._busy = True
        self.show_error("")
        self._clear_qr("Looking for a browser...")
        self.set_class(True, "-browser")
        self._countdown_timer = self.set_interval(1.0, self._tick_countdown)
        self.run_worker(self._guarded(self._browser_login()), group="login")

    def _verify_token(self) -> None:
        if self._busy:
            return
        token = self.field("#input-token").strip('"')
        if not token:
            self.show_error("Please enter a Discord token.")
            return
        self._busy = True
        self.show_error("")
        self.query_one("#row-login-save", ActionRow).update("Verifying the token...")
        self.run_worker(self._guarded(self._finish_login(lambda: token)), group="login")

    def _log_out(self) -> None:
        if self._busy:
            return
        TokenStore.default().delete()
        clear_cache()
        self.notify("Logged out and cache cleared.", title="Logout")
        self.dismiss(True)

    async def _guarded(self, login: Awaitable[None]) -> None:
        try:
            await login
        except login_flow.CaptchaRequired as e:
            self._login_failed(
                e.message,
                "Press b to log in through a browser window instead.",
                focus_selector="#row-login-browser",
            )
        except DiscoopError as e:
            self._login_failed(e.message, e.hint)
        except Exception as e:  # an unexpected error must not take the whole UI down
            self._login_failed(f"Login failed: {e}")

    def _login_failed(
        self,
        message: str,
        hint: str | None = None,
        *,
        focus_selector: str | None = None,
    ) -> None:
        was_qr = self.has_class("-qr")
        was_browser = self.has_class("-browser")
        self._busy = False
        self._stop_countdown()
        self.set_class(False, "-qr")
        self.set_class(False, "-browser")
        self.query_one("#row-login-save", ActionRow).update(VERIFY_LABEL)
        self.show_error(f"{message}\n{hint}" if hint else message)
        if focus_selector is not None:
            self.query_one(focus_selector, ActionRow).focus()
        elif was_qr:
            self.query_one("#row-login-qr", ActionRow).focus()
        elif was_browser:
            self.query_one("#row-login-browser", ActionRow).focus()

    async def _qr_login(self) -> None:
        ticket = await self.wait_for_ticket_fn(self)
        if ticket is None:
            return
        self.query_one("#qr-status-lbl", Label).update("Confirmed on the phone, finishing the login...")

        def exchange() -> str:
            with Trace(None) as trace, self.api_factory(None) as api:
                return login_flow.exchange_ticket(ticket, api, trace)

        await self._finish_login(exchange)

    async def _browser_login(self) -> None:
        browser = self.find_browser_fn()
        self._browser_name = browser.name
        token = await self.wait_for_browser_token_fn(self, browser=browser, timeout=login_flow.BROWSER_TIMEOUT)
        try:
            await self._finish_login(lambda: token)
        except DiscoopError as e:
            if e.code != ExitCode.AUTH_REQUIRED:
                raise
            raise DiscoopError(
                ExitCode.AUTH_REQUIRED,
                "Discord did not accept the token read from the browser window.",
                "Run `discoop login --browser` again. If it keeps failing, use `discoop login --token`.",
            ) from e

    async def _finish_login(self, get_token: Callable[[], str]) -> None:
        """Get the token and check it, in a thread. Esc until then leaves everything as it was."""

        def verified() -> tuple[str, dict[str, Any]]:
            token = get_token()
            with self.api_factory(token) as api:
                return token, api.get_me()

        token, me = await asyncio.to_thread(verified)
        TokenStore.default().save(token)
        clear_cache()
        self._stop_countdown()
        self.notify(f"Logged in as {me.get('username', 'user')}!", title="Success", markup=False)
        self.dismiss(True)

    def _stop_countdown(self) -> None:
        if self._countdown_timer is not None:
            self._countdown_timer.stop()
            self._countdown_timer = None

    def _tick_countdown(self) -> None:
        text = ""
        if self._qr_deadline is not None:
            left = max(0, int(self._qr_deadline - time.monotonic()))
            text = f"Expires in {left // 60}:{left % 60:02d}"
        label = self.query_one("#qr-countdown-lbl", Label)
        label.update(text)
        label.display = bool(text)

    def _clear_qr(self, status: str) -> None:
        self._qr_deadline = None
        self.query_one("#qr-box", Static).update("")
        countdown = self.query_one("#qr-countdown-lbl", Label)
        countdown.update("")
        countdown.display = False
        self.query_one("#qr-status-lbl", Label).update(status)

    # The listener of wait_for_ticket.

    def on_connecting(self, session: int) -> None:
        self._clear_qr("Getting a new QR code..." if session > 1 else "Connecting to the Discord QR gateway...")

    def on_qr(self, url: str, deadline: float | None) -> None:
        self._qr_deadline = deadline
        self.query_one("#qr-box", Static).update(qr_text(url))
        self.query_one("#qr-status-lbl", Label).update("Scan it in the Discord app: Settings > Scan QR Code.")
        self._tick_countdown()

    def on_scanned(self, user: UserPayload) -> None:
        self._clear_qr(f"Scanned as {user.username}. Confirm the login on your phone...")

    def on_restart(self, reason: str) -> None:
        self._clear_qr(f"{reason.capitalize()}, getting a new QR code...")

    # The listener of wait_for_browser_token.

    def on_launching(self, browser_name: str) -> None:
        self._browser_name = browser_name
        self._clear_qr(f"Opening {browser_name}...")

    def on_opened(self, deadline: float) -> None:
        self._qr_deadline = deadline
        self.query_one("#qr-status-lbl", Label).update(
            f"A browser window opened ({self._browser_name}). Log in to Discord there; solve a captcha if one appears."
        )
        self._tick_countdown()

    def on_captured(self) -> None:
        self._clear_qr("Login detected, closing the browser window...")
