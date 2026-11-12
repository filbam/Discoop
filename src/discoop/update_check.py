"""Optional GitHub Releases update check, local cache, and notice formatting.

Privacy and network rules:
- Sends an unauthenticated GET to `LATEST_RELEASE_URL` with only `Accept` and `User-Agent` headers.
- Never sends `Authorization`, cookies, or user data, even when `GITHUB_TOKEN` or `GH_TOKEN` is set.
- Times out after `TIMEOUT_SECONDS` (2.0 s). Errors and unexpected responses are debug-logged, never raised.

Public API for CLI, `doctor`, and TUI:
- `UpdateInfo`, `CheckResult`, `UpdateCache`, `BackgroundUpdateCheck`
- Status constants: `STATUS_UPDATE_AVAILABLE`, `STATUS_UP_TO_DATE`, `STATUS_NO_RELEASE`,
  `STATUS_DISABLED`, `STATUS_ERROR`
- Off-switch helpers: `is_disabled(...)`, `is_cli_disabled(...)`
- Blocking check (TUI worker with `force=False`, `doctor` with `force=True`): `check_for_update(...)`
- Non-blocking CLI background check: `start_background_check(...)` -> `.wait(timeout=1.0)`, `.mark_notified()`
- Formatting helpers: `format_cli_notice_lines(info)`, `format_tui_log_message(info)`,
  `format_doctor_detail(result)`
"""

from __future__ import annotations

import json
import logging
import math
import os
import re
import threading
import time
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import httpx

import discoop
from discoop import paths
from discoop.attachments import replace_file
from discoop.config import Config
from discoop.errors import DiscoopError

logger = logging.getLogger("discoop.update_check")
logger.addHandler(logging.NullHandler())  # never let Python's lastResort print to stderr

LATEST_RELEASE_URL = "https://api.github.com/repos/filbam/Discoop/releases/latest"
RELEASES_URL_PREFIX = "https://github.com/filbam/Discoop/releases/"
RELEASE_TAG_URL_BASE = "https://github.com/filbam/Discoop/releases/tag/"

TIMEOUT_SECONDS = 2.0
CHECK_INTERVAL = 24 * 3600
FAILURE_BACKOFF = 3600
NOTIFY_INTERVAL = 24 * 3600

DISABLE_ENV = "DISCOOP_NO_UPDATE_NOTIFIER"
CI_ENV = "CI"
_TRUTHY = {"1", "true", "yes", "on"}

CACHE_FILENAME = "update-check.json"

STATUS_UPDATE_AVAILABLE = "update_available"
STATUS_UP_TO_DATE = "up_to_date"
STATUS_NO_RELEASE = "no_release"
STATUS_DISABLED = "disabled"
STATUS_ERROR = "error"

_TAG_VERSION_RE = re.compile(r"^v?([0-9]+)\.([0-9]+)\.([0-9]+)$")
_SEMVER_RE = re.compile(r"^([0-9]+)\.([0-9]+)\.([0-9]+)$")

_CACHE_LOCK = threading.Lock()


@dataclass(frozen=True)
class UpdateInfo:
    """Details about a strictly newer release available on GitHub."""

    latest_version: str
    current_version: str
    url: str


@dataclass(frozen=True)
class CheckResult:
    """Result of an update check (cached, live, disabled, or failed)."""

    status: str
    update: UpdateInfo | None = None
    latest_version: str | None = None
    latest_url: str | None = None
    error: str | None = None


@dataclass(frozen=True)
class UpdateCache:
    """On-disk cache record stored in `update-check.json`."""

    checked_at: float | None = None
    latest_version: str | None = None
    latest_url: str | None = None
    failed_at: float | None = None
    notified_at: float | None = None


@dataclass(frozen=True)
class _FetchOutcome:
    kind: Literal["release", "no_release", "error"]
    latest_version: str | None = None
    latest_url: str | None = None
    error: str | None = None


def update_cache_path() -> Path:
    """Return the path to `update-check.json` in the platform data directory."""
    return paths.data_dir() / CACHE_FILENAME


