"""Start the user's browser as a separate instance with a throw-away profile, and make sure it is gone afterwards.

The browser gets a fresh temporary profile (`--user-data-dir`), which also keeps the user's own browser untouched
and is required anyway: Chrome 136 and newer ignore remote debugging on the default profile (per Chrome's
announcement, docs/analyses/browser-login.md D1). The user logs in in that window themselves; Discoop talks to the
browser over the DevTools Protocol (cdp.py).

Cleanup runs in every path (success, error, timeout, task cancellation, Ctrl+C, a failure while starting), because
the profile holds a live Discord web session. Details: docs/analyses/browser-login.md.
"""

import asyncio
import atexit
import os
import shutil
import signal
import stat
import tempfile
import time
from collections.abc import Awaitable, Callable
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from subprocess import DEVNULL
from typing import Any, Protocol

from websockets.exceptions import InvalidHandshake

from discoop.browser_login._log import logger
from discoop.browser_login.cdp import CdpClient, CdpConnectionLost, CdpError, CdpTimeout
from discoop.browser_login.locate import Browser
from discoop.errors import DiscoopError, ExitCode

LOGIN_URL = "https://discord.com/login"
PROFILE_PREFIX = "discoop-browser-"
STALE_AFTER = 24 * 60 * 60.0  # seconds: older profiles of earlier, hard-killed runs are deleted
ENDPOINT_FILE = "DevToolsActivePort"
ENDPOINT_PATH_PREFIX = "/devtools/browser/"
TRY_OTHER_HINT = "Try another browser with --browser-path, or use `discoop login --token`."
EXIT_PATIENCE = 5.0  # seconds the interpreter-exit hook may spend deleting a profile


class ProcessHandle(Protocol):
    """What the session needs from the started process (an `asyncio.subprocess.Process` fits)."""

    pid: int
    returncode: int | None

    def terminate(self) -> None: ...
    def kill(self) -> None: ...
    async def wait(self) -> int: ...


Spawn = Callable[..., Awaitable[ProcessHandle]]


@dataclass(frozen=True)
class SessionTimings:
    """Every wait in the life of a session, in seconds. Tests shrink them."""

    port_wait: float = 20.0  # DevToolsActivePort must show up
    connect_wait: float = 5.0  # the file can appear a little before the server accepts connections
    open_timeout: float = 3.0  # one WebSocket handshake attempt
    poll: float = 0.1  # between looks at the file / connection attempts
    pid_query: float = 2.0  # asking a relaunched browser for its process id
    close_command: float = 1.5  # Browser.close
    exit_wait: float = 3.0  # for the browser to go away after Browser.close
    terminate_wait: float = 2.0  # after terminate()
    kill_wait: float = 2.0  # after kill()
    profile_wait: float = 10.0  # retries of the profile deletion (Windows keeps file locks briefly)
    profile_poll: float = 0.2


def build_command(browser: Browser, profile_dir: Path, url: str) -> list[str]:
    """The browser's command line. No automation or detection-evasion flag belongs here: the user logs in as in
    any browser window (a test asserts it)."""
    return [
        str(browser.path),
        f"--user-data-dir={profile_dir}",
        "--remote-debugging-port=0",  # the browser picks a free port and writes it to DevToolsActivePort
        "--no-first-run",
        "--no-default-browser-check",
        url,
    ]


def parse_devtools_active_port(text: str) -> tuple[int, str]:
    """Parse DevToolsActivePort: line 1 is the port, line 2 the browser endpoint path (`/devtools/browser/<id>`).

    Raises ValueError for anything else, including a file that is only partly written.
    """
    lines = text.splitlines()
    if len(lines) < 2:
        raise ValueError("DevToolsActivePort has fewer than two lines")
    port_text, path = lines[0].strip(), lines[1].strip()
    if not (port_text.isascii() and port_text.isdigit()) or not 0 < int(port_text) < 65536:
        raise ValueError("DevToolsActivePort does not start with a port number")
    if not path.startswith(ENDPOINT_PATH_PREFIX) or len(path) == len(ENDPOINT_PATH_PREFIX) or " " in path:
        raise ValueError("DevToolsActivePort does not name a browser endpoint")
    return int(port_text), path


