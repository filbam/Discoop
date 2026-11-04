"""Textual Pilot integration tests and CLI/service equivalence tests for discoop TUI."""

from __future__ import annotations

import asyncio
import contextlib
from dataclasses import replace
from datetime import UTC, datetime, timedelta
import io
import json
from pathlib import Path
import re
import threading
import time
from typing import Any

import httpx
import pytest
from rich.style import Style
from textual.command import CommandPalette
from textual.geometry import Region
from textual.widgets import Button, Input, Label, OptionList, RichLog, Static

from discoop import cli, service
from discoop.api import DiscordAPI
from discoop.cache import Cache
from discoop.config import Config
from discoop.directory import Directory
from discoop.models import Channel, Server
from discoop.render import Query
from discoop.snowflake import Window
from discoop.tokenstore import TokenStore
from discoop.tui import app as tui_app
from discoop.tui.app import DiscoopApp
from discoop.tui.modals import HelpScreen, LoginModal, PreviewScreen, SettingsModal, TimeWindowModal
from discoop.tui.state import ExportSettings, SelectionState, WindowSpec, export_stamp, plan_jobs
from discoop.tui.widgets import ActionRow, ChannelTree, ChoiceRow, FormPanel, InputRow, display_name
from fake_messages import CET, FIT, NOW, FakeChannel, FakeDiscord, Network, series

SERVER_A = Server("1000", "Alpha Server", 10)
SERVER_B = Server("2000", "Beta Server", 20)
SERVER_C = Server("3000", "Gamma Server", 30)
WELCOME = Channel("2001", "2000", "welcome", 0, None, 0)
INFO = Channel("2100", "2000", "info", 4, None, 1)
README = Channel("2101", "2000", "readme", 0, "2100", 0)
NEWS = Channel("2102", "2000", "news", 5, "2100", 1)
LOBBY = Channel("2103", "2000", "lobby-forum", 15, "2100", 2)
FORUMS = Channel("2200", "2000", "forums", 4, None, 2)
HELP_FORUM = Channel("2201", "2000", "help", 15, "2200", 0)
CHANNELS_B = [WELCOME, INFO, README, NEWS, LOBBY, FORUMS, HELP_FORUM]


def _make_dummy_api_factory(transport: httpx.MockTransport | None = None):
    def factory(token: str | None = None, **kw: Any) -> DiscordAPI:
        kw["delay"] = 0.0  # no real pauses in tests
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