def parse_version(raw: Any, *, allow_v: bool = True) -> tuple[int, int, int] | None:
    """Parse an ASCII `X.Y.Z` (or `vX.Y.Z` when `allow_v=True`) string into an integer triple."""
    if not isinstance(raw, str):
        return None
    pattern = _TAG_VERSION_RE if allow_v else _SEMVER_RE
    match = pattern.fullmatch(raw)
    if match is None:
        return None
    return (int(match.group(1)), int(match.group(2)), int(match.group(3)))


def _env_truthy(key: str, env: Mapping[str, str] | None = None) -> bool:
    source = os.environ if env is None else env
    return source.get(key, "").strip().lower() in _TRUTHY


def _read_update_check_setting(config: Config | Mapping[str, Any] | None) -> Any:
    if config is not None:
        return config.get("update-check")
    try:
        return Config.default().get("update-check")
    except (DiscoopError, OSError) as exc:
        logger.debug("Could not read config.toml for update-check setting: %s", exc)
        return None


def _is_config_disabled(value: Any) -> bool:
    if isinstance(value, bool):
        return not value
    if isinstance(value, str):
        return value.strip().lower() == "off"
    return False


def is_disabled(
    config: Config | Mapping[str, Any] | None = None,
    *,
    include_ci: bool = False,
    env: Mapping[str, str] | None = None,
) -> bool:
    """Return True when update checks are disabled by environment or config."""
    if _env_truthy(DISABLE_ENV, env):
        return True
    if include_ci and _env_truthy(CI_ENV, env):
        return True
    return _is_config_disabled(_read_update_check_setting(config))


def is_cli_disabled(
    config: Config | Mapping[str, Any] | None = None,
    *,
    env: Mapping[str, str] | None = None,
) -> bool:
    """Return True when CLI background update checks are disabled (also honors `CI`)."""
    return is_disabled(config=config, include_ci=True, env=env)


