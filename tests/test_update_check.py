"""Offline tests for discoop.update_check."""

from __future__ import annotations

import json
import logging
import threading
import time
from pathlib import Path
from typing import Any

import httpx
import pytest

import discoop
from discoop import paths, update_check
from discoop.config import Config


@pytest.fixture
def notifier_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Enable the update notifier by clearing the suite-wide disable env vars."""
    monkeypatch.delenv("DISCOOP_NO_UPDATE_NOTIFIER", raising=False)
    monkeypatch.delenv("CI", raising=False)


def _json_transport(
    handler_or_status: Any,
    payload: Any = None,
    *,
    calls: list[httpx.Request] | None = None,
) -> httpx.MockTransport:
    def _handle(request: httpx.Request) -> httpx.Response:
        if calls is not None:
            calls.append(request)
        if callable(handler_or_status):
            return handler_or_status(request)
        if payload is None:
            return httpx.Response(handler_or_status)
        return httpx.Response(handler_or_status, json=payload)

    return httpx.MockTransport(_handle)


def _read_cache_json() -> dict[str, Any]:
    return json.loads((paths.data_dir() / "update-check.json").read_text(encoding="utf-8"))


def _write_cache_json(data: dict[str, Any]) -> Path:
    path = paths.data_dir() / "update-check.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def test_suite_default_env_disables_notifier() -> None:
    calls: list[httpx.Request] = []
    result = update_check.check_for_update(transport=_json_transport(200, {"tag_name": "v99.0.0"}, calls=calls))
    assert result.status == update_check.STATUS_DISABLED
    assert result.update is None
    assert calls == []


@pytest.mark.parametrize(
    ("tag_name", "html_url", "current", "expected_version", "expected_url"),
    [
        (
            "v1.5.0",
            "https://github.com/filbam/Discoop/releases/tag/v1.5.0",
            "1.4.0",
            "1.5.0",
            "https://github.com/filbam/Discoop/releases/tag/v1.5.0",
        ),
        (
            "2.1.0",
            None,
            "2.0.0",
            "2.1.0",
            "https://github.com/filbam/Discoop/releases/tag/2.1.0",
        ),
        (
            "v2.0.10",
            "https://evil.example/releases/tag/v2.0.10",
            "2.0.9",
            "2.0.10",
            "https://github.com/filbam/Discoop/releases/tag/v2.0.10",
        ),
    ],
)
def test_newer_release_and_url_validation(
    notifier_env: None,
    tag_name: str,
    html_url: str | None,
    current: str,
    expected_version: str,
    expected_url: str,
) -> None:
    payload: dict[str, Any] = {"tag_name": tag_name}
    if html_url is not None:
        payload["html_url"] = html_url

    result = update_check.check_for_update(
        transport=_json_transport(200, payload),
        now=1000.0,
        current_version=current,
    )
    assert result.status == update_check.STATUS_UPDATE_AVAILABLE
    assert result.update == update_check.UpdateInfo(
        latest_version=expected_version,
        current_version=current,
        url=expected_url,
    )
    assert result.latest_version == expected_version
    assert result.latest_url == expected_url
    assert result.error is None

    cached = _read_cache_json()
    assert cached == {
        "checked_at": 1000.0,
        "latest_version": expected_version,
        "latest_url": expected_url,
        "failed_at": None,
        "notified_at": None,
    }


@pytest.mark.parametrize(("tag_name", "current"), [("v1.2.3", "1.2.3"), ("v1.2.2", "1.2.3"), ("0.9.9", "1.2.3")])
def test_same_or_older_release_is_up_to_date(notifier_env: None, tag_name: str, current: str) -> None:
    result = update_check.check_for_update(
        transport=_json_transport(
            200,
            {"tag_name": tag_name, "html_url": f"https://github.com/filbam/Discoop/releases/tag/{tag_name}"},
        ),
        now=2000.0,
        current_version=current,
    )
    assert result.status == update_check.STATUS_UP_TO_DATE
    assert result.update is None
    assert result.latest_version is not None
    assert result.error is None


def test_unknown_current_version_never_notifies(notifier_env: None) -> None:
    transport = _json_transport(
        200,
        {"tag_name": "v9.9.9", "html_url": "https://github.com/filbam/Discoop/releases/tag/v9.9.9"},
    )
    result = update_check.check_for_update(transport=transport, now=3000.0, current_version="0+unknown")
    assert result.status == update_check.STATUS_UP_TO_DATE
    assert result.update is None
    assert result.latest_version == "9.9.9"
    assert update_check.format_doctor_detail(result) == "up to date (latest 9.9.9)"

    handle = update_check.start_background_check(transport=transport, now=3000.0, current_version="0+unknown")
    assert not handle.started_thread
    assert handle.wait() is None


def test_404_means_no_release_yet_and_clears_previous_failed_at(notifier_env: None) -> None:
    _write_cache_json(
        {
            "checked_at": 100.0,
            "latest_version": "1.2.0",
            "latest_url": "https://github.com/filbam/Discoop/releases/tag/v1.2.0",
            "failed_at": 200.0,
            "notified_at": 150.0,
        }
    )
    result = update_check.check_for_update(
        force=True,
        transport=_json_transport(404, {"message": "Not Found"}),
        now=5000.0,
        current_version="1.2.0",
    )
    assert result.status == update_check.STATUS_NO_RELEASE
    assert result.update is None
    assert result.latest_version is None
    assert result.latest_url is None
    assert result.error is None
    assert update_check.format_doctor_detail(result) == "no release published yet"

    cached = _read_cache_json()
    assert cached == {
        "checked_at": 5000.0,
        "latest_version": None,
        "latest_url": None,
        "failed_at": None,
        "notified_at": 150.0,
    }


@pytest.mark.parametrize(
    "handler",
    [
        lambda _req: httpx.Response(500, json={"message": "Server Error"}),
        lambda _req: (_ for _ in ()).throw(httpx.ReadTimeout("timed out")),
        lambda _req: (_ for _ in ()).throw(httpx.ConnectError("offline")),
        lambda _req: httpx.Response(200, content=b"{not-json"),
        lambda _req: httpx.Response(200, json=["not", "a", "dict"]),
        lambda _req: httpx.Response(200, json={"html_url": "https://github.com/filbam/Discoop/releases"}),
        lambda _req: httpx.Response(200, json={"tag_name": "nightly"}),
        lambda _req: httpx.Response(200, json={"tag_name": "v1.2.0-rc1"}),
        lambda _req: httpx.Response(200, json={"tag_name": "v1.2"}),
        lambda _req: httpx.Response(200, json={"tag_name": "v²1.0.0"}),
        lambda _req: httpx.Response(200, json={"tag_name": "v١.٢.٣"}),
    ],
)
def test_errors_and_bad_responses_debug_log_and_preserve_cache(
    notifier_env: None,
    caplog: pytest.LogCaptureFixture,
    capsys: pytest.CaptureFixture[str],
    handler: Any,
) -> None:
    _write_cache_json(
        {
            "checked_at": 100.0,
            "latest_version": "2.0.0",
            "latest_url": "https://github.com/filbam/Discoop/releases/tag/v2.0.0",
            "failed_at": None,
            "notified_at": 150.0,
        }
    )
    caplog.set_level(logging.DEBUG, logger="discoop.update_check")
    now = 100.0 + update_check.CHECK_INTERVAL

    # Forced check (doctor) returns error and does not fall back to stale cache.
    result = update_check.check_for_update(
        force=True,
        transport=httpx.MockTransport(handler),
        now=now,
        current_version="1.5.0",
    )
    assert result.status == update_check.STATUS_ERROR
    assert result.update is None
    assert result.latest_version is None
    assert result.error
    assert caplog.records
    assert all(r.levelno == logging.DEBUG for r in caplog.records)

    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == ""

    cached = _read_cache_json()
    assert cached == {
        "checked_at": 100.0,
        "latest_version": "2.0.0",
        "latest_url": "https://github.com/filbam/Discoop/releases/tag/v2.0.0",
        "failed_at": now,
        "notified_at": 150.0,
    }


def test_cache_freshness_and_expiration(notifier_env: None) -> None:
    calls: list[httpx.Request] = []
    transport = _json_transport(
        200,
        {"tag_name": "v2.0.0", "html_url": "https://github.com/filbam/Discoop/releases/tag/v2.0.0"},
        calls=calls,
    )

    first = update_check.check_for_update(transport=transport, now=1000.0, current_version="1.5.0")
    assert first.status == update_check.STATUS_UPDATE_AVAILABLE
    assert len(calls) == 1

    # Within 24h -> cache hit, no network call.
    second = update_check.check_for_update(
        transport=transport,
        now=1000.0 + update_check.CHECK_INTERVAL - 1.0,
        current_version="1.5.0",
    )
    assert second == first
    assert len(calls) == 1

    # At >= 24h -> cache expired, fetches again.
    third = update_check.check_for_update(
        transport=transport,
        now=1000.0 + update_check.CHECK_INTERVAL,
        current_version="1.5.0",
    )
    assert third.status == update_check.STATUS_UPDATE_AVAILABLE
    assert len(calls) == 2


def test_fresh_404_cache_returns_no_release_without_network(notifier_env: None) -> None:
    calls: list[httpx.Request] = []
    transport = _json_transport(404, calls=calls)

    first = update_check.check_for_update(transport=transport, now=1000.0, current_version="1.5.0")
    assert first.status == update_check.STATUS_NO_RELEASE
    assert len(calls) == 1

    second = update_check.check_for_update(transport=transport, now=2000.0, current_version="1.5.0")
    assert second.status == update_check.STATUS_NO_RELEASE
    assert len(calls) == 1


def test_failure_backoff_and_recovery(notifier_env: None) -> None:
    calls: list[httpx.Request] = []
    status_to_return = 500

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if status_to_return == 200:
            return httpx.Response(
                200,
                json={"tag_name": "v2.2.0", "html_url": "https://github.com/filbam/Discoop/releases/tag/v2.2.0"},
            )
        return httpx.Response(status_to_return)

    transport = httpx.MockTransport(handler)
    _write_cache_json(
        {
            "checked_at": 0.0,
            "latest_version": "2.0.0",
            "latest_url": "https://github.com/filbam/Discoop/releases/tag/v2.0.0",
            "failed_at": None,
            "notified_at": None,
        }
    )

    fail_time = update_check.CHECK_INTERVAL + 10.0
    # Fails at fail_time, preserves cached 2.0.0 for non-forced callers.
    res1 = update_check.check_for_update(transport=transport, now=fail_time, current_version="1.5.0")
    assert len(calls) == 1
    assert res1.status == update_check.STATUS_UPDATE_AVAILABLE
    assert res1.update is not None and res1.update.latest_version == "2.0.0"

    # Within 1h backoff -> no network call, still uses cached 2.0.0.
    res2 = update_check.check_for_update(
        transport=transport,
        now=fail_time + update_check.FAILURE_BACKOFF - 1.0,
        current_version="1.5.0",
    )
    assert len(calls) == 1
    assert res2.status == update_check.STATUS_UPDATE_AVAILABLE
    assert res2.update is not None and res2.update.latest_version == "2.0.0"

    # At >= 1h backoff -> retries and clears failed_at on success.
    status_to_return = 200
    retry_time = fail_time + update_check.FAILURE_BACKOFF
    res3 = update_check.check_for_update(transport=transport, now=retry_time, current_version="1.5.0")
    assert len(calls) == 2
    assert res3.status == update_check.STATUS_UPDATE_AVAILABLE
    assert res3.update is not None and res3.update.latest_version == "2.2.0"
    cached = _read_cache_json()
    assert cached["checked_at"] == retry_time
    assert cached["failed_at"] is None


def test_backoff_with_empty_cache_returns_error_without_network(notifier_env: None) -> None:
    calls: list[httpx.Request] = []
    fail_transport = _json_transport(503, calls=calls)

    res1 = update_check.check_for_update(transport=fail_transport, now=1000.0, current_version="1.5.0")
    assert res1.status == update_check.STATUS_ERROR
    assert len(calls) == 1

    res2 = update_check.check_for_update(
        transport=fail_transport,
        now=1000.0 + update_check.FAILURE_BACKOFF - 1.0,
        current_version="1.5.0",
    )
    assert res2.status == update_check.STATUS_ERROR
    assert len(calls) == 1


@pytest.mark.parametrize("bad_content", ["{corrupt", "[1, 2, 3]", '{"checked_at": true, "latest_version": 42}'])
def test_corrupt_cache_counts_as_empty_without_raising(
    notifier_env: None,
    caplog: pytest.LogCaptureFixture,
    bad_content: str,
) -> None:
    cache_file = paths.data_dir() / "update-check.json"
    cache_file.parent.mkdir(parents=True, exist_ok=True)
    cache_file.write_text(bad_content, encoding="utf-8")

    caplog.set_level(logging.DEBUG, logger="discoop.update_check")
    loaded = update_check.load_cache(cache_file)
    assert loaded.checked_at is None
    assert loaded.latest_version is None

    result = update_check.check_for_update(
        transport=_json_transport(200, {"tag_name": "v3.0.0"}),
        now=5000.0,
        current_version="1.5.0",
    )
    assert result.status == update_check.STATUS_UPDATE_AVAILABLE
    assert result.update is not None and result.update.latest_version == "3.0.0"


def test_unwritable_cache_does_not_raise(
    notifier_env: None,
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    blocker = tmp_path / "not-a-dir"
    blocker.write_text("file", encoding="utf-8")
    caplog.set_level(logging.DEBUG, logger="discoop.update_check")

    result = update_check.check_for_update(
        transport=_json_transport(200, {"tag_name": "v3.0.0"}),
        now=5000.0,
        cache_path=blocker / "update-check.json",
        current_version="1.5.0",
    )
    assert result.status == update_check.STATUS_UPDATE_AVAILABLE
    assert any("Could not write update cache" in rec.message for rec in caplog.records)


def test_atomic_write_creates_parents_and_reuses_replace_file(
    notifier_env: None,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    calls: list[tuple[Path, Path]] = []
    real_replace = update_check.replace_file

    def tracked_replace(source: Path | str, target: Path | str, **kwargs: Any) -> None:
        src_path = Path(source)
        dst_path = Path(target)
        calls.append((src_path, dst_path))
        assert src_path.parent == dst_path.parent
        assert src_path.name.startswith("update-check.") and src_path.name.endswith(".tmp")
        real_replace(source, target, **kwargs)

    monkeypatch.setattr(update_check, "replace_file", tracked_replace)

    nested_cache = tmp_path / "nested" / "subdir" / "update-check.json"
    result = update_check.check_for_update(
        transport=_json_transport(200, {"tag_name": "v2.0.0"}),
        now=1000.0,
        cache_path=nested_cache,
        current_version="1.5.0",
    )
    assert result.status == update_check.STATUS_UPDATE_AVAILABLE
    assert len(calls) == 1
    assert calls[0][1] == nested_cache
    assert nested_cache.is_file()
    assert list(nested_cache.parent.glob("*.tmp")) == []


def test_off_switches_env_config_and_ci(notifier_env: None, monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[httpx.Request] = []
    transport = _json_transport(200, {"tag_name": "v9.0.0"}, calls=calls)

    # 1. DISCOOP_NO_UPDATE_NOTIFIER truthy
    for val in ("1", "true", "YES", " on "):
        monkeypatch.setenv("DISCOOP_NO_UPDATE_NOTIFIER", val)
        assert update_check.is_disabled() is True
        assert update_check.check_for_update(force=True, transport=transport).status == update_check.STATUS_DISABLED
        handle = update_check.start_background_check(transport=transport)
        assert not handle.started_thread
        assert handle.wait() is None

    monkeypatch.setenv("DISCOOP_NO_UPDATE_NOTIFIER", "0")
    assert update_check.is_disabled() is False

    # 2. Config update-check = off
    Config.default().set("update-check", "off")
    assert update_check.is_disabled() is True
    res = update_check.check_for_update(force=True, transport=transport)
    assert res.status == update_check.STATUS_DISABLED
    assert update_check.format_doctor_detail(res) == "skipped (update-check is off)"
    assert not update_check.start_background_check(transport=transport).started_thread
    assert calls == []

    # 3. CI truthy disables CLI background check, but not non-CI checks (TUI / doctor)
    Config.default().unset("update-check")
    monkeypatch.setenv("CI", "true")
    assert update_check.is_cli_disabled() is True
    assert update_check.is_disabled(include_ci=False) is False
    assert not update_check.start_background_check(transport=transport).started_thread
    assert calls == []

    doc_res = update_check.check_for_update(
        force=True,
        include_ci=False,
        transport=transport,
        now=1000.0,
        current_version="1.5.0",
    )
    assert doc_res.status == update_check.STATUS_UPDATE_AVAILABLE
    assert len(calls) == 1


def test_broken_config_toml_does_not_crash_notifier(notifier_env: None) -> None:
    cfg = Config.default()
    cfg.path.parent.mkdir(parents=True, exist_ok=True)
    cfg.path.write_text("delay = = 1", encoding="utf-8")

    assert update_check.is_disabled() is False
    res = update_check.check_for_update(
        transport=_json_transport(200, {"tag_name": "v2.0.0"}),
        now=1000.0,
        current_version="1.5.0",
    )
    assert res.status == update_check.STATUS_UPDATE_AVAILABLE


def test_privacy_headers_timeout_and_no_auth_leak(
    notifier_env: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_secret_should_never_be_sent")
    monkeypatch.setenv("GH_TOKEN", "gho_secret_should_never_be_sent")
    seen: list[httpx.Request] = []

    res = update_check.check_for_update(
        transport=_json_transport(200, {"tag_name": "v9.0.0"}, calls=seen),
        now=1000.0,
        current_version="1.5.0",
    )
    assert res.status == update_check.STATUS_UPDATE_AVAILABLE
    assert len(seen) == 1
    req = seen[0]
    assert str(req.url) == "https://api.github.com/repos/filbam/Discoop/releases/latest"
    lower_headers = {k.lower(): v for k, v in req.headers.items()}
    assert "authorization" not in lower_headers
    assert "cookie" not in lower_headers
    assert lower_headers["accept"] == "application/vnd.github+json"
    assert lower_headers["user-agent"] == f"discoop/{discoop.__version__}"
    assert req.extensions["timeout"] == {"connect": 2.0, "read": 2.0, "write": 2.0, "pool": 2.0}


def test_background_check_notify_throttling_and_cache_refresh(notifier_env: None) -> None:
    calls: list[httpx.Request] = []
    latest_tag = "v2.0.0"

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(
            200,
            json={
                "tag_name": latest_tag,
                "html_url": f"https://github.com/filbam/Discoop/releases/tag/{latest_tag}",
            },
        )

    transport = httpx.MockTransport(handler)

    # First CLI run: starts daemon thread, finds 2.0.0, returns UpdateInfo, mark_notified records notified_at.
    h1 = update_check.start_background_check(transport=transport, now=1000.0, current_version="1.5.0")
    assert h1.started_thread is True
    assert h1._thread is not None and h1._thread.daemon is True
    info1 = h1.wait(timeout=1.0)
    assert info1 == update_check.UpdateInfo(
        latest_version="2.0.0",
        current_version="1.5.0",
        url="https://github.com/filbam/Discoop/releases/tag/v2.0.0",
    )
    h1.mark_notified()
    assert len(calls) == 1
    assert _read_cache_json()["notified_at"] == 1000.0

    # Second run 1h later: cache is fresh -> no thread, and notified within 24h -> returns None.
    h2 = update_check.start_background_check(transport=transport, now=4600.0, current_version="1.5.0")
    assert h2.started_thread is False
    assert h2.wait() is None
    assert len(calls) == 1

    # Third run when check cache expired (24h after 1000.0) while notified_at was more recent (say 23h ago):
    # cache refreshes to 2.1.0, notified_at is preserved, and CLI notice stays suppressed until 24h after notified_at.
    _write_cache_json(
        {
            "checked_at": 1000.0,
            "latest_version": "2.0.0",
            "latest_url": "https://github.com/filbam/Discoop/releases/tag/v2.0.0",
            "failed_at": None,
            "notified_at": 5000.0,
        }
    )
    latest_tag = "v2.1.0"
    t3 = 1000.0 + update_check.CHECK_INTERVAL
    h3 = update_check.start_background_check(transport=transport, now=t3, current_version="1.5.0")
    assert h3.started_thread is True
    assert h3.wait(timeout=1.0) is None  # notified_at=5000 is within 24h of t3
    assert len(calls) == 2
    cached = _read_cache_json()
    assert cached["latest_version"] == "2.1.0"
    assert cached["checked_at"] == t3
    assert cached["notified_at"] == 5000.0

    # After 24h from notified_at: cache answers without network and returns UpdateInfo again.
    t4 = 5000.0 + update_check.NOTIFY_INTERVAL
    h4 = update_check.start_background_check(transport=transport, now=t4, current_version="1.5.0")
    assert h4.started_thread is False
    info4 = h4.wait()
    assert info4 is not None and info4.latest_version == "2.1.0"
    assert len(calls) == 2


def test_background_check_skips_thread_during_failure_backoff(notifier_env: None) -> None:
    calls: list[httpx.Request] = []
    _write_cache_json(
        {
            "checked_at": 0.0,
            "latest_version": "2.0.0",
            "latest_url": "https://github.com/filbam/Discoop/releases/tag/v2.0.0",
            "failed_at": 90000.0,
            "notified_at": None,
        }
    )
    handle = update_check.start_background_check(
        transport=_json_transport(500, calls=calls),
        now=90000.0 + update_check.FAILURE_BACKOFF - 1.0,
        current_version="1.5.0",
    )
    assert handle.started_thread is False
    assert calls == []
    info = handle.wait()
    assert info is not None and info.latest_version == "2.0.0"


def test_background_check_timeout_returns_none_quickly_and_writes_cache(notifier_env: None) -> None:
    release = threading.Event()
    entered = threading.Event()

    def slow_handler(_request: httpx.Request) -> httpx.Response:
        entered.set()
        release.wait(timeout=5.0)
        return httpx.Response(
            200,
            json={"tag_name": "v2.5.0", "html_url": "https://github.com/filbam/Discoop/releases/tag/v2.5.0"},
        )

    handle = update_check.start_background_check(
        transport=httpx.MockTransport(slow_handler),
        now=1000.0,
        current_version="1.5.0",
    )
    try:
        assert entered.wait(timeout=1.0)
        start = time.monotonic()
        info = handle.wait(timeout=0.05)
        elapsed = time.monotonic() - start
        assert info is None
        assert elapsed < 0.5
    finally:
        release.set()
        if handle._thread is not None:
            handle._thread.join(timeout=2.0)

    assert _read_cache_json()["latest_version"] == "2.5.0"


def test_doctor_force_ignores_cache_and_backoff(notifier_env: None) -> None:
    calls: list[httpx.Request] = []
    _write_cache_json(
        {
            "checked_at": 1000.0,
            "latest_version": "1.5.0",
            "latest_url": "https://github.com/filbam/Discoop/releases/tag/v1.5.0",
            "failed_at": 1005.0,
            "notified_at": None,
        }
    )
    res = update_check.check_for_update(
        force=True,
        transport=_json_transport(200, {"tag_name": "v2.0.0"}, calls=calls),
        now=1010.0,
        current_version="1.5.0",
    )
    assert len(calls) == 1
    assert res.status == update_check.STATUS_UPDATE_AVAILABLE
    assert update_check.format_doctor_detail(res) == "2.0.0 available: uv tool upgrade discoop"


def test_formatting_helpers() -> None:
    info = update_check.UpdateInfo(
        latest_version="2.0.0",
        current_version="1.5.0",
        url="https://github.com/filbam/Discoop/releases/tag/v2.0.0",
    )
    assert update_check.format_cli_notice_lines(info) == (
        "A new release of discoop is available: 1.5.0 -> 2.0.0",
        "To upgrade, run: uv tool upgrade discoop",
        "https://github.com/filbam/Discoop/releases/tag/v2.0.0",
    )
    assert update_check.format_tui_log_message(info) == (
        "New release 2.0.0 is available (you have 1.5.0). "
        "Quit and run: uv tool upgrade discoop. "
        "Release notes: https://github.com/filbam/Discoop/releases/tag/v2.0.0"
    )
    assert update_check.format_doctor_detail(
        update_check.CheckResult(
            status=update_check.STATUS_UPDATE_AVAILABLE,
            update=info,
            latest_version="2.0.0",
            latest_url=info.url,
        )
    ) == "2.0.0 available: uv tool upgrade discoop"
    assert update_check.format_doctor_detail(
        update_check.CheckResult(status=update_check.STATUS_UP_TO_DATE, latest_version="1.5.0")
    ) == "up to date (latest 1.5.0)"
    assert update_check.format_doctor_detail(
        update_check.CheckResult(status=update_check.STATUS_NO_RELEASE)
    ) == "no release published yet"
    assert update_check.format_doctor_detail(
        update_check.CheckResult(status=update_check.STATUS_DISABLED)
    ) == "skipped (update-check is off)"
    assert update_check.format_doctor_detail(
        update_check.CheckResult(status=update_check.STATUS_ERROR, error="HTTP 500")
    ) == "could not check: HTTP 500"


def test_debug_logging_integration(
    notifier_env: None,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from discoop.logs import setup_logging, teardown_logging

    monkeypatch.setenv("GITHUB_TOKEN", "ghp_super_secret")
    monkeypatch.setenv("GH_TOKEN", "gho_super_secret")
    log_file = tmp_path / "debug.log"
    setup_logging(debug=True, log_file=log_file)
    try:
        res = update_check.check_for_update(
            force=True,
            transport=_json_transport(502),
            now=1000.0,
            current_version="1.5.0",
        )
        assert res.status == update_check.STATUS_ERROR
        assert update_check.format_doctor_detail(res) == "could not check: HTTP 502"
    finally:
        teardown_logging()

    log_text = log_file.read_text(encoding="utf-8")
    assert "update_check" in log_text
    assert "HTTP 502" in log_text
    assert "ghp_super_secret" not in log_text
    assert "gho_super_secret" not in log_text


def test_concurrent_notified_at_preservation(notifier_env: None) -> None:
    entered = threading.Event()
    release = threading.Event()

    def slow_success(_request: httpx.Request) -> httpx.Response:
        entered.set()
        release.wait(timeout=5.0)
        return httpx.Response(200, json={"tag_name": "v2.0.0"})

    handle = update_check.start_background_check(
        transport=httpx.MockTransport(slow_success),
        now=2000.0,
        current_version="1.5.0",
    )
    try:
        assert entered.wait(timeout=1.0)
        update_check._record_notified(update_check.update_cache_path(), 1900.0)
    finally:
        release.set()
        assert handle.wait(timeout=2.0) is None

    cached = _read_cache_json()
    assert cached["latest_version"] == "2.0.0"
    assert cached["notified_at"] == 1900.0


def test_null_handler_prevents_stderr_spam(
    notifier_env: None,
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert any(isinstance(h, logging.NullHandler) for h in update_check.logger.handlers)
    res = update_check.check_for_update(force=True, transport=_json_transport(500), now=1000.0)
    assert res.status == update_check.STATUS_ERROR
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == ""