def _clear_readonly(function: Callable[[str], Any], path: str, error: BaseException) -> None:
    """`shutil.rmtree` hook: Windows will not delete a read-only file, so lift the flag and try once more.

    Anything else that fails is left alone: `_try_remove` looks at what remains and the caller retries.
    """
    if function is os.unlink:
        with suppress(OSError):
            os.chmod(path, stat.S_IWRITE)
            os.unlink(path)


def _fs_path(path: Path) -> str:
    """The path as the file system calls should see it. On Windows that is the extended-length form: Chrome writes
    files deeper than the 260-character limit of ordinary calls, which then cannot be found, let alone deleted
    (seen with a profile in a long folder name, docs/analyses/browser-login.md)."""
    text = str(path)
    if os.name != "nt" or text.startswith("\\\\?\\"):
        return text
    absolute = os.path.abspath(text)
    if absolute.startswith("\\\\"):  # a network share
        return "\\\\?\\UNC\\" + absolute[2:]
    return "\\\\?\\" + absolute


def _remove_tree(path: Path) -> None:
    shutil.rmtree(_fs_path(path), onexc=_clear_readonly)


def sweep_stale_profiles(root: Path | None = None, *, max_age: float = STALE_AFTER, now: float | None = None) -> int:
    """Best effort: delete `discoop-browser-*` folders in `root` (the temp folder) that are older than `max_age`.

    A hard-killed run (power loss, kill -9) cannot clean up after itself, and its profile holds a web session.
    Returns how many folders were removed; never raises.
    """
    removed = 0
    try:
        limit = (time.time() if now is None else now) - max_age
        with os.scandir(root if root is not None else tempfile.gettempdir()) as entries:
            for entry in entries:
                try:
                    if not entry.name.startswith(PROFILE_PREFIX):
                        continue
                    if entry.is_symlink() or entry.is_junction() or not entry.is_dir(follow_symlinks=False):
                        continue
                    if entry.stat(follow_symlinks=False).st_mtime >= limit:
                        continue
                    with suppress(OSError):
                        _remove_tree(Path(entry.path))
                    if not os.path.exists(entry.path):
                        removed += 1
                except OSError:
                    continue
    except OSError:
        pass
    if removed:
        logger.debug("stale profiles removed count=%d", removed)
    return removed


def _reason(error: Exception) -> str:
    """A short reason for a failed start: the system's wording, never a path."""
    if isinstance(error, FileNotFoundError):
        return "the file was not found"
    if isinstance(error, PermissionError):
        return "permission denied"
    return getattr(error, "strerror", None) or type(error).__name__


def _terminate_pid(pid: int) -> None:
    """Stop one process by id: TerminateProcess on Windows, SIGTERM elsewhere."""
    os.kill(pid, signal.SIGTERM)


# Sessions whose cleanup has not finished. The interpreter-exit hook below deals with whatever is left, so a
# browser with a logged-in profile is not abandoned when the normal cleanup could not run to the end.
_live_sessions: set["BrowserSession"] = set()


def cleanup_leftover_sessions() -> None:
    """`atexit` hook: kill the browser a session started and delete its profile, if that never happened."""
    for session in list(_live_sessions):
        with suppress(Exception):
            session.emergency_cleanup()


atexit.register(cleanup_leftover_sessions)