def _as_timestamp(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    result = float(value)
    return result if math.isfinite(result) else None


def _is_fresh(timestamp: float | None, now: float, interval: float) -> bool:
    return timestamp is not None and 0.0 <= (now - timestamp) < interval


def _safe_release_url(url: Any, tag_or_version: str, *, add_v_prefix: bool = False) -> str:
    if isinstance(url, str) and url.startswith(RELEASES_URL_PREFIX):
        return url
    suffix = f"v{tag_or_version}" if add_v_prefix else tag_or_version
    return f"{RELEASE_TAG_URL_BASE}{suffix}"


def _read_cache_unlocked(path: Path) -> UpdateCache:
    if not path.is_file():
        return UpdateCache()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        logger.debug("Could not read update cache %s: %s", path, exc)
        return UpdateCache()
    if not isinstance(raw, dict):
        logger.debug("Ignoring update cache %s: root JSON value is not an object", path)
        return UpdateCache()

    parsed_version = parse_version(raw.get("latest_version"), allow_v=True)
    if parsed_version is not None:
        latest_version: str | None = f"{parsed_version[0]}.{parsed_version[1]}.{parsed_version[2]}"
        latest_url: str | None = _safe_release_url(raw.get("latest_url"), latest_version, add_v_prefix=True)
    else:
        latest_version = None
        latest_url = None

    return UpdateCache(
        checked_at=_as_timestamp(raw.get("checked_at")),
        latest_version=latest_version,
        latest_url=latest_url,
        failed_at=_as_timestamp(raw.get("failed_at")),
        notified_at=_as_timestamp(raw.get("notified_at")),
    )


def _write_cache_unlocked(path: Path, cache: UpdateCache) -> None:
    temp_path: Path | None = None
    replaced = False
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = path.parent / f"update-check.{os.getpid()}.{threading.get_ident()}.tmp"
        payload = {
            "checked_at": cache.checked_at,
            "latest_version": cache.latest_version,
            "latest_url": cache.latest_url,
            "failed_at": cache.failed_at,
            "notified_at": cache.notified_at,
        }
        temp_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        replace_file(temp_path, path)
        replaced = True
    except OSError as exc:
        logger.debug("Could not write update cache %s: %s", path, exc)
    finally:
        if temp_path is not None and not replaced:
            try:
                temp_path.unlink(missing_ok=True)
            except OSError:
                pass


def load_cache(path: Path | None = None) -> UpdateCache:
    """Read `update-check.json`, returning an empty cache if missing or corrupt."""
    target = update_cache_path() if path is None else path
    with _CACHE_LOCK:
        return _read_cache_unlocked(target)


def _record_success(
    path: Path,
    checked_at: float,
    latest_version: str | None,
    latest_url: str | None,
) -> UpdateCache:
    with _CACHE_LOCK:
        current = _read_cache_unlocked(path)
        updated = UpdateCache(
            checked_at=checked_at,
            latest_version=latest_version,
            latest_url=latest_url,
            failed_at=None,
            notified_at=current.notified_at,
        )
        _write_cache_unlocked(path, updated)
        return updated


def _record_failure(path: Path, failed_at: float) -> UpdateCache:
    with _CACHE_LOCK:
        current = _read_cache_unlocked(path)
        updated = UpdateCache(
            checked_at=current.checked_at,
            latest_version=current.latest_version,
            latest_url=current.latest_url,
            failed_at=failed_at,
            notified_at=current.notified_at,
        )
        _write_cache_unlocked(path, updated)
        return updated


def _record_notified(path: Path, notified_at: float) -> UpdateCache:
    with _CACHE_LOCK:
        current = _read_cache_unlocked(path)
        updated = UpdateCache(
            checked_at=current.checked_at,
            latest_version=current.latest_version,
            latest_url=current.latest_url,
            failed_at=current.failed_at,
            notified_at=notified_at,
        )
        _write_cache_unlocked(path, updated)
        return updated


def _build_update(
    latest_version: str | None,
    latest_url: str | None,
    current_version: str,
) -> UpdateInfo | None:
    latest_tuple = parse_version(latest_version, allow_v=False)
    current_tuple = parse_version(current_version, allow_v=False)
    if latest_tuple is None or current_tuple is None or latest_tuple <= current_tuple:
        return None
    assert latest_version is not None
    url = _safe_release_url(latest_url, latest_version, add_v_prefix=True)
    return UpdateInfo(latest_version=latest_version, current_version=current_version, url=url)


def _result_from_fresh_cache(cache: UpdateCache, current_version: str) -> CheckResult:
    if cache.latest_version is None:
        return CheckResult(status=STATUS_NO_RELEASE)
    update = _build_update(cache.latest_version, cache.latest_url, current_version)
    if update is not None:
        return CheckResult(
            status=STATUS_UPDATE_AVAILABLE,
            update=update,
            latest_version=update.latest_version,
            latest_url=update.url,
        )
    return CheckResult(
        status=STATUS_UP_TO_DATE,
        latest_version=cache.latest_version,
        latest_url=cache.latest_url,
    )


def _result_from_backoff_cache(cache: UpdateCache, current_version: str, error: str) -> CheckResult:
    update = _build_update(cache.latest_version, cache.latest_url, current_version)
    if update is not None:
        return CheckResult(
            status=STATUS_UPDATE_AVAILABLE,
            update=update,
            latest_version=update.latest_version,
            latest_url=update.url,
        )
    return CheckResult(status=STATUS_ERROR, error=error)


def _fetch_latest_release(transport: httpx.BaseTransport | None = None) -> _FetchOutcome:
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": f"discoop/{discoop.__version__}",
    }
    try:
        with httpx.Client(
            headers=headers,
            timeout=TIMEOUT_SECONDS,
            follow_redirects=True,
            transport=transport,
        ) as client:
            response = client.get(LATEST_RELEASE_URL)
    except httpx.TimeoutException:
        logger.debug("Update check timed out after %.1fs", TIMEOUT_SECONDS)
        return _FetchOutcome("error", error="request timed out")
    except httpx.HTTPError as exc:
        logger.debug("Update check network error: %s", exc)
        return _FetchOutcome("error", error="network error")

    if response.status_code == 404:
        return _FetchOutcome("no_release")
    if response.status_code != 200:
        logger.debug("Update check returned HTTP %d", response.status_code)
        return _FetchOutcome("error", error=f"HTTP {response.status_code}")

    try:
        payload = response.json()
    except (json.JSONDecodeError, UnicodeDecodeError, ValueError) as exc:
        logger.debug("Update check returned invalid JSON: %s", exc)
        return _FetchOutcome("error", error="invalid JSON response")

    if not isinstance(payload, dict):
        logger.debug("Update check returned non-object JSON (%s)", type(payload).__name__)
        return _FetchOutcome("error", error="unexpected JSON response")

    tag_name = payload.get("tag_name")
    parsed = parse_version(tag_name, allow_v=True)
    if parsed is None:
        logger.debug("Update check ignored invalid tag_name: %r", tag_name)
        return _FetchOutcome("error", error="invalid release tag")

    assert isinstance(tag_name, str)
    latest_version = f"{parsed[0]}.{parsed[1]}.{parsed[2]}"
    latest_url = _safe_release_url(payload.get("html_url"), tag_name, add_v_prefix=False)
    return _FetchOutcome("release", latest_version=latest_version, latest_url=latest_url)


