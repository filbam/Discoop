"""Main Textual Application for discoop.

Responsive Discord-inspired TUI for server & channel browsing,
export job planning, live progress reporting, and embedded preview.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx
from rich.text import Text
from textual import events, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, Vertical, VerticalScroll
from textual.widgets import (
    Button,
    Checkbox,
    Input,
    Label,
    OptionList,
    ProgressBar,
    RichLog,
    Static,
    Tree,
)
from textual.widgets.option_list import Option
from textual.widgets.tree import TreeNode

from discoop.api import DiscordAPI
from discoop.attachments import cdn_client
from discoop.cache import Cache
from discoop.cli import LOCAL_ZONE
from discoop.directory import Directory
from discoop.errors import DiscoopError, ExitCode
from discoop.models import (
    CATEGORY,
    Channel,
    ChannelMessages,
    Server,
    group_by_category,
)
from discoop.service import (
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
    ExportSettings,
    PlannedJob,
    SelectionState,
    WindowSpec,
    filter_channels,
    plan_jobs,
)


class DiscoopApp(App[None]):
    """The Discoop Terminal User Interface application."""

    TITLE = "discoop"
    CSS_PATH = "discoop.tcss"
    HORIZONTAL_BREAKPOINTS = [(0, "-narrow"), (95, "-wide")]

    BINDINGS = [
        Binding("f1", "help", "Help"),
        Binding("question_mark", "help", "Help"),
        Binding("f5", "start_export", "Start Export"),
        Binding("r", "refresh_channels", "Load Server Channels"),
        Binding("R", "load_all", "Load All Servers & Channels"),
        Binding("s", "refresh_servers", "Refresh Servers"),
        Binding("e", "edit_channel_window", "Custom Time"),
        Binding("slash", "focus_search", "Search"),
        Binding("c", "copy_command", "Copy CLI Cmd"),
        Binding("1", "tab_or_pane(1)", "Servers"),
        Binding("2", "tab_or_pane(2)", "Channels"),
        Binding("3", "tab_or_pane(3)", "Export"),
        Binding("space", "toggle_channel", "Toggle Channel"),
        Binding("escape", "stop_or_back", "Stop"),
        Binding("q", "quit", "Quit"),
    ]

    def __init__(
        self,
        api_factory: Callable[..., DiscordAPI] | None = None,
        cdn_factory: Callable[[], httpx.Client] | None = None,
    ) -> None:
        super().__init__()
        self.api_factory = api_factory or DiscordAPI
        self.cdn_factory = cdn_factory or cdn_client
        self.selection = SelectionState()
        self.settings = ExportSettings()
        self.servers: list[Server] = []
        self.current_server: Server | None = None
        self.server_channels: list[Channel] = []
        self.active_jobs: list[PlannedJob] = []
        self.cancel_token: CancelToken | None = None
        self.is_running_job: bool = False
        self.current_narrow_tab: int = 1

    def compose(self) -> ComposeResult:
        # Top Bar
        with Horizontal(id="top-bar"):
            yield Label("🔴 Checking...", id="status-indicator")
            yield Label("🛡️ SAFE", id="mode-indicator")
            yield Label("80x24", id="size-indicator")
            yield Static("", classes="top-bar-spacer")
            yield Button("? Help (F1)", classes="top-bar-btn", id="btn-help")
            yield Button("⚙ Settings", classes="top-bar-btn", id="btn-settings")
            yield Button("🔑 Login", classes="top-bar-btn", id="btn-login")

        # Narrow Tabs Bar (visible only in -narrow mode)
        with Horizontal(id="narrow-tabs"):
            yield Button("[1] Servers & Channels", classes="narrow-tab-btn -active", id="narrow-tab-1")
            yield Button("[2] Export & Settings", classes="narrow-tab-btn", id="narrow-tab-2")
            yield Button("[3] Run & Output", classes="narrow-tab-btn", id="narrow-tab-3")

        # Main 3 Columns / Panes
        with Container(id="main-columns"):
            # 1. Servers Pane
            with Vertical(classes="pane", id="servers-pane"):
                with Horizontal(classes="pane-header"):
                    yield Label("SERVERS", classes="pane-title")
                with Horizontal(classes="button-bar"):
                    yield Button("↻ Refresh", id="btn-refresh-servers")
                    yield Button("⇊ Load All", id="btn-load-all")
                yield OptionList(id="server-list")

            # 2. Channels Pane
            with Vertical(classes="pane", id="channels-pane"):
                with Horizontal(classes="pane-header"):
                    yield Label("CHANNELS", id="channel-pane-title", classes="pane-title")
                yield Input(
                    placeholder="Filter channels (ignores diacritics & emoji)...",
                    id="channel-search",
                )
                with Horizontal(classes="button-bar"):
                    yield Button("↻ Load Server Channels", id="btn-refresh-channels")
                    yield Button("☑ Select Shown", id="btn-select-shown")
                    yield Button("☐ Clear Server", id="btn-clear-server")
                yield Tree("Channels", id="channel-tree")

            # 3. Export & Progress Pane
            with Vertical(classes="pane", id="export-pane"):
                with Vertical(id="export-settings-box"):
                    with Horizontal(classes="pane-header"):
                        yield Label("EXPORT SELECTION", classes="pane-title")
                    with Horizontal(classes="button-bar"):
                        yield Button("✎ Custom Time (E)", id="btn-custom-time")
                        yield Button("✕ Clear All", id="btn-clear-all")
                    yield OptionList(id="selected-list")

                    yield Label("GLOBAL TIME WINDOW", classes="section-label")
                    with Horizontal(classes="button-bar"):
                        yield Button("24h", id="preset-24h")
                        yield Button("7d", classes="-active", id="preset-7d")
                        yield Button("30d", id="preset-30d")
                        yield Button("All", id="preset-all")
                    with Horizontal(classes="input-row"):
                        yield Label("From:")
                        yield Input(value="7d", placeholder="e.g. 7d, 2026-10-01", id="input-from")
                    with Horizontal(classes="input-row"):
                        yield Label("To:")
                        yield Input(value="", placeholder="e.g. now, 2026-10-15", id="input-to")
                    with Horizontal(classes="input-row"):
                        yield Label("Last N:")
                        yield Input(value="", placeholder="N most recent messages", id="input-last")
                    with Horizontal(classes="input-row"):
                        yield Label("Max:")
                        yield Input(value="5000", placeholder="Max messages safety limit", id="input-max-messages")

                    yield Label("PACING & ATTACHMENTS", classes="section-label")
                    with Horizontal(classes="radio-row"):
                        yield Button("🛡️ Safe", classes="-active", id="mode-safe")
                        yield Button("⚡ Fast", id="mode-fast")
                    with Horizontal(classes="input-row"):
                        yield Label("Delay (s):")
                        yield Input(value="1.0", placeholder="Pacing delay (seconds)", id="input-delay")
                    with Horizontal(classes="checkbox-row"):
                        yield Checkbox("Download attachments", value=True, id="chk-files")
                    with Horizontal(classes="input-row"):
                        yield Label("Max MB:")
                        yield Input(value="50.0", placeholder="Max file size in MB", id="input-max-file-size")
                    with Horizontal(classes="checkbox-row"):
                        yield Checkbox("Include system messages", value=False, id="chk-system")

                    yield Label("EXPORT TARGET", classes="section-label")
                    with Horizontal(classes="radio-row"):
                        yield Button("Folder (--out)", classes="-active", id="target-folder")
                        yield Button("ZIP (--zip)", id="target-zip")
                        yield Button("Preview", id="target-preview")
                    with Horizontal(classes="input-row"):
                        yield Label("Path:")
                        yield Input(
                            value="exports/discoop-export",
                            placeholder="Destination path",
                            id="input-path",
                        )
                    with Horizontal(classes="radio-row"):
                        yield Button("text", classes="-active", id="fmt-text")
                        yield Button("md", id="fmt-md")
                        yield Button("json", id="fmt-json")
                        yield Button("jsonl", id="fmt-jsonl")

                    with Horizontal(classes="action-row"):
                        yield Button("▶ START EXPORT (F5)", variant="success", id="btn-start")
                        yield Button("⏹ STOP (Esc)", variant="error", id="btn-stop")

                with Vertical(id="progress-box"):
                    yield Label("Ready.", id="run-status")
                    yield ProgressBar(id="job-progress", show_eta=False)
                    yield RichLog(id="event-log", highlight=True, markup=True)

        # Bottom Command Bar
        with Horizontal(id="command-bar"):
            yield Label("$", id="command-prefix")
            yield Static("(select channels to preview CLI command)", id="command-preview")
            yield Button("Copy (C)", id="btn-copy-command")

    def on_mount(self) -> None:
        self.screen.add_class("show-tab-1")
        self._update_login_status()
        self._sync_mode_indicator()
        self.action_refresh_servers(refresh=False)

    def on_resize(self, event: events.Resize) -> None:
        size_lbl = self.query_one("#size-indicator", Label)
        size_lbl.update(f"{event.size.width}x{event.size.height}")

    # ==================== Worker Thread Helpers ====================

    def _make_directory(self) -> Directory:
        cache = Cache.default()
        token_item = TokenStore.default().load()
        token = token_item.token if token_item else None
        api_fac = self.api_factory
        delay = self.settings.delay
        mode = self.settings.mode

        def open_api() -> DiscordAPI:
            try:
                return api_fac(token, delay=delay, mode=mode)
            except TypeError:
                return api_fac(token)

        return Directory(cache, open_api)

    # ==================== Status & Navigation ====================

    def _update_login_status(self) -> None:
        store = TokenStore.default()
        stored = store.load()
        indicator = self.query_one("#status-indicator", Label)
        login_btn = self.query_one("#btn-login", Button)

        if stored is None:
            indicator.update("🔴 Not logged in")
            indicator.add_class("not-logged-in")
            login_btn.label = "🔑 Login"
        else:
            indicator.remove_class("not-logged-in")
            login_btn.label = "🔑 Logged in"
            # Asynchronously verify user identity
            self._verify_user_worker(stored.token)

    @work(thread=True)
    def _verify_user_worker(self, token: str) -> None:
        try:
            api = self.api_factory(token)
            with api:
                me = api.get_me()
            name = me.get("global_name") or me.get("username") or "user"
            self.call_from_thread(self._set_logged_in_user, name)
        except Exception:
            self.call_from_thread(self._set_logged_in_user, "user")

    def _set_logged_in_user(self, name: str) -> None:
        try:
            indicator = self.query_one("#status-indicator", Label)
            indicator.update(f"🟢 @{name}")
        except Exception:
            pass

    def _sync_mode_indicator(self) -> None:
        mode_lbl = self.query_one("#mode-indicator", Label)
        if self.settings.mode == "fast":
            mode_lbl.update("⚡ FAST")
            mode_lbl.styles.color = "#5865F2"
        else:
            mode_lbl.update("🛡️ SAFE")
            mode_lbl.styles.color = "#fee75c"

    def _switch_narrow_tab(self, tab: int) -> None:
        self.current_narrow_tab = tab
        for t in (1, 2, 3):
            self.screen.remove_class(f"show-tab-{t}")
            btn = self.query_one(f"#narrow-tab-{t}", Button)
            if t == tab:
                btn.add_class("-active")
            else:
                btn.remove_class("-active")
        self.screen.add_class(f"show-tab-{tab}")

    def action_tab_or_pane(self, num: int) -> None:
        if self.screen.has_class("-narrow"):
            self._switch_narrow_tab(num)
        else:
            if num == 1:
                self.action_focus_pane("servers")
            elif num == 2:
                self.action_focus_pane("channels")
            elif num == 3:
                self.action_focus_pane("export")

    def action_focus_pane(self, pane: str) -> None:
        if pane == "servers":
            self._switch_narrow_tab(1)
            self.query_one("#server-list").focus()
        elif pane == "channels":
            self._switch_narrow_tab(1)
            self.query_one("#channel-tree").focus()
        elif pane == "export":
            self._switch_narrow_tab(2)
            self.query_one("#selected-list").focus()

    # ==================== Servers & Channels Logic ====================

    @work(thread=True)
    def action_refresh_servers(self, refresh: bool = True) -> None:
        try:
            with self._make_directory() as directory:
                srvs = list_servers(directory, refresh=refresh)
                # Compute cached channel count badges
                server_data: list[tuple[Server, int | None]] = []
                for srv in srvs:
                    if directory.cache.fetched_at(f"channels:{srv.id}") is not None:
                        count = len(directory.cache.channels(srv.id))
                        server_data.append((srv, count))
                    else:
                        server_data.append((srv, None))
            self.call_from_thread(self._update_servers_ui, server_data)
        except Exception as e:
            self.call_from_thread(self._handle_network_error, f"Servers: {e}")

    def _update_servers_ui(self, server_data: list[tuple[Server, int | None]]) -> None:
        self.servers = [s for s, _ in server_data]
        server_list = self.query_one("#server-list", OptionList)
        server_list.clear_options()

        for srv, count in server_data:
            badge = f"✓ {count}" if count is not None else "◌"
            server_list.add_option(Option(f"{srv.name}  [{badge}]", id=srv.id))

        if self.servers:
            # Select first server if none currently active
            if self.current_server is None:
                self.current_server = self.servers[0]
                server_list.highlighted = 0
                self.action_refresh_channels(refresh=False)

    def on_option_list_option_highlighted(self, event: OptionList.OptionHighlighted) -> None:
        if event.option_list.id == "server-list" and event.option_id is not None:
            srv = next((s for s in self.servers if s.id == event.option_id), None)
            if srv and srv != self.current_server:
                self.current_server = srv
                self.action_refresh_channels(refresh=False)

    @work(thread=True)
    def action_refresh_channels(self, refresh: bool = True) -> None:
        if self.current_server is None:
            return
        srv = self.current_server
        try:
            with self._make_directory() as directory:
                chans = list_channels(directory, srv, refresh=refresh)
            self.call_from_thread(self._update_channels_ui, srv, chans)
        except DiscoopError as e:
            if e.code == ExitCode.NO_ACCESS:
                self.selection.no_access_channels.add(srv.id)
                self.call_from_thread(self._update_channels_ui, srv, [])
            else:
                self.call_from_thread(self._handle_network_error, f"Channels: {e}")
        except Exception as e:
            self.call_from_thread(self._handle_network_error, f"Channels: {e}")

    def _update_channels_ui(self, server: Server, channels: list[Channel]) -> None:
        if self.current_server and self.current_server.id == server.id:
            self.server_channels = channels
            title = self.query_one("#channel-pane-title", Label)
            title.update(f"CHANNELS: {server.name}")
            self._rebuild_channel_tree()

    def _rebuild_channel_tree(self) -> None:
        search_query = self.query_one("#channel-search", Input).value.strip()
        filtered = filter_channels(self.server_channels, search_query)
        tree = self.query_one("#channel-tree", Tree)
        tree.clear()
        tree.root.expand()

        groups = group_by_category(filtered)
        for category, members in groups:
            if category is None:
                parent_node = tree.root
            else:
                all_selected = (
                    all(self.selection.is_selected(c.id) for c in members if self.selection.is_selectable(c))
                    if members
                    else False
                )
                check = "[✓]" if (members and all_selected) else "[ ]"
                parent_node = tree.root.add(f"{check} 📁 {category.name}", data=category)
                parent_node.expand()

            for channel in members:
                if self.selection.is_selectable(channel):
                    selected = self.selection.is_selected(channel.id)
                    lock = " 🔒" if channel.id in self.selection.no_access_channels else ""
                    check = "[✓]" if selected else "[ ]"
                    parent_node.add_leaf(f"{check} #{channel.name}{lock}", data=channel)
                else:
                    parent_node.add_leaf(f"    #{channel.name} ({channel.type_name})", data=channel)

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "channel-search":
            self._rebuild_channel_tree()
        elif event.input.id in ("input-from", "input-to", "input-last", "input-max-messages"):
            self._sync_global_window_from_inputs()
        elif event.input.id == "input-delay":
            try:
                self.settings.delay = float(event.value.strip())
            except ValueError:
                pass
            self._update_command_preview()
        elif event.input.id == "input-max-file-size":
            try:
                self.settings.max_file_size = float(event.value.strip())
            except ValueError:
                pass
            self._update_command_preview()
        elif event.input.id == "input-path":
            self.settings.path = event.value.strip()
            self._update_command_preview()

    def on_checkbox_changed(self, event: Checkbox.Changed) -> None:
        if event.checkbox.id == "chk-files":
            self.settings.files = event.value
            self._update_command_preview()
        elif event.checkbox.id == "chk-system":
            self.settings.include_system = event.value
            self._update_command_preview()

    def action_focus_search(self) -> None:
        self.action_focus_pane("channels")
        self.query_one("#channel-search", Input).focus()

    def on_tree_node_selected(self, event: Tree.NodeSelected) -> None:
        self._toggle_tree_node(event.node)

    def action_toggle_channel(self) -> None:
        tree = self.query_one("#channel-tree", Tree)
        if tree.cursor_node:
            self._toggle_tree_node(tree.cursor_node)

    def _toggle_tree_node(self, node: TreeNode[Any]) -> None:
        data = node.data
        if data is None or self.current_server is None:
            return

        if isinstance(data, Channel):
            if data.type == CATEGORY:
                # Toggle all selectable children under this category
                children = [
                    c
                    for c in self.server_channels
                    if c.parent_id == data.id and self.selection.is_selectable(c)
                ]
                if children:
                    all_selected = all(self.selection.is_selected(c.id) for c in children)
                    if all_selected:
                        self.selection.deselect_many(c.id for c in children)
                    else:
                        self.selection.select_many(self.current_server, children)
            elif self.selection.is_selectable(data):
                self.selection.toggle(self.current_server, data)

            self._rebuild_channel_tree()
            self._update_selected_ui()
            self._update_command_preview()

    def _update_selected_ui(self) -> None:
        selected_list = self.query_one("#selected-list", OptionList)
        selected_list.clear_options()

        for ch_id, (srv, ch) in self.selection.selected.items():
            win = self.selection.window_for(ch_id)
            win_label = win.label()
            custom_marker = "★ " if self.selection.has_custom_window(ch_id) else ""
            label = f"{srv.name} / #{ch.name} [{custom_marker}{win_label}]"
            selected_list.add_option(Option(label, id=ch_id))

    def _sync_global_window_from_inputs(self) -> None:
        from_val = self.query_one("#input-from", Input).value.strip() or None
        to_val = self.query_one("#input-to", Input).value.strip() or None
        last_raw = self.query_one("#input-last", Input).value.strip()
        max_raw = self.query_one("#input-max-messages", Input).value.strip()

        last_val: int | None = None
        if last_raw:
            try:
                last_val = int(last_raw)
            except ValueError:
                pass

        max_val = 5000
        if max_raw:
            try:
                max_val = int(max_raw)
            except ValueError:
                pass

        self.selection.global_window = WindowSpec(
            from_=from_val,
            to=to_val,
            last=last_val,
            max_messages=max_val,
        )
        self._update_selected_ui()
        self._update_command_preview()

    def _update_command_preview(self) -> None:
        jobs = plan_jobs(self.selection, self.settings)
        preview = self.query_one("#command-preview", Static)
        if not jobs:
            preview.update("(select channels to preview CLI command)")
        else:
            commands = [j.request.to_command_str() for j in jobs]
            preview.update(" && ".join(commands))

    def action_copy_command(self) -> None:
        jobs = plan_jobs(self.selection, self.settings)
        if not jobs:
            self.notify("No channels selected.", severity="warning")
            return
        cmd_str = " && ".join(j.request.to_command_str() for j in jobs)
        self.copy_to_clipboard(cmd_str)
        self.notify("Copied CLI command to clipboard!", title="Copied")

    # ==================== Load All Operation ====================

    @work(thread=True)
    def action_load_all(self) -> None:
        self.call_from_thread(self._start_progress, "Loading all servers & channels...")
        try:
            with self._make_directory() as directory:
                def on_server(idx: int, total: int, srv: Server) -> None:
                    self.call_from_thread(
                        self._log_progress,
                        f"[{idx}/{total}] Cached channels for [bold]{srv.name}[/bold]",
                    )

                results = load_all(directory, on_server=on_server)
                self.call_from_thread(
                    self._finish_progress,
                    f"Successfully loaded all {len(results)} servers and channels.",
                )
                self.call_from_thread(self.action_refresh_servers, False)
        except Exception as e:
            self.call_from_thread(self._handle_network_error, f"Load all failed: {e}")

    # ==================== Custom Time Window Modal ====================

    def action_edit_channel_window(self) -> None:
        selected_list = self.query_one("#selected-list", OptionList)
        target_ch_id: str | None = None
        target_ch_name = ""

        if selected_list.highlighted is not None and selected_list.highlighted < len(selected_list._options):
            opt = selected_list.get_option_at_index(selected_list.highlighted)
            target_ch_id = opt.id
            if target_ch_id and target_ch_id in self.selection.selected:
                target_ch_name = self.selection.selected[target_ch_id][1].name
        elif self.current_server:
            tree = self.query_one("#channel-tree", Tree)
            if tree.cursor_node and isinstance(tree.cursor_node.data, Channel):
                ch = tree.cursor_node.data
                if self.selection.is_selectable(ch):
                    target_ch_id = ch.id
                    target_ch_name = ch.name

        if not target_ch_id:
            self.notify("Select a channel first to edit its time window.", severity="warning")
            return

        current_win = self.selection.custom_windows.get(target_ch_id)

        def on_dismiss(result: Any) -> None:
            if result is WINDOW_CANCELLED:
                return
            assert target_ch_id is not None
            self.selection.set_custom_window(target_ch_id, result)
            self._update_selected_ui()
            self._update_command_preview()

        modal = TimeWindowModal(
            channel_name=target_ch_name,
            current_spec=current_win,
            global_spec=self.selection.global_window,
        )
        self.push_screen(modal, on_dismiss)

    # ==================== Export Execution ====================

    def action_start_export(self) -> None:
        if self.is_running_job:
            self.notify("An export job is already running. Press Esc to stop.", severity="warning")
            return

        jobs = plan_jobs(self.selection, self.settings)
        if not jobs:
            self.notify("No channels selected for export.", severity="warning")
            return

        self.is_running_job = True
        self.cancel_token = CancelToken()
        self._switch_narrow_tab(3)

        run_status = self.query_one("#run-status", Label)
        run_status.update("Starting export...")
        event_log = self.query_one("#event-log", RichLog)
        event_log.clear()
        event_log.write("[bold green]=== Export started ===[/bold green]")

        progress_bar = self.query_one("#job-progress", ProgressBar)
        progress_bar.update(total=len(jobs), progress=0)

        self._run_export_worker(jobs, self.cancel_token)

    @work(thread=True)
    def _run_export_worker(self, jobs: list[PlannedJob], cancel_token: CancelToken) -> None:
        all_outcomes: list[MessagesOutcome] = []
        try:
            with self._make_directory() as directory:
                def emit_event(name: str, payload: dict[str, Any]) -> None:
                    self.call_from_thread(self._handle_bridge_event, name, payload)

                events_bridge = TuiEvents(cancel_token, emit_event)
                total_jobs = len(jobs)

                for idx, job in enumerate(jobs, start=1):
                    cancel_token.check()
                    self.call_from_thread(
                        self._update_job_status,
                        f"Job {idx}/{total_jobs}: {job.window.label()}",
                    )
                    outcome = run_messages(
                        job.request,
                        directory=directory,
                        cdn=self.cdn_factory,
                        events=events_bridge,
                    )
                    all_outcomes.append(outcome)
                    self.call_from_thread(self._advance_job_progress, idx)
        except Cancelled:
            self.call_from_thread(self._handle_job_cancelled)
            return
        except Exception as e:
            self.call_from_thread(self._handle_job_error, str(e))
            return
        finally:
            self.call_from_thread(self._cleanup_job_state)

        self.call_from_thread(self._handle_jobs_completed, all_outcomes)

    def _handle_bridge_event(self, name: str, payload: dict[str, Any]) -> None:
        event_log = self.query_one("#event-log", RichLog)
        status_lbl = self.query_one("#run-status", Label)

        if name == "channel_start":
            ch = payload.get("channel")
            ch_name = getattr(ch, "name", str(ch))
            status_lbl.update(f"Scraping #{ch_name}...")
            event_log.write(f"[cyan]▶ Fetching #{ch_name}[/cyan]")
        elif name == "page":
            count = payload.get("count", 0)
            event_log.write(f"  [dim]• Page fetched: {count} messages[/dim]")
        elif name == "pause":
            secs = payload.get("seconds", 0)
            reason = payload.get("reason", "safe mode")
            status_lbl.update(f"🛡️ Pausing {secs:.1f}s ({reason})...")
            event_log.write(f"[dim yellow]⏸ Safe pause {secs:.1f}s ({reason})[/dim yellow]")
        elif name == "channel_done":
            event_log.write("[green]✓ Channel completed[/green]")
        elif name == "skipped":
            reason = payload.get("reason", "")
            event_log.write(f"[yellow]⚠ Skipped: {reason}[/yellow]")
        elif name == "warning":
            msg = payload.get("message", "")
            event_log.write(f"[yellow]⚠ Warning: {msg}[/yellow]")
        elif name == "note":
            text = payload.get("text", "")
            event_log.write(f"[dim]ℹ {text}[/dim]")
        elif name == "dl_start":
            files = payload.get("files", 0)
            event_log.write(f"[cyan]Downloading {files} attachments...[/cyan]")
        elif name == "dl_file":
            num = payload.get("number", 0)
            total = payload.get("total", 0)
            job = payload.get("job")
            fn = getattr(job, "filename", str(job)) if job else ""
            status_lbl.update(f"Downloading file {num}/{total}: {fn}")
        elif name == "dl_finish":
            event_log.write("[green]✓ Attachments downloaded[/green]")

    def _update_job_status(self, text: str) -> None:
        self.query_one("#run-status", Label).update(text)

    def _advance_job_progress(self, progress: int) -> None:
        self.query_one("#job-progress", ProgressBar).update(progress=progress)

    def _cleanup_job_state(self) -> None:
        self.is_running_job = False
        self.cancel_token = None

    def _handle_job_cancelled(self) -> None:
        self.query_one("#run-status", Label).update("⏹ Operation cancelled.")
        self.query_one("#event-log", RichLog).write("[bold red]⏹ Stopped by user.[/bold red]")
        self.notify("Export stopped by user.", severity="warning")

    def _handle_job_error(self, message: str) -> None:
        self.query_one("#run-status", Label).update("❌ Error occurred.")
        self.query_one("#event-log", RichLog).write(f"[bold red]ERROR: {message}[/bold red]")
        self.notify(f"Export failed: {message}", severity="error")

    def _handle_jobs_completed(self, outcomes: list[MessagesOutcome]) -> None:
        self.query_one("#run-status", Label).update("✓ All jobs completed.")
        event_log = self.query_one("#event-log", RichLog)
        event_log.write("[bold green]✓ All export jobs finished successfully![/bold green]")
        self.notify("Export completed!", title="Discoop")

        if self.settings.target == "preview":
            results = [r for o in outcomes for r in o.results]
            query = outcomes[0].query if outcomes else None
            self.push_screen(PreviewScreen(results, query=query, initial_format=self.settings.preview_format))

    def action_stop_or_back(self) -> None:
        if self.is_running_job and self.cancel_token:
            self.cancel_token.cancel()
            self.notify("Stopping active job...", severity="information")
        elif self.current_narrow_tab != 1:
            self._switch_narrow_tab(1)

    # ==================== Button & UI Event Handling ====================

    def on_button_pressed(self, event: Button.Pressed) -> None:
        btn_id = event.button.id
        if not btn_id:
            return

        if btn_id == "btn-help":
            self.action_help()
        elif btn_id == "btn-settings":
            self._open_settings()
        elif btn_id == "btn-login":
            self._open_login()
        elif btn_id == "narrow-tab-1":
            self._switch_narrow_tab(1)
        elif btn_id == "narrow-tab-2":
            self._switch_narrow_tab(2)
        elif btn_id == "narrow-tab-3":
            self._switch_narrow_tab(3)
        elif btn_id == "btn-refresh-servers":
            self.action_refresh_servers(refresh=True)
        elif btn_id == "btn-load-all":
            self.action_load_all()
        elif btn_id == "btn-refresh-channels":
            self.action_refresh_channels(refresh=True)
        elif btn_id == "btn-select-shown":
            self._select_shown_channels()
        elif btn_id == "btn-clear-server":
            if self.current_server:
                self.selection.clear_server(self.current_server.id)
                self._rebuild_channel_tree()
                self._update_selected_ui()
                self._update_command_preview()
        elif btn_id == "btn-custom-time":
            self.action_edit_channel_window()
        elif btn_id == "btn-clear-all":
            self.selection.clear_all()
            self._rebuild_channel_tree()
            self._update_selected_ui()
            self._update_command_preview()
        elif btn_id == "preset-24h":
            self._set_preset_window("24h")
        elif btn_id == "preset-7d":
            self._set_preset_window("7d")
        elif btn_id == "preset-30d":
            self._set_preset_window("30d")
        elif btn_id == "preset-all":
            self._set_preset_window("all")
        elif btn_id == "mode-safe":
            self._set_mode("safe")
        elif btn_id == "mode-fast":
            self._set_mode("fast")
        elif btn_id == "target-folder":
            self._set_target("folder")
        elif btn_id == "target-zip":
            self._set_target("zip")
        elif btn_id == "target-preview":
            self._set_target("preview")
        elif btn_id == "fmt-text":
            self._set_preview_format("text")
        elif btn_id == "fmt-md":
            self._set_preview_format("md")
        elif btn_id == "fmt-json":
            self._set_preview_format("json")
        elif btn_id == "fmt-jsonl":
            self._set_preview_format("jsonl")
        elif btn_id == "btn-start":
            self.action_start_export()
        elif btn_id == "btn-stop":
            self.action_stop_or_back()
        elif btn_id == "btn-copy-command":
            self.action_copy_command()

    def _select_shown_channels(self) -> None:
        if self.current_server is None:
            return
        query = self.query_one("#channel-search", Input).value.strip()
        filtered = filter_channels(self.server_channels, query)
        selectable = [c for c in filtered if self.selection.is_selectable(c)]
        self.selection.select_many(self.current_server, selectable)
        self._rebuild_channel_tree()
        self._update_selected_ui()
        self._update_command_preview()

    def _set_preset_window(self, preset: str) -> None:
        self.query_one("#input-from", Input).value = preset
        self.query_one("#input-to", Input).value = ""
        self.query_one("#input-last", Input).value = ""
        for p in ("24h", "7d", "30d", "all"):
            btn = self.query_one(f"#preset-{p}", Button)
            if p == preset:
                btn.add_class("-active")
            else:
                btn.remove_class("-active")
        self._sync_global_window_from_inputs()

    def _set_mode(self, mode: str) -> None:
        self.settings.mode = mode
        self._sync_mode_indicator()
        btn_safe = self.query_one("#mode-safe", Button)
        btn_fast = self.query_one("#mode-fast", Button)
        if mode == "safe":
            btn_safe.add_class("-active")
            btn_fast.remove_class("-active")
        else:
            btn_fast.add_class("-active")
            btn_safe.remove_class("-active")
        self._update_command_preview()

    def _set_target(self, target: str) -> None:
        self.settings.target = target
        for t in ("folder", "zip", "preview"):
            btn = self.query_one(f"#target-{t}", Button)
            if t == target:
                btn.add_class("-active")
            else:
                btn.remove_class("-active")
        self._update_command_preview()

    def _set_preview_format(self, fmt: str) -> None:
        self.settings.preview_format = fmt
        for f in ("text", "md", "json", "jsonl"):
            btn = self.query_one(f"#fmt-{f}", Button)
            if f == fmt:
                btn.add_class("-active")
            else:
                btn.remove_class("-active")
        self._update_command_preview()

    def action_help(self) -> None:
        self.push_screen(HelpScreen())

    def _open_settings(self) -> None:
        def on_saved(saved: bool) -> None:
            if saved:
                self._update_login_status()
                self._sync_mode_indicator()
        self.push_screen(SettingsModal(), on_saved)

    def _open_login(self) -> None:
        def on_logged_in(changed: bool) -> None:
            if changed:
                self._update_login_status()
                self.action_refresh_servers(refresh=True)
        self.push_screen(LoginModal(self.api_factory), on_logged_in)

    def _start_progress(self, msg: str) -> None:
        self.query_one("#run-status", Label).update(msg)
        self.query_one("#event-log", RichLog).write(f"[bold cyan]{msg}[/bold cyan]")

    def _log_progress(self, msg: str) -> None:
        self.query_one("#event-log", RichLog).write(msg)

    def _finish_progress(self, msg: str) -> None:
        self.query_one("#run-status", Label).update("✓ Done.")
        self.query_one("#event-log", RichLog).write(f"[bold green]{msg}[/bold green]")
        self.notify(msg, title="Discoop")

    def _handle_network_error(self, message: str) -> None:
        self.query_one("#run-status", Label).update("⚠ Network error.")
        self.query_one("#event-log", RichLog).write(f"[bold red]{message}[/bold red]")
        self.notify(message, severity="error")


def run_app() -> None:
    """Run the interactive discoop TUI."""
    app = DiscoopApp()
    app.run()
