"""Tests for the TUI update indicator, mount worker, cache semantics, and responsive top bar."""

from __future__ import annotations

import json
import threading
import time
from typing import Any

import httpx
import pytest
from textual.widgets import Input, Label, RichLog

import discoop
from discoop import update_check
from discoop.api import DiscordAPI
from discoop.cache import Cache
from discoop.config import Config
from discoop.models import Server
from discoop.tokenstore import TokenStore
from discoop.tui.app import DiscoopApp
from discoop.tui.modals import SettingsModal
from discoop.tui.widgets import ChannelTree, ChoiceRow
from discoop.update_check import (
    STATUS_DISABLED,
    STATUS_ERROR,
    STATUS_NO_RELEASE,
    STATUS_UP_TO_DATE,
    STATUS_UPDATE_AVAILABLE,
    CheckResult,
    UpdateInfo,
    format_tui_log_message,
    update_cache_path,
)
from test_tui_app import RecordingDiscord, _make_dummy_api_factory, screen_text, started, visible_rows, wait_until

SAMPLE_URL = "https://github.com/filbam/Discoop/releases/tag/v99.0.0"


def _sample_info(latest: str = "99.0.0", current: str = "1.0.0") -> UpdateInfo:
    return UpdateInfo(latest_version=latest, current_version=current, url=SAMPLE_URL)


def _normalized_log_text(app: DiscoopApp) -> str:
    raw = " ".join(strip.text for strip in app.query_one("#event-log", RichLog).lines)
    return " ".join(raw.split())


def _update_worker_done(app: DiscoopApp) -> bool:
    return not any(w.group == "update" for w in app.workers)


def _release_transport(
    tag_name: str = "v99.0.0",
    *,
    calls: list[httpx.Request] | None = None,
) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        if calls is not None:
            calls.append(request)
        return httpx.Response(
            200,
            json={
                "tag_name": tag_name,
                "html_url": f"https://github.com/filbam/Discoop/releases/tag/{tag_name}",
            },
        )

    return httpx.MockTransport(handler)


async def test_update_indicator_order_and_initial_hidden_state() -> None:
    gate = threading.Event()
    called = threading.Event()

    def blocked_check() -> CheckResult:
        called.set()
        gate.wait(10)
        return CheckResult(status=STATUS_UP_TO_DATE, latest_version=discoop.__version__)

    app = DiscoopApp(api_factory=_make_dummy_api_factory(), update_check_fn=blocked_check)
    try:
        async with app.run_test(size=(140, 40)) as pilot:
            await started(app, pilot)
            await wait_until(pilot, called.is_set)

            top_bar_children = [widget.id for widget in app.query("#top-bar > Label")]
            assert top_bar_children == [
                "app-title",
                "status-indicator",
                "mode-indicator",
                "update-indicator",
                "help-hint",
            ]
            indicator = app.query_one("#update-indicator", Label)
            assert indicator.display is False
            assert "↑" not in screen_text(app, app.query_one("#top-bar").region)

            gate.set()
            await wait_until(pilot, lambda: _update_worker_done(app))
            assert indicator.display is False
    finally:
        gate.set()


@pytest.mark.parametrize(
    "result",
    [
        CheckResult(status=STATUS_UP_TO_DATE, latest_version="1.0.0"),
        CheckResult(status=STATUS_NO_RELEASE),
        CheckResult(status=STATUS_DISABLED),
        CheckResult(status=STATUS_ERROR, error="network error"),
        CheckResult(status=STATUS_UPDATE_AVAILABLE, update=None),
    ],
)
async def test_update_indicator_stays_hidden_for_non_update_results(result: CheckResult) -> None:
    done = threading.Event()

    def check() -> CheckResult:
        done.set()
        return result

    app = DiscoopApp(api_factory=_make_dummy_api_factory(), update_check_fn=check)
    async with app.run_test(size=(140, 40)) as pilot:
        await started(app, pilot)
        await wait_until(pilot, done.is_set)
        await wait_until(pilot, lambda: _update_worker_done(app))

        indicator = app.query_one("#update-indicator", Label)
        assert indicator.display is False
        assert "New release" not in _normalized_log_text(app)