def _apply_outcome(
    outcome: _FetchOutcome,
    target_path: Path,
    check_now: float,
    current_version: str,
    *,
    force: bool,
) -> tuple[CheckResult, UpdateCache]:
    if outcome.kind == "no_release":
        disk = _record_success(target_path, check_now, None, None)
        return CheckResult(status=STATUS_NO_RELEASE), disk

    if outcome.kind == "release":
        assert outcome.latest_version is not None and outcome.latest_url is not None
        disk = _record_success(target_path, check_now, outcome.latest_version, outcome.latest_url)
        update = _build_update(outcome.latest_version, outcome.latest_url, current_version)
        if update is not None:
            result = CheckResult(
                status=STATUS_UPDATE_AVAILABLE,
                update=update,
                latest_version=update.latest_version,
                latest_url=update.url,
            )
        else:
            result = CheckResult(
                status=STATUS_UP_TO_DATE,
                latest_version=outcome.latest_version,
                latest_url=outcome.latest_url,
            )
        return result, disk

    disk = _record_failure(target_path, check_now)
    error_msg = outcome.error or "check failed"
    if not force:
        return _result_from_backoff_cache(disk, current_version, error_msg), disk
    return CheckResult(status=STATUS_ERROR, error=error_msg), disk


def check_for_update(
    *,
    force: bool = False,
    include_ci: bool = False,
    transport: httpx.BaseTransport | None = None,
    now: float | None = None,
    config: Config | Mapping[str, Any] | None = None,
    cache_path: Path | None = None,
    current_version: str | None = None,
    env: Mapping[str, str] | None = None,
) -> CheckResult:
    """Check for a newer discoop release, respecting off switches and cache intervals."""
    if is_disabled(config=config, include_ci=include_ci, env=env):
        return CheckResult(status=STATUS_DISABLED)

    target_path = update_cache_path() if cache_path is None else cache_path
    cur_ver = discoop.__version__ if current_version is None else current_version
    check_now = time.time() if now is None else float(now)

    if not force:
        cache = load_cache(target_path)
        if _is_fresh(cache.checked_at, check_now, CHECK_INTERVAL):
            return _result_from_fresh_cache(cache, cur_ver)
        if _is_fresh(cache.failed_at, check_now, FAILURE_BACKOFF):
            return _result_from_backoff_cache(cache, cur_ver, "recent check failed")

    outcome = _fetch_latest_release(transport=transport)
    result, _ = _apply_outcome(outcome, target_path, check_now, cur_ver, force=force)
    return result


