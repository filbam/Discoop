"""The dim suffix of a channel in the tree (time since the last message, date of the last export) and its helpers."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest
from rich.style import Style

from discoop import service
from discoop.api import DiscordAPI
from discoop.cache import Cache
from discoop.models import Channel, Server
from discoop.render import Query
from discoop.snowflake import Window, from_time
from discoop.tokenstore import TokenStore
from discoop.tui import app as tui_app
from discoop.tui.app import DiscoopApp
from discoop.tui.tuistate import format_activity, format_last_exported, save_user_state
from discoop.tui.widgets import ChannelTree
from test_tui_app import (
    _export_network,
    _export_to,
    _make_dummy_api_factory,
    _seed_export,
    _select,
    label_of,
    row_of,
    screen_text,
    started,
    wait_until,
)

CLUB = Server("1", "Club")


def ago(**delta: float) -> str:
    """A last_message_id of a message sent that long ago."""
    return str(from_time(datetime.now(UTC) - timedelta(**delta)))


def seed_club(*channels: Channel) -> None:
    TokenStore.default().save("fake-token")
    with Cache.default() as cache:
        cache.replace_servers([CLUB])
        cache.replace_channels(CLUB.id, list(channels))


def node_of(app: DiscoopApp, channel: Channel) -> Any:
    return app._tree_nodes[f"channel:{channel.id}"]


def tree_of(app: DiscoopApp) -> ChannelTree:
    return app.query_one("#channel-tree", ChannelTree)


async def open_club(app: DiscoopApp, pilot: Any) -> ChannelTree:
    await started(app, pilot)
    await pilot.press("right")  # the server opens: its channels are in the cache
    await pilot.pause()
    return tree_of(app)


def painted_rows(app: DiscoopApp) -> list[str]:
    return screen_text(app, tree_of(app).region).splitlines()


# ==================== Helpers ====================


def test_format_activity_short_and_long() -> None:
    now = datetime(2026, 11, 4, 12, 0, tzinfo=UTC)

    def flake(**delta: float) -> int:
        return from_time(now - timedelta(**delta))

    assert format_activity(flake(seconds=5), now) == "just now"
    assert format_activity(flake(seconds=5), now, short=True) == "now"
    assert format_activity(flake(minutes=12), now) == "12m ago"
    assert format_activity(flake(minutes=12), now, short=True) == "12m"
    assert format_activity(flake(hours=3), now, short=True) == "3h"
    assert format_activity(flake(days=2, hours=1), now, short=True) == "2d"
    assert format_activity(flake(days=45), now, short=True) == "1mo"
    assert format_activity(flake(days=45), now) == "1mo ago"
    assert format_activity(flake(days=800), now, short=True) == "2y"
    assert format_activity(flake(days=-3), now, short=True) == "now", "a clock that runs behind never shows a minus"


@pytest.mark.parametrize("days", [359, 360, 364])
def test_format_activity_never_says_zero_years(days: int) -> None:
    now = datetime(2026, 11, 4, 12, 0, tzinfo=UTC)
    flake = from_time(now - timedelta(days=days, hours=1))
    assert format_activity(flake, now) == "11mo ago"
    assert format_activity(flake, now, short=True) == "11mo"
    assert format_activity(from_time(now - timedelta(days=365, hours=1)), now, short=True) == "1y"


@pytest.mark.parametrize("bad", [None, "", "0", "-5", "abc", 0, "9" * 40])
def test_format_activity_ignores_a_missing_or_invalid_id(bad: Any) -> None:
    assert format_activity(bad, short=True) == ""
    assert format_activity(bad) == ""


def test_format_last_exported_short_is_a_date_in_the_given_zone() -> None:
    now = datetime(2026, 11, 4, 12, 0, tzinfo=UTC)
    stored = datetime(2026, 11, 3, 23, 30, tzinfo=UTC).isoformat()
    assert format_last_exported(stored, now, short=True, tz=UTC) == "exp 11-03"
    assert format_last_exported(stored, now, short=True, tz=timezone(timedelta(hours=2))) == "exp 11-04"
    last_year = datetime(2025, 11, 3, 12, 0, tzinfo=UTC).isoformat()
    assert format_last_exported(last_year, now, short=True, tz=UTC) == "exp 2025-11-03"
    assert format_last_exported(last_year, now, tz=UTC) == "exported 366d ago"
    assert format_last_exported("2026-11-03T12:00:00", now, short=True, tz=UTC) == "exp 11-03", "no zone means UTC"
    assert format_last_exported("not a time", now, short=True) == ""
    assert format_last_exported(None, now, short=True) == ""


# ==================== The suffix in the tree ====================


async def test_suffix_shows_the_activity_of_a_channel_that_has_one() -> None:
    active = Channel("11", CLUB.id, "active", 0, None, 0, last_message_id=ago(days=2, hours=1))
    quiet = Channel("12", CLUB.id, "quiet", 0, None, 1)
    seed_club(active, quiet)
    app = DiscoopApp(api_factory=_make_dummy_api_factory())
    async with app.run_test(size=(120, 40)) as pilot:
        tree = await open_club(app, pilot)

        assert tree.suffix_of(node_of(app, active)) == ("2d",)
        assert tree.suffix_of(node_of(app, quiet)) == ()
        assert row_of(tree, node_of(app, active)).startswith("[ ] #active"), "the name comes first"
        assert row_of(tree, node_of(app, active)).rstrip().endswith("2d")
        assert row_of(tree, node_of(app, quiet)).strip() == "[ ] #quiet", "nothing is shown without an ID"

        # The label stays the name of the node: the suffix is painted next to it, not part of it
        assert label_of(node_of(app, active)) == "[ ] #active"
        assert label_of(node_of(app, quiet)) == "[ ] #quiet"

        rows = painted_rows(app)
        assert any("#active" in row and row.rstrip().endswith("2d") for row in rows)
        assert [row.split("#quiet")[1].strip() for row in rows if "#quiet" in row] == [""]


async def test_suffix_is_dim_and_the_checkmark_stays() -> None:
    active = Channel("11", CLUB.id, "active", 0, None, 0, last_message_id=ago(hours=5, minutes=5))
    seed_club(active)
    app = DiscoopApp(api_factory=_make_dummy_api_factory())
    async with app.run_test(size=(120, 40)) as pilot:
        tree = await open_club(app, pilot)
        await pilot.press("down", "space")
        await pilot.pause()

        node = node_of(app, active)
        assert app.selection.is_selected(active.id)
        assert label_of(node) == "[x] #active"
        text = tree.render_label(node, Style(), Style())
        assert text.plain.startswith("[x] #active") and text.plain.rstrip().endswith("5h")
        assert text.spans[-1].style.dim, "the suffix is dim, like the badge of a server"
        assert text.plain[text.spans[-1].start : text.spans[-1].end] == "5h"


async def test_forum_and_voice_rows_get_a_suffix_but_a_category_does_not() -> None:
    category = Channel("10", CLUB.id, "talk", 4, None, 0, last_message_id=ago(days=1))
    text_channel = Channel("11", CLUB.id, "chat", 0, "10", 0, last_message_id=ago(days=3, hours=1))
    voice = Channel("12", CLUB.id, "lounge", 2, "10", 1, last_message_id=ago(days=4, hours=1))
    seed_club(category, text_channel, voice)
    app = DiscoopApp(api_factory=_make_dummy_api_factory())
    async with app.run_test(size=(120, 40)) as pilot:
        tree = await open_club(app, pilot)
        assert tree.suffix_of(app._tree_nodes[f"channel:{category.id}"]) == ()
        assert tree.suffix_of(node_of(app, text_channel)) == ("3d",)
        assert tree.suffix_of(node_of(app, voice)) == ("4d",)


async def test_suffix_ages_with_the_clock(monkeypatch: pytest.MonkeyPatch) -> None:
    active = Channel("11", CLUB.id, "active", 0, None, 0, last_message_id=ago(days=2, hours=1))
    seed_club(active)
    app = DiscoopApp(api_factory=_make_dummy_api_factory())
    async with app.run_test(size=(120, 40)) as pilot:
        tree = await open_club(app, pilot)
        assert tree.suffix_of(node_of(app, active)) == ("2d",)

        later = datetime.now(UTC) + timedelta(days=3)
        monkeypatch.setattr(tui_app, "utc_now", lambda: later)
        app._refresh_suffixes()
        await pilot.pause()
        assert tree.suffix_of(node_of(app, active)) == ("5d",)
        assert row_of(tree, node_of(app, active)).rstrip().endswith("5d")


async def test_suffix_survives_a_filter_and_a_rebuild() -> None:
    active = Channel("11", CLUB.id, "active", 0, None, 0, last_message_id=ago(days=2, hours=1))
    other = Channel("12", CLUB.id, "other", 0, None, 1, last_message_id=ago(days=9, hours=1))
    seed_club(active, other)
    app = DiscoopApp(api_factory=_make_dummy_api_factory())
    async with app.run_test(size=(120, 40)) as pilot:
        tree = await open_club(app, pilot)
        app.query_one("#tree-filter").value = "oth"
        await wait_until(pilot, lambda: f"channel:{active.id}" not in app._tree_nodes)
        assert tree.suffix_of(node_of(app, other)) == ("9d",)
        app.query_one("#tree-filter").value = ""
        await wait_until(pilot, lambda: f"channel:{active.id}" in app._tree_nodes)
        assert tree.suffix_of(node_of(app, active)) == ("2d",)
        assert tree.suffix_of(node_of(app, other)) == ("9d",)


# ==================== The export date ====================


async def test_export_date_appears_after_an_export(tmp_path: Path) -> None:
    server, first, second = _seed_export()
    first = Channel(first.id, first.server_id, first.name, 0, None, 0, last_message_id=ago(minutes=30))
    with Cache.default() as cache:
        cache.replace_channels(server.id, [first, second])
    _, transport = _export_network(6)

    def factory(token: str | None = None, **kw: Any) -> DiscordAPI:
        kw["delay"] = 0.0
        return DiscordAPI("fake-token", transport=transport, **kw)

    app = DiscoopApp(api_factory=factory)
    async with app.run_test(size=(140, 40)) as pilot:
        await started(app, pilot)
        await pilot.press("right")
        await pilot.pause()
        tree = tree_of(app)
        assert tree.suffix_of(node_of(app, first)) == ("30m",), "before an export: the activity only"
        assert tree.suffix_of(node_of(app, second)) == ()

        _select(app, server, first)
        _export_to(app, tmp_path / "out")
        await pilot.pause()
        await pilot.press("f5")
        await wait_until(pilot, lambda: app.cancel_token is None and first.id in app.last_exported)
        await pilot.pause()

        expected = format_last_exported(app.last_exported[first.id], short=True)
        assert expected.startswith("exp ")
        assert tree.suffix_of(node_of(app, first)) == ("30m", expected)
        assert row_of(tree, node_of(app, first)).rstrip().endswith(f"30m  {expected}")
        assert tree.suffix_of(node_of(app, second)) == (), "a channel that was not exported has no date"
        assert any(f"#general" in row and row.rstrip().endswith(expected) for row in painted_rows(app))


async def test_a_preview_is_not_an_export() -> None:
    channel = Channel("2", "1", "general", 0)
    result = service.ChannelMessages(Server("1", "Study Group"), channel, ())
    outcome = service.MessagesOutcome([result], [], None, Query(Window(None, datetime(2026, 11, 3, 11, 0, tzinfo=UTC))))
    app = DiscoopApp(api_factory=_make_dummy_api_factory())
    async with app.run_test(size=(140, 40)) as pilot:
        await started(app, pilot)
        app._export_finished([outcome], "md")  # shown on the screen only
        await pilot.pause()
        assert app.last_exported == {}
        await pilot.press("escape")
        await pilot.pause()

        app._export_finished([outcome], None)
        assert list(app.last_exported) == ["2"]


async def test_export_date_comes_back_with_the_saved_state() -> None:
    active = Channel("11", CLUB.id, "active", 0, None, 0, last_message_id=ago(days=2, hours=1))
    quiet = Channel("12", CLUB.id, "quiet", 0, None, 1)
    seed_club(active, quiet)
    exported = datetime.now(UTC) - timedelta(days=1)
    save_user_state(
        "42",
        {
            "selection": {active.id: {"server_id": CLUB.id, "custom_window": None}, "999": {"server_id": CLUB.id}},
            "last_exported": {quiet.id: exported.isoformat()},
        },
    )
    app = DiscoopApp(api_factory=_make_dummy_api_factory())
    async with app.run_test(size=(120, 40)) as pilot:
        tree = await open_club(app, pilot)
        await wait_until(pilot, lambda: bool(app.last_exported))
        assert app.current_user_id == "42"
        expected = format_last_exported(exported.isoformat(), short=True)

        assert app.selection.is_selected(active.id) and "999" not in app.selection.selected
        assert tree.suffix_of(node_of(app, active)) == ("2d",)
        assert tree.suffix_of(node_of(app, quiet)) == (expected,), "no activity, but it was exported"
        assert row_of(tree, node_of(app, quiet)).rstrip().endswith(expected)
        assert label_of(node_of(app, active)) == "[x] #active", "the restored selection shows too"


# ==================== Room: 80x24, a wide window and in between ====================

SIZES = [(40, 24), (80, 24), (96, 30), (120, 40), (160, 40)]


@pytest.mark.parametrize("size", SIZES, ids=lambda size: f"{size[0]}x{size[1]}")
async def test_names_stay_whole_and_the_suffix_gives_way(size: tuple[int, int]) -> None:
    """The export date goes first, then the activity, and only then does a name lose its end."""
    activity = ago(days=2, hours=1)
    stored = datetime.now(UTC) - timedelta(days=1)
    # An early guess at the width: names are made after measuring the real row below.
    seed_club(Channel("11", CLUB.id, "probe", 0, None, 0))
    app = DiscoopApp(api_factory=_make_dummy_api_factory())
    async with app.run_test(size=size) as pilot:
        tree = await open_club(app, pilot)
        width = len(row_of(tree, node_of(app, app.channels_by_server[CLUB.id][0])))
        assert width >= 20, "the tree has room for a row"
        both = "2d  " + format_last_exported(stored.isoformat(), short=True)  # '2d  exp 11-03'
        name_cells = len("[ ] #")

        def channel(number: int, cells: int, name: str) -> Channel:
            assert cells >= name_cells + 1
            return Channel(
                str(20 + number), CLUB.id, name + "x" * (cells - name_cells - len(name)), 0, None, number,
                last_message_id=activity,
            )

        # `cells` is the width of the whole label: '[ ] #name'
        fits_both = channel(0, width - len(both) - 2, "both-")
        fits_activity = channel(1, width - len(both) - 1, "activity-")  # one cell too wide for both
        fits_activity_tight = channel(2, width - 2 - 2, "tight-")  # exactly room for the activity
        fits_none = channel(3, width - 2 - 2 + 1, "none-")  # one cell too wide for any suffix
        full_row = channel(4, width, "full-")  # as wide as the row itself
        too_long = channel(5, width + 15, "long-")  # wider than the row: the end gives way
        channels = [fits_both, fits_activity, fits_activity_tight, fits_none, full_row, too_long]
        with Cache.default() as cache:
            cache.replace_channels(CLUB.id, channels)
        app.channels_by_server[CLUB.id] = channels
        app.last_exported.update({c.id: stored.isoformat() for c in channels})
        app._rebuild_tree()
        await pilot.pause()

        expect = {
            fits_both: ("2d", "exp"),
            fits_activity: ("2d",),
            fits_activity_tight: ("2d",),
            fits_none: (),
            full_row: (),
            too_long: (),
        }
        rows = painted_rows(app)
        for channel_, shown in expect.items():
            node = node_of(app, channel_)
            assert len(tree.suffix_of(node)) == 2, "the tree remembers both parts whatever it shows"
            row = row_of(tree, node)
            assert len(row) == width, "every row is exactly as wide as the tree: nothing wraps or scrolls"
            name = f"#{channel_.name}"
            if channel_ is too_long:
                assert row.rstrip().endswith("…") and "2d" not in row and "exp" not in row
                assert row.startswith("[ ] #long-")
                continue
            assert row.startswith(f"[ ] {name}"), "the name is whole"
            painted = [r for r in rows if name in r]
            assert len(painted) == 1, f"{name} is painted once, whole: {rows}"
            tail = row[len(f"[ ] {name}") :].strip()
            if shown == ("2d", "exp"):
                assert tail == both
            elif shown == ("2d",):
                assert tail == "2d"
            else:
                assert tail == ""
            assert painted[0].rstrip().endswith(tail or name)
        assert not tree.show_horizontal_scrollbar


async def test_help_explains_the_suffix() -> None:
    seed_club(Channel("11", CLUB.id, "active", 0, None, 0))
    app = DiscoopApp(api_factory=_make_dummy_api_factory())
    async with app.run_test(size=(140, 60)) as pilot:
        await started(app, pilot)
        await pilot.press("f1")
        await pilot.pause()
        guide = " ".join(str(app.screen.query_one("#help-content").content).split())
        assert "the time since its last message (2d)" in guide
        assert "the date of the last export (exp 11-03)" in guide