async def test_update_worker_exception_does_not_crash_app() -> None:
    attempted = threading.Event()

    def failing_check() -> CheckResult:
        attempted.set()
        raise RuntimeError("unexpected failure")

    app = DiscoopApp(api_factory=_make_dummy_api_factory(), update_check_fn=failing_check)
    async with app.run_test(size=(140, 40)) as pilot:
        await started(app, pilot)
        await wait_until(pilot, attempted.is_set)
        await wait_until(pilot, lambda: _update_worker_done(app))

        assert app.is_running
        assert app.query_one("#update-indicator", Label).display is False
        assert "New release" not in _normalized_log_text(app)


async def test_update_available_shows_warning_indicator_and_logs_once() -> None:
    info = _sample_info(latest="99.1.0", current="1.0.0")
    app = DiscoopApp(
        api_factory=_make_dummy_api_factory(),
        update_check_fn=lambda: CheckResult(status=STATUS_UPDATE_AVAILABLE, update=info),
    )
    async with app.run_test(size=(140, 40)) as pilot:
        await started(app, pilot)
        indicator = app.query_one("#update-indicator", Label)
        await wait_until(
            pilot,
            lambda: indicator.display and "↑ 99.1.0" in screen_text(app, app.query_one("#top-bar").region),
        )

        assert str(indicator.content) == "↑ 99.1.0"
        assert indicator.styles.color == app.query_one("#threads-warning", Label).styles.color

        expected_msg = format_tui_log_message(info)
        await wait_until(pilot, lambda: expected_msg in _normalized_log_text(app))
        assert _normalized_log_text(app).count("New release ") == 1

        # Calling the UI handler again in the same session does not duplicate the log line.
        app._apply_update_available(_sample_info(latest="99.2.0", current="1.0.0"))
        await wait_until(pilot, lambda: str(indicator.content) == "↑ 99.2.0")
        assert _normalized_log_text(app).count("New release ") == 1


async def test_update_log_and_indicator_escape_rich_markup_brackets() -> None:
    info = UpdateInfo(
        latest_version="99.0.0-[rc1]",
        current_version="1.0.0",
        url="https://github.com/filbam/Discoop/releases/tag/v99.0.0?[x]=1&[bold]",
    )
    app = DiscoopApp(
        api_factory=_make_dummy_api_factory(),
        update_check_fn=lambda: CheckResult(status=STATUS_UPDATE_AVAILABLE, update=info),
    )
    async with app.run_test(size=(140, 40)) as pilot:
        await started(app, pilot)
        indicator = app.query_one("#update-indicator", Label)
        expected_msg = format_tui_log_message(info)
        await wait_until(
            pilot,
            lambda: indicator.display and expected_msg in _normalized_log_text(app) and _update_worker_done(app),
        )

        assert app.is_running
        assert str(indicator.content) == "↑ 99.0.0-[rc1]"
        assert expected_msg in _normalized_log_text(app)