class BackgroundUpdateCheck:
    """Handle for a non-blocking CLI background update check."""

    def __init__(
        self,
        *,
        cache_path: Path,
        now: float | None,
        check_now: float,
        thread: threading.Thread | None = None,
        result: CheckResult | None = None,
        notified_at: float | None = None,
    ) -> None:
        self._cache_path = cache_path
        self._now = now
        self._check_now = check_now
        self._thread = thread
        self._lock = threading.Lock()
        self._result = result
        self._notified_at = notified_at

    @property
    def started_thread(self) -> bool:
        """True when a background HTTP thread was started."""
        return self._thread is not None

    def _finish(self, result: CheckResult, notified_at: float | None) -> None:
        with self._lock:
            self._result = result
            self._notified_at = notified_at

    def wait(self, timeout: float = 1.0) -> UpdateInfo | None:
        """Wait up to `timeout` seconds and return `UpdateInfo` if a CLI notice should be shown."""
        if self._thread is not None:
            self._thread.join(timeout=max(0.0, timeout))
            if self._thread.is_alive():
                return None

        with self._lock:
            result = self._result
            notified_at = self._notified_at

        if result is None or result.update is None:
            return None
        if _is_fresh(notified_at, self._check_now, NOTIFY_INTERVAL):
            return None
        return result.update

    def mark_notified(self, *, now: float | None = None) -> None:
        """Record `notified_at` in `update-check.json` after showing a CLI notice."""
        if now is not None:
            timestamp = float(now)
        elif self._now is not None:
            timestamp = float(self._now)
        else:
            timestamp = time.time()
        disk = _record_notified(self._cache_path, timestamp)
        with self._lock:
            self._notified_at = disk.notified_at


def start_background_check(
    *,
    transport: httpx.BaseTransport | None = None,
    now: float | None = None,
    config: Config | Mapping[str, Any] | None = None,
    cache_path: Path | None = None,
    current_version: str | None = None,
    env: Mapping[str, str] | None = None,
) -> BackgroundUpdateCheck:
    """Start a daemon thread for a CLI update check only when enabled and cache is stale."""
    target_path = update_cache_path() if cache_path is None else cache_path
    check_now = time.time() if now is None else float(now)

    if is_cli_disabled(config=config, env=env):
        return BackgroundUpdateCheck(
            cache_path=target_path,
            now=now,
            check_now=check_now,
            result=CheckResult(status=STATUS_DISABLED),
        )

    cur_ver = discoop.__version__ if current_version is None else current_version
    cache = load_cache(target_path)

    if _is_fresh(cache.checked_at, check_now, CHECK_INTERVAL):
        return BackgroundUpdateCheck(
            cache_path=target_path,
            now=now,
            check_now=check_now,
            result=_result_from_fresh_cache(cache, cur_ver),
            notified_at=cache.notified_at,
        )

    if _is_fresh(cache.failed_at, check_now, FAILURE_BACKOFF):
        return BackgroundUpdateCheck(
            cache_path=target_path,
            now=now,
            check_now=check_now,
            result=_result_from_backoff_cache(cache, cur_ver, "recent check failed"),
            notified_at=cache.notified_at,
        )

    def _worker() -> None:
        try:
            outcome = _fetch_latest_release(transport=transport)
            result, disk = _apply_outcome(outcome, target_path, check_now, cur_ver, force=False)
            handle._finish(result, disk.notified_at)
        except Exception as exc:
            logger.debug("Background update check failed: %s", exc)

    thread = threading.Thread(target=_worker, name="discoop-update-check", daemon=True)
    handle = BackgroundUpdateCheck(
        cache_path=target_path,
        now=now,
        check_now=check_now,
        thread=thread,
    )
    thread.start()
    return handle


def format_cli_notice_lines(info: UpdateInfo) -> tuple[str, str, str]:
    """Return the three CLI stderr notice lines for a newer release."""
    return (
        f"A new release of discoop is available: {info.current_version} -> {info.latest_version}",
        "To upgrade, run: uv tool upgrade discoop",
        info.url,
    )


def format_tui_log_message(info: UpdateInfo) -> str:
    """Return the TUI activity log message for a newer release."""
    return (
        f"New release {info.latest_version} is available (you have {info.current_version}). "
        f"Quit and run: uv tool upgrade discoop. Release notes: {info.url}"
    )


def format_doctor_detail(result: CheckResult) -> str:
    """Return the one-line detail string for `discoop doctor`."""
    if result.status == STATUS_UPDATE_AVAILABLE and result.update is not None:
        return f"{result.update.latest_version} available: uv tool upgrade discoop"
    if result.status == STATUS_UP_TO_DATE:
        if result.latest_version:
            return f"up to date (latest {result.latest_version})"
        return "up to date"
    if result.status == STATUS_NO_RELEASE:
        return "no release published yet"
    if result.status == STATUS_DISABLED:
        return "skipped (update-check is off)"
    return f"could not check: {result.error or 'unknown error'}"
