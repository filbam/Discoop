"""Forums and media channels in the TUI: they can be selected like any channel, and their posts are threads.

Everything here talks to fakes: a cached server, a fake Discord (tests/fake_messages.py, tests/fake_threads.py), no CDN.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
import json
from pathlib import Path
from typing import Any

import httpx
from rich.style import Style
from textual.widgets import Input, Label, OptionList, Static

from discoop import profiles
from discoop.api import DiscordAPI
from discoop.cache import Cache
from discoop.models import Channel, Server
from discoop.tokenstore import TokenStore
from discoop.tui import modals
from discoop.tui.app import DiscoopApp
from discoop.tui.modals import HelpScreen, LoadProfileModal, SaveProfileModal, TimeWindowModal
from discoop.tui.state import ExportSettings, SelectionState, WindowSpec, forums_without_threads, plan_jobs
from discoop.tui.tuistate import load_user_state, restore_app_state, save_user_state
from discoop.tui.widgets import ChannelTree, ChoiceRow, TextView
from fake_messages import FIT, FakeChannel, FakeDiscord, message
from fake_threads import FakeThreadSearch, thread
from test_tui_app import (
    _export_to,
    _select,
    label_of,
    log_text,
    notifications,
    screen_text,
    started,
    visible_rows,
    wait_until,
)
from test_tui_tree_suffix import ago, node_of, tree_of

SERVER = Server(FIT, "Study Group", 5000)
STUDY = Channel("100", FIT, "study", 4, None, 0)
GENERAL = Channel("200", FIT, "general", 0, "100", 0)
HELP = Channel("204", FIT, "help-center", 15, "100", 1)
GALLERY = Channel("206", FIT, "gallery", 16, "100", 2)
HALL = Channel("208", FIT, "hall", 14, "100", 3)  # a directory channel: the one type here that cannot be selected

FIRST_MESSAGE = "How do I register for the course?"


class ForumDiscord:
    """A fake Discord with one forum (204): `threads/search` answers its posts, each post has a few messages.

    `log` keeps the path of every request, to see that a refused Start asks Discord for nothing.
    """

    def __init__(self, posts: int = 2) -> None:
        now = datetime.now(UTC).replace(microsecond=0)  # whole seconds: the IDs encode them
        self.threads: list[dict] = []
        channels: dict[str, FakeChannel] = {}
        for number in range(1, posts + 1):
            last = now - timedelta(hours=number)
            post = thread(last, created=last - timedelta(hours=1), seq=number, parent_id=HELP.id, name=f"post {number}")
            self.threads.append(post)
            channels[post["id"]] = FakeChannel(
                [
                    message(last - timedelta(minutes=10), FIRST_MESSAGE, seq=number, channel_id=post["id"]),
                    message(last, "Use the study information system.", seq=number + 10, channel_id=post["id"]),
                ]
            )
        self.search = FakeThreadSearch(self.threads)
        self.fake = FakeDiscord(channels)
        self.log: list[str] = []

    def handle(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path.removeprefix("/api/v9")
        self.log.append(path)
        if path == "/users/@me":
            return httpx.Response(200, json={"id": "42", "username": "student_a"})
        if path == f"/channels/{HELP.id}/threads/search":
            return self.search.respond(request)
        return self.fake.handle(request)

    def factory(self, token: str | None = None, **kw: Any) -> DiscordAPI:
        kw["delay"] = 0.0
        return DiscordAPI("fake-token", transport=httpx.MockTransport(self.handle), **kw)

    def exported_calls(self) -> list[str]:
        """The requests an export makes: messages and thread lists."""
        return [path for path in self.log if path.endswith("/messages") or path.endswith("/threads/search")]


def seed(*extra: Channel) -> None:
    TokenStore.default().save("fake-token")
    with Cache.default() as cache:
        cache.replace_servers([SERVER])
        cache.replace_channels(FIT, [STUDY, GENERAL, HELP, GALLERY, HALL, *extra])


async def open_study(app: DiscoopApp, pilot: Any) -> ChannelTree:
    """Wait for the start, open the server and its category: the cursor stands on the category."""
    await started(app, pilot)
    await pilot.press("right")
    await pilot.pause()
    await pilot.press("down", "right")
    await pilot.pause()
    tree = tree_of(app)
    assert tree.cursor_node is not None and tree.cursor_node.data == STUDY
    return tree


def command(app: DiscoopApp) -> str:
    return str(app.query_one("#command-preview", Static).content)


def warning_shown(app: DiscoopApp) -> bool:
    return app.query_one("#threads-warning", Label).display


def threads_row(app: DiscoopApp) -> ChoiceRow:
    return app.query_one("#row-threads", ChoiceRow)


# ==================== The selection rule ====================


def test_a_forum_and_a_media_channel_are_selectable_a_category_and_a_directory_are_not() -> None:
    state = SelectionState()
    for channel in (GENERAL, HELP, GALLERY, Channel("9", FIT, "lounge", 2), Channel("10", FIT, "stage", 13)):
        assert state.is_selectable(channel), channel.name
    for channel in (STUDY, HALL):
        assert not state.is_selectable(channel), channel.name

    assert state.select_many(SERVER, [STUDY, GENERAL, HELP, GALLERY, HALL]) == 3
    assert list(state.selected) == [GENERAL.id, HELP.id, GALLERY.id]


def test_only_forums_and_media_channels_are_refused_without_threads() -> None:
    state = SelectionState()
    state.select_many(SERVER, [GENERAL, HELP, GALLERY])
    assert forums_without_threads(state, ExportSettings(threads=True)) == []
    assert forums_without_threads(state, ExportSettings(threads=False)) == [HELP, GALLERY]

    text_only = SelectionState()
    text_only.select_many(SERVER, [GENERAL])
    assert forums_without_threads(text_only, ExportSettings(threads=False)) == []
    assert forums_without_threads(SelectionState(), ExportSettings(threads=False)) == []


def test_restoring_a_saved_selection_keeps_a_forum_and_drops_what_cannot_be_selected() -> None:
    state = {
        "selection": {
            GENERAL.id: {"server_id": FIT, "custom_window": None},
            HELP.id: {"server_id": FIT, "custom_window": {"from": "30d", "to": None, "last": None}},
            GALLERY.id: {"server_id": FIT, "custom_window": None},
            HALL.id: {"server_id": FIT, "custom_window": None},
            STUDY.id: {"server_id": FIT, "custom_window": None},
        },
        "settings": {"mode": "safe", "folder": "", "name": "", "threads": True},
    }
    selection, settings = SelectionState(), ExportSettings()
    count, _ = restore_app_state(state, [SERVER], {FIT: [STUDY, GENERAL, HELP, GALLERY, HALL]}, selection, settings)
    assert count == 3
    assert list(selection.selected) == [GENERAL.id, HELP.id, GALLERY.id]
    assert selection.window_for(HELP.id).from_ == "30d"


def test_the_help_describes_the_real_selection_rule() -> None:
    text = " ".join(modals.guide_text().plain.split())
    assert "Forums and media channels can be selected" in text
    assert "A category cannot be selected itself: selecting it selects its channels" in text
    assert "the Threads row must be yes" in text
    assert "voice channels cannot be selected" not in text, "voice and stage chats are selectable"
    assert "Forums and voice" not in text


async def test_the_help_screen_shows_the_selection_rule() -> None:
    seed()
    app = DiscoopApp(api_factory=ForumDiscord().factory)
    async with app.run_test(size=(140, 60)) as pilot:
        await started(app, pilot)
        await pilot.press("f1")
        await pilot.pause()
        assert isinstance(app.screen, HelpScreen)
        guide = " ".join(str(app.screen.query_one("#help-content", TextView).content).split())
        assert "Forums and media channels can be selected" in guide
        assert "cannot be selected" in guide  # a category
        assert "Forums and voice channels cannot be selected" not in guide


# ==================== In the tree ====================


async def test_a_forum_and_a_media_channel_are_selected_with_the_keys() -> None:
    seed()
    app = DiscoopApp(api_factory=ForumDiscord().factory)
    async with app.run_test(size=(140, 40)) as pilot:
        tree = await open_study(app, pilot)
        assert label_of(node_of(app, HELP)) == "[ ] #help-center", "a forum row looks like any channel row"
        assert label_of(node_of(app, GALLERY)) == "[ ] #gallery"
        assert label_of(node_of(app, HALL)).strip() == "#hall (directory)"

        await pilot.press("down", "down")  # general, then the forum
        await pilot.pause()
        assert tree.cursor_node is node_of(app, HELP)
        await pilot.press("space")
        await pilot.pause()
        assert app.selection.is_selected(HELP.id)
        assert label_of(node_of(app, HELP)) == "[x] #help-center"
        assert label_of(node_of(app, STUDY)) == "[~] study"

        await pilot.press("down", "enter")  # Enter selects a media channel too
        await pilot.pause()
        assert app.selection.is_selected(GALLERY.id)
        assert label_of(node_of(app, GALLERY)) == "[x] #gallery"
        assert tree.cursor_node is node_of(app, GALLERY), "selecting does not move the cursor"

        await pilot.press("down", "space")  # the directory channel cannot be selected
        await pilot.pause()
        assert set(app.selection.selected) == {HELP.id, GALLERY.id}

        await pilot.press("up", "space")  # and a second Space takes the media channel out again
        await pilot.pause()
        assert set(app.selection.selected) == {HELP.id}
        assert label_of(node_of(app, GALLERY)) == "[ ] #gallery"


async def test_selecting_a_category_selects_its_forums_and_media_channels_too() -> None:
    seed()
    app = DiscoopApp(api_factory=ForumDiscord().factory)
    async with app.run_test(size=(140, 40)) as pilot:
        await open_study(app, pilot)
        await pilot.press("space")
        await pilot.pause()
        assert set(app.selection.selected) == {GENERAL.id, HELP.id, GALLERY.id}
        assert label_of(node_of(app, STUDY)) == "[x] study"
        assert label_of(node_of(app, HELP)) == "[x] #help-center"

        await pilot.press("space")  # all selected: clears
        await pilot.pause()
        assert not app.selection.selected
        assert label_of(node_of(app, STUDY)) == "[ ] study"


async def test_a_category_with_only_a_forum_gets_a_box() -> None:
    lonely = Channel("300", FIT, "archive", 4, None, 5)
    only_forum = Channel("301", FIT, "old-posts", 15, "300", 0)
    seed(lonely, only_forum)
    app = DiscoopApp(api_factory=ForumDiscord().factory)
    async with app.run_test(size=(140, 40)) as pilot:
        await open_study(app, pilot)
        assert label_of(node_of(app, lonely)) == "[ ] archive"
        tree_of(app).move_cursor(node_of(app, lonely))
        await pilot.press("space")
        await pilot.pause()
        assert list(app.selection.selected) == [only_forum.id]
        assert label_of(node_of(app, lonely)) == "[x] archive"


async def test_select_all_and_the_filter_take_forums() -> None:
    seed()
    app = DiscoopApp(api_factory=ForumDiscord().factory)
    async with app.run_test(size=(140, 40)) as pilot:
        tree = await open_study(app, pilot)
        await pilot.press("slash", *"help")
        await wait_until(pilot, lambda: len(visible_rows(tree)) == 3)
        assert visible_rows(tree) == ["Study Group", "[ ] study", "[ ] #help-center"]
        await pilot.press("enter")  # back to the tree
        await pilot.pause()
        await pilot.press("a")
        await pilot.pause()
        assert list(app.selection.selected) == [HELP.id]

        await pilot.press("escape")
        await wait_until(pilot, lambda: app.query_one("#tree-filter", Input).value == "")
        await pilot.press("a")  # every channel of the server: no category, no directory
        await pilot.pause()
        assert set(app.selection.selected) == {GENERAL.id, HELP.id, GALLERY.id}


async def test_a_forum_is_listed_with_its_server_and_can_have_its_own_window() -> None:
    seed()
    app = DiscoopApp(api_factory=ForumDiscord().factory)
    async with app.run_test(size=(140, 40)) as pilot:
        tree = await open_study(app, pilot)
        await pilot.press("down", "down", "space")  # the forum
        await pilot.pause()
        selected = app.query_one("#selected-list", OptionList)
        assert selected.display and selected.option_count == 1
        assert str(selected.get_option(HELP.id).prompt) == "Study Group/#help-center  7d"

        await pilot.press("e")  # the tree offers the window of a forum like that of any channel
        await pilot.pause()
        assert isinstance(app.screen, TimeWindowModal)
        await pilot.press("escape")
        await pilot.pause()
        assert not isinstance(app.screen, TimeWindowModal)
        assert not any("Move to a channel" in message_text for message_text in notifications(app))

        _select(app, SERVER, GENERAL)
        app.selection.set_custom_window(HELP.id, WindowSpec(from_="30d"))
        app._selection_changed([HELP.id])
        await pilot.pause()
        assert str(selected.get_option(HELP.id).prompt) == "Study Group/#help-center  30d*"
        jobs = plan_jobs(app.selection, app.settings)
        assert len(jobs) == 2
        assert {job.window.from_: job.request.channels for job in jobs} == {"7d": (GENERAL.id,), "30d": (HELP.id,)}
        assert tree.cursor_node is node_of(app, HELP)


async def test_a_forum_row_gets_the_dim_suffix_like_other_channels() -> None:
    forum = Channel("204", FIT, "help-center", 15, "100", 1, last_message_id=ago(days=2, hours=1))  # its newest post
    text = Channel("200", FIT, "general", 0, "100", 0, last_message_id=ago(days=3, hours=1))
    TokenStore.default().save("fake-token")
    with Cache.default() as cache:
        cache.replace_servers([SERVER])
        cache.replace_channels(FIT, [STUDY, text, forum])
    app = DiscoopApp(api_factory=ForumDiscord().factory)
    async with app.run_test(size=(120, 40)) as pilot:
        tree = await open_study(app, pilot)
        assert tree.suffix_of(node_of(app, STUDY)) == ()
        assert tree.suffix_of(node_of(app, text)) == ("3d",)
        assert tree.suffix_of(node_of(app, forum)) == ("2d",)

        row = tree.render_label(node_of(app, forum), Style(), Style())
        assert row.plain.startswith("[ ] #help-center") and row.plain.rstrip().endswith("2d")
        assert row.spans[-1].style.dim, "the suffix is dim"
        assert row.plain[row.spans[-1].start : row.spans[-1].end] == "2d"


# ==================== The CLI command ====================


async def test_the_command_has_the_forum_and_no_threads_only_when_the_switch_is_no() -> None:
    seed()
    app = DiscoopApp(api_factory=ForumDiscord().factory)
    async with app.run_test(size=(140, 40)) as pilot:
        await open_study(app, pilot)
        await pilot.press("down", "down", "space")
        await pilot.pause()
        assert f"-s {FIT}" in command(app) and f"-c {HELP.id}" in command(app)
        assert "--no-threads" not in command(app)
        assert [job.request.channels for job in plan_jobs(app.selection, app.settings)] == [(HELP.id,)]

        threads_row(app).action_step(1)  # Threads: no
        await pilot.pause()
        assert app.settings.threads is False
        assert f"-c {HELP.id}" in command(app) and "--no-threads" in command(app)

        threads_row(app).action_step(1)  # and yes again
        await pilot.pause()
        assert "--no-threads" not in command(app)


# ==================== Threads: no ====================


async def test_threads_no_with_a_forum_warns_and_refuses_start_before_any_job(tmp_path: Path) -> None:
    seed()
    discord = ForumDiscord()
    app = DiscoopApp(api_factory=discord.factory)
    async with app.run_test(size=(140, 40)) as pilot:
        await open_study(app, pilot)
        _select(app, SERVER, GENERAL)
        assert not warning_shown(app), "Threads is yes"
        threads_row(app).action_step(1)
        await pilot.pause()
        assert not warning_shown(app), "no forum is selected, a text channel is fine without threads"

        _select(app, SERVER, HELP)
        await pilot.pause()
        assert warning_shown(app)
        assert "set Threads to yes or deselect it" in str(app.query_one("#threads-warning", Label).content)
        painted = " ".join(screen_text(app, app.query_one("#export-pane").region).split())
        assert "A forum or media channel is selected: set Threads" in painted

        _export_to(app, tmp_path / "out")
        requests = len(discord.log)
        await pilot.press("f5")
        await pilot.pause()
        assert app.cancel_token is None and not app.is_running_job
        assert not app._export_jobs, "no job was planned"
        assert len(discord.log) == requests, "Discord was not asked for anything"
        assert not discord.exported_calls()
        assert not (tmp_path / "out").exists() and not (tmp_path / "out.partial").exists()
        refused = [text for text in notifications(app) if "set Threads to yes or deselect #help-center" in text]
        assert refused, notifications(app)
        assert str(app.query_one("#run-status", Label).content).startswith("Ready")
        assert str(app.query_one("#row-start").content) == "[ Start (F5) ]"

        await pilot.press("escape")  # the keys work as before: a second Start is refused the same way
        app.action_start_export()
        await pilot.pause()
        assert app.cancel_token is None and len(discord.log) == requests


async def test_the_refusal_names_every_forum_up_to_three_and_counts_the_rest(tmp_path: Path) -> None:
    posts = [Channel(str(310 + n), FIT, f"forum-{n}", 15, "100", 10 + n) for n in range(5)]
    seed(*posts)
    discord = ForumDiscord()
    app = DiscoopApp(api_factory=discord.factory)
    async with app.run_test(size=(140, 40)) as pilot:
        await started(app, pilot)
        _select(app, SERVER, HELP, GALLERY, *posts)
        threads_row(app).action_step(1)
        await pilot.pause()
        app.action_start_export()
        await pilot.pause()
        assert any(
            "deselect #help-center, #gallery, #forum-0 and 4 more." in text for text in notifications(app)
        ), notifications(app)
        assert not discord.exported_calls()


async def test_the_warning_follows_the_selection_and_the_switch() -> None:
    seed()
    app = DiscoopApp(api_factory=ForumDiscord().factory)
    async with app.run_test(size=(140, 40)) as pilot:
        await open_study(app, pilot)
        assert not warning_shown(app)
        threads_row(app).action_step(1)
        await pilot.pause()
        assert not warning_shown(app), "nothing selected"

        await pilot.press("space")  # the whole category, forum and media channel included
        await pilot.pause()
        assert warning_shown(app)

        await pilot.press("down", "down", "space")  # the forum goes: the media channel is still there
        await pilot.pause()
        assert warning_shown(app)
        await pilot.press("down", "space")  # and the media channel
        await pilot.pause()
        assert not warning_shown(app), "only the text channel is left"

        await pilot.press("space")
        await pilot.pause()
        assert warning_shown(app)
        app.action_clear_selected()
        await pilot.pause()
        assert not warning_shown(app)

        _select(app, SERVER, HELP)
        await pilot.pause()
        assert warning_shown(app)
        threads_row(app).action_step(1)  # Threads: yes
        await pilot.pause()
        assert not warning_shown(app)


# ==================== Threads: yes ====================


async def test_threads_yes_with_a_forum_starts_and_exports_its_posts(tmp_path: Path) -> None:
    seed()
    discord = ForumDiscord(posts=2)
    app = DiscoopApp(api_factory=discord.factory)
    async with app.run_test(size=(140, 40)) as pilot:
        await open_study(app, pilot)
        _select(app, SERVER, HELP)
        _export_to(app, tmp_path / "out")
        threads_row(app).action_step(1)  # no: refused first
        await pilot.pause()
        await pilot.press("f5")
        await pilot.pause()
        assert not discord.exported_calls()

        threads_row(app).action_step(1)  # yes: the same Start now runs
        await pilot.pause()
        assert not warning_shown(app)
        await pilot.press("f5")
        await wait_until(pilot, lambda: app.cancel_token is None and (tmp_path / "out" / "manifest.json").exists())

        assert app._export_jobs and app._export_jobs[0].request.channels == (HELP.id,)
        assert app._export_jobs[0].request.threads is True
        assert f"/channels/{HELP.id}/threads/search" in discord.log
        manifest = json.loads((tmp_path / "out" / "manifest.json").read_text(encoding="utf-8"))
        assert manifest["counts"]["channels"] == 1
        assert manifest["counts"]["messages"] == 0, "a forum has no messages of its own"
        assert manifest["counts"]["thread_messages"] == 4, "two posts, two messages each"
        status = str(app.query_one("#run-status", Label).content)
        assert status == "Done: 1 channel, 4 messages.", status
        log = log_text(app)
        assert "#help-center: 0 messages, 2 threads (4 messages)" in log
        assert "Export done: 1 channel, 4 messages." in log
        assert app.last_exported.keys() == {HELP.id}


# ==================== Saved selection and profiles ====================


async def test_a_saved_selection_with_a_forum_comes_back_and_threads_no_still_refuses() -> None:
    seed()
    save_user_state(
        "42",
        {
            "selection": {
                HELP.id: {"server_id": FIT, "custom_window": {"from": "30d", "to": None, "last": None}},
                GALLERY.id: {"server_id": FIT, "custom_window": None},
                "999": {"server_id": FIT, "custom_window": None},  # gone from the server
            },
            "global_window": {"from": "7d", "to": None, "last": None, "max_messages": 5000},
            "settings": {"mode": "safe", "folder": "", "name": "", "threads": False},
        },
    )
    discord = ForumDiscord()
    app = DiscoopApp(api_factory=discord.factory)
    async with app.run_test(size=(140, 40)) as pilot:
        await started(app, pilot)
        await wait_until(pilot, lambda: app._state_loaded)
        assert app.selection.selected.keys() == {HELP.id, GALLERY.id}
        assert app.selection.window_for(HELP.id).from_ == "30d"
        assert app.settings.threads is False and threads_row(app).value == "no"
        assert warning_shown(app), "the saved form says Threads: no"
        assert label_of(node_of(app, HELP)) == "[x] #help-center"
        selected = app.query_one("#selected-list", OptionList)
        assert str(selected.get_option(HELP.id).prompt) == "Study Group/#help-center  30d*"

        requests = len(discord.log)
        await pilot.press("f5")
        await pilot.pause()
        assert not app._export_jobs and len(discord.log) == requests
        assert any("set Threads to yes or deselect" in text for text in notifications(app))

        await pilot.pause()
        saved = load_user_state("42")
        assert saved["selection"].keys() == {HELP.id, GALLERY.id}, "the forums are saved again with the rest"
        assert saved["settings"]["threads"] is False


async def test_a_profile_can_hold_a_forum() -> None:
    seed()
    app = DiscoopApp(api_factory=ForumDiscord().factory)
    async with app.run_test(size=(140, 40)) as pilot:
        await open_study(app, pilot)
        _select(app, SERVER, GENERAL, HELP, GALLERY)
        await pilot.press("P")
        await pilot.pause()
        assert isinstance(app.screen, SaveProfileModal)
        app.screen.query_one("#input-profile-name", Input).value = "study"
        await pilot.press("enter")
        await pilot.pause()
        assert profiles.load()["study"]["channels"] == [GENERAL.id, HELP.id, GALLERY.id]
        assert profiles.load()["study"]["server"] == FIT

        app.action_clear_selected()
        await pilot.pause()
        assert not app.selection.selected

        await pilot.press("p")
        await pilot.pause()
        assert isinstance(app.screen, LoadProfileModal)
        await pilot.press("enter")
        await pilot.pause()
        assert set(app.selection.selected) == {GENERAL.id, HELP.id, GALLERY.id}
        assert label_of(node_of(app, HELP)) == "[x] #help-center"
        assert label_of(node_of(app, GALLERY)) == "[x] #gallery"
        assert f"-c {HELP.id}" in command(app)
        assert not warning_shown(app)


async def test_a_profile_with_a_forum_and_a_directory_keeps_only_what_can_be_selected() -> None:
    seed()
    app = DiscoopApp(api_factory=ForumDiscord().factory)
    async with app.run_test(size=(140, 40)) as pilot:
        await started(app, pilot)
        threads_row(app).action_step(1)  # Threads: no, so a loaded forum must raise the warning
        await pilot.pause()
        app._apply_profile("odd", {"channels": [HELP.id, HALL.id, STUDY.id, "999"], "from": "7d"})
        await pilot.pause()
        assert list(app.selection.selected) == [HELP.id]
        assert warning_shown(app)