async def test_tui_end_to_end_live_fetch_and_never_writes_notified_at(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DISCOOP_NO_UPDATE_NOTIFIER", raising=False)
    monkeypatch.setenv("CI", "1")  # CI suppresses CLI notice only, not TUI
    calls: list[httpx.Request] = []
    transport = _release_transport("v99.0.0", calls=calls)
    real_check = update_check.check_for_update
    monkeypatch.setattr(update_check, "check_for_update", lambda **kw: real_check(transport=transport, **kw))

    app = DiscoopApp(api_factory=_make_dummy_api_factory())
    async with app.run_test(size=(140, 40)) as pilot:
        await started(app, pilot)
        indicator = app.query_one("#update-indicator", Label)
        expected_msg = format_tui_log_message(UpdateInfo("99.0.0", discoop.__version__, SAMPLE_URL))
        await wait_until(
            pilot,
            lambda: indicator.display and expected_msg in _normalized_log_text(app) and _update_worker_done(app),
        )

        assert len(calls) == 1
        assert str(indicator.content) == "↑ 99.0.0"

    cache_data = json.loads(update_cache_path().read_text(encoding="utf-8"))
    assert cache_data["latest_version"] == "99.0.0"
    assert cache_data["notified_at"] is None


@pytest.mark.parametrize("failure_mode", ["404", "network_error"])
async def test_tui_end_to_end_404_and_network_error_stay_silent(
    monkeypatch: pytest.MonkeyPatch,
    failure_mode: str,
) -> None:
    monkeypatch.delenv("DISCOOP_NO_UPDATE_NOTIFIER", raising=False)
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if failure_mode == "404":
            return httpx.Response(404, json={"message": "Not Found"})
        raise httpx.ConnectError("offline", request=request)

    transport = httpx.MockTransport(handler)
    real_check = update_check.check_for_update
    monkeypatch.setattr(update_check, "check_for_update", lambda **kw: real_check(transport=transport, **kw))

    app = DiscoopApp(api_factory=_make_dummy_api_factory())
    async with app.run_test(size=(140, 40)) as pilot:
        await started(app, pilot)
        await wait_until(pilot, lambda: _update_worker_done(app))

        assert app.is_running
        assert len(calls) == 1
        assert app.query_one("#update-indicator", Label).display is False
        assert "New release" not in _normalized_log_text(app)

    cache_data = json.loads(update_cache_path().read_text(encoding="utf-8"))
    assert cache_data["latest_version"] is None
    assert cache_data["notified_at"] is None
    if failure_mode == "404":
        assert cache_data["checked_at"] is not None
        assert cache_data["failed_at"] is None
    else:
        assert cache_data["failed_at"] is not None


async def test_tui_ignores_recent_notified_at_and_preserves_it(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DISCOOP_NO_UPDATE_NOTIFIER", raising=False)
    now = time.time()
    recent_notified = now - 5.0
    cache_file = update_cache_path()
    cache_file.parent.mkdir(parents=True, exist_ok=True)
    cache_file.write_text(
        json.dumps(
            {
                "checked_at": now - 60.0,
                "latest_version": "99.0.0",
                "latest_url": SAMPLE_URL,
                "failed_at": None,
                "notified_at": recent_notified,
            }
        ),
        encoding="utf-8",
    )

    calls: list[httpx.Request] = []
    transport = _release_transport("v99.0.0", calls=calls)
    real_check = update_check.check_for_update
    monkeypatch.setattr(update_check, "check_for_update", lambda **kw: real_check(transport=transport, **kw))

    app = DiscoopApp(api_factory=_make_dummy_api_factory())
    async with app.run_test(size=(140, 40)) as pilot:
        await started(app, pilot)
        indicator = app.query_one("#update-indicator", Label)
        expected_msg = format_tui_log_message(UpdateInfo("99.0.0", discoop.__version__, SAMPLE_URL))
        await wait_until(
            pilot,
            lambda: indicator.display and expected_msg in _normalized_log_text(app) and _update_worker_done(app),
        )

        assert calls == [], "fresh cache must avoid HTTP request"
        assert str(indicator.content) == "↑ 99.0.0"

    after = json.loads(cache_file.read_text(encoding="utf-8"))
    assert after["notified_at"] == pytest.approx(recent_notified)


async def test_tui_honors_off_switches(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[httpx.Request] = []
    observed: list[CheckResult] = []
    transport = _release_transport("v99.0.0", calls=calls)
    real_check = update_check.check_for_update

    def tracked_check(**kw: Any) -> CheckResult:
        res = real_check(transport=transport, **kw)
        observed.append(res)
        return res

    monkeypatch.setattr(update_check, "check_for_update", tracked_check)

    # 1. Default isolated_env has DISCOOP_NO_UPDATE_NOTIFIER=1
    app_env_off = DiscoopApp(api_factory=_make_dummy_api_factory())
    async with app_env_off.run_test(size=(140, 40)) as pilot:
        await started(app_env_off, pilot)
        await wait_until(pilot, lambda: len(observed) == 1 and _update_worker_done(app_env_off))
        assert observed == [CheckResult(status=STATUS_DISABLED)]
        assert calls == []
        assert app_env_off.query_one("#update-indicator", Label).display is False

    # 2. Env var unset, but config update-check = off
    observed.clear()
    monkeypatch.delenv("DISCOOP_NO_UPDATE_NOTIFIER", raising=False)
    Config.default().set("update-check", "off")
    app_cfg_off = DiscoopApp(api_factory=_make_dummy_api_factory())
    async with app_cfg_off.run_test(size=(140, 40)) as pilot:
        await started(app_cfg_off, pilot)
        await wait_until(pilot, lambda: len(observed) == 1 and _update_worker_done(app_cfg_off))
        assert observed == [CheckResult(status=STATUS_DISABLED)]
        assert calls == []
        assert app_cfg_off.query_one("#update-indicator", Label).display is False


async def test_update_worker_isolated_from_net_group_and_discord_refresh() -> None:
    with Cache.default() as cache:
        cache.replace_servers([Server("1000", "Alpha Server", 10)])
    TokenStore.default().save("fake-token")
    discord = RecordingDiscord()
    gate = threading.Event()
    started_update = threading.Event()
    info = _sample_info("99.0.0", "1.0.0")

    def slow_update() -> CheckResult:
        started_update.set()
        gate.wait(10)
        return CheckResult(status=STATUS_UPDATE_AVAILABLE, update=info)

    app = DiscoopApp(api_factory=discord.factory, update_check_fn=slow_update)
    try:
        async with app.run_test(size=(140, 40)) as pilot:
            # Directory loading finishes while update worker is still waiting.
            await started(app, pilot)
            await wait_until(pilot, started_update.is_set)

            update_workers = [w for w in app.workers if w.group == "update"]
            assert len(update_workers) == 1
            assert update_workers[0].is_running
            assert update_workers[0].group != "net"
            assert visible_rows(app.query_one("#channel-tree", ChannelTree)) == ["Alpha Server"]

            # Refreshing servers (net group) does not block on or cancel the update worker.
            await pilot.press("R")
            await wait_until(
                pilot,
                lambda: app.cancel_token is None
                and visible_rows(app.query_one("#channel-tree", ChannelTree))
                == ["Alpha Server", "Beta Server", "Gamma Server"],
            )
            assert update_workers[0].is_running
            assert not update_workers[0].is_cancelled

            gate.set()
            indicator = app.query_one("#update-indicator", Label)
            await wait_until(pilot, lambda: indicator.display and _update_worker_done(app))
            assert str(indicator.content) == "↑ 99.0.0"
    finally:
        gate.set()


async def test_quit_does_not_hang_while_update_worker_is_pending() -> None:
    gate = threading.Event()
    entered = threading.Event()

    def slow_update() -> CheckResult:
        entered.set()
        gate.wait(10)
        return CheckResult(status=STATUS_UPDATE_AVAILABLE, update=_sample_info())

    app = DiscoopApp(api_factory=_make_dummy_api_factory(), update_check_fn=slow_update)
    t0 = time.monotonic()
    try:
        async with app.run_test(size=(140, 40)) as pilot:
            await started(app, pilot)
            await wait_until(pilot, entered.is_set)
            await pilot.press("q")
            await wait_until(pilot, lambda: app._exit)
    finally:
        gate.set()
    assert time.monotonic() - t0 < 2.0


async def test_late_update_ui_call_after_close_is_harmless() -> None:
    app = DiscoopApp(
        api_factory=_make_dummy_api_factory(),
        update_check_fn=lambda: CheckResult(status=STATUS_DISABLED),
    )
    async with app.run_test(size=(140, 40)) as pilot:
        await started(app, pilot)
        await wait_until(pilot, lambda: _update_worker_done(app))
    app._apply_update_available(_sample_info())


async def test_settings_modal_preserves_update_check_in_config() -> None:
    Config.default().set("update-check", "off")
    app = DiscoopApp(
        api_factory=_make_dummy_api_factory(),
        update_check_fn=lambda: CheckResult(status=STATUS_UPDATE_AVAILABLE, update=_sample_info()),
    )
    async with app.run_test(size=(140, 40)) as pilot:
        await started(app, pilot)
        indicator = app.query_one("#update-indicator", Label)
        await wait_until(pilot, lambda: indicator.display and _update_worker_done(app))

        await pilot.press("f2")
        await wait_until(pilot, lambda: isinstance(app.screen, SettingsModal))
        modal = app.screen
        await pilot.press("left")  # mode -> fast
        delay_input = modal.query_one("#input-cfg-delay", Input)
        delay_input.focus()
        await wait_until(pilot, lambda: app.focused is delay_input)
        await pilot.press("enter")
        await wait_until(pilot, lambda: not isinstance(app.screen, SettingsModal))

        config = Config.default()
        assert config.get("mode") == "fast"
        assert config.get("update-check") == "off"
        assert str(app.query_one("#mode-indicator", Label).content) == "fast"
        assert indicator.display is True
        assert str(indicator.content) == "↑ 99.0.0"


def _make_user_api_factory(username: str):
    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path.removeprefix("/api/v9")
        if path == "/users/@me":
            return httpx.Response(200, json={"id": "42", "username": username})
        if path == "/users/@me/guilds":
            return httpx.Response(200, json=[])
        return httpx.Response(404, json={"message": "Not Found"})

    def api_factory(token: str | None = None, **kw: Any) -> DiscordAPI:
        kw["delay"] = 0.0
        return DiscordAPI("fake-token", transport=httpx.MockTransport(handler), **kw)

    return api_factory


def _assert_top_bar_layout(
    app: DiscoopApp,
    size: tuple[int, int],
    *,
    show_update: bool,
    mode: str,
    version_text: str = "10.20.30",
) -> None:
    top_bar = app.query_one("#top-bar")
    assert top_bar.region.x == 0
    assert top_bar.region.y == 0
    assert top_bar.region.width == size[0]
    assert top_bar.region.height == 1

    visible_children = [w for w in app.query("#top-bar > Label") if w.display]
    expected_ids = ["app-title", "status-indicator", "mode-indicator"]
    if show_update:
        expected_ids.append("update-indicator")
    expected_ids.append("help-hint")
    assert [w.id for w in visible_children] == expected_ids

    for prev, curr in zip(visible_children, visible_children[1:]):
        assert prev.region.right <= curr.region.x, f"{prev.id} overlaps {curr.id} at {size}"

    for widget in visible_children:
        assert widget.region.height == 1, widget
        assert widget.region.width >= 1, widget
        assert widget.region.x >= top_bar.region.x, widget
        assert widget.region.right <= top_bar.region.right, widget
        assert screen_text(app, widget.region).strip(), widget

    top_text = screen_text(app, top_bar.region)
    assert "discoop" in top_text
    assert mode in top_text
    assert "F1 help" in top_text
    if show_update:
        assert f"↑ {version_text}" in top_text
    else:
        assert "↑" not in top_text


@pytest.mark.parametrize("size", [(75, 28), (80, 24), (140, 40)], ids=lambda s: f"{s[0]}x{s[1]}")
@pytest.mark.parametrize("show_update", [False, True], ids=["hidden", "visible"])
@pytest.mark.parametrize("username", ["student_a", "a_very_long_discord_username_32c"], ids=["short_user", "long_user"])
async def test_top_bar_responsive_layout(
    size: tuple[int, int],
    show_update: bool,
    username: str,
) -> None:
    TokenStore.default().save("fake-token")
    result = (
        CheckResult(status=STATUS_UPDATE_AVAILABLE, update=_sample_info("10.20.30", "1.0.0"))
        if show_update
        else CheckResult(status=STATUS_UP_TO_DATE, latest_version="1.0.0")
    )
    app = DiscoopApp(api_factory=_make_user_api_factory(username), update_check_fn=lambda: result)
    async with app.run_test(size=size) as pilot:
        await started(app, pilot)
        indicator = app.query_one("#update-indicator", Label)
        if show_update:
            await wait_until(
                pilot,
                lambda: indicator.display
                and "↑ 10.20.30" in screen_text(app, app.query_one("#top-bar").region)
                and _update_worker_done(app),
            )
        else:
            await wait_until(pilot, lambda: _update_worker_done(app))
            assert indicator.display is False

        _assert_top_bar_layout(app, size, show_update=show_update, mode="safe")


@pytest.mark.parametrize("size", [(75, 28), (80, 24), (140, 40)], ids=lambda s: f"{s[0]}x{s[1]}")
async def test_top_bar_fast_mode_with_update_indicator_responsive(size: tuple[int, int]) -> None:
    TokenStore.default().save("fake-token")
    result = CheckResult(status=STATUS_UPDATE_AVAILABLE, update=_sample_info("10.20.30", "1.0.0"))
    app = DiscoopApp(
        api_factory=_make_user_api_factory("a_very_long_discord_username_32c"),
        update_check_fn=lambda: result,
    )
    async with app.run_test(size=size) as pilot:
        await started(app, pilot)
        indicator = app.query_one("#update-indicator", Label)
        mode_indicator = app.query_one("#mode-indicator", Label)
        await wait_until(
            pilot,
            lambda: indicator.display
            and "↑ 10.20.30" in screen_text(app, app.query_one("#top-bar").region)
            and _update_worker_done(app),
        )

        # Switch to fast mode at runtime while #update-indicator is visible.
        await pilot.press("2")
        row_mode = app.query_one("#row-mode", ChoiceRow)
        row_mode.focus()
        await wait_until(pilot, lambda: app.focused is row_mode)
        await pilot.press("right")
        await wait_until(
            pilot,
            lambda: str(mode_indicator.content) == "fast"
            and mode_indicator.has_class("-fast")
            and "fast" in screen_text(app, app.query_one("#top-bar").region),
        )

        assert mode_indicator.styles.color == indicator.styles.color
        _assert_top_bar_layout(app, size, show_update=True, mode="fast")