class BrowserSession:
    """Async context manager: starts the browser and yields a connected `CdpClient`; leaving it closes the browser
    and deletes the profile.

    The `spawn` seam (default `asyncio.create_subprocess_exec`) and `profile_root` (default: the temp folder) let
    tests run without a real browser.
    """

    def __init__(
        self,
        browser: Browser,
        *,
        url: str = LOGIN_URL,
        spawn: Spawn = asyncio.create_subprocess_exec,
        profile_root: Path | None = None,
        timings: SessionTimings | None = None,
        kill_pid: Callable[[int], None] = _terminate_pid,
    ) -> None:
        self.browser = browser
        self.url = url
        self._spawn = spawn
        self._profile_root = profile_root
        self._timings = timings or SessionTimings()
        self._kill_pid = kill_pid
        self._profile: Path | None = None
        self._process: ProcessHandle | None = None
        self._client: CdpClient | None = None
        # Some browsers start a second process and let the first one exit with code 0 (Edge on Windows does).
        # The handle is then useless: the real browser is found over the DevTools connection instead.
        self._handed_off = False
        self._browser_pid: int | None = None
        self._profile_made = False
        self._closed = False
        self._removal_deadline: float | None = None

    @property
    def exited(self) -> bool:
        """True if the browser process we started has exited (so the window is gone)."""
        process = self._process
        return process is not None and not self._handed_off and process.returncode is not None

    async def __aenter__(self) -> CdpClient:
        try:
            return await self._open()
        except BaseException:
            await self._close()  # Python does not call __aexit__ when __aenter__ fails
            raise

    async def __aexit__(self, *exc: object) -> None:
        await self._close()

    # -- starting ---------------------------------------------------------------------------------------------

    async def _open(self) -> CdpClient:
        name = self.browser.name
        sweep_stale_profiles(self._profile_root)
        try:
            if self._profile_root is not None:
                self._profile_root.mkdir(parents=True, exist_ok=True)
            self._profile = Path(tempfile.mkdtemp(prefix=PROFILE_PREFIX, dir=self._profile_root))
            self._profile_made = True
        except OSError as e:
            raise DiscoopError(
                ExitCode.ERROR, f"{name} could not be started: no temporary profile ({_reason(e)}).", TRY_OTHER_HINT
            ) from e
        _live_sessions.add(self)
        command = build_command(self.browser, self._profile, self.url)
        try:
            self._process = await self._spawn(*command, stdin=DEVNULL, stdout=DEVNULL, stderr=DEVNULL)
        except (OSError, ValueError, NotImplementedError) as e:  # the last: an event loop without subprocess support
            raise DiscoopError(
                ExitCode.ERROR, f"{name} could not be started: {_reason(e)}.", TRY_OTHER_HINT
            ) from e
        logger.debug("browser started browser=%s", name)
        self._client = await self._connect()
        if self._handed_off:
            self._browser_pid = await self._ask_browser_pid(self._client)
        logger.debug("browser connected browser=%s handed_off=%s", name, str(self._handed_off).lower())
        return self._client

    async def _connect(self) -> CdpClient:
        """Wait for DevToolsActivePort, then connect to the endpoint it names."""
        t = self._timings
        port_deadline = time.monotonic() + t.port_wait
        connect_deadline: float | None = None
        refused = False
        while True:
            self._check_process()
            endpoint = self._read_endpoint()
            if endpoint is not None:
                port, path = endpoint
                if connect_deadline is None:
                    connect_deadline = time.monotonic() + t.connect_wait
                try:
                    return await CdpClient.connect(f"ws://127.0.0.1:{port}{path}", open_timeout=t.open_timeout)
                except InvalidHandshake:
                    refused = True
                except (OSError, TimeoutError):
                    refused = False
                if time.monotonic() >= connect_deadline:
                    raise self._start_failure("the debugging connection was refused" if refused else None)
            elif time.monotonic() >= port_deadline:
                raise self._start_failure(None)
            await asyncio.sleep(t.poll)

    def _check_process(self) -> None:
        process = self._process
        code = process.returncode if process is not None else None
        if code is None:
            return
        if code != 0:
            raise self._start_failure(f"it exited right away (code {code})")
        if not self._handed_off:
            self._handed_off = True
            logger.debug("browser process exited with code 0 before connecting: assuming it relaunched")

    def _read_endpoint(self) -> tuple[int, str] | None:
        if self._profile is None:
            return None
        try:
            return parse_devtools_active_port((self._profile / ENDPOINT_FILE).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None  # not there yet, or only partly written

    def _start_failure(self, reason: str | None) -> DiscoopError:
        name = self.browser.name
        message = f"{name} could not be started: {reason}." if reason else f"{name} did not start in time."
        return DiscoopError(ExitCode.ERROR, message, TRY_OTHER_HINT)

    async def _ask_browser_pid(self, client: CdpClient) -> int | None:
        """After a relaunch, learn the id of the real browser process (used only as a last resort to stop it)."""
        try:
            result = await client.send("SystemInfo.getProcessInfo", timeout=self._timings.pid_query)
        except (CdpError, CdpTimeout, CdpConnectionLost):
            return None
        infos = result.get("processInfo")
        for info in infos if isinstance(infos, list) else []:
            if isinstance(info, dict) and info.get("type") == "browser" and isinstance(info.get("id"), int):
                return info["id"]
        return None

    # -- stopping ---------------------------------------------------------------------------------------------

    async def _close(self) -> None:
        if self._closed:
            return
        self._closed = True
        interrupted: BaseException | None = None
        try:
            await self._shutdown()
        except BaseException as e:  # noqa: BLE001 - cancellation or Ctrl+C: finish the cleanup, then re-raise
            interrupted = e
        finally:
            # Nothing below awaits, so nothing can cancel it: the process is stopped and the profile deleted.
            self._finish()
        if interrupted is not None:
            raise interrupted

    async def _shutdown(self) -> None:
        """The polite part: ask the browser to close, wait for it, force it if it ignores us, delete the profile."""
        t = self._timings
        client, process = self._client, self._process
        if client is not None and not client.lost:
            with suppress(CdpError, CdpTimeout, CdpConnectionLost):
                await client.send("Browser.close", timeout=t.close_command)
        if self._handed_off:
            # Our handle is the dead first process: the real browser is gone when its connection is.
            if client is not None and not await client.wait_lost(t.exit_wait):
                self._stop_browser_by_pid()
                await client.wait_lost(t.terminate_wait)
            if client is not None:
                await client.close()
        else:
            if client is not None:
                await client.close()
            if process is not None:
                await self._reap(process)
        await self._remove_profile()

    async def _reap(self, process: ProcessHandle) -> None:
        t = self._timings
        if process.returncode is None:
            with suppress(TimeoutError):
                await asyncio.wait_for(process.wait(), t.exit_wait)
        if process.returncode is None:
            with suppress(OSError):
                process.terminate()
            with suppress(TimeoutError):
                await asyncio.wait_for(process.wait(), t.terminate_wait)
        if process.returncode is None:
            with suppress(OSError):
                process.kill()
            with suppress(TimeoutError):
                await asyncio.wait_for(process.wait(), t.kill_wait)

    async def _remove_profile(self) -> None:
        end = self._removal_deadline = time.monotonic() + self._timings.profile_wait
        while not self._try_remove():
            if time.monotonic() >= end:
                return
            await asyncio.sleep(self._timings.profile_poll)

    def _try_remove(self) -> bool:
        """One attempt to delete the profile. True once it is gone."""
        profile = self._profile
        if profile is None:
            return True
        with suppress(OSError):
            _remove_tree(profile)
        if os.path.exists(profile):
            return False
        self._profile = None
        return True

    def _stop_browser_by_pid(self) -> None:
        pid = self._browser_pid
        if pid is not None:
            with suppress(Exception):
                self._kill_pid(pid)

    def _browser_alive(self) -> bool:
        if self._handed_off:
            return self._client is not None and not self._client.lost
        return self._process is not None and self._process.returncode is None

    def _finish(self, patience: float | None = None) -> None:
        """Stop the browser if it still runs and delete the profile; blocking and immune to cancellation.

        The normal path has done all of this already and finds nothing to do. When it was interrupted (a second
        Ctrl+C, a cancelled task), this is what keeps the profile from being left behind.
        """
        if self._browser_alive():
            if self._handed_off:
                self._stop_browser_by_pid()
            elif self._process is not None:
                with suppress(Exception):
                    self._process.kill()
        if self._client is not None and not self._client.lost:
            self._client.abort()  # an interrupted cleanup must not leave the connection dangling
        if self._profile is not None:
            if self._removal_deadline is None:
                wait = self._timings.profile_wait if patience is None else patience
                self._removal_deadline = time.monotonic() + wait
            while not self._try_remove() and time.monotonic() < self._removal_deadline:
                time.sleep(self._timings.profile_poll)
        if self._profile is not None:
            logger.warning(
                "A temporary browser profile could not be removed; a later run deletes it once it is 24 hours old."
            )
        elif self._profile_made:
            logger.debug("profile_removed=true")
        _live_sessions.discard(self)

    def emergency_cleanup(self) -> None:
        """For the interpreter-exit hook: the same as the end of a normal cleanup, with a short patience."""
        self._closed = True
        self._finish(patience=EXIT_PATIENCE)
