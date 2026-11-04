"""The discoop terminal UI: one tree of servers, categories and channels, an export form and a log.

The keyboard comes first and bindings live on the widget they belong to (widgets.py); the mouse still works.

Only these reach Discord: →/Enter on a server that is not loaded, r, R, L and F5, plus the token check and a missing
server list at startup. Moving the cursor never does. One network operation runs at a time (`_begin_net`), and its
workers talk back to the UI only through `_ui`, which keeps their messages in order and never blocks them.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Iterator
from contextlib import contextmanager
from datetime import datetime
import time
from typing import Any

import httpx
from rich.text import Text
from textual import work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, Vertical
from textual.message import Message
from textual.timer import Timer
from textual.widgets import Footer, Input, Label, ProgressBar, RichLog, Static
from textual.widgets.option_list import Option
from textual.widgets.tree import TreeNode

from discoop.api import DiscordAPI
from discoop.attachments import DOWNLOADED, FAILED, NO_FILES, PRESENT, SKIPPED, cdn_client
from discoop.cache import Cache
from discoop.cli import LOCAL_ZONE
from discoop.config import MODES, Config
from discoop.directory import Directory
from discoop.errors import DiscoopError, ExitCode, auth_required
from discoop.models import CATEGORY, Channel, Server, group_by_category
from discoop.service import (
    DEFAULT_MAX_MESSAGES,
    FORMATS,
    Cancelled,
    MessagesOutcome,
    list_channels,
    list_servers,
    load_all,
    run_messages,
)
from discoop.tokenstore import TokenStore
from discoop.tui.bridge import CancelToken, TuiEvents
from discoop.tui.modals import (
    WINDOW_CANCELLED,
    HelpScreen,
    LoginModal,
    PreviewScreen,
    SettingsModal,
    TimeWindowModal,
)
from discoop.tui.state import (
    WINDOW_PRESETS,
    ExportSettings,
    PlannedJob,
    SelectionState,
    WindowSpec,
    default_folder,
    default_name,
    filter_channels,
    plan_jobs,
    window_preset,
)
from discoop.tui.widgets import (
    ActionRow,
    ChannelTree,
    ChoiceRow,
    FilterInput,
    FormPanel,
    InputRow,
    SelectedList,
    TailInput,
    display_name,
)

TARGETS = ("folder", "zip", "preview")
NAME_REFRESH = 30  # seconds: the automatic name and the CLI command follow the clock
START_LABEL = "[ Start (F5) ]"
STOP_LABEL = "[ Stop (Esc) ]"
NO_COMMAND = "(select channels to preview CLI command)"
FILTER_DELAY = 0.08  # seconds of no typing before the tree follows the filter
DOWNLOAD_REPORT_INTERVAL = 0.1  # seconds between progress updates during a download


class UiCall(Message):
    """A call a worker thread wants done on the UI thread."""

    def __init__(self, function: Callable[..., None], args: tuple[Any, ...]) -> None:
        super().__init__()
        self.function = function
        self.args = args


def plural(count: int, noun: str) -> str:
    return f"{count} {noun}" if count == 1 else f"{count} {noun}s"


def short_window(window: WindowSpec) -> str:
    return window.label().removesuffix(" → now")


class DiscoopApp(App[None]):
    """The Discoop Terminal User Interface application."""

    TITLE = "discoop"
    CSS_PATH = "discoop.tcss"
    HORIZONTAL_BREAKPOINTS = [(0, "-narrow"), (95, "-wide")]

    BINDINGS = [  # in Footer order: what matters most stays visible in a narrow window
        Binding("tab", "cycle_pane(1)", "Panel", key_display="Tab", priority=True),
        Binding("shift+tab", "cycle_pane(-1)", "Panel", show=False, priority=True),
        Binding("f5", "start_export", "Start", key_display="F5"),
        Binding("slash", "focus_filter", "Filter", key_display="/"),
        Binding("escape", "stop_or_back", "Stop", key_display="Esc"),
        Binding("f1,question_mark", "help", "Help", key_display="F1"),
        Binding("f2", "settings", "Settings", key_display="F2"),
        Binding("f3", "login", "Login", key_display="F3"),
        Binding("R", "reload_servers", "Servers"),
        Binding("L", "load_all", "Load all"),
        Binding("c", "copy_command", "Copy"),
        Binding("q", "quit", "Quit"),
        Binding("1", "pane(1)", "Tree", show=False),
        Binding("2", "pane(2)", "Export", show=False),
        Binding("3", "pane(3)", "Log", show=False),
    ]

    def __init__(
        self,
        api_factory: Callable[..., DiscordAPI] | None = None,
        cdn_factory: Callable[[], httpx.Client] | None = None,
    ) -> None:
        super().__init__()
        self.theme = "ansi-dark"
        self.api_factory = api_factory or DiscordAPI
        self.cdn_factory = cdn_factory or cdn_client
        self.selection = SelectionState()
        self.settings = ExportSettings()
        self.servers: list[Server] = []
        self.channels_by_server: dict[str, list[Channel]] = {}  # only servers with loaded channels
        self.no_access_servers: set[str] = set()
        self.cancel_token: CancelToken | None = None  # set while a network operation runs
        self.is_running_job = False  # that operation is an export
        self.current_narrow_tab = 1
        self._tree_nodes: dict[str, TreeNode[Any]] = {}  # node of each server and channel in the tree
        self._expanded: set[str] = set()  # nodes the user opened; a filter opens its own and leaves this alone
        self._loading: set[str] = set()  # servers whose channels are on their way
        self._delay = 1.0  # from the config, for when the Delay field is empty
        self._filter_timer: Timer | None = None
        self._channels_done = 0
        self._channels_total = 0
        self._current_channel = ""

    def compose(self) -> ComposeResult:
        # Kept as attributes here, not in on_mount: the Footer asks check_action() before on_mount runs.
        self._status = Label("Ready.", id="run-status", markup=False)
        self._progress = ProgressBar(id="job-progress", show_eta=False)
        self._event_log = RichLog(id="event-log", wrap=True, min_width=20, max_lines=1000)
        self._filter = FilterInput(id="tree-filter")
        self._tree = ChannelTree("Servers", id="channel-tree")
        self._selected_list = SelectedList(id="selected-list")
        self._form = FormPanel(id="export-form")
        self._start_row = ActionRow(START_LABEL, id="row-start")

        with Horizontal(id="top-bar"):
            yield Label("discoop", id="app-title")
            yield Label("checking...", id="status-indicator", markup=False)
            yield Label("safe", id="mode-indicator")
            yield Label("F1 help", id="help-hint")

        with Container(id="main-columns"):
            with Vertical(classes="pane", id="tree-pane"):
                yield self._filter
                yield self._tree

            with Vertical(classes="pane", id="export-pane"):
                yield Label("Selected (0)", id="selected-title")
                yield self._selected_list
                with self._form:
                    yield ChoiceRow("Window", WINDOW_PRESETS, "7d", id="row-window")
                    yield InputRow("From", "input-from", value="7d", placeholder="7d, 2026-10-01, all", id="row-from")
                    yield InputRow("To", "input-to", placeholder="now", id="row-to")
                    yield InputRow(
                        "Last N", "input-last", placeholder="all in window", input_type="integer", id="row-last"
                    )
                    yield InputRow(
                        "Max messages",
                        "input-max-messages",
                        value=str(DEFAULT_MAX_MESSAGES),
                        input_type="integer",
                        id="row-max-messages",
                    )
                    yield ChoiceRow("Mode", MODES, "safe", id="row-mode")
                    yield InputRow("Delay", "input-delay", input_type="number", id="row-delay")
                    yield ChoiceRow("Attachments", ("yes", "no"), id="row-files")
                    yield InputRow(
                        "Max MB",
                        "input-max-file-size",
                        value=f"{self.settings.max_file_size:g}",
                        input_type="number",
                        id="row-max-mb",
                    )
                    yield ChoiceRow("System msgs", ("no", "yes"), id="row-system")
                    yield ChoiceRow("Target", TARGETS, id="row-target")
                    yield InputRow(
                        "Folder",
                        "input-folder",
                        placeholder=str(default_folder(self.settings)),
                        tail_placeholder=True,
                        id="row-folder",
                    )
                    yield InputRow("Name", "input-name", placeholder=default_name(), id="row-name")
                    yield ChoiceRow("Format", FORMATS, id="row-format")
                    yield self._start_row

        with Vertical(classes="pane", id="log-pane"):
            with Horizontal(id="run-bar"):
                yield self._status
                yield self._progress
            yield self._event_log

        with Horizontal(id="command-bar"):
            yield Label("$", id="command-prefix")
            yield Static(NO_COMMAND, id="command-preview", markup=False)
            yield Label("(c copy)", id="command-hint")

        # No palette hint: docked over the keys it lets one of them show through. Ctrl+P works all the same.
        yield Footer(compact=True, show_command_palette=False)

    def on_mount(self) -> None:
        self.query_one("#tree-pane").border_title = "Servers & channels"
        self.query_one("#export-pane").border_title = "Export"
        self.query_one("#log-pane").border_title = "Log"
        self.screen.add_class(f"show-tab-{self.current_narrow_tab}")
        self._progress.display = False
        self._selected_list.display = False

        self._load_config()
        self._sync_form()
        self._tree.focus()
        self._start_directory(refresh=False)
        self.set_interval(NAME_REFRESH, self._update_command_preview)

    def check_action(self, action: str, parameters: tuple[object, ...]) -> bool | None:
        if action == "cycle_pane":  # a priority binding: dialogs must keep their own Tab
            return len(self.screen_stack) == 1
        if action == "stop_or_back":
            return self.cancel_token is not None or self._filter.has_focus or bool(self._filter.value)
        return True

    # ==================== Config and form ====================

    def _load_config(self) -> None:
        """Take mode, delay and export-dir from the config, so the form shows what an export would really use."""
        try:
            config = Config.default()
            mode = config.get("mode")
            self._delay = float(config.get("delay"))
            export_dir = config.get("export-dir")
        except (DiscoopError, TypeError, ValueError) as e:
            self._log_line(f"Config: {e}", "red")
            return
        self.settings.mode = mode if mode in MODES else "safe"
        self.settings.delay = self._delay
        self.settings.export_dir = export_dir

    def _sync_form(self) -> None:
        self.query_one("#row-mode", ChoiceRow).set_value(self.settings.mode)
        if self.settings.delay is not None:
            self.query_one("#input-delay", Input).value = f"{self.settings.delay:g}"
        self._sync_form_rows()
        self._sync_mode_indicator()
        self._update_command_preview()

    def _sync_form_rows(self) -> None:
        settings = self.settings
        preview = settings.target == "preview"
        self.query_one("#row-delay").display = settings.mode == "fast"
        self.query_one("#row-files").display = not preview
        self.query_one("#row-max-mb").display = settings.files and not preview
        self.query_one("#row-folder").display = not preview
        self.query_one("#row-name").display = not preview
        self.query_one("#row-format").display = preview

    def _sync_mode_indicator(self) -> None:
        indicator = self.query_one("#mode-indicator", Label)
        indicator.update(self.settings.mode)
        indicator.set_class(self.settings.mode == "fast", "-fast")

    def on_choice_row_changed(self, event: ChoiceRow.Changed) -> None:
        settings = self.settings
        row_id = event.row.id
        if row_id == "row-window":
            self._apply_preset(event.value)
        elif row_id == "row-mode":
            settings.mode = event.value
            self._sync_mode_indicator()
        elif row_id == "row-files":
            settings.files = event.value == "yes"
        elif row_id == "row-system":
            settings.include_system = event.value == "yes"
        elif row_id == "row-target":
            settings.target = event.value
        elif row_id == "row-format":
            settings.preview_format = event.value
        self._sync_form_rows()
        self._update_command_preview()

    def _apply_preset(self, preset: str) -> None:
        self.query_one("#input-from", Input).value = preset
        self.query_one("#input-to", Input).value = ""
        self.query_one("#input-last", Input).value = ""
        self._sync_global_window_from_inputs()

    def on_input_changed(self, event: Input.Changed) -> None:
        input_id = event.input.id
        raw = event.value.strip()
        if input_id == "tree-filter":
            if self._filter_timer is not None:
                self._filter_timer.stop()
            self._filter_timer = self.set_timer(FILTER_DELAY, self._rebuild_tree)
            self.refresh_bindings()
        elif input_id in ("input-from", "input-to", "input-last", "input-max-messages"):
            self._sync_global_window_from_inputs()
        elif input_id == "input-delay":
            self.settings.delay = self._parse(float, raw, self.settings.delay)
            self._update_command_preview()
        elif input_id == "input-max-file-size":
            self.settings.max_file_size = self._parse(float, raw, self.settings.max_file_size)
            self._update_command_preview()
        elif input_id == "input-folder":
            self.settings.folder = raw
            self._update_command_preview()
        elif input_id == "input-name":
            self.settings.name = raw
            self._update_command_preview()

    @staticmethod
    def _parse(kind: type, raw: str, previous: Any) -> Any:
        """`raw` as a number, None when empty, `previous` while it is half typed (e.g. "-")."""
        if not raw:
            return None
        try:
            return kind(raw)
        except ValueError:
            return previous

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input is self._filter:
            self._focus_region("tree")

    def _sync_global_window_from_inputs(self) -> None:
        from_ = self.query_one("#input-from", Input).value.strip() or None
        to = self.query_one("#input-to", Input).value.strip() or None
        last = self._parse(int, self.query_one("#input-last", Input).value.strip(), None)
        limit = self._parse(int, self.query_one("#input-max-messages", Input).value.strip(), None)
        self.selection.global_window = WindowSpec(
            from_=from_, to=to, last=last, max_messages=DEFAULT_MAX_MESSAGES if limit is None else limit
        )
        self.query_one("#row-window", ChoiceRow).set_value(window_preset(from_, to, last))
        self._update_selected_ui()
        self._update_command_preview()

    def _update_command_preview(self) -> None:
        self.query_one("#input-folder", TailInput).set_placeholder(str(default_folder(self.settings)))
        self.query_one("#input-name", Input).placeholder = default_name()
        commands = [job.request.to_command_str() for job in plan_jobs(self.selection, self.settings)]
        self.query_one("#command-preview", Static).update(" && ".join(commands) or NO_COMMAND)

    def action_copy_command(self) -> None:
        jobs = plan_jobs(self.selection, self.settings)
        if not jobs:
            self.notify("No channels selected.", severity="warning")
            return
        self.copy_to_clipboard(" && ".join(job.request.to_command_str() for job in jobs))
        self.notify("Copied the CLI command.")

    # ==================== Panels ====================

    def _switch_narrow_tab(self, tab: int) -> None:
        self.current_narrow_tab = tab
        for number in (1, 2, 3):
            self.screen.set_class(number == tab, f"show-tab-{number}")

    def _focus_region(self, region: str) -> None:
        self._switch_narrow_tab({"tree": 1, "list": 2, "form": 2, "log": 3}[region])
        if region == "tree":
            self._tree.focus()
        elif region == "list":
            self._selected_list.focus()
        elif region == "form":
            self._form.focus_row()
        else:
            self._event_log.focus()

    def _current_region(self) -> str | None:
        focused = self.screen.focused
        if focused is None:
            return None
        if focused is self._tree or focused is self._filter:
            return "tree"
        if focused is self._selected_list:
            return "list"
        return "log" if focused is self._event_log else "form"

    def action_cycle_pane(self, delta: int) -> None:
        regions = ["tree", "list", "form"] if self.selection.selected else ["tree", "form"]
        current = self._current_region()
        index = regions.index(current) if current in regions else -1
        self._focus_region(regions[(index + delta) % len(regions)])

    def action_pane(self, number: int) -> None:
        if number == 1:
            self._focus_region("tree")
        elif number == 2:
            self._focus_region("list" if self.selection.selected else "form")
        else:
            self._focus_region("log")

    def action_focus_filter(self) -> None:
        self._switch_narrow_tab(1)
        self._filter.focus()

    def action_stop_or_back(self) -> None:
        if self.cancel_token is not None:
            self.cancel_token.cancel()
            self._set_status("Stopping...")
        elif self._filter.has_focus:
            self._focus_region("tree")
        elif self._filter.value:
            self._filter.value = ""

    async def action_quit(self) -> None:
        if self.cancel_token is not None:
            self.cancel_token.cancel()
        self.exit()

    def action_help(self) -> None:
        self.push_screen(HelpScreen())

    def action_settings(self) -> None:
        def on_saved(saved: bool | None) -> None:
            if saved:
                self._load_config()
                self._sync_form()

        self.push_screen(SettingsModal(), on_saved)

    def action_login(self) -> None:
        def on_changed(changed: bool | None) -> None:
            if changed:  # what was selected or refused belongs to the previous account
                self.no_access_servers.clear()
                self._clear_selection()
                self._start_directory(refresh=True)

        self.push_screen(LoginModal(self.api_factory), on_changed)

    # ==================== Tree ====================

    @staticmethod
    def _key(data: Any) -> str:
        return f"server:{data.id}" if isinstance(data, Server) else f"channel:{data.id}"

    def _filter_query(self) -> str:
        return self._filter.value.strip()

    def _selectable(self, category: Channel) -> list[Channel]:
        channels = self.channels_by_server.get(category.server_id, [])
        return [c for c in channels if c.parent_id == category.id and self.selection.is_selectable(c)]

    def _channel_label(self, channel: Channel) -> Text:
        name = display_name(channel.name)
        if not self.selection.is_selectable(channel):
            return Text(f"    #{name} ({channel.type_name})", style="dim")
        if self.selection.is_selected(channel.id):
            return Text.assemble(("[x]", "bold"), f" #{name}")
        return Text(f"[ ] #{name}")

    def _category_label(self, category: Channel) -> Text:
        name = display_name(category.name)
        members = self._selectable(category)
        if not members:
            return Text(name, style="dim")
        picked = sum(self.selection.is_selected(c.id) for c in members)
        if picked == len(members):
            return Text.assemble(("[x]", "bold"), f" {name}")
        return Text.assemble(("[~]", "bold"), f" {name}") if picked else Text(f"[ ] {name}")

    def _server_badge(self, server: Server) -> str:
        if server.id in self._loading:
            return "loading..."
        if server.id in self.no_access_servers:
            return "no access"
        channels = self.channels_by_server.get(server.id)
        if channels is None:
            return "not loaded"
        return str(sum(c.type != CATEGORY for c in channels))

    def _rebuild_tree(self) -> None:
        """Lay the tree out again, for new data or a new filter. The cursor stays on its server or channel.

        A filter opens every node that holds a match and hides the rest. `_expanded` stays untouched meanwhile, so
        clearing the filter brings back what the user had open. Selecting never comes here: see `_relabel`.
        """
        tree = self._tree
        cursor = tree.cursor_node
        cursor_key = None if cursor is None or cursor.data is None else self._key(cursor.data)
        query = self._filter_query()
        tree.clear()
        self._tree_nodes = {}
        for server in self.servers:
            channels = self.channels_by_server.get(server.id)
            shown = filter_channels(channels, query) if channels and query else channels
            if query and not shown:
                continue
            key = self._key(server)
            node = tree.add_top(
                Text(display_name(server.name)),
                data=server,
                badge=self._server_badge(server),
                expand=bool(query) or key in self._expanded,
            )
            self._tree_nodes[key] = node
            self._add_channels(node, shown or [], bool(query))
        self._restore_cursor(cursor_key)

    def _add_channels(self, server_node: TreeNode[Any], channels: Iterable[Channel], open_all: bool) -> None:
        for category, members in group_by_category(channels):
            parent = server_node
            if category is not None:
                key = self._key(category)
                expand = open_all or key in self._expanded
                parent = server_node.add(self._category_label(category), data=category, expand=expand)
                self._tree_nodes[key] = parent
            for channel in members:
                self._tree_nodes[self._key(channel)] = parent.add_leaf(self._channel_label(channel), data=channel)

    def _restore_cursor(self, key: str | None) -> None:
        tree = self._tree
        if tree.last_line < 0:  # also builds the lines `move_cursor` needs
            tree.move_cursor(None)
            return
        node = self._tree_nodes.get(key) if key is not None else None
        if node is None:
            tree.move_cursor(tree.get_node_at_line(0))
            return
        ancestors: list[TreeNode[Any]] = []
        parent = node.parent
        while parent is not None and not parent.is_root:
            ancestors.append(parent)
            parent = parent.parent
        closed = next((a for a in reversed(ancestors) if not a.is_expanded), None)
        tree.move_cursor(closed or node)

    def _relabel(self, channel_ids: Iterable[str]) -> None:
        """Update just the rows of these channels and of their categories: cursor and open nodes stay."""
        categories: dict[str, Channel] = {}
        for channel_id in channel_ids:
            node = self._tree_nodes.get(f"channel:{channel_id}")
            if node is None:
                continue
            node.set_label(self._channel_label(node.data))
            parent = node.parent
            if parent is not None and isinstance(parent.data, Channel):
                categories[parent.data.id] = parent.data
        for category in categories.values():
            self._tree_nodes[self._key(category)].set_label(self._category_label(category))

    def _selection_changed(self, channel_ids: Iterable[str]) -> None:
        self._relabel(channel_ids)
        self._update_selected_ui()
        self._update_command_preview()

    def on_tree_node_expanded(self, event: ChannelTree.NodeExpanded[Any]) -> None:
        data = event.node.data
        if data is None:
            return
        if not self._filter_query():
            self._expanded.add(self._key(data))
        known = data.id in self.channels_by_server or data.id in self.no_access_servers
        if isinstance(data, Server) and not known and not self._start_channels(data, refresh=False):
            event.node.collapse()

    def on_tree_node_collapsed(self, event: ChannelTree.NodeCollapsed[Any]) -> None:
        if event.node.data is not None and not self._filter_query():
            self._expanded.discard(self._key(event.node.data))

    def on_tree_node_selected(self, event: ChannelTree.NodeSelected[Any]) -> None:
        """Enter or a click: a channel changes its selection, anything else opens or closes."""
        data = event.node.data
        if isinstance(data, Channel) and data.type != CATEGORY:
            self._toggle(data)
        elif data is not None:
            event.node.toggle()

    def action_toggle_cursor(self) -> None:
        node = self._tree.cursor_node
        if node is None:
            return
        if isinstance(node.data, Server):
            self.notify("Space selects a channel or a category. On a server, a selects all shown channels.")
        else:
            self._toggle(node.data)

    def _toggle(self, channel: Channel) -> None:
        server = next(s for s in self.servers if s.id == channel.server_id)
        if channel.type != CATEGORY:
            if self.selection.is_selectable(channel):
                self.selection.toggle(server, channel)
                self._selection_changed([channel.id])
            return
        members = self._selectable(channel)
        if members and all(self.selection.is_selected(c.id) for c in members):
            self.selection.deselect_many(c.id for c in members)
        else:
            self.selection.select_many(server, members)
        self._selection_changed(c.id for c in members)

    def _server_at_cursor(self) -> Server | None:
        node = self._tree.cursor_node
        while node is not None and not isinstance(node.data, Server):
            node = node.parent
        return node.data if node is not None else None

    def action_select_shown(self) -> None:
        server = self._server_at_cursor()
        if server is None:
            return
        channels = self.channels_by_server.get(server.id)
        if channels is None:
            self.notify("Load the server first with the right arrow.", severity="warning")
            return
        shown = [c for c in filter_channels(channels, self._filter_query()) if self.selection.is_selectable(c)]
        self.selection.select_many(server, shown)
        self._selection_changed(c.id for c in shown)

    # ==================== Selected channels ====================

    def _update_selected_ui(self) -> None:
        selected = self._selected_list
        option = selected.highlighted_option
        highlighted_id = None if option is None else option.id
        highlighted_index = selected.highlighted or 0

        options = []
        for channel_id, (server, channel) in self.selection.selected.items():
            mark = "*" if self.selection.has_custom_window(channel_id) else ""
            window = short_window(self.selection.window_for(channel_id))
            label = f"{display_name(server.name)}/#{display_name(channel.name)}  {window}{mark}"
            options.append(Option(Text(label), id=channel_id))

        selected.clear_options()
        selected.add_options(options)
        selected.display = bool(options)
        if options:
            ids = [o.id for o in options]
            selected.highlighted = (
                ids.index(highlighted_id) if highlighted_id in ids else min(highlighted_index, len(ids) - 1)
            )
        self.query_one("#selected-title", Label).update(f"Selected ({len(options)})")

    def action_remove_selected(self) -> None:
        option = self._selected_list.highlighted_option
        if option is None or option.id is None:
            return
        self.selection.deselect_many([option.id])
        self._selection_changed([option.id])
        if not self.selection.selected:
            self._focus_region("tree")

    def action_clear_selected(self) -> None:
        self._clear_selection()
        self._focus_region("tree")

    def _clear_selection(self) -> None:
        channel_ids = list(self.selection.selected)
        self.selection.clear_all()
        self._selection_changed(channel_ids)

    def action_edit_tree_window(self) -> None:
        node = self._tree.cursor_node
        channel = None if node is None else node.data
        if not isinstance(channel, Channel) or not self.selection.is_selectable(channel):
            self.notify("Move to a channel first.", severity="warning")
            return
        self._edit_window(channel)

    def action_edit_selected_window(self) -> None:
        option = self._selected_list.highlighted_option
        if option is not None and option.id in self.selection.selected:
            self._edit_window(self.selection.selected[option.id][1])

    def _edit_window(self, channel: Channel) -> None:
        def on_dismiss(result: Any) -> None:
            if result is WINDOW_CANCELLED:
                return
            self.selection.set_custom_window(channel.id, result)
            if result is not None and not self.selection.is_selected(channel.id):
                self._toggle(channel)  # a window only means something on a channel that gets exported
            else:
                self._selection_changed([channel.id])

        modal = TimeWindowModal(
            channel_name=display_name(channel.name),
            current_spec=self.selection.custom_windows.get(channel.id),
            global_spec=self.selection.global_window,
        )
        self.push_screen(modal, on_dismiss)

    # ==================== Network operations ====================

    def _begin_net(self, status: str) -> CancelToken | None:
        """Claim the one network slot, or say busy and return None.

        A flag, not `@work(exclusive=True)`: that would only mark a running thread as cancelled, and its API call would
        go on next to the new one.
        """
        if self.cancel_token is not None:
            self.notify("Busy — wait or press Esc", severity="warning")
            return None
        self.cancel_token = CancelToken()
        self._set_status(status)
        self.refresh_bindings()
        return self.cancel_token

    def _ui(self, function: Callable[..., None], *args: Any) -> None:
        """From a worker thread: run `function` on the UI thread, after everything sent earlier.

        Never blocks the worker, unlike `call_from_thread`, and goes nowhere once the app has closed.
        """
        self.post_message(UiCall(function, args))

    def on_ui_call(self, message: UiCall) -> None:
        if self.screen_stack:  # gone while the app closes, and a late worker has nothing left to update
            message.function(*message.args)

    @contextmanager
    def _net_guard(self, what: str) -> Iterator[None]:
        """Around a worker's body: report how it ended and give the network slot back."""
        try:
            yield
        except Cancelled:
            self._ui(self._net_stopped)
        except DiscoopError as e:
            self._ui(self._net_failed, f"{what}: {e.message}")
        except Exception as e:  # an unexpected error must not take the whole UI down
            self._ui(self._net_failed, f"{what}: {e}")
        finally:
            self._ui(self._net_finished)

    def _net_stopped(self) -> None:
        self._set_status("Stopped.")
        self._log_line("Stopped by user.", "yellow")
        self.notify("Stopped.", severity="warning")

    def _net_failed(self, message: str) -> None:
        self._set_status("Error, see the log.")
        self._log_line(message, "bold red")
        self.notify(message, severity="error", markup=False)

    def _net_finished(self) -> None:
        self.cancel_token = None
        self.is_running_job = False
        self._start_row.update(START_LABEL)
        self._progress.display = False
        servers = [s for s in self.servers if s.id in self._loading]
        self._loading.clear()
        for server in servers:  # a load that failed: back to the state before it
            node = self._tree_nodes.get(self._key(server))
            if node is not None:
                self._tree.set_badge(node, self._server_badge(server))
                if server.id not in self.channels_by_server:
                    node.collapse()
        self.refresh_bindings()

    @contextmanager
    def _open_directory(self, cancel: CancelToken, *, mode: str, delay: float) -> Iterator[Directory]:
        """A Directory for a worker thread. Its pauses end at once when `cancel` fires."""
        stored = TokenStore.default().load()
        api_factory = self.api_factory

        def on_pause(seconds: float, reason: str) -> None:
            self._ui(self._handle_pause, seconds, reason)

        def open_api() -> DiscordAPI:
            if stored is None:
                raise auth_required()
            return api_factory(stored.token, delay=delay, mode=mode, sleep=cancel.sleep, on_pause=on_pause)

        with Cache.default() as cache, Directory(cache, open_api) as directory:
            yield directory

    def _api_options(self) -> dict[str, Any]:
        delay = self.settings.delay
        return {"mode": self.settings.mode, "delay": self._delay if delay is None else delay}

    @staticmethod
    def _read_cached() -> tuple[list[Server], dict[str, list[Channel]]]:
        with Cache.default() as cache:
            servers = cache.servers()
            channels = {s.id: cache.channels(s.id) for s in servers if cache.fetched_at(f"channels:{s.id}") is not None}
        return servers, channels

    def _apply_directory(self, servers: list[Server], channels: dict[str, list[Channel]]) -> None:
        self.servers = servers
        self.channels_by_server = channels
        self._rebuild_tree()

    def _set_login_status(self, text: str, state: str) -> None:
        indicator = self.query_one("#status-indicator", Label)
        indicator.update(text)
        for name in ("-ok", "-bad", "-warn"):
            indicator.set_class(name == state, name)

    # Startup and R: who am I, and which servers do I have.

    def _start_directory(self, refresh: bool) -> None:
        cancel = self._begin_net("Reloading servers..." if refresh else "Starting...")
        if cancel is not None:
            self._directory_worker(refresh, cancel, self._api_options())

    def action_reload_servers(self) -> None:
        self._start_directory(refresh=True)

    @work(thread=True, group="net", exit_on_error=False)
    def _directory_worker(self, refresh: bool, cancel: CancelToken, options: dict[str, Any]) -> None:
        with self._net_guard("Servers"):
            usable = self._check_login(cancel)
            if usable:
                with self._open_directory(cancel, **options) as directory:
                    list_servers(directory, refresh=refresh)
            servers, channels = self._read_cached()
            self._ui(self._apply_directory, servers, channels)
            self._ui(self._set_status, f"Ready. {plural(len(servers), 'server')}.")
            if not servers and not usable:
                self._ui(self._log_line, "Not logged in or Discord is out of reach: press F3 to log in.", "yellow")

    def _check_login(self, cancel: CancelToken) -> bool:
        """Show who is logged in. True if Discord can be asked for more."""
        stored = TokenStore.default().load()
        if stored is None:
            self._ui(self._set_login_status, "not logged in", "-bad")
            return False
        try:
            with self.api_factory(stored.token, sleep=cancel.sleep) as api:
                me = api.get_me()
        except Cancelled:
            raise
        except Exception as e:
            if isinstance(e, DiscoopError) and e.code == ExitCode.AUTH_REQUIRED:
                self._ui(self._set_login_status, "token invalid", "-bad")
            else:
                self._ui(self._set_login_status, "offline?", "-warn")
            return False
        self._ui(self._set_login_status, f"@{me.get('username') or me.get('global_name') or 'user'}", "-ok")
        return True

    # → or Enter on a server that is not loaded, and r.

    def action_reload_channels(self) -> None:
        server = self._server_at_cursor()
        if server is not None:
            self._start_channels(server, refresh=True)

    def _start_channels(self, server: Server, refresh: bool) -> bool:
        cancel = self._begin_net(f"Loading channels of {display_name(server.name)}...")
        if cancel is None:
            return False
        self._loading.add(server.id)
        node = self._tree_nodes.get(self._key(server))
        if node is not None:
            self._tree.set_badge(node, self._server_badge(server))
        self._channels_worker(server, refresh, cancel, self._api_options())
        return True

    @work(thread=True, group="net", exit_on_error=False)
    def _channels_worker(
        self, server: Server, refresh: bool, cancel: CancelToken, options: dict[str, Any]
    ) -> None:
        with self._net_guard("Channels"):
            try:
                with self._open_directory(cancel, **options) as directory:
                    channels = list_channels(directory, server, refresh=refresh)
            except DiscoopError as e:
                if e.code != ExitCode.NO_ACCESS:
                    raise
                self._ui(self._server_no_access, server)
                return
            self._ui(self._apply_channels, server, channels)

    def _apply_channels(self, server: Server, channels: list[Channel]) -> None:
        self.no_access_servers.discard(server.id)
        self.channels_by_server[server.id] = channels
        self._loading.discard(server.id)
        self._rebuild_tree()
        count = sum(c.type != CATEGORY for c in channels)
        self._set_status(f"Ready. {display_name(server.name)}: {plural(count, 'channel')}.")

    def _server_no_access(self, server: Server) -> None:
        self.no_access_servers.add(server.id)
        self.channels_by_server.pop(server.id, None)
        self._loading.discard(server.id)
        self._expanded.discard(self._key(server))
        self._rebuild_tree()
        self._set_status(f"No access to {display_name(server.name)}.")

    # L: everything, at the safe pace.

    def action_load_all(self) -> None:
        cancel = self._begin_net("Loading all servers...")
        if cancel is not None:
            self._load_all_worker(cancel, self._api_options()["delay"])

    @work(thread=True, group="net", exit_on_error=False)
    def _load_all_worker(self, cancel: CancelToken, delay: float) -> None:
        def on_server(index: int, total: int, server: Server) -> None:
            cancel.check()
            self._ui(self._set_status, f"Loading {index}/{total}: {display_name(server.name)}")

        with self._net_guard("Load all"):
            results: list[tuple[Server, list[Channel]]] = []
            try:
                with self._open_directory(cancel, mode="safe", delay=delay) as directory:
                    results = load_all(directory, on_server=on_server)
            finally:  # also after Esc: what did load stays in the cache and in the tree
                servers, channels = self._read_cached()
                self._ui(self._apply_directory, servers, channels)
            no_access = {s.id for s, found in results if not found and s.id not in channels}
            self._ui(self._load_all_done, no_access, len(results))

    def _load_all_done(self, no_access: set[str], total: int) -> None:
        self.no_access_servers = no_access
        self._rebuild_tree()
        self._set_status(f"Ready. Channels of {plural(total, 'server')} loaded.")
        self._log_line(f"Loaded the channels of {plural(total, 'server')}.", "green")

    # F5: export.

    def action_start_export(self) -> None:
        jobs = plan_jobs(self.selection, self.settings)
        if not jobs:
            self.notify("No channels selected.", severity="warning")
            return
        cancel = self._begin_net("Starting export...")
        if cancel is None:
            return
        self.is_running_job = True
        self._start_row.update(STOP_LABEL)
        self._channels_done = 0
        self._channels_total = sum(len(job.targets) for job in jobs)
        self._progress.update(total=self._channels_total, progress=0)
        self._progress.display = True
        self._log_line(f"Export of {plural(self._channels_total, 'channel')} started.", "bold")
        for job in jobs:
            if target := job.request.out_dir or job.request.zip_file:
                self._log_line(f"Saving to {target}")
        preview_format = self.settings.preview_format if self.settings.target == "preview" else None
        self._export_worker(jobs, cancel, self._api_options(), preview_format)

    def on_action_row_pressed(self, event: ActionRow.Pressed) -> None:
        if self.is_running_job:
            self.action_stop_or_back()
        else:
            self.action_start_export()

    @work(thread=True, group="net", exit_on_error=False)
    def _export_worker(
        self, jobs: list[PlannedJob], cancel: CancelToken, options: dict[str, Any], preview_format: str | None
    ) -> None:
        with self._net_guard("Export"):
            outcomes: list[MessagesOutcome] = []
            with self._open_directory(cancel, **options) as directory:
                events = TuiEvents(cancel, self._bridge_emit())
                for job in jobs:
                    cancel.check()
                    outcomes.append(
                        run_messages(
                            job.request, directory=directory, cdn=self.cdn_factory, tz=LOCAL_ZONE, events=events
                        )
                    )
            self._ui(self._export_finished, outcomes, preview_format)

    def _bridge_emit(self) -> Callable[[str, dict[str, Any]], None]:
        """The event sink for `TuiEvents`. A download reports each chunk, so those go out in batches."""
        pending = 0
        reported = 0.0

        def emit(name: str, payload: dict[str, Any]) -> None:
            nonlocal pending, reported
            if name == "dl_advance":
                pending += payload["size"]
                now = time.monotonic()
                if now - reported < DOWNLOAD_REPORT_INTERVAL:
                    return
                payload = {"size": pending}
                pending, reported = 0, now
            self._ui(self._handle_bridge_event, name, payload)

        return emit

    def _handle_bridge_event(self, name: str, payload: dict[str, Any]) -> None:
        if name == "channel_start":
            channel = payload["channel"]
            self._current_channel = display_name(channel.name)
            self._set_status(f"#{self._current_channel} ({self._channels_done + 1}/{self._channels_total})")
            self._log_line(f"Reading #{self._current_channel}")
        elif name == "page":
            self._set_status(f"#{self._current_channel}: {payload['count']} messages")
        elif name == "pause":
            self._handle_pause(payload["seconds"], payload["reason"])
        elif name == "channel_done":
            self._channel_finished()
            result = payload["result"]
            self._log_line(f"#{display_name(result.channel.name)}: {plural(len(result.messages), 'message')}", "green")
        elif name == "skipped":
            self._channel_finished()
            self._log_line(f"Skipped: {payload['reason']}", "yellow")
        elif name == "warning":
            self._log_line(payload["message"], "yellow")
        elif name == "note":
            self._log_line(payload["text"], "dim")
        elif name == "dl_start":
            self._log_line(f"Downloading {plural(payload['files'], 'file')}")
            self._progress.update(total=max(payload["total_bytes"], 1), progress=0)
        elif name == "dl_file":
            filename = payload["job"].attachment.filename
            self._set_status(f"File {payload['number']}/{payload['total']}: {filename}")
        elif name == "dl_advance":
            self._progress.advance(payload["size"])
        elif name == "dl_finish":
            self._progress.update(total=self._channels_total, progress=self._channels_done)

    def _handle_pause(self, seconds: float, reason: str) -> None:
        self._set_status(f"Pause {seconds:.1f} s ({reason})")

    def _channel_finished(self) -> None:
        self._channels_done += 1
        self._progress.update(progress=self._channels_done)

    def _export_finished(self, outcomes: list[MessagesOutcome], preview_format: str | None) -> None:
        results = [result for outcome in outcomes for result in outcome.results]
        skipped = sum(len(outcome.skipped) for outcome in outcomes)
        truncated = sum(result.truncated for result in results)
        messages = sum(len(result.messages) for result in results)

        summary = f"{plural(len(results), 'channel')}, {plural(messages, 'message')}"
        if skipped:
            summary += f", {skipped} skipped"
        if truncated:
            summary += f", {truncated} cut at Max messages"
        problems = bool(skipped or truncated)
        for outcome in outcomes:
            if outcome.exported is not None:
                problems |= self._log_exported(outcome)

        self._set_status(f"Done: {summary}.")
        self._log_line(f"Export done: {summary}.", "yellow" if problems else "green")
        self.notify(f"Export done: {summary}.", severity="warning" if problems else "information", markup=False)
        if preview_format is not None and results:
            self.push_screen(PreviewScreen(results, query=outcomes[0].query, initial_format=preview_format))

    def _log_exported(self, outcome: MessagesOutcome) -> bool:
        """Say where an export went and how its files fared. True if some are missing."""
        exported = outcome.exported
        assert exported is not None
        jobs = exported.jobs
        wanted = [job for job in jobs if job.reason != NO_FILES]
        too_large = sum(job.status == SKIPPED for job in wanted)
        failed = exported.count(FAILED)
        if wanted:
            files = (
                f"{plural(len(wanted), 'file')}: {exported.count(DOWNLOADED)} downloaded,"
                f" {exported.count(PRESENT)} already present, {failed} failed, {too_large} too large"
            )
        else:
            files = "no files"
        self._log_line(f"{exported.path} ({files})", "yellow" if failed or too_large else "")
        return bool(failed or too_large)

    # ==================== Log panel ====================

    def _set_status(self, text: str) -> None:
        self._status.update(text)

    def _log_line(self, message: str, style: str = "") -> None:
        stamp = datetime.now().strftime("%H:%M:%S")
        self._event_log.write(Text.assemble((f"{stamp} ", "dim"), (message, style)))


def run_app() -> None:
    """Run the interactive discoop TUI."""
    app = DiscoopApp()
    app.run()