class RecordingDiscord:
    """A fake Discord that keeps every request. `hold` makes channel lists wait, to catch an operation mid-way."""

    def __init__(self, *, me_status: int = 200, delay: float = 0.0) -> None:
        self.requests: list[str] = []
        self.me_status = me_status
        self.delay = delay
        self.channels: dict[str, list[dict[str, Any]]] = {}
        self.channel_status: dict[str, int] = {}
        self.hold = threading.Event()
        self.hold.set()
        self.holding = threading.Event()

    def handle(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path.removeprefix("/api/v9")
        self.requests.append(path)
        if path == "/users/@me":
            if self.me_status != 200:
                return httpx.Response(self.me_status, json={"message": "error", "code": 0})
            return httpx.Response(200, json={"id": "42", "username": "student_a"})
        if path == "/users/@me/guilds":
            servers = (SERVER_A, SERVER_B, SERVER_C)
            return httpx.Response(200, json=[{"id": s.id, "name": s.name} for s in servers])
        match = re.fullmatch(r"/guilds/(\d+)/channels", path)
        if match:
            self.holding.set()
            self.hold.wait(10)
            server_id = match.group(1)
            if server_id in self.channel_status:
                return httpx.Response(self.channel_status[server_id], json={"message": "no", "code": 50001})
            return httpx.Response(200, json=self.channels.get(server_id, []))
        return httpx.Response(404, json={"message": "Not Found", "code": 10003})

    def factory(self, token: str | None = None, **kw: Any) -> DiscordAPI:
        kw["delay"] = self.delay
        kw.setdefault("max_retries", 0)
        return DiscordAPI("fake-token", transport=httpx.MockTransport(self.handle), **kw)

    def calls_to(self, suffix: str) -> int:
        return sum(path.endswith(suffix) for path in self.requests)


def seed_cache() -> None:
    """Three servers; only the second one has its channels cached."""
    with Cache.default() as cache:
        cache.replace_servers([SERVER_A, SERVER_B, SERVER_C])
        cache.replace_channels("2000", CHANNELS_B)


async def wait_until(pilot: Any, condition: Any, timeout: float = 10.0) -> None:
    """Wait in real time: on Windows a sleep shorter than the clock tick (15 ms) does not wait at all."""
    deadline = time.monotonic() + timeout
    while not condition():
        assert time.monotonic() < deadline, "timed out"
        await pilot.pause(0.02)
    await pilot.pause()


async def started(app: DiscoopApp, pilot: Any) -> None:
    """The startup worker has finished. Every test waits for it, so it never outlives the isolated environment."""
    await wait_until(pilot, lambda: app.cancel_token is None)


def label_of(node: Any) -> str:
    return node.label.plain


def row_of(tree: ChannelTree, node: Any) -> str:
    """What the tree shows for a node, arrow and right edge included."""
    return tree.render_label(node, Style(), Style()).plain


def visible_rows(tree: ChannelTree) -> list[str]:
    return [label_of(tree.get_node_at_line(line)) for line in range(tree.last_line + 1)]


def screen_text(app: DiscoopApp, region: Region) -> str:
    """The characters really painted on the screen in `region`."""
    strips = app.screen._compositor.render_strips()
    return "\n".join(strip.crop(region.x, region.right).text for strip in strips[region.y : region.bottom])


def log_text(app: DiscoopApp) -> str:
    return "\n".join(strip.text for strip in app.query_one("#event-log", RichLog).lines)


def notifications(app: DiscoopApp) -> list[str]:
    return [notification.message for notification in app._notifications]


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
        await started(wide_app, pilot)
        assert wide_app.screen.has_class("-wide")
        assert not wide_app.screen.has_class("-narrow")

    # 2. Narrow breakpoint and tab switching
    narrow_app = DiscoopApp(api_factory=dummy_api)
    async with narrow_app.run_test(size=(75, 28)) as pilot:
        await started(narrow_app, pilot)
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
        assert narrow_app.query_one("#export-pane").display
        assert not narrow_app.query_one("#tree-pane").display
        # Selection state is preserved
        assert narrow_app.selection.is_selected("101")

        # Press "3" -> switch to narrow tab 3 (the log)
        await pilot.press("3")
        await pilot.pause()
        assert narrow_app.current_narrow_tab == 3
        assert narrow_app.screen.has_class("show-tab-3")
        assert not narrow_app.screen.has_class("show-tab-2")
        assert narrow_app.focused is narrow_app.query_one("#event-log")
        # Selection state is preserved
        assert narrow_app.selection.is_selected("101")

        # Press "1" -> switch back to narrow tab 1 (the tree)
        await pilot.press("1")
        await pilot.pause()
        assert narrow_app.current_narrow_tab == 1
        assert narrow_app.screen.has_class("show-tab-1")
        assert not narrow_app.screen.has_class("show-tab-3")
        assert narrow_app.focused is narrow_app.query_one("#channel-tree")
        # Selection state is preserved
        assert narrow_app.selection.is_selected("101")
        assert "101" in narrow_app.selection.selected


async def test_server_and_channel_selection_updates_command_bar() -> None:
    """2. Cached servers & channel selection:

    - Pre-populate Cache.default() with 2 servers (Server("100", "VUT FIT", 390), Server("200", "AI Club", 25))
      and channels for "100" (category type=4, text channel type=0, forum channel type=15).
    - Launch DiscoopApp under run_test(size=(140, 40)).
    - Verify servers appear in the tree.
    - Select channel "101" (isc-public) with the keyboard;
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
        await started(app, pilot)

        tree = app.query_one("#channel-tree", ChannelTree)
        assert visible_rows(tree) == ["AI Club", "VUT FIT"]

        # Verify category (type=4) and forum (type=15) cannot be selected
        assert app.selection.toggle(server_fit, category_ch) is False
        assert not app.selection.is_selected(category_ch.id)
        assert app.selection.toggle(server_fit, forum_ch) is False
        assert not app.selection.is_selected(forum_ch.id)

        # Open the server and the category, then select text channel "101"
        await pilot.press("down", "right")
        await pilot.pause()
        await pilot.press("down", "right")
        await pilot.pause()
        await pilot.press("down", "space")
        await pilot.pause()
        assert app.selection.is_selected(text_ch.id)

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
        await started(app, pilot)

        # Select both channels
        app.selection.toggle(server, ch1)
        app.selection.toggle(server, ch2)

        # Set custom window on "102"
        custom_spec = WindowSpec(from_="2026-10-01", to="2026-10-31")
        app.selection.set_custom_window("102", custom_spec)

        app._selection_changed(["101", "102"])

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

        # The list marks the channel with its own window
        selected = app.query_one("#selected-list", OptionList)
        assert str(selected.get_option("102").prompt).endswith("*")
        assert not str(selected.get_option("101").prompt).endswith("*")


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


# ==================== Main screen ====================


def test_display_name_strips_invisible_characters() -> None:
    assert display_name("\U0001f4da️-info") == "\U0001f4da-info"
    assert display_name("a︎b‍c") == "abc"
    assert display_name("plain [name]") == "plain [name]"


async def test_theme_and_styles_come_from_the_terminal() -> None:
    css = Path(tui_app.__file__).with_name("discoop.tcss").read_text(encoding="utf-8")
    assert re.findall(r"^\s*[\w-]+:.*#[0-9a-fA-F]{3,8}\b", css, re.MULTILINE) == []
    assert "rgb" not in css

    app = DiscoopApp(api_factory=_make_dummy_api_factory())
    async with app.run_test(size=(140, 40)) as pilot:
        await started(app, pilot)
        assert app.theme == "ansi-dark"
        assert app.current_theme.ansi


async def test_everything_on_screen_shows_text() -> None:
    """Regression: controls one line high with a default border drew nothing at all."""
    seed_cache()
    app = DiscoopApp(api_factory=_make_dummy_api_factory())
    async with app.run_test(size=(140, 40)) as pilot:
        await started(app, pilot)

        assert not app.query(Button), "the main screen needs no Button, and a default one breaks at height 1"
        one_liners = [*app.query(ChoiceRow), *app.query(InputRow), *app.query(ActionRow)]
        assert len(one_liners) > 10
        for widget in [*one_liners, *app.query(Label)]:
            if widget.display and all(parent.display for parent in widget.ancestors):
                assert widget.region.height == 1, widget
                assert screen_text(app, widget.region).strip(), widget

        for row in one_liners:
            assert row.styles.height.value == 1
        assert "[ Start (F5) ]" in screen_text(app, app.query_one("#row-start").region)
        assert "Mode" in screen_text(app, app.query_one("#row-mode").region)
        assert "< safe >" in screen_text(app, app.query_one("#row-mode").region)
        assert "F1 help" in screen_text(app, app.query_one("#top-bar").region)

        # No emoji left in the app's own text: top bar, form, log and command line
        painted = screen_text(app, app.screen.region)
        assert not re.search("[\U0001f300-\U0001faff☀-➿]", painted)


async def test_tree_starts_collapsed_with_server_badges() -> None:
    seed_cache()
    TokenStore.default().save("fake-token")
    discord = RecordingDiscord()
    discord.channel_status["3000"] = 403
    app = DiscoopApp(api_factory=discord.factory)
    async with app.run_test(size=(140, 40)) as pilot:
        await started(app, pilot)
        tree = app.query_one("#channel-tree", ChannelTree)

        assert visible_rows(tree) == ["Alpha Server", "Beta Server", "Gamma Server"]
        assert not any(node.is_expanded for node in tree.root.children)
        assert app.focused is tree

        rows = [row_of(tree, node) for node in tree.root.children]
        assert rows[0].startswith("▸ Alpha Server") and rows[0].endswith("not loaded")
        assert rows[1].startswith("▸ Beta Server") and rows[1].endswith(" 5")  # categories do not count

        tree.move_cursor(tree.root.children[2])
        await pilot.press("right")
        await wait_until(pilot, lambda: "3000" in app.no_access_servers)
        assert row_of(tree, tree.root.children[2]).endswith("no access")


async def test_tree_arrows_open_close_and_walk() -> None:
    seed_cache()
    discord = RecordingDiscord()
    app = DiscoopApp(api_factory=discord.factory)
    async with app.run_test(size=(140, 40)) as pilot:
        await started(app, pilot)
        tree = app.query_one("#channel-tree", ChannelTree)
        assert tree.cursor_line == 0

        await pilot.press("down")
        beta = tree.cursor_node
        assert beta is not None and beta.data == SERVER_B

        await pilot.press("right")  # opens, stays
        await pilot.pause()
        assert beta.is_expanded and tree.cursor_node is beta
        assert visible_rows(tree)[2:5] == ["[ ] #welcome", "[ ] info", "forums"]

        await pilot.press("right")  # already open: first child
        await pilot.pause()
        assert tree.cursor_node is not None and tree.cursor_node.data == WELCOME

        await pilot.press("left")  # a leaf: its parent
        await pilot.pause()
        assert tree.cursor_node is beta and beta.is_expanded

        await pilot.press("down", "down")
        await pilot.press("right")
        await pilot.pause()
        category = tree.cursor_node
        assert category is not None and category.data == INFO and category.is_expanded

        await pilot.press("left")  # open: closes, stays
        await pilot.pause()
        assert tree.cursor_node is category and not category.is_expanded

        await pilot.press("left")  # closed: its parent
        await pilot.pause()
        assert tree.cursor_node is beta

        await pilot.press("enter")  # Enter closes a server...
        await pilot.pause()
        assert not beta.is_expanded
        await pilot.press("enter")  # ...and opens it, the category keeps its state
        await pilot.pause()
        assert beta.is_expanded and not category.is_expanded
        assert not app.selection.selected


async def test_space_selects_without_moving_or_rebuilding() -> None:
    seed_cache()
    app = DiscoopApp(api_factory=RecordingDiscord().factory)
    async with app.run_test(size=(140, 40)) as pilot:
        await started(app, pilot)
        tree = app.query_one("#channel-tree", ChannelTree)
        await pilot.press("down", "right")
        await pilot.pause()
        await pilot.press("down", "down", "right")  # info
        await pilot.pause()
        await pilot.press("down")  # readme
        await pilot.pause()

        node = tree.cursor_node
        assert node is not None and node.data == README
        line = tree.cursor_line
        expanded = [n.data for n in app._tree_nodes.values() if n.is_expanded]

        await pilot.press("space")
        await pilot.pause()
        assert app.selection.is_selected(README.id)
        assert tree.cursor_node is node, "a rebuild would have replaced the node"
        assert tree.cursor_line == line
        assert [n.data for n in app._tree_nodes.values() if n.is_expanded] == expanded
        assert label_of(node).startswith("[x]")

        await pilot.press("space")
        await pilot.pause()
        assert not app.selection.is_selected(README.id)
        assert label_of(node).startswith("[ ]")

        await pilot.press("enter")  # Enter toggles a channel too
        await pilot.pause()
        assert app.selection.is_selected(README.id)
        assert tree.cursor_line == line


async def test_space_is_not_global() -> None:
    """Regression: Space at App level changed the channel under the tree cursor from anywhere."""
    seed_cache()
    app = DiscoopApp(api_factory=RecordingDiscord().factory)
    async with app.run_test(size=(140, 40)) as pilot:
        await started(app, pilot)
        tree = app.query_one("#channel-tree", ChannelTree)
        await pilot.press("down", "right")
        await pilot.pause()
        await pilot.press("down")
        await pilot.pause()
        assert tree.cursor_node is not None and tree.cursor_node.data == WELCOME

        await pilot.press("tab")  # the form
        await pilot.pause()
        await pilot.press("down", "space")  # Input: types a space
        await pilot.pause()
        assert not app.selection.selected


async def test_space_on_a_server_only_hints() -> None:
    seed_cache()
    app = DiscoopApp(api_factory=RecordingDiscord().factory)
    async with app.run_test(size=(140, 40)) as pilot:
        await started(app, pilot)
        await pilot.press("down", "space")
        await pilot.pause()
        assert not app.selection.selected
        assert any("Space selects" in message for message in notifications(app))


async def test_category_box_shows_partial_selection_and_none_without_channels() -> None:
    seed_cache()
    app = DiscoopApp(api_factory=RecordingDiscord().factory)
    async with app.run_test(size=(140, 40)) as pilot:
        await started(app, pilot)
        tree = app.query_one("#channel-tree", ChannelTree)
        info = app._tree_nodes[f"channel:{INFO.id}"]
        forums = app._tree_nodes[f"channel:{FORUMS.id}"]

        assert label_of(info) == "[ ] info"
        assert label_of(forums) == "forums", "no box: nothing in it can be selected"

        app.selection.toggle(SERVER_B, README)
        app._selection_changed([README.id])
        await pilot.pause()
        assert label_of(info) == "[~] info"

        await pilot.press("down", "right")
        await pilot.pause()
        tree.move_cursor(info)
        await pilot.press("space")  # part of it selected: selects all
        await pilot.pause()
        assert app.selection.is_selected(README.id) and app.selection.is_selected(NEWS.id)
        assert not app.selection.is_selected(LOBBY.id)
        assert label_of(info) == "[x] info"

        await pilot.press("space")  # all selected: clears
        await pilot.pause()
        assert not app.selection.selected
        assert label_of(info) == "[ ] info"

        tree.move_cursor(forums)
        await pilot.press("space")
        await pilot.pause()
        assert not app.selection.selected

        forum_row = app._tree_nodes[f"channel:{LOBBY.id}"]
        assert label_of(forum_row).strip() == "#lobby-forum (forum)"


async def test_moving_the_cursor_never_calls_discord() -> None:
    with Cache.default() as cache:
        cache.replace_servers([SERVER_A, SERVER_B, SERVER_C])
    TokenStore.default().save("fake-token")
    discord = RecordingDiscord()
    discord.channels["1000"] = [{"id": "1001", "type": 0, "name": "general", "position": 0}]
    app = DiscoopApp(api_factory=discord.factory)
    async with app.run_test(size=(140, 40)) as pilot:
        await started(app, pilot)
        tree = app.query_one("#channel-tree", ChannelTree)
        at_start = list(discord.requests)
        assert at_start == ["/users/@me"]  # the server list came from the cache

        await pilot.press("down", "down", "up", "up", "down")
        await pilot.pause()
        await pilot.press("left", "up", "down")
        await pilot.pause(0.05)
        assert discord.requests == at_start

        # → on a server that is not loaded is the one thing that asks for its channels
        tree.move_cursor(tree.root.children[0])
        await pilot.press("right")
        await wait_until(pilot, lambda: "1000" in app.channels_by_server)
        assert discord.requests == [*at_start, "/guilds/1000/channels"]
        assert tree.root.children[0].is_expanded
        assert visible_rows(tree)[1] == "[ ] #general"


async def test_only_one_network_operation_at_a_time() -> None:
    with Cache.default() as cache:
        cache.replace_servers([SERVER_A, SERVER_B])
    TokenStore.default().save("fake-token")
    discord = RecordingDiscord()
    app = DiscoopApp(api_factory=discord.factory)
    async with app.run_test(size=(140, 40)) as pilot:
        await started(app, pilot)
        tree = app.query_one("#channel-tree", ChannelTree)
        discord.hold.clear()

        await pilot.press("right")
        await wait_until(pilot, discord.holding.is_set)
        assert app.cancel_token is not None
        assert row_of(tree, tree.root.children[0]).endswith("loading...")

        await pilot.press("down", "right")  # another server
        await pilot.pause()
        await pilot.press("R")
        await pilot.pause()
        assert "Busy — wait or press Esc" in notifications(app)
        assert discord.calls_to("/channels") == 1
        assert discord.calls_to("/guilds") == 0
        assert not tree.root.children[1].is_expanded, "a refused load must not leave the node open"

        discord.hold.set()
        await wait_until(pilot, lambda: app.cancel_token is None)
        assert SERVER_A.id in app.channels_by_server


async def test_failed_load_closes_the_server_again() -> None:
    with Cache.default() as cache:
        cache.replace_servers([SERVER_A])
    TokenStore.default().save("fake-token")
    discord = RecordingDiscord()
    discord.channel_status["1000"] = 500
    app = DiscoopApp(api_factory=discord.factory)
    async with app.run_test(size=(140, 40)) as pilot:
        await started(app, pilot)
        tree = app.query_one("#channel-tree", ChannelTree)
        await pilot.press("right")
        await wait_until(pilot, lambda: discord.calls_to("/channels") == 1 and app.cancel_token is None)
        node = tree.root.children[0]
        assert not node.is_expanded
        assert row_of(tree, node).endswith("not loaded")
        assert "Channels:" in log_text(app)


async def test_reload_keeps_cursor_and_open_nodes() -> None:
    seed_cache()
    TokenStore.default().save("fake-token")
    discord = RecordingDiscord()
    discord.channels["2000"] = [
        {"id": c.id, "type": c.type, "name": c.name, "parent_id": c.parent_id, "position": c.position}
        for c in CHANNELS_B
    ]
    discord.channels["2000"].append({"id": "2104", "type": 0, "name": "extra", "parent_id": "2100", "position": 3})
    app = DiscoopApp(api_factory=discord.factory)
    async with app.run_test(size=(140, 40)) as pilot:
        await started(app, pilot)
        tree = app.query_one("#channel-tree", ChannelTree)
        await pilot.press("down", "right")
        await pilot.pause()
        await pilot.press("down", "down", "right")
        await pilot.pause()
        await pilot.press("down")
        await pilot.pause()
        assert tree.cursor_node is not None and tree.cursor_node.data == README

        await pilot.press("r")
        await wait_until(pilot, lambda: discord.calls_to("/guilds/2000/channels") == 1 and app.cancel_token is None)
        assert tree.cursor_node is not None and tree.cursor_node.data == README
        assert app._tree_nodes[f"channel:{INFO.id}"].is_expanded
        assert "[ ] #extra" in visible_rows(tree)

        before = discord.calls_to("/users/@me/guilds")
        await pilot.press("R")
        await wait_until(
            pilot, lambda: discord.calls_to("/users/@me/guilds") == before + 1 and app.cancel_token is None
        )
        assert tree.cursor_node is not None and tree.cursor_node.data == README


async def test_filter_hides_opens_and_restores() -> None:
    seed_cache()
    with Cache.default() as cache:
        cache.replace_channels("3000", [Channel("3001", "3000", "news-c", 0, None, 0)])
    app = DiscoopApp(api_factory=RecordingDiscord().factory)
    async with app.run_test(size=(140, 40)) as pilot:
        await started(app, pilot)
        tree = app.query_one("#channel-tree", ChannelTree)
        filter_input = app.query_one("#tree-filter", Input)

        await pilot.press("down", "right")  # Beta open, its categories closed
        await pilot.pause()
        await pilot.press("down")  # welcome
        await pilot.pause()

        await pilot.press("slash")
        await pilot.pause()
        assert app.focused is filter_input
        await pilot.press(*"news")
        await wait_until(pilot, lambda: len(visible_rows(tree)) == 5)
        assert visible_rows(tree) == ["Beta Server", "[ ] info", "[ ] #news", "Gamma Server", "[ ] #news-c"]
        assert app.focused is filter_input

        # ↓ goes back to the tree, the filter stays
        await pilot.press("down")
        await pilot.pause()
        assert app.focused is tree
        assert filter_input.value == "news"

        # Selecting while filtered does not disturb anything
        tree.move_cursor(app._tree_nodes[f"channel:{NEWS.id}"])
        await pilot.press("space")
        await pilot.pause()
        assert app.selection.is_selected(NEWS.id)
        assert len(visible_rows(tree)) == 5

        # Esc clears it once the tree has the focus; what was open comes back, Beta's category stays closed
        await pilot.press("escape")
        await wait_until(pilot, lambda: len(visible_rows(tree)) > 5 or filter_input.value == "")
        await wait_until(pilot, lambda: "[ ] #welcome" in visible_rows(tree))
        assert filter_input.value == ""
        assert not app._tree_nodes[f"channel:{INFO.id}"].is_expanded
        assert not app._tree_nodes[f"server:{SERVER_C.id}"].is_expanded
        assert app._tree_nodes[f"server:{SERVER_B.id}"].is_expanded
        assert tree.cursor_node is app._tree_nodes[f"channel:{INFO.id}"], "the channel folded away, so its parent"
        assert app.selection.is_selected(NEWS.id)


async def test_escape_leaves_the_filter() -> None:
    seed_cache()
    app = DiscoopApp(api_factory=RecordingDiscord().factory)
    async with app.run_test(size=(140, 40)) as pilot:
        await started(app, pilot)
        await pilot.press("slash")
        await pilot.pause()
        await pilot.press("x", "escape")
        await pilot.pause()
        assert app.focused is app.query_one("#channel-tree")
        assert app.query_one("#tree-filter", Input).value == "x"


async def test_select_shown_takes_only_what_the_filter_shows() -> None:
    seed_cache()
    app = DiscoopApp(api_factory=RecordingDiscord().factory)
    async with app.run_test(size=(140, 40)) as pilot:
        await started(app, pilot)
        tree = app.query_one("#channel-tree", ChannelTree)
        await pilot.press("slash", "r", "e", "a")
        await wait_until(pilot, lambda: len(visible_rows(tree)) == 3)
        await pilot.press("enter")  # back to the tree
        await pilot.pause()
        assert app.focused is tree

        await pilot.press("a")
        await pilot.pause()
        assert list(app.selection.selected) == [README.id]

        await pilot.press("escape")
        await wait_until(pilot, lambda: app.query_one("#tree-filter", Input).value == "")
        await pilot.press("a")
        await pilot.pause()
        assert set(app.selection.selected) == {WELCOME.id, README.id, NEWS.id}, "no forums, no categories"


async def test_select_shown_needs_a_loaded_server() -> None:
    seed_cache()
    app = DiscoopApp(api_factory=RecordingDiscord().factory)
    async with app.run_test(size=(140, 40)) as pilot:
        await started(app, pilot)
        await pilot.press("a")  # the cursor is on Alpha, not loaded
        await pilot.pause()
        assert not app.selection.selected
        assert any("Load the server first" in message for message in notifications(app))


async def test_selected_list_keys() -> None:
    seed_cache()
    app = DiscoopApp(api_factory=RecordingDiscord().factory)
    async with app.run_test(size=(140, 40)) as pilot:
        await started(app, pilot)
        tree = app.query_one("#channel-tree", ChannelTree)
        selected = app.query_one("#selected-list", OptionList)
        await pilot.press("down", "a")  # Beta: all of it
        await pilot.pause()
        assert selected.option_count == 3
        assert str(selected.get_option(WELCOME.id).prompt) == "Beta Server/#welcome  7d"
        assert app.query_one("#selected-title", Label).content == "Selected (3)"

        await pilot.press("tab")
        await pilot.pause()
        assert app.focused is selected

        await pilot.press("down", "x")  # the second one
        await pilot.pause()
        assert set(app.selection.selected) == {WELCOME.id, NEWS.id}
        assert label_of(app._tree_nodes[f"channel:{README.id}"]).startswith("[ ]")
        assert label_of(app._tree_nodes[f"channel:{INFO.id}"]).startswith("[~]")

        await pilot.press("delete")
        await pilot.pause()
        assert set(app.selection.selected) == {WELCOME.id}

        await pilot.press("x")  # the last one: nothing left here, back to the tree
        await pilot.pause()
        assert not app.selection.selected
        assert app.focused is tree
        assert not selected.display


async def test_shift_x_clears_the_whole_selection() -> None:
    seed_cache()
    app = DiscoopApp(api_factory=RecordingDiscord().factory)
    async with app.run_test(size=(140, 40)) as pilot:
        await started(app, pilot)
        tree = app.query_one("#channel-tree", ChannelTree)
        selected = app.query_one("#selected-list", OptionList)
        await pilot.press("down", "a")  # Beta: all of it
        await pilot.pause()
        app.selection.set_custom_window(README.id, WindowSpec(from_="30d"))
        await pilot.press("tab")
        await pilot.pause()
        assert app.focused is selected

        await pilot.press("X")
        await pilot.pause()
        assert not app.selection.selected and not app.selection.custom_windows
        assert app.focused is tree
        assert not selected.display
        assert app.query_one("#selected-title", Label).content == "Selected (0)"
        assert label_of(app._tree_nodes[f"channel:{WELCOME.id}"]).startswith("[ ]")
        assert label_of(app._tree_nodes[f"channel:{INFO.id}"]).startswith("[ ]")
        assert "--from" not in str(app.query_one("#command-preview", Static).content)


async def test_e_edits_the_channel_of_the_focused_panel() -> None:
    seed_cache()
    app = DiscoopApp(api_factory=RecordingDiscord().factory)
    async with app.run_test(size=(140, 40)) as pilot:
        await started(app, pilot)
        tree = app.query_one("#channel-tree", ChannelTree)
        await pilot.press("down", "right")
        await pilot.pause()

        await pilot.press("e")  # a server has no window
        await pilot.pause()
        assert not isinstance(app.screen, TimeWindowModal)
        assert "Move to a channel first." in notifications(app)

        # Tree: the channel under the tree cursor, although the list has another one highlighted
        app.selection.toggle(SERVER_B, README)
        app._selection_changed([README.id])
        await pilot.press("down")  # welcome
        await pilot.pause()
        await pilot.press("e")
        await pilot.pause()
        assert isinstance(app.screen, TimeWindowModal)
        assert app.screen.channel_name == WELCOME.name

        # Saving a window on a channel that is not selected selects it
        app.screen.query_one("#modal-input-from", Input).value = "30d"
        await pilot.press("enter")
        await pilot.pause()
        assert app.selection.is_selected(WELCOME.id)
        assert app.selection.window_for(WELCOME.id).from_ == "30d"
        assert app.selection.window_for(README.id).from_ == "7d"
        assert app.focused is tree

        # List: its highlighted channel, whatever the tree cursor is on
        await pilot.press("tab")
        await pilot.pause()
        await pilot.press("e")
        await pilot.pause()
        assert isinstance(app.screen, TimeWindowModal)
        assert app.screen.channel_name == README.name
        await pilot.press("escape")
        await pilot.pause()
        assert app.selection.window_for(README.id).from_ == "7d"


async def test_tab_walks_panels_not_fields() -> None:
    seed_cache()
    app = DiscoopApp(api_factory=RecordingDiscord().factory)
    async with app.run_test(size=(140, 40)) as pilot:
        await started(app, pilot)
        tree = app.query_one("#channel-tree", ChannelTree)
        selected = app.query_one("#selected-list", OptionList)
        form = app.query_one("#export-form", FormPanel)

        # Nothing selected: the empty list is skipped
        await pilot.press("tab")
        await pilot.pause()
        assert app.focused is form.rows()[0]
        await pilot.press("tab")
        await pilot.pause()
        assert app.focused is tree

        await pilot.press("down", "a")
        await pilot.pause()
        await pilot.press("tab")
        await pilot.pause()
        assert app.focused is selected
        await pilot.press("tab")
        await pilot.pause()
        assert app.focused is form.rows()[0]

        await pilot.press("down", "down")
        await pilot.pause()
        third = form.rows()[2]
        assert app.focused is third
        await pilot.press("tab")
        await pilot.pause()
        assert app.focused is tree

        await pilot.press("shift+tab")  # back to the row left last
        await pilot.pause()
        assert app.focused is third
        await pilot.press("shift+tab")
        await pilot.pause()
        assert app.focused is selected

        await pilot.press("3")
        await pilot.pause()
        assert app.focused is app.query_one("#event-log")
        await pilot.press("2")
        await pilot.pause()
        assert app.focused is selected
        await pilot.press("1")
        await pilot.pause()
        assert app.focused is tree


async def test_tab_stays_inside_a_dialog() -> None:
    app = DiscoopApp(api_factory=_make_dummy_api_factory())
    async with app.run_test(size=(140, 40)) as pilot:
        await started(app, pilot)
        await pilot.press("f2")
        await pilot.pause()
        assert isinstance(app.screen, SettingsModal)
        first = app.screen.focused
        await pilot.press("tab")
        await pilot.pause()
        assert isinstance(app.screen, SettingsModal)
        assert app.screen.focused is not first
        assert app.screen.focused in app.screen.query("*")


async def test_form_arrows_move_between_rows_and_change_values() -> None:
    seed_cache()
    app = DiscoopApp(api_factory=RecordingDiscord().factory)
    async with app.run_test(size=(140, 40)) as pilot:
        await started(app, pilot)
        await pilot.press("down", "a", "tab", "tab")  # Beta selected, then the form
        await pilot.pause()
        form = app.query_one("#export-form", FormPanel)
        preview = app.query_one("#command-preview", Static)
        assert app.focused is app.query_one("#row-window")
        assert "--from 7d" in str(preview.content)

        # ↓ goes through Input rows too, and they keep their text
        await pilot.press("down")
        await pilot.pause()
        assert app.focused is app.query_one("#input-from", Input)
        await pilot.press("down", "down", "down")
        await pilot.pause()
        assert app.focused is app.query_one("#input-max-messages", Input)
        await pilot.press("down")
        await pilot.pause()
        mode = app.query_one("#row-mode", ChoiceRow)
        assert app.focused is mode

        delay_row = app.query_one("#row-delay")
        assert not delay_row.display
        assert "--safe" in str(preview.content)
        await pilot.press("right")
        await pilot.pause()
        assert app.settings.mode == "fast"
        assert mode.value == "fast"
        assert "--fast" in str(preview.content)
        assert "--safe" not in str(preview.content)
        assert str(app.query_one("#mode-indicator", Label).content) == "fast"
        assert delay_row.display

        await pilot.press("left")
        await pilot.pause()
        assert app.settings.mode == "safe"
        assert "--safe" in str(preview.content)
        assert not delay_row.display

        await pilot.press("up")  # hidden rows and all, ↑ works the same way
        await pilot.pause()
        assert app.focused is app.query_one("#input-max-messages", Input)

        # Window preset fills From and clears the rest
        form.rows()[0].focus()
        await pilot.pause()
        await pilot.press("right")
        await pilot.pause()
        assert app.query_one("#row-window", ChoiceRow).value == "30d"
        assert app.query_one("#input-from", Input).value == "30d"
        assert "--from 30d" in str(preview.content)


async def test_form_rows_follow_their_settings() -> None:
    seed_cache()
    app = DiscoopApp(api_factory=RecordingDiscord().factory)
    async with app.run_test(size=(140, 40)) as pilot:
        await started(app, pilot)
        preview = app.query_one("#command-preview", Static)
        app.selection.toggle(SERVER_B, WELCOME)
        app._selection_changed([WELCOME.id])

        await pilot.press("tab", "tab")
        await pilot.pause()
        form = app.query_one("#export-form", FormPanel)

        app.query_one("#row-files", ChoiceRow).focus()
        await pilot.pause()
        await pilot.press("right")
        await pilot.pause()
        assert app.settings.files is False
        assert not app.query_one("#row-max-mb").display
        assert "--no-files" in str(preview.content)

        app.query_one("#row-system", ChoiceRow).focus()
        await pilot.pause()
        await pilot.press("space")  # Space steps a choice like →
        await pilot.pause()
        assert app.settings.include_system is True
        assert "--include-system" in str(preview.content)

        target = app.query_one("#row-target", ChoiceRow)
        target.focus()
        await pilot.pause()
        await pilot.press("left")
        await pilot.pause()
        assert app.settings.target == "preview"
        assert not app.query_one("#row-path").display
        assert not app.query_one("#row-files").display, "a preview downloads no files"
        assert app.query_one("#row-format").display
        assert app.query_one("#row-format") in form.rows()

        await pilot.press("down")
        await pilot.pause()
        assert app.focused is app.query_one("#row-format")
        await pilot.press("right")
        await pilot.pause()
        assert app.settings.preview_format == "md"

        target.focus()
        await pilot.pause()
        await pilot.press("right")  # wraps around
        await pilot.pause()
        assert app.settings.target == "folder"
        assert app.query_one("#row-path").display
        assert app.query_one("#row-files").display
        assert not app.query_one("#row-max-mb").display, "Attachments is still no"
        assert not app.query_one("#row-format").display

        app.query_one("#row-files", ChoiceRow).action_step(1)  # yes
        await pilot.pause()
        assert app.query_one("#row-max-mb").display
        app.query_one("#row-target", ChoiceRow).action_step(-1)  # preview
        await pilot.pause()
        assert not app.query_one("#row-max-mb").display


async def test_typing_a_window_updates_preset_and_rejects_nothing_silently() -> None:
    seed_cache()
    app = DiscoopApp(api_factory=RecordingDiscord().factory)
    async with app.run_test(size=(140, 40)) as pilot:
        await started(app, pilot)
        window = app.query_one("#row-window", ChoiceRow)
        from_input = app.query_one("#input-from", Input)
        from_input.value = "2026-10-01"
        await pilot.pause()
        assert app.selection.global_window.from_ == "2026-10-01"
        assert window.value == "custom"

        from_input.value = "24h"
        await pilot.pause()
        assert window.value == "24h"

        app.query_one("#input-last", Input).value = "20"
        await pilot.pause()
        assert app.selection.global_window.last == 20
        assert window.value == "custom"

        window.action_step(1)  # from "custom" back to the first preset
        await pilot.pause()
        assert window.value == "24h"
        assert app.selection.global_window.last is None


async def test_choice_row_and_start_row_work_with_the_mouse() -> None:
    seed_cache()
    app = DiscoopApp(api_factory=RecordingDiscord().factory)
    async with app.run_test(size=(140, 40)) as pilot:
        await started(app, pilot)
        mode = app.query_one("#row-mode", ChoiceRow)

        await pilot.click("#row-mode", offset=(mode.label_width + 3, 0))  # the value
        await pilot.pause()
        assert app.focused is mode
        assert mode.value == "fast"

        await asyncio.sleep(0.5)  # not a double click
        await pilot.click("#row-mode", offset=(mode.label_width, 0))  # the left arrow
        await pilot.pause()
        assert mode.value == "safe"

        await asyncio.sleep(0.5)
        await pilot.click("#row-mode", offset=(2, 0))  # the label only focuses
        await pilot.pause()
        assert mode.value == "safe"

        await asyncio.sleep(0.5)
        await pilot.click("#row-start")  # nothing selected: says so
        await pilot.pause()
        assert "No channels selected." in notifications(app)


async def test_tree_clicks_open_and_select() -> None:
    seed_cache()
    app = DiscoopApp(api_factory=RecordingDiscord().factory)
    async with app.run_test(size=(140, 40)) as pilot:
        await started(app, pilot)
        tree = app.query_one("#channel-tree", ChannelTree)
        await pilot.click("#channel-tree", offset=(4, 1))  # Beta Server
        await pilot.pause()
        beta = tree.root.children[1]
        assert beta.is_expanded

        await asyncio.sleep(0.5)
        await pilot.click("#channel-tree", offset=(4, 2))  # welcome
        await pilot.pause()
        assert app.selection.is_selected(WELCOME.id)


async def test_footer_key_runs_the_binding() -> None:
    app = DiscoopApp(api_factory=_make_dummy_api_factory())
    async with app.run_test(size=(140, 40)) as pilot:
        await started(app, pilot)
        await pilot.click("FooterKey", offset=(1, 0))  # whichever comes first: Space on the tree, only a hint here
        await pilot.pause()
        assert app.is_running

        keys = [key for key in app.query("FooterKey") if key.key == "f1"]
        assert keys
        await pilot.click(keys[0])
        await pilot.pause()
        assert isinstance(app.screen, HelpScreen)


async def test_function_keys_open_the_dialogs() -> None:
    app = DiscoopApp(api_factory=_make_dummy_api_factory())
    async with app.run_test(size=(140, 40)) as pilot:
        await started(app, pilot)
        await pilot.press("f2")
        await pilot.pause()
        assert isinstance(app.screen, SettingsModal)
        await pilot.press("escape")
        await pilot.pause()

        await pilot.press("f3")
        await pilot.pause()
        assert isinstance(app.screen, LoginModal)
        await pilot.press("escape")
        await pilot.pause()

        await pilot.press("question_mark")
        await pilot.pause()
        assert isinstance(app.screen, HelpScreen)
        await pilot.press("escape")
        await pilot.pause()
        assert app.screen is app.screen_stack[0]


async def test_login_status_valid_token() -> None:
    seed_cache()
    TokenStore.default().save("fake-token")
    app = DiscoopApp(api_factory=RecordingDiscord().factory)
    async with app.run_test(size=(140, 40)) as pilot:
        await started(app, pilot)
        indicator = app.query_one("#status-indicator", Label)
        assert str(indicator.content) == "@student_a"
        assert indicator.has_class("-ok")


async def test_login_status_invalid_token() -> None:
    TokenStore.default().save("expired-token")
    discord = RecordingDiscord(me_status=401)
    app = DiscoopApp(api_factory=discord.factory)
    async with app.run_test(size=(140, 40)) as pilot:
        await started(app, pilot)
        indicator = app.query_one("#status-indicator", Label)
        assert str(indicator.content) == "token invalid"
        assert indicator.has_class("-bad")
        assert not indicator.has_class("-ok")
        assert discord.requests == ["/users/@me"], "no point in asking for anything else"


async def test_login_status_offline() -> None:
    seed_cache()
    TokenStore.default().save("fake-token")

    def unreachable(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no route to host")

    def factory(token: str | None = None, **kw: Any) -> DiscordAPI:
        kw["max_retries"] = 0
        return DiscordAPI("fake-token", transport=httpx.MockTransport(unreachable), **kw)

    app = DiscoopApp(api_factory=factory)
    async with app.run_test(size=(140, 40)) as pilot:
        await started(app, pilot)
        indicator = app.query_one("#status-indicator", Label)
        assert str(indicator.content) == "offline?"
        assert not indicator.has_class("-ok")
        assert visible_rows(app.query_one("#channel-tree", ChannelTree))[0] == "Alpha Server", "the cache still shows"


async def test_login_status_without_token() -> None:
    discord = RecordingDiscord()
    app = DiscoopApp(api_factory=discord.factory)
    async with app.run_test(size=(140, 40)) as pilot:
        await started(app, pilot)
        assert str(app.query_one("#status-indicator", Label).content) == "not logged in"
        assert discord.requests == []
        assert "F3" in log_text(app)


async def test_a_login_change_clears_the_selection() -> None:
    seed_cache()
    app = DiscoopApp(api_factory=RecordingDiscord().factory)
    async with app.run_test(size=(140, 40)) as pilot:
        await started(app, pilot)
        await pilot.press("down", "a")  # Beta: all of it
        await pilot.pause()
        assert app.selection.selected

        await pilot.press("f3")
        await pilot.pause()
        await pilot.press("escape")  # cancelled: the account is the same
        await pilot.pause()
        assert app.selection.selected

        await pilot.press("f3")
        await pilot.pause()
        app.no_access_servers.add(SERVER_C.id)
        app.screen.dismiss(True)
        await pilot.pause()
        await started(app, pilot)
        assert not app.selection.selected
        assert not app.no_access_servers
        assert not app.query_one("#selected-list").display
        assert label_of(app._tree_nodes[f"channel:{WELCOME.id}"]).startswith("[ ]")
        assert "(select channels" in str(app.query_one("#command-preview", Static).content)


async def test_form_shows_the_real_config_values(tmp_path: Path) -> None:
    config = Config.default()
    config.set("mode", "fast")
    config.set("delay", 2.5)
    config.set("export-dir", str(tmp_path / "exports"))

    app = DiscoopApp(api_factory=_make_dummy_api_factory())
    async with app.run_test(size=(140, 40)) as pilot:
        await started(app, pilot)
        assert app.settings.mode == "fast"
        assert app.settings.delay == 2.5
        assert app.query_one("#row-mode", ChoiceRow).value == "fast"
        assert app.query_one("#input-delay", Input).value == "2.5"
        assert app.query_one("#row-delay").display
        assert str(app.query_one("#mode-indicator", Label).content) == "fast"

        assert app.settings.export_dir == str(tmp_path / "exports")
        assert app.query_one("#input-path", Input).value == ""
        assert app.settings.path == ""


async def test_config_defaults_are_real_values_too() -> None:
    app = DiscoopApp(api_factory=_make_dummy_api_factory())
    async with app.run_test(size=(140, 40)) as pilot:
        await started(app, pilot)
        assert app.settings.delay == 1.0
        assert app.query_one("#input-delay", Input).value == "1"
        assert app.settings.export_dir is None
        assert app.query_one("#input-path", Input).value == ""


async def test_saving_settings_updates_the_form() -> None:
    app = DiscoopApp(api_factory=_make_dummy_api_factory())
    async with app.run_test(size=(140, 40)) as pilot:
        await started(app, pilot)
        await pilot.press("f2")
        await pilot.pause()
        await pilot.press("right")  # Mode: fast
        await pilot.pause()
        app.screen.query_one("#input-cfg-delay", Input).value = "0.5"
        await pilot.press("enter")
        await pilot.pause()

        assert not isinstance(app.screen, SettingsModal)
        assert app.settings.mode == "fast"
        assert app.settings.delay == 0.5
        assert app.query_one("#row-mode", ChoiceRow).value == "fast"
        assert app.query_one("#input-delay", Input).value == "0.5"


async def test_name_row_shows_the_automatic_name_and_the_typed_one() -> None:
    app = DiscoopApp(api_factory=_make_dummy_api_factory())
    async with app.run_test(size=(140, 40)) as pilot:
        await started(app, pilot)
        server, channel = Server(FIT, "Study Group", 5000), Channel("200", FIT, "general", 0, None, 0)
        app.selection.toggle(server, channel)
        app.query_one("#input-path", Input).value = ""
        app._update_command_preview()
        await pilot.pause()
        stamp = export_stamp()
        assert app.query_one("#input-path", Input).placeholder == stamp
        assert f"--out exports/{stamp}" in str(app.query_one("#command-preview", Static).content)

        app.query_one("#input-path", Input).value = "semester"
        await pilot.pause()
        assert "exports/semester" in str(app.query_one("#command-preview", Static).content)
        assert stamp not in str(app.query_one("#command-preview", Static).content)


async def test_an_edited_path_survives_a_config_reload(tmp_path: Path) -> None:
    app = DiscoopApp(api_factory=_make_dummy_api_factory())
    async with app.run_test(size=(140, 40)) as pilot:
        await started(app, pilot)
        app.query_one("#input-path", Input).value = "my-own-folder"
        await pilot.pause()
        Config.default().set("export-dir", str(tmp_path))
        app._load_config()
        app._sync_form()
        await pilot.pause()
        assert app.settings.path == "my-own-folder"


def _export_network(count: int = 150) -> tuple[FakeDiscord, httpx.MockTransport]:
    messages = series(count, newest=datetime.now(UTC) - timedelta(minutes=1), step=timedelta(minutes=1))
    discord = FakeDiscord({"200": FakeChannel(messages), "202": FakeChannel([])})
    return discord, httpx.MockTransport(Network(discord, None).handle)


def _seed_export() -> tuple[Server, Channel, Channel]:
    server = Server(FIT, "Study Group", 5000)
    first = Channel("200", FIT, "general", 0, None, 0)
    second = Channel("202", FIT, "dates", 0, None, 1)
    TokenStore.default().save("fake-token")
    with Cache.default() as cache:
        cache.replace_servers([server])
        cache.replace_channels(FIT, [first, second])
    return server, first, second


def _select(app: DiscoopApp, server: Server, *channels: Channel) -> None:
    app.selection.select_many(server, channels)
    app._selection_changed(c.id for c in channels)


async def test_export_reports_what_happened(tmp_path: Path) -> None:
    server, first, second = _seed_export()
    discord, transport = _export_network(6)
    discord.status["202"] = 403

    def factory(token: str | None = None, **kw: Any) -> DiscordAPI:
        kw["delay"] = 0.0
        return DiscordAPI("fake-token", transport=transport, **kw)

    app = DiscoopApp(api_factory=factory)
    async with app.run_test(size=(140, 40)) as pilot:
        await started(app, pilot)
        _select(app, server, first, second)
        app.query_one("#input-path", Input).value = str(tmp_path / "out")
        await pilot.pause()

        await pilot.press("f5")
        await wait_until(pilot, lambda: app.cancel_token is None)

        status = str(app.query_one("#run-status", Label).content)
        assert status == "Done: 1 channel, 6 messages, 1 skipped."
        log = log_text(app)
        assert "Export done: 1 channel, 6 messages, 1 skipped." in log
        assert "Skipped" in log
        assert str(tmp_path / "out") in log.replace("\n", "")
        assert (tmp_path / "out" / "manifest.json").exists()
        assert not app.query_one("#job-progress").display
        assert str(app.query_one("#row-start", ActionRow).content) == "[ Start (F5) ]"


async def test_export_failure_shows_the_error(tmp_path: Path) -> None:
    server, first, _ = _seed_export()
    _, transport = _export_network(1)

    def factory(token: str | None = None, **kw: Any) -> DiscordAPI:
        kw["delay"] = 0.0
        return DiscordAPI("fake-token", transport=transport, **kw)

    app = DiscoopApp(api_factory=factory)
    async with app.run_test(size=(140, 40)) as pilot:
        await started(app, pilot)
        _select(app, server, first)
        app.query_one("#input-from", Input).value = "not-a-date"
        app.query_one("#input-path", Input).value = str(tmp_path / "out")
        await pilot.pause()

        await pilot.press("f5")
        await wait_until(pilot, lambda: app.cancel_token is None)
        assert "Export:" in log_text(app)
        assert "Done" not in str(app.query_one("#run-status", Label).content)


async def test_start_row_starts_with_enter(tmp_path: Path) -> None:
    server, first, _ = _seed_export()
    _, transport = _export_network(1)

    def factory(token: str | None = None, **kw: Any) -> DiscordAPI:
        kw["delay"] = 0.0
        return DiscordAPI("fake-token", transport=transport, **kw)

    app = DiscoopApp(api_factory=factory)
    async with app.run_test(size=(140, 40)) as pilot:
        await started(app, pilot)
        _select(app, server, first)
        app.query_one("#input-path", Input).value = str(tmp_path / "out")
        await pilot.pause()

        app.query_one("#row-start", ActionRow).focus()
        await pilot.pause()
        await pilot.press("enter")
        await wait_until(pilot, lambda: (tmp_path / "out" / "manifest.json").exists() and app.cancel_token is None)
        assert "Done: 1 channel, 1 message." == str(app.query_one("#run-status", Label).content)


async def test_preview_target_opens_the_preview_screen() -> None:
    app = DiscoopApp(api_factory=_make_dummy_api_factory())
    async with app.run_test(size=(140, 40)) as pilot:
        await started(app, pilot)
        server = Server("1", "Study Group")
        channel = Channel("2", "1", "general", 0)
        result = service.ChannelMessages(server, channel, ())
        window = Window(None, NOW)
        outcome = service.MessagesOutcome([result], [], None, Query(window))

        app._export_finished([outcome], "md")
        await pilot.pause()
        assert isinstance(app.screen, PreviewScreen)
        assert app.screen.current_format == "md"


async def test_preview_export_runs_against_the_fake_api() -> None:
    server, first, _ = _seed_export()
    _, transport = _export_network(3)

    def factory(token: str | None = None, **kw: Any) -> DiscordAPI:
        kw["delay"] = 0.0
        return DiscordAPI("fake-token", transport=transport, **kw)

    app = DiscoopApp(api_factory=factory)
    async with app.run_test(size=(140, 40)) as pilot:
        await started(app, pilot)
        _select(app, server, first)
        app.settings.target = "preview"
        app.settings.preview_format = "md"
        await pilot.press("f5")
        await wait_until(pilot, lambda: app.cancel_token is None)
        assert isinstance(app.screen, PreviewScreen)
        assert app.screen.current_format == "md"


async def test_escape_stops_an_export_inside_a_pause(tmp_path: Path) -> None:
    server, first, _ = _seed_export()
    discord, transport = _export_network()

    def slow_factory(token: str | None = None, **kw: Any) -> DiscordAPI:
        kw["delay"] = 60.0  # the wait before the second page
        kw["mode"] = "fast"
        return DiscordAPI("fake-token", transport=transport, **kw)

    app = DiscoopApp(api_factory=slow_factory)
    async with app.run_test(size=(140, 40)) as pilot:
        await started(app, pilot)
        _select(app, server, first)
        app.query_one("#input-path", Input).value = str(tmp_path / "out")
        await pilot.pause()

        await pilot.press("f5")
        await wait_until(pilot, lambda: len(discord.channels["200"].requests) == 1)
        await pilot.pause(0.1)  # now in the pause
        assert app.cancel_token is not None
        assert app.is_running_job
        assert str(app.query_one("#row-start", ActionRow).content) == "[ Stop (Esc) ]"
        assert app.query_one("#job-progress").display
        assert app.query_one("#job-progress").region.height == 1
        assert app.query_one("#run-status").region.width > 20
        assert "#general" in str(app.query_one("#run-status", Label).content)

        stopped_at = time.monotonic()
        await pilot.press("escape")
        await wait_until(pilot, lambda: app.cancel_token is None)
        assert time.monotonic() - stopped_at < 0.5
        assert str(app.query_one("#run-status", Label).content) == "Stopped."
        assert not app.is_running_job
        assert len(discord.channels["200"].requests) == 1


async def test_escape_stops_load_all() -> None:
    """Regression: the pauses of load_all could not be stopped at all."""
    with Cache.default() as cache:
        cache.replace_servers([SERVER_A])
    TokenStore.default().save("fake-token")
    requests: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request.url.path)
        if request.url.path.endswith("/users/@me"):
            return httpx.Response(200, json={"id": "42", "username": "student_a"})
        return httpx.Response(200, json=[{"id": s.id, "name": s.name} for s in (SERVER_A, SERVER_B)])

    def factory(token: str | None = None, **kw: Any) -> DiscordAPI:
        assert kw.get("delay", 1.0) >= 1.0
        return DiscordAPI("fake-token", transport=httpx.MockTransport(handler), **kw)

    app = DiscoopApp(api_factory=factory)
    async with app.run_test(size=(140, 40)) as pilot:
        await started(app, pilot)
        await pilot.press("L")
        await wait_until(pilot, lambda: any(path.endswith("/guilds") for path in requests))
        await pilot.pause(0.1)  # waiting 2 to 4.5 s before the channels of the first server
        assert app.cancel_token is not None

        stopped_at = time.monotonic()
        await pilot.press("escape")
        await wait_until(pilot, lambda: app.cancel_token is None)
        assert time.monotonic() - stopped_at < 0.5
        assert str(app.query_one("#run-status", Label).content) == "Stopped."
        assert not any(path.endswith("/channels") for path in requests)


async def test_load_all_fills_the_tree() -> None:
    with Cache.default() as cache:
        cache.replace_servers([SERVER_A])
    TokenStore.default().save("fake-token")
    discord = RecordingDiscord()
    discord.channels["1000"] = [{"id": "1001", "type": 0, "name": "general", "position": 0}]
    discord.channel_status["2000"] = 403
    app = DiscoopApp(api_factory=discord.factory)
    async with app.run_test(size=(140, 40)) as pilot:
        await started(app, pilot)
        tree = app.query_one("#channel-tree", ChannelTree)
        await pilot.press("L")
        await wait_until(pilot, lambda: discord.calls_to("/channels") == 3 and app.cancel_token is None)
        assert visible_rows(tree) == ["Alpha Server", "Beta Server", "Gamma Server"]
        assert row_of(tree, tree.root.children[0]).endswith(" 1")
        assert row_of(tree, tree.root.children[1]).endswith("no access")


async def test_q_while_running_cancels_before_quitting(tmp_path: Path) -> None:
    server, first, _ = _seed_export()
    discord, transport = _export_network()

    def slow_factory(token: str | None = None, **kw: Any) -> DiscordAPI:
        kw["delay"] = 60.0
        kw["mode"] = "fast"
        return DiscordAPI("fake-token", transport=transport, **kw)

    app = DiscoopApp(api_factory=slow_factory)
    async with app.run_test(size=(140, 40)) as pilot:
        await started(app, pilot)
        _select(app, server, first)
        app.query_one("#input-path", Input).value = str(tmp_path / "out")
        await pilot.pause()
        await pilot.press("f5")
        await wait_until(pilot, lambda: len(discord.channels["200"].requests) == 1)
        token = app.cancel_token
        assert token is not None

        await pilot.press("q")
        await pilot.pause()
        assert token.is_cancelled
        assert app._exit


async def test_late_worker_message_after_close_is_harmless() -> None:
    app = DiscoopApp(api_factory=_make_dummy_api_factory())
    async with app.run_test(size=(140, 40)) as pilot:
        await started(app, pilot)
    assert not app.screen_stack
    app.on_ui_call(tui_app.UiCall(app._net_finished, ()))


async def test_the_log_only_shows_a_scrollbar_when_it_needs_one() -> None:
    app = DiscoopApp(api_factory=_make_dummy_api_factory())
    async with app.run_test(size=(140, 40)) as pilot:
        await started(app, pilot)
        log = app.query_one("#event-log", RichLog)
        log.clear()
        await pilot.pause()
        assert not log.show_vertical_scrollbar

        for number in range(50):
            app._log_line(f"line {number}")
        await wait_until(pilot, lambda: log.show_vertical_scrollbar and log.scroll_y == log.max_scroll_y)
        assert log.max_scroll_y > 0
        assert log.styles.scrollbar_size_vertical == 1
        assert log.vertical_scrollbar.region.width == 1

        app._log_line("the newest line")  # still follows the end
        await wait_until(pilot, lambda: log.scroll_y == log.max_scroll_y)
        assert "the newest line" in screen_text(app, log.region)


async def test_names_with_brackets_and_emoji_stay_literal() -> None:
    server = Server("1", "[bold]Club️")
    channel = Channel("2", "1", "a[1]-️info", 0, None, 0)
    with Cache.default() as cache:
        cache.replace_servers([server])
        cache.replace_channels("1", [channel])
    app = DiscoopApp(api_factory=_make_dummy_api_factory())
    async with app.run_test(size=(140, 40)) as pilot:
        await started(app, pilot)
        tree = app.query_one("#channel-tree", ChannelTree)
        assert visible_rows(tree) == ["[bold]Club"]
        await pilot.press("right")
        await pilot.pause()
        await pilot.press("down", "space")
        await pilot.pause()
        assert visible_rows(tree)[1] == "[x] #a[1]-info"
        selected = app.query_one("#selected-list", OptionList)
        assert str(selected.get_option("2").prompt) == "[bold]Club/#a[1]-info  7d"
        # The data keeps the original name
        assert app.selection.selected["2"][1].name == channel.name


async def test_long_names_never_widen_the_tree() -> None:
    long_name = "a-very-long-channel-name-" * 6
    server = Server("1", "Club")
    with Cache.default() as cache:
        cache.replace_servers([server])
        cache.replace_channels("1", [Channel("2", "1", long_name, 0, None, 0)])
    app = DiscoopApp(api_factory=_make_dummy_api_factory())
    async with app.run_test(size=(100, 30)) as pilot:
        await started(app, pilot)
        tree = app.query_one("#channel-tree", ChannelTree)
        await pilot.press("right")
        await pilot.pause()
        row = row_of(tree, tree.root.children[0].children[0])
        assert row.rstrip().endswith("…")
        assert not tree.show_horizontal_scrollbar

        await pilot.press("down", "space")
        await pilot.pause()
        selected = app.query_one("#selected-list", OptionList)
        assert selected.region.height == 1, "one channel, one line"
        assert screen_text(app, selected.region).rstrip().endswith("…")


async def test_long_command_ends_with_an_ellipsis_on_one_line() -> None:
    seed_cache()
    app = DiscoopApp(api_factory=RecordingDiscord().factory)
    async with app.run_test(size=(80, 30)) as pilot:
        await started(app, pilot)
        await pilot.press("down", "a")
        await pilot.pause()
        preview = app.query_one("#command-preview", Static)
        full = str(preview.content)
        assert "--max-file-size" in full, "the widget keeps the whole command"
        assert preview.region.height == 1
        painted = screen_text(app, preview.region)
        assert painted.startswith("discoop messages")
        assert painted.rstrip().endswith("…")
        assert len(painted.rstrip()) < len(full)


async def test_c_copies_the_command() -> None:
    seed_cache()
    app = DiscoopApp(api_factory=RecordingDiscord().factory)
    async with app.run_test(size=(140, 40)) as pilot:
        await started(app, pilot)
        await pilot.press("c")
        await pilot.pause()
        assert "No channels selected." in notifications(app)

        await pilot.press("down", "a", "c")
        await pilot.pause()
        assert app.clipboard == str(app.query_one("#command-preview", Static).content)


async def test_tab_in_a_narrow_window_shows_one_panel_at_a_time() -> None:
    seed_cache()
    app = DiscoopApp(api_factory=RecordingDiscord().factory)
    async with app.run_test(size=(80, 30)) as pilot:
        await started(app, pilot)
        tree_pane = app.query_one("#tree-pane")
        export_pane = app.query_one("#export-pane")
        log_pane = app.query_one("#log-pane")
        assert tree_pane.display and not export_pane.display and log_pane.display

        await pilot.press("down", "a", "tab")
        await pilot.pause()
        assert app.focused is app.query_one("#selected-list")
        assert export_pane.display and not tree_pane.display and log_pane.display
        assert app.query_one("#command-bar").display

        await pilot.press("tab")
        await pilot.pause()
        assert app.query_one("#export-form") in app.focused.ancestors
        assert export_pane.display and not tree_pane.display

        await pilot.press("tab")
        await pilot.pause()
        assert app.focused is app.query_one("#channel-tree")
        assert tree_pane.display and not export_pane.display

        await pilot.press("3")
        await pilot.pause()
        assert log_pane.region.height > 8, "on its own tab the log fills the window"
        assert not app.query_one("#main-columns").display

        await pilot.press("slash")  # the filter is in the tree panel
        await pilot.pause()
        assert app.focused is app.query_one("#tree-filter")
        assert app.query_one("#main-columns").display and tree_pane.display and not export_pane.display


async def test_ctrl_p_opens_the_command_palette() -> None:
    app = DiscoopApp(api_factory=_make_dummy_api_factory())
    async with app.run_test(size=(140, 40)) as pilot:
        await started(app, pilot)
        assert app.ENABLE_COMMAND_PALETTE
        await pilot.press("ctrl+p")
        await pilot.pause()
        assert isinstance(app.screen, CommandPalette)
        await pilot.press("escape")
        await pilot.pause()
        assert app.screen is app.screen_stack[0]
